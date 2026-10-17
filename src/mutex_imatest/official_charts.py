"""Compatibility profiles for photographs of Imatest and standard test targets.

Profiles describe analyzable patterns; they contain no proprietary chart artwork
or invented factory reference values. Irregular layouts require local ROI data.
"""
from __future__ import annotations

from pathlib import Path
import json
import uuid
import numpy as np
from .models import ChartDefinition, Region

DOCS = "https://docs.imatest.com/docs"
COLOR_DOC = "https://www.imatest.com/imaging/color-tone-test-chart-reference/"


def _profile(name, mode, **kwargs):
    return {"name": name, "mode": mode, "documentation": DOCS, **kwargs}


PROFILES = {
    "sfrplus": _profile("Imatest SFRplus", "edges", detail="自动寻找有效斜边；灰阶/可选色块用布局和批次参考文件补充。"),
    "esfr_iso": _profile("Imatest eSFR ISO 12233 · 2014/2017", "edges", detail="自动寻找斜边；色块、楔形与灰阶须导入正确版本布局。"),
    "esfr_iso_2024": _profile("Imatest eSFR ISO 12233 · 2023/2024", "edges", detail="自动寻找斜边；新版对数楔形参数由布局提供。"),
    "iso12233_2000": _profile("ISO 12233:2000", "edges", detail="高对比老图卡，保留剪切和混叠门控。"),
    "sfrreg": _profile("Imatest SFRreg", "edges", detail="独立分布图案的斜边候选；需检查每个 ROI。"),
    "checkerboard": _profile("Imatest Checkerboard", "grid", kind="grid", detail="声明实际内角点行列数；单视图径向拟合，多视图可做完整镜头标定。"),
    "dot_pattern": _profile("Imatest Dot Pattern", "grid", kind="dot", detail="声明点阵行列数，计算径向畸变和二维 RGB 质心差。"),
    "colorchecker24": _profile("ColorChecker Classic · 24", "patches", kind="color", rows=4, cols=6, detail="框定色块矩形；CSV/CGATS 实测参考，明确 D50/D65。"),
    "colorchecker_sg": _profile("ColorChecker SG · 140", "patches", kind="color", rows=10, cols=14, detail="140 块，按行编号；提供批次参考。"),
    "sfrplus_color20": _profile("SFRplus SQ-20 · 彩色", "patches", kind="color", rows=4, cols=5, detail="选择可选 20 色块区域及随卡参考，不能套用 ColorChecker 24。"),
    "sfrplus_gray20": _profile("SFRplus SQ-20 · 灰阶", "patches", kind="step", rows=4, cols=5, detail="选择 4×5 灰阶区域；参考按实际编号导入。"),
    "colorgray44": _profile("Imatest ColorGray-44", "layout", detail="不规则混合彩色/灰阶/楔形；导入本地图卡布局及对应批次参考。"),
    "dr36": _profile("Imatest DR-36 / HDR-36", "layout", detail="旧版与不同层数密度不同；必须提供实际布局和密度文件。"),
    "dr36_color": _profile("Imatest DR36+Color · 新版", "layout", detail="新版顺序和附加色块由布局指定；不假设密度等步长。"),
    "oecf20": _profile("Imatest OECF · 20 块环形", "layout", detail="环形布局需 ROI 定义；提供密度参考。"),
    "iso14524": _profile("ISO 14524 / ST-52 · OECF", "layout", detail="导入 12 块的实际位置及密度参考。"),
    "iso15739": _profile("ISO 15739 · 噪声", "layout", detail="导入布局、密度；可配合重复帧工作台测量时间噪声。"),
    "iso21550": _profile("ISO 21550 · 扫描动态范围", "layout", detail="提供非顺序排列的 24 块布局及透射密度参考。"),
    "linear_step": _profile("线性灰阶 / Q-13 / Q-14 / Stouffer", "patches", kind="step", rows=1, cols=20, detail="框定整条灰阶，按实际数量和顺序导入密度文件。"),
    "it8": _profile("IT8.7 · CGATS", "layout", detail="按 SAMPLE_ID 映射色块 ROI，支持 Lab/XYZ CGATS；不猜测批次色值。"),
    "chroma_du_monde": _profile("ChromaDuMonde · 28", "layout", detail="使用实际 28 块布局及测量参考。"),
    "general_color": _profile("通用 m×n 彩色图", "patches", kind="color", rows=4, cols=6, detail="自定义行列数、色块中心占比与参考文件。"),
    "general_gray": _profile("通用 m×n 灰阶图", "patches", kind="step", rows=4, cols=5, detail="自定义行列数与密度/亮度参考。"),
    "siemens_binary": _profile("二值 Siemens / ISO 星图", "stars", detail="自动检测完整星图和实际线对数，输出 CTF。"),
    "siemens_sine": _profile("正弦 Siemens · S-SFR", "layout", detail="提供完整星图 ROI、线对数及参考调制度，才输出 MTF。"),
    "usaf1951": _profile("USAF 1951", "layout", detail="单元素或多频率布局须提供组/元素/方向；现有 SVG 检测继续可用。"),
    "log_frequency": _profile("Imatest Log Frequency / Log F-Contrast", "layout", detail="导入各对比度带 ROI、起止频率、方向与参考调制度。"),
    "spilled_coins": _profile("Imatest Spilled Coins", "single", kind="texture", detail="功率谱；有同尺度线性参考时可测 PSD 比值纹理响应。"),
    "dead_leaves": _profile("Dead Leaves / Random", "single", kind="texture", detail="噪声扣除可选；有参考才测纹理频率响应。"),
    "flatfield": _profile("均匀场 / Even Field", "single", kind="flat", detail="均匀性、色偏、候选坏点/污点及二维径向噪声谱。"),
    "iso18844_flare": _profile("ISO 18844 · 眩光图", "layout", detail="声明真实遮光暗区与亮区；工程比值，不冒称完整标准方法。"),
    "ieee2020_flare": _profile("IEEE 2020 Method A · 眩光靶", "layout", detail="可导入区域做工程暗/亮比值；标准硬件/归一化流程仍需专项验收。"),
    "concentric_rings": _profile("ISO 8600-3 · 同心圆", "single", kind="rings", detail="提供中心及各边界角度；角度和检出数量不匹配时拒绝。"),
    "point_source": _profile("点源 / PSF", "single", kind="point", detail="PSF 质心、包围能量和二维宽度，声明点源尺寸。"),
    "arbitrary": _profile("Arbitrary Charts · 自定义混合图", "layout", detail="本地 JSON 布局混合各类区域；支持同卡多指标测量。"),
}


def profile_metadata(chart):
    return next((f for f in chart.fiducials if f.get("kind") == "compatibility_profile"), {})


def patch_grid(box, rows, cols, kind, fill=.5):
    if not 1 <= rows <= 100 or not 1 <= cols <= 100 or rows*cols > 2000 or not .1 <= fill <= .9:
        raise ValueError("色块行列需在 1–100，最多 2000 块；中心取样比例需在 0.1–0.9")
    x, y, w, h = map(float, box)
    regions = []
    for row in range(rows):
        for col in range(cols):
            number = str(row*cols+col+1)
            params = {"patch_id": number}
            if kind == "color":
                params["rgb_space"] = "sRGB"
            regions.append(Region(number, kind, (x+w*(col+(1-fill)/2)/cols, y+h*(row+(1-fill)/2)/rows, w*fill/cols, h*fill/rows),
                                  f"色块 {number}" if kind == "color" else f"灰阶 {number}", params))
    return regions


def read_layout(path):
    path = Path(path)
    if path.stat().st_size > 8*2**20:
        raise ValueError("图卡布局超过 8 MiB")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    regions = data.get("regions") if isinstance(data, dict) else data
    if not isinstance(regions, list) or len(regions) > 2000:
        raise ValueError("布局应为最多 2000 个 regions 的 JSON")
    output = [Region(**r) for r in regions]
    if len({r.id for r in output}) != len(output):
        raise ValueError("布局中的区域编号重复")
    return output


def prepare_profile(source, profile_id, *, box=(0, 0, 1, 1), rows=None, cols=None,
                    fill=.5, reference=None, layout=None, match="id", illuminant="D50",
                    transmissive=False, parameters=None, preview_path=None):
    from .detection import suggest_edges
    from .analysis.sfr import slanted_edge
    from .analysis.preprocess import channel_image
    from .config import AnalysisConfig
    from .reference_io import read_reference, attach_references
    from PIL import Image
    if profile_id not in PROFILES:
        raise ValueError("未知图卡兼容配置")
    profile = PROFILES[profile_id]
    if len(box)!=4 or not np.all(np.isfinite(box)) or min(box[:2])<0 or min(box[2:])<=0 or box[0]+box[2]>1 or box[1]+box[3]>1:
        raise ValueError('图卡有效矩形必须位于归一化图像范围内')
    if rows is not None and not 1<=rows<=100 or cols is not None and not 1<=cols<=100:
        raise ValueError('行列数必须位于 1–100')
    preview = source.preview(2048)
    params = dict(parameters or {})
    mode = profile["mode"]
    if layout:
        regions = read_layout(layout)
    elif mode == "edges":
        boxes = suggest_edges(preview, max_count=192)
        regions = []
        test = AnalysisConfig(transfer="unknown", reject_clipping=False)
        for candidate in boxes:
            x, y, w, h = candidate
            if x<box[0] or y<box[1] or x+w>box[0]+box[2] or y+h>box[1]+box[3]:continue
            patch = preview[int(y*preview.shape[0]):int((y+h)*preview.shape[0]), int(x*preview.shape[1]):int((x+w)*preview.shape[1])]
            result = slanted_edge(channel_image(patch.astype(float)/255, "G"), test)
            if "invalid_edge" not in result.get("flags", []) and "low_contrast" not in result.get("flags", []) and result.get("confidence", 0) > .3:
                i = str(len(regions)+1)
                regions.append(Region("edge-"+i, "edge", candidate, "斜边 "+i, {"profile": profile_id}))
        if not regions:
            raise ValueError("未检测到可信斜边；请使用布局文件或模板编辑器手动选区")
    elif mode == "stars":
        from .chart_targets import detect_stars
        regions = []
        for i, s in enumerate(detect_stars(preview), 1):
            radius = s["radius"]
            regions.append(Region(f"star-{i}", "star", ((s["cx"]-radius)/preview.shape[1], (s["cy"]-radius)/preview.shape[0],
                                                        2*radius/preview.shape[1], 2*radius/preview.shape[0]), f"星图 {i}", {"cycles": s["cycles"], "pattern": "binary"}))
        if not regions:
            raise ValueError("未找到完整星图；请用布局文件声明 ROI 和线对数")
    elif mode == "patches":
        regions = patch_grid(box, rows or profile["rows"], cols or profile["cols"], profile["kind"], fill)
    elif mode in {"single", "grid"}:
        if mode == "grid":
            if rows is None or cols is None:
                raise ValueError("请填写实际内角点 / 点阵行列数")
            params.update(rows=rows, cols=cols)
        regions = [Region("target", profile["kind"], box, profile["name"], params)]
    else:
        raise ValueError("该图卡布局不规则，请提供本地 JSON 布局；可先在模板编辑器逐块标记并保存")
    metadata = {"kind": "compatibility_profile", "profile_id": profile_id,
                "detection": "user_layout" if layout else mode, "documentation": profile["documentation"],
                "reference_required": any(r.kind in {"step", "color"} for r in regions)}
    if reference:
        ref = read_reference(reference, illuminant=illuminant)
        regions = attach_references(regions, ref, match=match, transmissive=transmissive)
        metadata.update(reference_sha256=ref["sha256"], reference_name=ref["filename"], reference_illuminant=ref["illuminant"])
    elif any(r.kind in {"step", "color"} and not ("reference_lab" in r.params or "reference_density" in r.params or "reference_luminance" in r.params) for r in regions):
        metadata["warning"] = "缺少批次参考：可测像素统计，色差/OECF/动态范围不产生参考数值。"
    for region in regions:
        if region.kind=='step':region.params['transmissive']=bool(transmissive)
    if preview_path:
        Path(preview_path).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(preview).save(preview_path)
    return ChartDefinition(uuid.uuid4().hex, profile["name"], regions,
                           reference_size=(source.metadata.width, source.metadata.height),
                           fiducials=[metadata], preview=str(preview_path) if preview_path else None,
                           source_path=None, notes=profile["detail"]+" 兼容配置不含官方图卡源文件；候选 ROI 需目视检查。")
