"""Geometric measurements with declared target geometry and model convention."""
from __future__ import annotations

import numpy as np
import cv2
from scipy.optimize import least_squares
from scipy.ndimage import map_coordinates, gaussian_filter1d
from scipy.signal import find_peaks


def fit_radial_distortion(ideal, observed, image_size, center=None):
    """Fit projective plane + k1*r^2 + k2*r^4 at a FIXED principal point.

    r is in image half-diagonals. These coefficients are not interchangeable
    with a calibrated OpenCV camera model or Imatest's division polynomial.
    """
    ideal, observed = np.asarray(ideal, float), np.asarray(observed, float)
    if ideal.shape != observed.shape or ideal.ndim != 2 or ideal.shape[1] != 2 or len(ideal) < 16:
        raise ValueError("畸变拟合至少需要 16 个对应二维点")
    if not np.all(np.isfinite(ideal)) or not np.all(np.isfinite(observed)):
        raise ValueError("畸变控制点必须有限")
    width, height = map(float, image_size)
    if min(width, height) <= 0:
        raise ValueError("无效图像尺寸")
    center = np.array(center if center is not None else (width/2, height/2), float)
    if center.shape != (2,) or not np.all(np.isfinite(center)):
        raise ValueError("无效畸变中心")
    scale = np.hypot(width, height)/2
    target = (observed-center)/scale
    if cv2.contourArea(cv2.convexHull(observed.astype(np.float32))) < width*height*.08:
        raise ValueError("控制点覆盖不足，无法可靠估计径向畸变")
    normalized = (ideal-ideal.mean(axis=0))/max(np.ptp(ideal, axis=0).max(), 1e-12)
    H, _ = cv2.findHomography(normalized, target, 0)
    if H is None:
        raise ValueError("控制点几何退化")
    homogeneous = np.column_stack([normalized, np.ones(len(ideal))])
    def project(parameters):
        matrix = np.r_[parameters[:8], 1].reshape(3, 3)
        p = homogeneous@matrix.T
        z = p[:, 2:]
        if np.any(np.abs(z) < 1e-8):
            return np.full_like(target, 1e6), np.full_like(target, 1e6)
        plane = p[:, :2]/z
        r2 = np.sum(plane*plane, axis=1)
        return plane*(1+parameters[8]*r2+parameters[9]*r2*r2)[:, None], plane
    initial = np.r_[(H/H[2, 2]).ravel()[:8], 0, 0]
    fitted = least_squares(lambda p: (project(p)[0]-target).ravel(), initial, loss="soft_l1", f_scale=.5/scale, max_nfev=1000)
    if not fitted.success or np.linalg.matrix_rank(fitted.jac) < 10:
        raise ValueError("径向畸变拟合未收敛或参数不可辨识")
    prediction, plane = project(fitted.x)
    residual = np.linalg.norm((prediction-target)*scale, axis=1)
    radius = np.linalg.norm(plane, axis=1)
    order = np.argsort(radius)
    distortion = 100*(fitted.x[8]*radius**2+fitted.x[9]*radius**4)
    return {"values": {"radial_k1": float(fitted.x[8]), "radial_k2": float(fitted.x[9]),
                       "radial_fit_rms_px": float(np.sqrt(np.mean(residual**2))),
                       "radial_distortion_max_pct": float(distortion[np.argmax(np.abs(distortion))]),
                       "geometry_point_count": len(ideal)},
            "curves": {"radial_distortion": {"x": radius[order].tolist(), "y": distortion[order].tolist(), "x_unit": "image half-diagonal", "y_unit": "% radial displacement"},
                       "radial_residual": {"x": list(range(len(ideal))), "y": residual.tolist(), "x_unit": "point", "y_unit": "px"}},
            "flags": ["assumed_fixed_distortion_center", "target_geometry_affects_result"], "confidence": 1,
            "center_px": center.tolist(), "radius_scale_px": float(scale),
            "model": "p_distorted = center + (p_projective-center)*(1+k1*r²+k2*r⁴); r=|p_projective-center|/half_diagonal",
            "homography_normalized": np.r_[fitted.x[:8], 1].reshape(3, 3).tolist()}


def detect_dot_grid(a, rows, cols, asymmetric=False):
    img = np.clip(np.asarray(a)*255, 0, 255).astype(np.uint8)
    if img.ndim != 2 or min(rows, cols) < 3 or rows*cols > 2000:
        raise ValueError("点阵需要二维图像和至少 3×3、最多 2000 点的布局")
    params = cv2.SimpleBlobDetector_Params()
    params.filterByArea = True; params.minArea = 5; params.maxArea = max(50, img.size/(rows*cols)*.8)
    params.filterByCircularity = True; params.minCircularity = .45
    params.filterByConvexity = False; params.filterByInertia = False
    params.filterByColor = True; params.blobColor = 0
    detector = cv2.SimpleBlobDetector_create(params)
    flag = cv2.CALIB_CB_ASYMMETRIC_GRID if asymmetric else cv2.CALIB_CB_SYMMETRIC_GRID
    for image in (img, 255-img):
        found, points = cv2.findCirclesGrid(image, (cols, rows), flags=flag|cv2.CALIB_CB_CLUSTERING, blobDetector=detector)
        if found:
            return points.reshape(-1, 2).astype(float)
    raise ValueError("未检测到声明行列数的完整点阵；检查裁切、反光和行列数")


def dot_geometry(a, params, config):
    rows, cols = int(params.get("rows", 0)), int(params.get("cols", 0))
    asymmetric = bool(params.get("asymmetric", False))
    points = detect_dot_grid(a, rows, cols, asymmetric)
    yy, xx = np.mgrid[:rows, :cols]
    ideal = np.column_stack([(2*xx+yy % 2).ravel() if asymmetric else xx.ravel(), yy.ravel()])
    result = fit_radial_distortion(ideal, points, (a.shape[1], a.shape[0]), params.get("center_px"))
    result["points"] = points.tolist()
    return result


def dot_chromatic_aberration(rgb, points):
    rgb = np.asarray(rgb, float)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        return {}
    points = np.asarray(points, float)
    from scipy.spatial.distance import pdist
    spacing = float(np.min(pdist(points)))
    radius = max(3, int(spacing*.28))
    shifts = {"R": [], "B": []}
    for px, py in points:
        x, y = int(round(px)), int(round(py))
        if x-radius < 0 or y-radius < 0 or x+radius >= rgb.shape[1] or y+radius >= rgb.shape[0]:
            continue
        patch = rgb[y-radius:y+radius+1, x-radius:x+radius+1, :3]
        yy, xx = np.mgrid[:patch.shape[0], :patch.shape[1]]
        positions = []
        for i in range(3):
            channel = patch[..., i]
            border = np.r_[channel[0], channel[-1], channel[:, 0], channel[:, -1]]
            background = float(np.median(border))
            sign = 1 if channel[radius, radius] > background else -1
            signal = np.maximum(sign*(channel-background), 0)
            if signal.sum() < 1e-8:
                break
            positions.append(np.array([np.sum(signal*xx), np.sum(signal*yy)])/signal.sum())
        if len(positions) == 3:
            shifts["R"].append(positions[0]-positions[1]); shifts["B"].append(positions[2]-positions[1])
    values = {}
    for channel, samples in shifts.items():
        if samples:
            values[f"dot_ca_{channel.lower()}_g_rms_px"] = float(np.sqrt(np.mean(np.sum(np.asarray(samples)**2, axis=1))))
    return values


def calibrate_camera(object_points, image_points, image_size):
    if len(image_points) < 5 or len(object_points) != len(image_points):
        raise ValueError("完整镜头标定需要至少 5 个不同姿态的图像")
    objects = [np.asarray(p, np.float32).reshape(-1, 3) for p in object_points]
    images = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in image_points]
    if any(len(a) != len(b) or len(a) < 12 for a, b in zip(objects, images)):
        raise ValueError("每帧至少需要 12 个对应角点")
    # Reject repeated/translated identical views, which cannot constrain intrinsics.
    descriptors = []
    for p in images:
        q = p.reshape(-1, 2)
        q = (q-q.mean(axis=0))/max(np.std(q), 1e-9)
        descriptors.append(q.ravel())
    if max(np.linalg.norm(d-descriptors[0])/np.sqrt(len(d)) for d in descriptors) < .015:
        raise ValueError("图像姿态变化不足；请包含倾斜角度、距离和画面位置不同的图卡")
    rms, matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(objects, images, tuple(map(int, image_size)), None, None)
    if not np.isfinite(rms) or not np.all(np.isfinite(matrix)) or min(matrix[0, 0], matrix[1, 1]) <= 0:
        raise ValueError("相机标定失败")
    errors = []
    for obj, pts, rv, tv in zip(objects, images, rvecs, tvecs):
        predicted, _ = cv2.projectPoints(obj, rv, tv, matrix, distortion)
        errors.append(float(np.sqrt(np.mean(np.sum((predicted-pts)**2, axis=2)))))
    fovx, fovy, _, _, _ = cv2.calibrationMatrixValues(matrix, tuple(map(int, image_size)), 0, 0)
    return {"format": "MUTEX OpenCV Camera Calibration", "version": 1, "model": "OpenCV Brown-Conrady k1,k2,p1,p2,k3",
            "image_size": list(image_size), "camera_matrix": matrix.tolist(), "distortion": distortion.ravel().tolist(),
            "rms_px": float(rms), "per_view_rms_px": errors, "horizontal_fov_deg": float(fovx), "vertical_fov_deg": float(fovy),
            "view_count": len(images), "warnings": ["系数只适用于当前焦距、对焦、分辨率和裁切；残差包含图卡误差。"]}


def concentric_rings(a, params, config):
    a = np.asarray(a, float)
    h, w = a.shape
    cx, cy = params.get("center_px", ((w-1)/2, (h-1)/2))
    radius = min(cx, cy, w-1-cx, h-1-cy)
    if radius < 20:
        raise ValueError("同心圆需要完整可见的圆环和正确中心")
    r = np.linspace(2, radius, max(64, int(radius*2)))
    theta = np.linspace(0, 2*np.pi, 360, endpoint=False)
    sampled = map_coordinates(a, [cy+r[:, None]*np.sin(theta), cx+r[:, None]*np.cos(theta)], order=1)
    profile = sampled.mean(axis=1)
    gradient = np.abs(np.gradient(gaussian_filter1d(profile, 1)))
    peaks, _ = find_peaks(gradient, prominence=max(.005, gradient.max()*.15), distance=4)
    radii = r[peaks]
    values = {"ring_transition_count": len(radii), "outer_ring_radius_px": float(radii[-1]) if len(radii) else None}
    angles = params.get("transition_angles_deg")
    flags = ["declared_ring_center", "not_iso8600_certification"]
    if angles is not None:
        angles = np.asarray(angles, float)
        if len(angles) != len(radii) or len(radii) < 3 or np.any(np.diff(angles) <= 0):
            raise ValueError("已知圆环角度数量必须匹配实际检出的边界，至少 3 条")
        values["measured_angular_diameter_deg"] = float(2*angles[-1])
        values["ring_scale_deg_per_px"] = float(np.dot(radii, angles)/np.dot(radii, radii))
    else:
        flags.append("missing_angular_reference")
    return {"values": values, "curves": {"ring_profile": {"x": r.tolist(), "y": profile.tolist(), "x_unit": "px radius", "y_unit": "signal"}},
            "detected_radii_px": radii.tolist(), "flags": flags, "confidence": 1 if len(radii) else 0}
