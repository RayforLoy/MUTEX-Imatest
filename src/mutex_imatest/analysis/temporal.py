"""Bounded video/sequence statistics, stabilization and AE/AWB/AF diagnostics."""
from __future__ import annotations

import numpy as np
import cv2
from .preprocess import linearize, channel_image
from .sfr import slanted_edge
from ..utils import check_cancel


def settling_time(times, values, target=None, tolerance=.05, step_time=0, stable_duration=.5):
    t, a = np.asarray(times, float), np.asarray(values, float)
    if t.shape != a.shape or len(a) < 3 or not np.all(np.isfinite(t)) or not np.all(np.isfinite(a)) or np.any(np.diff(t) <= 0) or tolerance <= 0 or stable_duration <= 0:
        raise ValueError("稳定时间需要递增时间戳、至少三点和正容差/持续时间")
    final = float(np.median(a[-max(3, len(a)//5):])) if target is None else float(target)
    allowed = max(abs(final)*tolerance, 1e-8)
    inside = np.isfinite(a) & (np.abs(a-final) <= allowed) & (t >= step_time)
    # Require every remaining sample to stay within tolerance.
    suffix = np.logical_and.accumulate(inside[::-1])[::-1]
    candidates = np.flatnonzero(suffix & (t[-1]-t >= stable_duration))
    return {"target": final, "settling_seconds": float(t[candidates[0]]-step_time) if len(candidates) else None,
            "within_tolerance": bool(len(candidates)), "tolerance_fraction": tolerance,
            "stable_duration_seconds": stable_duration,
            "overshoot_pct": float(100*max(0, np.max(a[t >= step_time])-final)/max(abs(final), 1e-8)) if np.any(t >= step_time) else None}


def analyze_frames(frames, times, config, roi=None, target_gray=None, tolerance=.05, step_time=0, stable_duration=.5, cancel=None):
    records, previous, window, shifts = [], None, None, []
    geometry = None
    for index, (frame, timestamp) in enumerate(zip(frames, times, strict=True)):
        check_cancel(cancel)
        frame = np.asarray(frame)
        if geometry is not None and frame.shape != geometry:
            raise ValueError("视频 / 序列的图像尺寸发生变化")
        geometry = frame.shape
        if roi is not None:
            x, y, w, h = map(int, roi)
            if min(x, y) < 0 or min(w, h) < 16 or x+w > frame.shape[1] or y+h > frame.shape[0]:
                raise ValueError("视频 ROI 越界或小于 16 px")
            frame = frame[y:y+h, x:x+w]
        a = linearize(frame, config)
        y = channel_image(a, "Y")
        if min(y.shape) < 16:
            raise ValueError("视频帧过小")
        mean = float(y.mean())
        rgb_mean = np.mean(a[..., :3], axis=(0, 1)) if a.ndim == 3 else np.repeat(mean, 3)
        gx, gy = cv2.Sobel(y, cv2.CV_64F, 1, 0), cv2.Sobel(y, cv2.CV_64F, 0, 1)
        row = {"frame": index, "time_s": float(timestamp), "mean": mean,
               "r_g": float(rgb_mean[0]/max(rgb_mean[1], 1e-12)), "b_g": float(rgb_mean[2]/max(rgb_mean[1], 1e-12)),
               "focus_score": float(np.mean(gx*gx+gy*gy)), "clipped_fraction": float(np.mean((a <= 0)|(a >= 1)))}
        # The score remains a relative focus statistic unless an actual edge is measured.
        edge = slanted_edge(y, config)
        if not set(edge.get("flags", [])) & {"invalid_edge", "low_contrast", "insufficient_samples"} and not (config.reject_clipping and row['clipped_fraction']>config.maximum_clip_fraction):
            row["mtf50"] = edge.get("values", {}).get("mtf50")
        # Motion is measured on a bounded preview; convert shifts back to source px.
        ratio = min(1, 640/max(y.shape))
        small = cv2.resize(y.astype(np.float32), None, fx=ratio, fy=ratio) if ratio < 1 else y.astype(np.float32)
        if previous is None:
            window = cv2.createHanningWindow((small.shape[1], small.shape[0]), cv2.CV_32F)
            row.update(dx_px=0., dy_px=0., motion_response=1.)
        elif np.std(small) > 1e-5 and np.std(previous) > 1e-5:
            shift, response = cv2.phaseCorrelate(previous.copy(), small.copy(), window)
            row["motion_response"] = float(response)
            if response > .2:
                row.update(dx_px=float(shift[0]/ratio), dy_px=float(shift[1]/ratio))
                shifts.append(np.array(shift)/ratio)
            else:
                row.update(dx_px=None, dy_px=None)
        else:
            row.update(dx_px=None, dy_px=None, motion_response=0.)
        previous = small
        records.append(row)
    if len(records) < 3:
        raise ValueError("时间序列至少需要 3 个采样帧")
    t = [r["time_s"] for r in records]
    means = np.array([r["mean"] for r in records])
    summary = {"frame_count": len(records), "duration_s": t[-1]-t[0],
               "brightness_flicker_pct": float(100*np.std(means)/max(means.mean(), 1e-12)),
               "ae": settling_time(t, means, target_gray, tolerance, step_time, stable_duration),
               "awb_r_g": settling_time(t, [r["r_g"] for r in records], 1., tolerance, step_time, stable_duration),
               "awb_b_g": settling_time(t, [r["b_g"] for r in records], 1., tolerance, step_time, stable_duration),
               "focus": settling_time(t, [r["focus_score"] for r in records], None, tolerance, step_time, stable_duration),
               "motion_step_rms_px": float(np.sqrt(np.mean(np.sum(np.asarray(shifts)**2, axis=1)))) if shifts else None,
               "best_focus_time_s": records[int(np.argmax([r["focus_score"] for r in records]))]["time_s"]}
    return {"summary": summary, "frames": records, "warnings": [
        "AWB 只对用户选定的中性灰区域有意义；AE/AF 必须声明真实阶跃时刻。",
        "视频解码为 RGB 8-bit；不能据此标定原始传感器 PTC、读出噪声或滚动快门。",
        "运动为相邻采样帧平移；不是 ISO 防抖等级或高速运动/丢帧测量。",
        "焦点评分受曝光和场景内容影响；未检出有效斜边时不输出 MTF50。"]}


def video_frames(path, every=1, max_frames=300, cancel=None):
    if not 1 <= every <= 10000 or not 3 <= max_frames <= 10000:
        raise ValueError("视频抽样间隔需为 1–10000，采样帧数需为 3–10000")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError("无法打开视频")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not np.isfinite(fps) or fps <= 0:
        capture.release()
        raise ValueError("视频未提供有效帧率；请改用带实际时间戳的图像序列")
    def iterator():
        index, delivered = 0, 0
        try:
            while delivered < max_frames:
                check_cancel(cancel)
                ok = capture.grab()
                if not ok:
                    break
                if index % every == 0:
                    ok, bgr = capture.retrieve()
                    if not ok:
                        raise ValueError("视频帧解码失败")
                    delivered += 1
                    yield cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), index/fps
                index += 1
        finally:
            capture.release()
    return iterator(), float(fps)
