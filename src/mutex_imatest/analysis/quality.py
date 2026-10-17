"""Independent image-quality measurements; all arrays use native linear pixels.

These are engineering measurements, not implementations certified by Imatest,
ISO, IEEE or CPIQ. Missing references produce explicit failed measurements.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter, label, find_objects, uniform_filter
from scipy.signal import welch
from .sfr import first_crossing


def image_array(a, minimum=8):
    a = np.asarray(a, dtype=np.float64)
    if a.ndim != 2 or min(a.shape) < minimum or not np.all(np.isfinite(a)):
        raise ValueError(f"需要有限的二维像素数组，短边至少 {minimum} px")
    return a


def radial_spectrum(a, bins=64):
    a = image_array(a)
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    spectrum = np.abs(np.fft.fft2((a-a.mean())*window))**2 / np.sum(window**2)
    radius = np.hypot(np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :])
    index = np.minimum((radius*2*bins).astype(int), bins)
    count = np.bincount(index.ravel(), minlength=bins+1)
    power = np.bincount(index.ravel(), weights=spectrum.ravel(), minlength=bins+1)
    return (np.arange(bins)+.5)/(2*bins), power[:bins]/np.maximum(count[:bins], 1)


def uniformity(a, params, config):
    a = image_array(a)
    h, w = a.shape
    n = int(params.get("uniformity_grid", 9))
    if not 3 <= n <= 32 or min(h, w) < n*2:
        raise ValueError("均匀性网格应为 3–32，且每格至少 2 像素")
    tiles = np.array([[np.mean(t) for t in np.array_split(row, n, axis=1)]
                      for row in np.array_split(a, n, axis=0)])
    center = float(np.mean(a[h*2//5:h*3//5, w*2//5:w*3//5]))
    if center <= 0:
        raise ValueError("平场中心信号必须大于 0")
    corners = np.array([tiles[0, 0], tiles[0, -1], tiles[-1, 0], tiles[-1, -1]])
    background = gaussian_filter(a, max(4, min(h, w)/16))
    local = a-gaussian_filter(a, 1)
    noise = float(1.4826*np.median(np.abs(local-np.median(local))))
    threshold = max(float(params.get("defect_threshold", .05)), float(params.get("defect_sigma", 8))*noise)
    if threshold <= 0:
        raise ValueError("坏点阈值必须大于 0")
    # Pixel outliers and broad blemishes are separate masks.
    hot = (a-gaussian_filter(a, 1.5)) > threshold
    dead = (gaussian_filter(a, 1.5)-a) > threshold
    smooth_residual = gaussian_filter(a, 2)-background
    blemish_limit = float(params.get("blemish_threshold", .03))*center
    if blemish_limit <= 0:
        raise ValueError("污点相对阈值必须大于 0")
    mask = np.abs(smooth_residual) > blemish_limit
    margin = max(2, int(min(h, w)*.02))
    mask[:margin] = False; mask[-margin:] = False
    mask[:, :margin] = False; mask[:, -margin:] = False
    components, _ = label(mask)
    spots = []
    for i, box in enumerate(find_objects(components), 1):
        if box is None:
            continue
        selected = components[box] == i
        area = int(selected.sum())
        if area < int(params.get("blemish_min_area", 9)):
            continue
        yy, xx = np.nonzero(selected)
        spots.append({"x_px": float(xx.mean()+box[1].start), "y_px": float(yy.mean()+box[0].start),
                      "area_px": area, "peak_relative": float(np.max(np.abs(smooth_residual[box][selected]))/center)})
    yy, xx = np.mgrid[:h, :w]
    stride = max(1, int(np.sqrt(a.size/100000)))
    design = np.column_stack([np.ones(a[::stride, ::stride].size),
                              xx[::stride, ::stride].ravel()/w, yy[::stride, ::stride].ravel()/h])
    fit = np.linalg.lstsq(design, a[::stride, ::stride].ravel(), rcond=None)[0]
    residual = a-(fit[0]+fit[1]*xx/w+fit[2]*yy/h)
    f, nps = radial_spectrum(residual)
    values = {"relative_illumination_min_pct": float(100*tiles.min()/center),
              "corner_illumination_pct": float(100*corners.mean()/center),
              "illumination_nonuniformity_pct": float(100*(tiles.max()-tiles.min())/center),
              "hot_pixel_count": int(hot.sum()), "dead_pixel_count": int(dead.sum()),
              "blemish_count": len(spots), "defect_fraction_pct": float(100*np.mean(hot|dead)),
              "nps_integral": float(np.mean(residual**2))}
    if config.transfer != "unknown":
        values["corner_falloff_ev"] = float(-np.log2(max(corners.mean()/center, 1e-12)))
    return {"values": values, "flags": ["single_frame_defect_candidates"], "confidence": 1,
            "curves": {"radial_nps": {"x": f.tolist(), "y": nps.tolist(), "x_unit": "cy/px", "y_unit": "signal²/(cy/px)²"},
                       "illumination_grid": {"x": list(range(n*n)), "y": (100*tiles/center).ravel().tolist(), "x_unit": "row-major tile", "y_unit": "% of center"}},
            "blemishes": spots, "grid": tiles.tolist()}


def compare_images(reference, image, data_range=1.0):
    """Wang et al. SSIM, Gaussian 11x11 sigma=1.5, population covariance.

    Discard the five-pixel filter boundary. Do not register or rescale inputs.
    """
    a, b = np.asarray(reference, float), np.asarray(image, float)
    if a.shape != b.shape or a.ndim not in {2, 3} or min(a.shape[:2]) < 11:
        raise ValueError("SSIM 需要同尺寸、已对齐的图像，短边至少 11 px")
    if not np.isfinite(data_range) or data_range <= 0 or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError("像素与 data_range 必须有限，data_range 必须大于 0")
    if a.ndim == 3:
        results = [compare_images(a[..., i], b[..., i], data_range) for i in range(a.shape[2])]
        mse = float(np.mean((a-b)**2))
        return {"mse": mse, "psnr_db": float(10*np.log10(data_range**2/mse)) if mse else None,
                "identical": bool(mse == 0), "ssim": float(np.mean([r["ssim"] for r in results])), "channels": results}
    ma = gaussian_filter(a, 1.5, truncate=3.5)
    mb = gaussian_filter(b, 1.5, truncate=3.5)
    va = np.maximum(gaussian_filter(a*a, 1.5, truncate=3.5)-ma*ma, 0)
    vb = np.maximum(gaussian_filter(b*b, 1.5, truncate=3.5)-mb*mb, 0)
    cov = gaussian_filter(a*b, 1.5, truncate=3.5)-ma*mb
    c1, c2 = (.01*data_range)**2, (.03*data_range)**2
    score = (2*ma*mb+c1)*(2*cov+c2)/((ma*ma+mb*mb+c1)*(va+vb+c2))
    mse = float(np.mean((a-b)**2))
    return {"mse": mse, "psnr_db": float(10*np.log10(data_range**2/mse)) if mse else None,
            "identical": bool(mse == 0), "ssim": float(np.mean(score[5:-5, 5:-5]))}


def texture_transfer(a, reference, noise=None):
    """PSD-ratio texture response for matched chart scale and transfer curve."""
    a, reference = image_array(a, 32), image_array(reference, 32)
    if a.shape != reference.shape:
        raise ValueError("纹理参考和被测 ROI 必须同尺寸、同图案尺度")
    f, observed = radial_spectrum(a)
    _, original = radial_spectrum(reference)
    if noise is not None:
        noise = image_array(noise, 32)
        if noise.shape != a.shape:
            raise ValueError("噪声参考必须与纹理 ROI 同尺寸")
        _, nps = radial_spectrum(noise)
        observed = np.maximum(observed-nps, 0)
    valid = original > max(original.max()*1e-8, 1e-16)
    response = np.sqrt(observed[valid]/original[valid])
    freq = f[valid]
    if len(freq) < 12 or np.mean(original) < 1e-12:
        raise ValueError("纹理参考频率覆盖不足")
    norm = float(np.median(response[:4]))
    if norm <= 0:
        raise ValueError("纹理低频参考不足")
    response /= norm
    flags = ["matched_reference_psd_ratio", "not_iso_texture_mtf"]
    if noise is None:
        flags.append("noise_not_subtracted")
    return {"values": {"texture_mtf50": first_crossing(freq, response, .5),
                       "texture_mtf10": first_crossing(freq, response, .1),
                       "texture_acutance_area": float(np.trapezoid(response, freq)/.5)},
            "curves": {"texture_response": {"x": freq.tolist(), "y": response.tolist(), "x_unit": "cy/px", "y_unit": "normalized PSD amplitude ratio"}},
            "flags": flags, "confidence": 1}


def log_frequency(a, params, config):
    """Local sine regression at the target's declared log-frequency geometry."""
    a = image_array(a, 32)
    if params.get("direction", "vertical") == "horizontal":
        a = a.T
    h, w = a.shape
    f0, f1 = float(params.get("f_start", 0)), float(params.get("f_end", 0))
    reference = float(params.get("reference_modulation", 0))
    if not 0 < f0 < f1 <= .5 or not 0 < reference <= 1:
        return {"values": {}, "curves": {}, "flags": ["missing_reference"], "confidence": 0}
    x = np.arange(w)
    rate = np.log(f1/f0)/(w-1)
    phase = 2*np.pi*f0*np.expm1(rate*x)/rate+float(params.get("phase_rad", 0))
    frequencies, responses, errors = [], [], []
    for cx in np.linspace(w*.06, w*.94, 48):
        freq = f0*np.exp(rate*cx)
        half = max(8, int(2/freq))
        lo, hi = max(0, int(cx)-half), min(w, int(cx)+half+1)
        if hi-lo < 16 or phase[hi-1]-phase[lo] < 4*np.pi:
            continue
        p = phase[lo:hi]
        design = np.column_stack([np.ones(len(p)), np.sin(p), np.cos(p), np.linspace(-1, 1, len(p))])
        profile = np.mean(a[:, lo:hi], axis=0)
        beta = np.linalg.lstsq(design, profile, rcond=None)[0]
        modulation = np.hypot(beta[1], beta[2])/max(abs(beta[0]), 1e-12)
        frequencies.append(float(freq)); responses.append(float(modulation/reference))
        errors.append(float(np.sqrt(np.mean((design@beta-profile)**2))))
    if len(frequencies) < 8:
        return {"values": {}, "curves": {}, "flags": ["insufficient_samples"], "confidence": 0}
    binary = params.get("pattern", "sinusoidal") == "binary"
    # A square wave has fundamental amplitude 4/pi times its Michelson modulation.
    if binary:
        responses = (np.asarray(responses)*np.pi/4).tolist()
    prefix = "log_ctf" if binary else "log_mtf"
    return {"values": {prefix+"50": first_crossing(frequencies, responses, .5),
                       prefix+"10": first_crossing(frequencies, responses, .1),
                       "log_fit_rms": float(np.mean(errors))},
            "curves": {"log_frequency_response": {"x": frequencies, "y": responses, "x_unit": "cy/px", "y_unit": "CTF fundamental" if binary else "MTF"}},
            "flags": ["declared_log_geometry"]+(["square_wave_fundamental"] if binary else []), "confidence": 1}


def flare(a, params, config):
    a = image_array(a)
    # Boxes are normalized to the ROI; the dark box is an actual shielded trap.
    def sample(key):
        box = params.get(key)
        if box is None or len(box) != 4:
            raise ValueError("眩光测量需要 dark_box 与 bright_box（ROI 内归一化坐标）")
        x, y, w, h = map(float, box)
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > 1 or y+h > 1:
            raise ValueError("眩光取样框越界")
        return a[int(y*a.shape[0]):max(int(y*a.shape[0])+1, int((y+h)*a.shape[0])),
                 int(x*a.shape[1]):max(int(x*a.shape[1])+1, int((x+w)*a.shape[1]))]
    dark, bright = sample("dark_box"), sample("bright_box")
    offset = float(params.get("black_level", 0))
    d, b = float(np.mean(dark)-offset), float(np.mean(bright)-offset)
    if b <= 0 or d < 0:
        raise ValueError("扣除黑电平后的眩光参考无效")
    flags = ["engineering_trap_ratio", "not_iso_ieee_flare_certification"]
    if config.transfer == "unknown":
        flags.append("transfer_unknown")
    return {"values": {"veiling_glare_pct": float(100*d/b), "flare_dark_mean": d, "flare_bright_mean": b},
            "flags": flags, "curves": {}, "confidence": 1}


def color_moire(rgb):
    rgb = np.asarray(rgb, float)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        return {}
    y = np.einsum("ijk,k->ij", rgb[..., :3], [.2126, .7152, .0722])
    chroma = rgb[..., :3]-y[..., None]
    high = chroma-gaussian_filter(chroma, (2, 2, 0))
    return {"color_moire_rms": float(np.sqrt(np.mean(high**2))),
            "color_moire_pct": float(100*np.sqrt(np.mean(high**2))/max(np.mean(y), 1e-12))}


def edge_information(result, a, params=None):
    """Measured flat-side NPS + MTF Shannon integral (1D, bits/pixel).

    Explicit white-input model; this is not Imatest C4/Cmax/NEQ or CPIQ acutance.
    """
    if "sfr" not in result.get("curves", {}) or "invalid_edge" in result.get("flags", []):
        return
    a = image_array(a)
    if abs(result.get("normal", [1, 0])[1]) > .7:
        a = a.T
    n = max(8, a.shape[1]//6)
    sides = [a[:, :n], a[:, -n:]]
    spectra = []
    for side in sides:
        # Spectral density along the edge-normal direction, native sampling.
        side = side-np.mean(side, axis=1, keepdims=True)
        f, power = welch(side, axis=1, nperseg=min(n, 128), detrend="constant", scaling="density")
        spectra.append(np.mean(power, axis=0))
    nps = np.mean(spectra, axis=0)
    noise_var = float(np.trapezoid(nps, f))
    signal_var = float(result["values"].get("contrast", 0))**2/12
    curve = result["curves"]["sfr"]
    freq, mtf = np.array(curve["x"]), np.array(curve["y"])
    # One-sided noise PSD and white-input PSD both integrate over [0,.5].
    noise = np.interp(freq, f, nps)
    if noise_var > 1e-16 and signal_var > 0:
        capacity = float(np.trapezoid(np.log2(1+2*signal_var*mtf**2/np.maximum(noise, 1e-16)), freq))
        result["values"]["information_capacity_1d"] = capacity
    result["values"]["edge_noise_rms"] = float(np.sqrt(max(noise_var, 0)))
    result["values"]["mtf_area"] = float(np.trapezoid(mtf, freq)/.5)
    result["curves"]["edge_nps"] = {"x": f.tolist(), "y": nps.tolist(), "x_unit": "cy/px", "y_unit": "signal²/(cy/px)"}
    result.setdefault("flags", []).append("white_input_information_model")
