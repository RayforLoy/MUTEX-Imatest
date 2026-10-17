"""Referenced tone/noise and color calibration, with explicit measurement limits."""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares
from ..models import Measurement


def reference_xyz(lab, illuminant="D65"):
    import colour
    if illuminant not in {"D50", "D65"}:
        raise ValueError("Lab 参考白点必须是 D50 或 D65")
    white = colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"][illuminant]
    xyz = colour.Lab_to_XYZ(np.asarray(lab, float), illuminant=white)
    if illuminant != "D65":
        d65 = colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"]["D65"]
        xyz = colour.adaptation.chromatic_adaptation_VonKries(xyz, colour.xy_to_XYZ(white), colour.xy_to_XYZ(d65), transform="Bradford")
    return np.asarray(xyz, float)


def color_metrics(linear_rgb, reference_lab, illuminant="D65"):
    import colour
    rgb = np.asarray(linear_rgb, float)
    ref_xyz = reference_xyz(reference_lab, illuminant)
    ref = colour.XYZ_to_Lab(ref_xyz)
    measured = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(rgb, apply_cctf_decoding=False))
    c, rc = np.hypot(measured[1], measured[2]), np.hypot(ref[1], ref[2])
    return {"L": float(measured[0]), "a": float(measured[1]), "b": float(measured[2]),
            "delta_e_2000": float(colour.delta_E(measured, ref, method="CIE 2000")),
            "delta_e_76": float(np.linalg.norm(measured-ref)),
            "delta_l": float(measured[0]-ref[0]), "delta_c": float(c-rc),
            "chroma_ratio": float(c/rc) if rc > 1e-6 else None,
            "white_balance_delta_ab": float(np.hypot(*(measured[1:]-ref[1:]))) if rc < 5 else None}


def fit_color_matrix(measured_rgb, reference_lab, illuminant="D65", weights=None, offset=False, optimize_lab=True):
    import colour
    rgb, lab = np.asarray(measured_rgb, float), np.asarray(reference_lab, float)
    if rgb.ndim != 2 or rgb.shape[1] != 3 or lab.shape != rgb.shape or len(rgb) < 6 or not np.all(np.isfinite([rgb, lab])):
        raise ValueError("CCM 至少需要 6 组有限的 RGB / Lab 三元组")
    xyz = reference_xyz(lab, illuminant)
    target = colour.XYZ_to_sRGB(xyz, apply_cctf_encoding=False)
    design = np.column_stack([rgb, np.ones(len(rgb))]) if offset else rgb
    if np.linalg.matrix_rank(design) < design.shape[1] or np.linalg.cond(design) > 1e6:
        raise ValueError("CCM 色块分布退化，请使用覆盖三维颜色空间的色块")
    weight = np.ones(len(rgb)) if weights is None else np.asarray(weights, float)
    if weight.shape != (len(rgb),) or not np.all(np.isfinite(weight)) or np.any(weight <= 0):
        raise ValueError("CCM 权重必须为每色块一个正数")
    root = np.sqrt(weight/weight.mean())
    beta = np.linalg.lstsq(design*root[:, None], target*root[:, None], rcond=None)[0]
    target_lab = colour.XYZ_to_Lab(xyz)
    if optimize_lab:
        def residual(parameters):
            corrected = design@parameters.reshape(beta.shape)
            predicted = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(corrected, apply_cctf_decoding=False))
            return ((predicted-target_lab)*root[:, None]).ravel()
        fitted = least_squares(residual, beta.ravel(), max_nfev=300)
        if not fitted.success:
            raise ValueError("CCM Lab 优化未收敛")
        beta = fitted.x.reshape(beta.shape)
    corrected = design@beta
    before_lab = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(rgb, apply_cctf_decoding=False))
    after_lab = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(corrected, apply_cctf_decoding=False))
    before = colour.delta_E(before_lab, target_lab, method="CIE 2000")
    after = colour.delta_E(after_lab, target_lab, method="CIE 2000")
    return {"format": "MUTEX Color Matrix", "version": 1, "input": "linear source RGB", "output": "linear sRGB D65",
            "matrix": beta[:3].tolist(), "offset": beta[3].tolist() if offset else [0, 0, 0],
            "convention": "output = input @ matrix + offset", "reference_illuminant": illuminant,
            "patch_count": len(rgb), "condition_number": float(np.linalg.cond(design)),
            "delta_e_2000_before": before.tolist(), "delta_e_2000_after": after.tolist(),
            "mean_delta_e_before": float(np.mean(before)), "mean_delta_e_after": float(np.mean(after)),
            "warnings": ["误差为拟合用色块误差；独立验证需另拍图卡，光源与输入解码必须保持一致。"]}


def apply_color_matrix(rgb, definition):
    if definition.get("format") != "MUTEX Color Matrix" or definition.get("version") != 1:
        raise ValueError("不支持的 CCM 定义")
    matrix, offset = np.asarray(definition["matrix"], float), np.asarray(definition["offset"], float)
    if matrix.shape != (3, 3) or offset.shape != (3,) or not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(offset)):
        raise ValueError("CCM 必须含有限 3×3 matrix 和 3 元素 offset")
    return np.asarray(rgb)[..., :3]@matrix+offset


def summarize_tone(measurements, chart, image_size):
    """Scene SNR = x dY/dx / sigma_Y. Never extrapolate beyond sampled exposure."""
    regions = {r.id: r for r in chart.regions}
    summaries = []
    for channel in dict.fromkeys(m.channel for m in measurements if m.kind == "step"):
        patches = [m for m in measurements if m.kind == "step" and m.channel == channel and m.values.get("mean") is not None]
        records = []
        for m in patches:
            p = regions[m.region_id].params
            x = 10**(-float(p["reference_density"])) if "reference_density" in p else p.get("reference_luminance")
            if x is not None and np.isfinite(x) and x > 0:
                records.append((float(x), m, p))
        if len(records) < 4:
            continue
        records.sort(key=lambda row: row[0])
        # Pool duplicate exposure levels, preserving the no-clipping gate.
        levels = sorted(set(row[0] for row in records))
        exposure, mean, noise, encoded, clipped = [], [], [], [], []
        for x in levels:
            rows = [(m, p) for level, m, p in records if level == x]
            exposure.append(x)
            mean.append(float(np.median([m.values["mean"] for m, _ in rows])))
            noise.append(float(np.sqrt(np.mean([m.values["noise"]**2 for m, _ in rows]))))
            encoded.append(float(np.median([m.values.get("encoded_mean", m.values["mean"]) for m, _ in rows])))
            clipped.append(any(m.values.get("white_clip_fraction", 0) > .01 or m.values.get("black_clip_fraction", 0) > .01 or m.values.get('clipping_fraction',0)>.01 for m, _ in rows))
        x, y, sigma = map(np.asarray, (exposure, mean, noise))
        enc, clipped = np.array(encoded), np.array(clipped)
        if len(x) < 4:
            continue
        monotonic = bool(np.all(np.diff(y) > 0))
        good = ~clipped & np.isfinite(y) & (y > 0) & np.isfinite(enc) & (enc > 0)
        flags = ["single_frame_spatial_noise", "measured_exposure_range_only"]
        values = {"tone_patch_count": len(records), "tone_unique_levels": len(x),
                  "tone_monotonic": int(monotonic), "measured_tonal_range_stops": float(np.log2(x[-1]/x[0]))}
        if good.sum() >= 4 and np.all(np.diff(enc[good]) > 0):
            slope, intercept = np.polyfit(np.log10(x[good]), np.log10(enc[good]), 1)
            predicted = slope*np.log10(x[good])+intercept
            values["oecf_gamma"] = float(slope)
            values["oecf_fit_rms_log"] = float(np.sqrt(np.mean((predicted-np.log10(enc[good]))**2)))
        snr = np.full(len(x), np.nan)
        if monotonic:
            # Derivative in log exposure is stable on density-spaced patches.
            derivative = np.gradient(y, np.log(x))
            np.divide(derivative, sigma, out=snr, where=sigma > 0)
        else:
            flags.append("nonmonotonic_oecf")
        # A reflective chart does not establish sensor/camera dynamic range.
        transmission = all(bool(p.get("transmissive")) for _, _, p in records)
        if transmission and monotonic and good.sum() >= 4:
            maximum = int(np.flatnonzero(good)[-1])
            for threshold in (1, 2, 10, 20):
                # Start at the bright reference and walk downward contiguously.
                if not np.isfinite(snr[maximum]) or snr[maximum] < threshold:
                    continue
                lowest = maximum
                while lowest > 0 and good[lowest-1] and np.isfinite(snr[lowest-1]) and snr[lowest-1] >= threshold:
                    lowest -= 1
                limit = x[lowest]
                bounded = lowest > 0 and good[lowest-1] and np.isfinite(snr[lowest-1]) and snr[lowest-1] > 0
                if bounded and snr[lowest-1] < threshold and snr[lowest] > snr[lowest-1]:
                    t = (np.log(threshold)-np.log(snr[lowest-1]))/(np.log(snr[lowest])-np.log(snr[lowest-1]))
                    limit = np.exp(np.log(x[lowest-1])+t*np.log(x[lowest]/x[lowest-1]))
                values[f"dynamic_range_snr{threshold}_stops"] = float(np.log2(x[maximum]/limit))
                values[f"dynamic_range_snr{threshold}_lower_bound"] = int(not bounded)
        elif not transmission:
            flags.append("reflective_chart_no_sensor_dr")
        width, height = image_size
        curves = {"oecf": {"x": x.tolist(), "y": enc.tolist(), "x_unit": "relative exposure", "y_unit": "encoded signal"},
                  "linear_response": {"x": x.tolist(), "y": y.tolist(), "x_unit": "relative exposure", "y_unit": "linear signal"},
                  "scene_snr": {"x": np.log2(x/x[-1]).tolist(), "y": snr.tolist(), "x_unit": "stops below brightest reference", "y_unit": "scene SNR"}}
        units = {k: "stops" if k.endswith("_stops") else "ratio" for k in values}
        summaries.append(Measurement("tone-summary", "灰阶 / OECF / 动态范围汇总", "tone_summary", channel,
                                     (width/2, height/2), (0, 0, width, height), values, units, curves, flags,
                                     1 if monotonic else .3, "scene-derivative-snr/measured-range"))
    return summaries


def export_oecf(result, channel="G"):
    found = next((m for m in result.measurements if m.kind == "tone_summary" and m.channel == channel), None)
    if found is None or not found.values.get("tone_monotonic"):
        raise ValueError("需要单调且至少四级有效灰阶的 OECF 结果")
    curve = found.curves["oecf"]
    encoded, linear = np.asarray(curve["y"]), np.asarray(curve["x"])
    if np.any(np.diff(encoded) <= 0) or np.any(encoded < 0) or np.any(encoded > 1):
        raise ValueError("编码值重复、非单调或越界，不能导出线性化表")
    linear = linear/linear[-1]
    return {"encoded": encoded.tolist(), "linear": linear.tolist(), "channel": channel,
            "source_fingerprint": result.image.fingerprint,
            "normalization": "brightest measured reference = 1; outside measured range clamps to endpoints"}
