"""Deterministic, explicitly parameterized optical/sensor/ISP simulation."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter


def simulate(linear_image, *, blur_sigma_px=1., exposure=1., full_well_e=30000., read_noise_e=3.,
             prnu_pct=0., black_level=0., white_balance=(1., 1., 1.), matrix=None,
             sharpening=0., gamma=1., bits=16, seed=1):
    a = np.asarray(linear_image, float)
    if a.ndim not in {2, 3} or not np.all(np.isfinite(a)) or min(a.shape[:2]) < 8:
        raise ValueError("仿真需要有效二维或 RGB 线性图像")
    values = [blur_sigma_px, exposure, full_well_e, read_noise_e, prnu_pct, black_level, sharpening, gamma]
    if not np.all(np.isfinite(values)) or not 0 <= blur_sigma_px <= 100 or not 0 < exposure <= 100 or not 1 <= full_well_e <= 1e9 or read_noise_e < 0 or prnu_pct < 0 or not 0 < gamma <= 5 or bits not in {8, 10, 12, 14, 16}:
        raise ValueError("无效光学 / 传感器 / ISP 参数")
    rng = np.random.default_rng(seed)
    sigma = (blur_sigma_px, blur_sigma_px, 0) if a.ndim == 3 else blur_sigma_px
    optical = np.maximum(gaussian_filter(a, sigma)*exposure, 0)
    fixed_pattern = rng.normal(1, prnu_pct/100, optical.shape)
    electrons = rng.poisson(np.clip(optical*fixed_pattern, 0, 100)*full_well_e).astype(float)
    sensor = np.clip((electrons+rng.normal(0, read_noise_e, a.shape))/full_well_e+black_level, 0, 1)
    signal = sensor.copy()
    if a.ndim == 3:
        wb = np.asarray(white_balance, float)
        if wb.shape != (3,) or a.shape[2] != 3 or np.any(wb <= 0) or not np.all(np.isfinite(wb)):
            raise ValueError("白平衡必须为三个正数，输入为 RGB")
        signal *= wb
        if matrix is not None:
            m = np.asarray(matrix, float)
            if m.shape != (3, 3) or not np.all(np.isfinite(m)):
                raise ValueError("仿真 CCM 必须为有限 3×3 数组")
            signal = signal@m
    if sharpening:
        signal += sharpening*(signal-gaussian_filter(signal, (1, 1, 0) if signal.ndim == 3 else 1))
    encoded = np.clip(signal, 0, 1)**(1/gamma)
    maximum = 2**bits-1
    quantized = np.rint(encoded*maximum)/maximum
    result = (quantized*(255 if bits == 8 else 65535)).round().astype(np.uint8 if bits == 8 else np.uint16)
    return result, {"seed": seed, "bits": bits, "optical_sigma_px": blur_sigma_px, "full_well_e": full_well_e,
                    "read_noise_e": read_noise_e, "prnu_pct": prnu_pct, "exposure": exposure, "gamma": gamma,
                    "clipped_fraction": float(np.mean((signal <= 0)|(signal >= 1))),
                    "pipeline": "Gaussian optics → PRNU → Poisson shot noise → Gaussian read noise → clipping → WB → CCM → unsharp → gamma → quantization",
                    "limitations": ["固定位置 PRNU 仅在本次仿真中保持；无光谱 QE、衍射瞳面、CFA/去马赛克或实物光源控制。"]}
