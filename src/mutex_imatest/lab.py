"""Desktop/CLI shared workflows for measurements that need more than one ROI.

All paths in saved specifications are data, never executable commands. Jobs are
bounded, cancellable, and produce self-contained HTML plus machine-readable JSON.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import csv
import html
import json
import time
import numpy as np
from .config import AnalysisConfig
from .utils import atomic_json, check_cancel, file_fingerprint
from .models import plain, AnalysisResult


WORKFLOWS = {
    "compare": ("双图 SSIM / PSNR", {"roi": [0, 0, 512, 512], "channel": "Y"}),
    "ptc": ("传感器 PTC / 读出噪声 / PRNU / DSNU", {"dark_count": 2, "group_size": 2, "roi": [0, 0, 256, 256], "channel": "G", "saturation_dn": 65535, "fit_range": [.05, .75]}),
    "dark_flat": ("暗场 / 平场校正", {"dark_count": 2, "flat_count": 2, "roi": [0, 0, 512, 512], "channel": "G"}),
    "ccm": ("色彩矩阵 CCM 标定", {"illuminant": "D50", "offset": False, "optimize_lab": True}),
    "oecf": ("导出 OECF 线性化表", {"channel": "G"}),
    "calibrate": ("多视图镜头标定", {"rows": 7, "cols": 9, "square_mm": 10., "pattern": "checkerboard"}),
    "undistort": ("应用镜头标定 / 去畸变", {"calibration": "", "transfer": "linear"}),
    "video": ("视频 AE / AWB / AF / 防抖 / 闪烁", {"every": 3, "max_frames": 300, "tolerance": .05, "step_time": 0., "stable_duration": .5, "step_declared": False, "neutral_roi_confirmed": False}),
    "sequence": ("重复帧 / 时间噪声 / 稳定性", {"roi": [0, 0, 256, 256], "channel": "G", "interval_seconds": .1}),
    "simulate": ("光学 / 传感器 / ISP 仿真", {"roi": [0, 0, 512, 512], "blur_sigma_px": 1., "exposure": 1., "full_well_e": 30000., "read_noise_e": 3., "prnu_pct": .5, "gamma": 1., "bits": 16, "seed": 1}),
    "capture": ("摄像头 / 视频帧采集", {"source": "", "count": 5, "interval_seconds": .2, "camera_index": None}),
    "test_plan": ("测试计划 / Pass-Fail / 数据库", {"plan": ""}),
    "rank": ("批量锐度排名 / 找最清晰图像", {"roi": [0, 0, 512, 512], "channel": "G"}),
}


def read_pixels(path, config, roi=None, channel=None, cancel=None, native_dn=False, cfa_site=None):
    from .imaging import ImageSource
    from .analysis.preprocess import linearize, channel_image
    with ImageSource(path, config, cancel) as source:
        box = roi or [0, 0, source.metadata.width, source.metadata.height]
        if len(box) != 4:
            raise ValueError("ROI 应为 x,y,w,h 四个整数")
        x, y, w, h = map(int, box)
        if min(x, y) < 0 or min(w, h) < 8 or x+w > source.metadata.width or y+h > source.metadata.height:
            raise ValueError("ROI 越界或短边小于 8 px")
        if w*h*max(source.metadata.channels, 1)*96 > config.budget_bytes()*.6:
            raise MemoryError("工作台 ROI 超过内存预算，请缩小区域")
        if native_dn and source.metadata.is_raw:
            # PTC must use undemosaiced photosites. Select a fixed 2x2 Bayer site.
            if not source.raw_cfa_path:
                raise ValueError("RAW 未提供 CFA，不能做原始像素 PTC")
            pattern=np.asarray(source.raw_info.get('raw_pattern'))
            if cfa_site is None or pattern.ndim!=2 or len(cfa_site)!=2:
                raise ValueError('RAW PTC 需要显式指定 cfa_site:[行偏移,列偏移]；仅测同一 CFA 位置，不使用去马赛克像素')
            site=tuple(map(int,cfa_site))
            if any(v<0 or v>=s for v,s in zip(site,pattern.shape)):
                raise ValueError('cfa_site 超出传感器 CFA 周期')
            cfa=np.load(source.raw_cfa_path,mmap_mode='r')
            if y+h>cfa.shape[0] or x+w>cfa.shape[1]:raise ValueError('CFA ROI 越界')
            ry=(site[0]-y)%pattern.shape[0];rx=(site[1]-x)%pattern.shape[1]
            raw=np.array(cfa[y+ry:y+h:pattern.shape[0],x+rx:x+w:pattern.shape[1]])
            if min(raw.shape)<8:raise ValueError('分离后的 CFA ROI 短边至少 8 像素')
        else:raw = source.read_roi((x, y, w, h))
        if native_dn:
            if raw.ndim == 3 and raw.shape[2] > 1:
                raise ValueError("传感器 PTC 需要未处理单通道 DN 图，不接受去马赛克 RGB 或 JPEG")
            if (not source.metadata.is_raw and source.path.suffix.lower() not in {".tif", ".tiff", ".png"}) or config.transfer != "linear":
                raise ValueError("传感器标定仅接受线性 DN TIFF/PNG")
            data = raw.astype(float)
        else:
            data = linearize(raw, config, source.metadata.is_linear)
        if channel:
            data = channel_image(data, channel)
        source.verify_unchanged()
        return np.array(data), {"path": str(source.path), "sha256": source.metadata.fingerprint,
                               "width": source.metadata.width, "height": source.metadata.height,
                               "bits": source.metadata.bits_per_sample, "roi": [x, y, w, h], "dtype": str(raw.dtype),
                               "cfa_site":cfa_site if native_dn and source.metadata.is_raw else None,
                               "sensor_white_level":source.raw_info.get('white_level') if native_dn and source.metadata.is_raw else None}


def _stack(paths, config, roi, channel, cancel, native_dn=False, cfa_site=None):
    frames, sources = [], []
    for path in paths:
        check_cancel(cancel)
        a, source = read_pixels(path, config, roi, channel, cancel, native_dn,cfa_site)
        if frames and a.shape != frames[0].shape:
            raise ValueError("多帧尺寸不匹配")
        if (len(frames)+1)*a.nbytes*4 > config.budget_bytes()*.6:
            raise MemoryError("多帧缓存超过内存预算，请减小 ROI 或帧数")
        frames.append(a); sources.append(source)
    return frames, sources


def run_workflow(spec, destination, config=None, cancel=None, progress=None):
    from .analysis.preprocess import channel_image
    kind = spec.get("workflow")
    if kind not in WORKFLOWS:
        raise ValueError("未知工作台任务")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    config = AnalysisConfig.from_dict({**(config or AnalysisConfig()).to_dict(), **spec.get("config", {})}).validate()
    p = {**WORKFLOWS[kind][1], **spec.get("parameters", {})}
    paths = list(spec.get("files", []))
    sources, artifacts = [], []
    progress = progress or (lambda *args: None)
    progress(5, WORKFLOWS[kind][0])
    check_cancel(cancel)
    if kind == "compare":
        from .analysis.quality import compare_images
        if len(paths) != 2:
            raise ValueError("双图比较需要恰好两张已对齐的图像")
        arrays, sources = _stack(paths, config, p.get("roi"), p.get("channel"), cancel)
        output = compare_images(*arrays)
    elif kind == "ptc":
        from .analysis.sensor import photon_transfer
        dark_count, size = int(p["dark_count"]), int(p["group_size"])
        if dark_count < 2 or size < 2 or (len(paths)-dark_count) % size or len(paths)-dark_count < 4*size:
            raise ValueError("先选择至少 2 张暗场，再按曝光分组选择至少 4 组平场，每组至少两帧")
        arrays, sources = _stack(paths, config, p.get("roi"), p.get("channel"), cancel, native_dn=True,cfa_site=p.get('cfa_site'))
        if any(s.get('sensor_white_level') and p['saturation_dn']>s['sensor_white_level'] for s in sources):raise ValueError('饱和 DN 超过 RAW 白电平，请按实际传感器填写')
        maximum = int(np.iinfo(np.dtype(sources[0]['dtype'])).max) if np.dtype(sources[0]['dtype']).kind in 'ui' else None
        if maximum and p['saturation_dn'] > maximum:
            raise ValueError('饱和 DN 超过输入数据类型上限')
        output = photon_transfer(arrays[:dark_count], [arrays[i:i+size] for i in range(dark_count, len(arrays), size)], float(p["saturation_dn"]), p["fit_range"])
    elif kind == "dark_flat":
        from .analysis.sensor import dark_flat_calibration
        dark_count, flat_count = int(p["dark_count"]), int(p["flat_count"])
        if min(dark_count, flat_count) < 2 or len(paths) <= dark_count+flat_count:
            raise ValueError("依次选择至少两暗场、两平场及至少一张待校正图")
        arrays, sources = _stack(paths, config, p.get("roi"), p.get("channel"), cancel)
        offset, gain, valid = dark_flat_calibration(arrays[:dark_count], arrays[dark_count:dark_count+flat_count])
        np.savez_compressed(destination/"dark-flat.npz", offset=offset, gain=gain, valid=valid)
        artifacts.append(str(destination/"dark-flat.npz"))
        import tifffile
        for i, image in enumerate(arrays[dark_count+flat_count:]):
            corrected = (image-offset)*gain
            target = destination/f"corrected-{i+1:03d}.tif"
            tifffile.imwrite(target, corrected.astype(np.float32), metadata={"description": "linear dark/flat corrected; see valid mask"})
            artifacts.append(str(target))
        output = {"valid_pixel_fraction": float(np.mean(valid)), "corrected_count": len(paths)-dark_count-flat_count,
                  "warnings": ["校正仅适用于同温度、增益、曝光条件与固定像素坐标；无响应像素在 valid 掩码中标记。"]}
    elif kind == "ccm":
        from .analysis.tone_color import fit_color_matrix
        if paths:
            result = AnalysisResult.load(paths[0])
            refs = {r["id"]: r.get("params", {}) for r in result.template["regions"]}
            unique = {m.region_id: m for m in result.measurements if m.kind == "color" and m.values.get("mean_R") is not None and "clipped" not in m.flags}
            matched = [(m, refs[m.region_id]) for m in unique.values() if "reference_lab" in refs[m.region_id]]
            if len({r.get("reference_illuminant", "D65") for _, r in matched}) > 1:
                raise ValueError("CCM 色块参考白点必须一致")
            measured = [[m.values["mean_"+c] for c in "RGB"] for m, _ in matched]
            reference = [r["reference_lab"] for _, r in matched]
            illuminant = matched[0][1].get("reference_illuminant", "D65") if matched else p["illuminant"]
            sources.append({"path": paths[0], "sha256": file_fingerprint(paths[0]), "image_sha256": result.image.fingerprint})
        else:
            measured, reference, illuminant = p.get("measured_rgb"), p.get("reference_lab"), p["illuminant"]
        output = fit_color_matrix(measured, reference, illuminant, p.get("weights"), bool(p["offset"]), bool(p["optimize_lab"]))
        atomic_json(destination/"color-matrix.json", output); artifacts.append(str(destination/"color-matrix.json"))
    elif kind == "oecf":
        from .analysis.tone_color import export_oecf
        if len(paths) != 1:
            raise ValueError("请选择一份含灰阶汇总的 result.json")
        output = export_oecf(AnalysisResult.load(paths[0]), p["channel"])
        atomic_json(destination/"oecf.json", output); artifacts.append(str(destination/"oecf.json"))
        sources.append({"path": paths[0], "sha256": file_fingerprint(paths[0])})
    elif kind == "calibrate":
        import cv2
        from .analysis.geometry import calibrate_camera, detect_dot_grid
        rows, cols = int(p["rows"]), int(p["cols"])
        if not 3 <= rows <= 50 or not 3 <= cols <= 50 or not 0 < float(p["square_mm"]) < 10000:
            raise ValueError("无效标定行列或尺寸")
        objects, images, rejected, geometry = [], [], [], None
        yy, xx = np.mgrid[:rows, :cols]
        obj = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(rows*cols)]).astype(np.float32)*float(p["square_mm"])
        for path in paths:
            check_cancel(cancel)
            pixels, source = read_pixels(path, config, channel="G", cancel=cancel)
            shape = (pixels.shape[1], pixels.shape[0])
            if geometry is not None and geometry != shape:
                raise ValueError("标定图像分辨率必须相同")
            geometry = shape
            if p["pattern"] == "checkerboard":
                found, corners = cv2.findChessboardCornersSB(np.clip(pixels*255, 0, 255).astype(np.uint8), (cols, rows))
                if not found:
                    rejected.append(path); continue
            elif p["pattern"] == "dot":
                try:
                    corners = detect_dot_grid(pixels, rows, cols)
                except ValueError:
                    rejected.append(path); continue
            else:
                raise ValueError("标定 pattern 需为 checkerboard 或 dot")
            objects.append(obj); images.append(corners); sources.append(source)
        output = calibrate_camera(objects, images, geometry)
        output["rejected_images"] = rejected
        atomic_json(destination/"camera-calibration.json", output); artifacts.append(str(destination/"camera-calibration.json"))
    elif kind == "undistort":
        import cv2, tifffile
        definition = json.loads(Path(p["calibration"]).read_text(encoding="utf-8-sig"))
        if definition.get("format") != "MUTEX OpenCV Camera Calibration":
            raise ValueError("需要多视图生成的 OpenCV 相机标定，不能混用单视图径向系数")
        matrix, distortion = np.array(definition["camera_matrix"]), np.array(definition["distortion"])
        for i, path in enumerate(paths):
            a, source = read_pixels(path, config, cancel=cancel)
            if [a.shape[1], a.shape[0]] != definition["image_size"]:
                raise ValueError("图像分辨率与标定不一致")
            corrected = cv2.undistort(a.astype(np.float32), matrix, distortion)
            target = destination/f"undistorted-{i+1:03d}.tif"
            tifffile.imwrite(target, corrected); artifacts.append(str(target)); sources.append(source)
        if not paths:
            raise ValueError("请选择待校正图像")
        output = {"corrected_count": len(paths), "calibration_sha256": file_fingerprint(p["calibration"]), "output_space": "linear floating point; resampled"}
    elif kind == "video":
        from .analysis.temporal import video_frames, analyze_frames
        import itertools
        if len(paths) != 1:
            raise ValueError("请选择一个视频文件")
        pairs, fps = video_frames(paths[0], int(p["every"]), int(p["max_frames"]), cancel)
        first, second = itertools.tee(pairs)
        output = analyze_frames((a for a, _ in first), (t for _, t in second), config, p.get("roi"), p.get("target_gray"), p["tolerance"], p["step_time"], p["stable_duration"], cancel)
        output["container_fps"] = fps
        sources.append({"path": paths[0], "sha256": file_fingerprint(paths[0])})
    elif kind == "sequence":
        from .analysis.extra import temporal_noise
        from .analysis.temporal import analyze_frames
        arrays, sources = _stack(paths, config, p.get("roi"), None, cancel)
        if len(arrays) < 3:
            raise ValueError("重复帧分析至少需要 3 张匹配图像")
        timing = p.get("times_seconds") or (np.arange(len(arrays))*float(p["interval_seconds"])).tolist()
        linear = AnalysisConfig.from_dict(dict(config.to_dict(), transfer="linear"))
        output = analyze_frames(arrays, timing, linear, cancel=cancel)
        output["noise"] = temporal_noise([channel_image(a, p["channel"]) for a in arrays])
        output["timestamp_source"] = "user supplied" if p.get("times_seconds") else "assumed constant interval supplied by user"
    elif kind == "simulate":
        from .analysis.simulation import simulate
        import tifffile
        if len(paths) != 1:
            raise ValueError("仿真需要一张线性参考图像")
        a, source = read_pixels(paths[0], config, p.get("roi"), cancel=cancel)
        # Evaluation settings describe the report, never the simulator's model.
        simulation_parameters = {key: value for key, value in p.items() if key not in {"roi", "evaluation_targets"}}
        simulated, output = simulate(a, **simulation_parameters)
        tifffile.imwrite(destination/"simulated.tif", simulated)
        artifacts.append(str(destination/"simulated.tif")); sources.append(source)
    elif kind == "capture":
        import cv2, tifffile
        count, interval = int(p["count"]), float(p["interval_seconds"])
        if not 1 <= count <= 1000 or not 0 <= interval <= 60:
            raise ValueError("采集帧数需在 1–1000，间隔 0–60 秒")
        camera = p.get("camera_index")
        source = int(camera) if camera is not None else p.get("source") or (paths[0] if paths else None)
        if source is None or source == "":
            raise ValueError("请选择视频源，或明确填写 camera_index")
        capture = cv2.VideoCapture(source, cv2.CAP_DSHOW) if isinstance(source, int) else cv2.VideoCapture(str(source))
        records = []
        try:
            if not capture.isOpened():
                raise ValueError("采集源无法打开，设备可能被占用或缺少驱动")
            start = time.monotonic()
            for i in range(count):
                check_cancel(cancel)
                ok, bgr = capture.read()
                if not ok:
                    break
                target = destination/f"capture-{i+1:04d}.tif"
                tifffile.imwrite(target, cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                records.append({"file": str(target), "time_s": time.monotonic()-start}); artifacts.append(str(target))
                if isinstance(source, int):
                    deadline = time.monotonic()+interval
                    while time.monotonic() < deadline:
                        check_cancel(cancel); time.sleep(min(.05, max(0, deadline-time.monotonic())))
        finally:
            capture.release()
        if not records:
            raise ValueError("采集源没有有效图像")
        output = {"captured": len(records), "frames": records, "requested": count, "complete": len(records) == count,
                  "warnings": ["DirectShow/视频源输出为驱动转换的 RGB 8-bit，非传感器 RAW。"]}
    elif kind == "test_plan":
        from .test_manager import run_plan
        plan_path = p.get("plan") or (paths[0] if paths else None)
        if not plan_path:
            raise ValueError("请选择测试计划 JSON")
        output = run_plan(json.loads(Path(plan_path).read_text(encoding="utf-8-sig")), destination, config, cancel, progress)
        sources.append({"path": plan_path, "sha256": file_fingerprint(plan_path)})
    else:
        import cv2
        from .analysis.sfr import slanted_edge
        rows = []
        for path in paths:
            a, source = read_pixels(path, config, p.get("roi"), p.get("channel", "G"), cancel)
            edge = slanted_edge(a, config)
            clip=float(np.mean((a<=0)|(a>=1)))
            mtf = edge.get("values", {}).get("mtf50") if not set(edge.get("flags", [])) & {"invalid_edge", "low_contrast", "insufficient_samples"} and not (config.reject_clipping and clip>config.maximum_clip_fraction) else None
            tenengrad = float(np.mean(cv2.Sobel(a, cv2.CV_64F, 1, 0)**2+cv2.Sobel(a, cv2.CV_64F, 0, 1)**2))
            rows.append({"file": path, "mtf50": mtf, "focus_score": tenengrad, "mean": float(a.mean()),'clipped_fraction':clip}); sources.append(source)
        if not rows:
            raise ValueError("请选择待排名图像")
        rows.sort(key=lambda row: row["mtf50"] if row["mtf50"] is not None else -1, reverse=True)
        output = {"ranking": rows, "warnings": ["按有效 MTF50 排名；无有效斜边的图像保留相对焦点评分，排在末尾。"]}
    check_cancel(cancel)
    from .lab_evaluation import assess_workflow
    evaluation = assess_workflow(kind, output, dict(p, _input_transfer=config.transfer))
    report = {"format": "MUTEX IQ Workbench", "version": 1, "workflow": kind, "name": WORKFLOWS[kind][0],
              "created_utc": datetime.now(timezone.utc).isoformat(), "specification": spec, "settings": config.to_dict(),
              "sources": sources, "output": output, "artifacts": artifacts, "evaluation": evaluation}
    atomic_json(destination/"lab-result.json", report)
    export_lab_report(report, destination)
    progress(100, "测量及离线报告已保存")
    return report


def export_lab_report(report, destination):
    from .lab_evaluation import assess_workflow, evaluation_html
    destination = Path(destination)
    if not isinstance(report.get("evaluation"), dict):
        report = dict(report, evaluation=assess_workflow(report.get("workflow"), report.get("output", {}),
                      report.get("specification", {}).get("parameters", {})))
    text = json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False)
    esc = lambda value: html.escape(str(value), quote=True)
    tables = []
    for name, data in report["output"].items():
        if isinstance(data, list) and data and isinstance(data[0], dict):
            keys = list(dict.fromkeys(k for row in data for k in row))
            with (destination/(name+".csv")).open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=keys); writer.writeheader()
                writer.writerows([{k: json.dumps(plain(v), ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in data])
            rows = "".join("<tr>"+"".join(f"<td>{esc(row.get(k, ''))}</td>" for k in keys)+"</tr>" for row in data[:500])
            tables.append(f"<h2>{esc(name)}</h2><div class='scroll'><table><thead><tr>"+"".join(f"<th>{esc(k)}</th>" for k in keys)+f"</tr></thead><tbody>{rows}</tbody></table></div>")
    content = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(report['name'])}</title><style>body{{font:14px/1.6 'Microsoft YaHei',system-ui;background:#eef3f6;color:#193343;margin:0}}main{{max-width:1200px;background:white;margin:24px auto;padding:28px;border-radius:10px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;padding:18px}}table{{border-collapse:collapse;font-size:12px}}td,th{{padding:8px;border-bottom:1px solid #d8e2ea;text-align:left;overflow-wrap:anywhere}}.scroll{{overflow:auto}}button{{padding:8px 16px}}.evaluation{{width:100%}}.evaluation td{{vertical-align:top}}.evaluation td:first-child{{width:18%}}.evaluation td:nth-child(2){{width:12%}}.verdict{{display:inline-block;padding:3px 7px;border-radius:4px;background:#e9eef4;color:#344c61;font-weight:600}}.within_target,.complete{{background:#daf1e7;color:#075e3b}}.outside_target,.invalid,.incomplete{{background:#fde1e4;color:#9b1831}}.review,.insufficient,.estimate,.needs_target{{background:#fff0cc;color:#77500b}}a{{color:#006a83}}@media print{{button{{display:none}}main{{margin:0;padding:0}}.scroll{{overflow:visible}}thead{{display:table-header-group}}tr{{break-inside:avoid}}}}</style>
<main><h1>{esc(report['name'])}</h1><p>MUTEX Imatest · 独立工程测量 · {esc(report['created_utc'])}</p>
<p>完整输入指纹、设置、质量限制与输出保存在同目录 lab-result.json。所有数据均在本机处理。</p><button onclick="window.print()">打印 / 另存 PDF</button>
{evaluation_html(report['evaluation'])}{''.join(tables)}<h2>完整结果与测量条件</h2><pre>{esc(text)}</pre></main></html>"""
    (destination/"report.html").write_text(content, encoding="utf-8")
