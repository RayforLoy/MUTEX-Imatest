"""Paired-frame PTC and calibrated dark/flat measurements in digital numbers."""
from __future__ import annotations

import numpy as np
from scipy.optimize import nnls


def _frames(values):
    a = np.asarray(values, float)
    if a.ndim != 3 or a.shape[0] < 2 or min(a.shape[1:]) < 8 or not np.all(np.isfinite(a)):
        raise ValueError("每组需要至少 2 张匹配的二维暗场 / 平场，短边至少 8 px")
    return a


def photon_transfer(dark_frames, flat_groups, saturation_dn, fit_range=(.05, .75)):
    dark = _frames(dark_frames)
    if not np.isfinite(saturation_dn) or saturation_dn <= 0 or not 0 < fit_range[0] < fit_range[1] < 1:
        raise ValueError("需要有效饱和 DN 和 0–1 范围内的 PTC 拟合区间")
    if len(flat_groups) < 4:
        raise ValueError("PTC 至少需要 4 个不同曝光级别，每级至少两帧")
    dark_mean = dark.mean(axis=0)
    dark_var = dark.var(axis=0, ddof=1)
    read_var = float(np.mean(dark_var))
    black = float(dark_mean.mean())
    dsnu_var = max(0, float(dark_mean.var(ddof=1))-read_var/len(dark))
    records = []
    for group in flat_groups:
        frames = _frames(group)
        if frames.shape[1:] != dark.shape[1:]:
            raise ValueError("PTC 暗场与平场尺寸必须匹配")
        # Average all disjoint differences; fixed pattern cancels before fitting.
        pairs = frames[:len(frames)//2*2].reshape(-1, 2, *frames.shape[1:])
        differences = (pairs[:, 0]-pairs[:, 1])/np.sqrt(2)
        pair_variances = np.var(differences, axis=(1, 2), ddof=1)
        signal = float(np.mean(frames)-black)
        temporal = float(np.mean(pair_variances))
        mean_frame = frames.mean(axis=0)-dark_mean
        fixed = max(0, float(np.var(mean_frame, ddof=1))-temporal/len(frames)-read_var/len(dark))
        records.append({"signal_dn": signal, "variance_dn2": temporal,
                        "prnu_pct": float(100*np.sqrt(fixed)/signal) if signal > 0 else None,
                        "clipped_fraction": float(np.mean((frames >= saturation_dn)|(frames <= 0))), "frame_count": len(frames)})
    records.sort(key=lambda r: r["signal_dn"])
    usable = [r for r in records if fit_range[0]*(saturation_dn-black) <= r["signal_dn"] <= fit_range[1]*(saturation_dn-black) and r["clipped_fraction"] < .001]
    if len(usable) < 4 or len(set(round(r["signal_dn"], 6) for r in usable)) < 4:
        raise ValueError("未剪切、位于拟合区间内的独立曝光级别少于 4")
    x = np.array([r["signal_dn"] for r in usable]); y = np.array([r["variance_dn2"] for r in usable])
    # In DN units: temporal variance = read_variance + gain_DN/e * signal_DN.
    gain, intercept = np.linalg.lstsq(np.column_stack([x, np.ones(len(x))]), y, rcond=None)[0]
    if gain <= 0 or np.ptp(x) < (saturation_dn-black)*.1:
        raise ValueError("PTC 斜率非正或曝光覆盖不足；请检查非线性处理、降噪和配对")
    residual = y-(gain*x+intercept)
    r2 = 1-float(np.sum(residual**2))/max(float(np.sum((y-y.mean())**2)), 1e-20)
    full_well = (saturation_dn-black)/gain
    read_e = np.sqrt(read_var)/gain
    # Total spatial model adds signal-proportional fixed pattern; fit scaled axes.
    all_x = np.array([r["signal_dn"]/(saturation_dn-black) for r in usable])
    model_design = np.column_stack([np.ones(len(x)), all_x, all_x**2])
    coefficients, _ = nnls(model_design, y/(saturation_dn-black)**2)
    warnings = ["工程 PTC；需未处理、线性、同温度与同增益像素，不构成 EMVA1288 认证。",
                "PRNU 同时包含照明/靶材不均匀性；饱和 DN 由用户提供，非自动实测满阱。"]
    if r2 < .98:
        warnings.append("PTC 线性拟合 R² 低于 0.98，增益和电子数估计需复核。")
    return {"gain_dn_per_e": float(gain), "gain_e_per_dn": float(1/gain), "black_level_dn": black,
            "read_noise_dn": float(np.sqrt(read_var)), "read_noise_e": float(read_e),
            "dsnu_dn": float(np.sqrt(dsnu_var)), "dsnu_e": float(np.sqrt(dsnu_var)/gain),
            "estimated_full_well_e": float(full_well),
            "estimated_dynamic_range_stops": float(np.log2(full_well/read_e)) if read_e > 0 else None,
            "prnu_pct": float(np.median([r["prnu_pct"] for r in usable])),
            "ptc_r_squared": r2, "variance_intercept_dn2": float(intercept),
            "normalized_temporal_noise_model": coefficients.tolist(),
            "fit_range": list(fit_range), "fitted_levels": len(usable), "levels": records, "warnings": warnings}


def dark_flat_calibration(dark_frames, flat_frames):
    dark, flat = _frames(dark_frames), _frames(flat_frames)
    if dark.shape[1:] != flat.shape[1:]:
        raise ValueError("暗平场尺寸不匹配")
    offset = dark.mean(axis=0)
    response = flat.mean(axis=0)-offset
    mean = float(response.mean())
    if mean <= 0:
        raise ValueError("平场减暗场后信号必须大于 0")
    valid = response > mean*.1
    gain = np.divide(mean, response, out=np.ones_like(response), where=valid)
    return offset, gain, valid
