"""HTML/PDF presentation for the reproducible example/999.tif analysis."""
from __future__ import annotations
import base64
import hashlib
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image

REFERENCES = [
    ("Thorlabs USAF 1951: 组/元素与名义 lp/mm", "https://www.thorlabs.us/NewGroupPage9.cfm?ObjectGroup_ID=4338"),
    ("Imatest: Tonal response and gamma", "https://www.imatest.com/imaging/tonal-response-gamma/"),
    ("Imatest: Sharpness / MTF measurement", "https://www.imatest.com/imaging/sharpness/"),
]
ROOT = Path(__file__).resolve().parents[1]
PALETTE = {"R": "#b32929", "G": "#2d844a", "B": "#2d56a6"}


def rulers(data, x, y):
    left, right = data["calibration"]["rulers"]
    fraction = (x-left["x"])/(right["x"]-left["x"])
    slope = left["pixels_per_step"]*(1-fraction)+right["pixels_per_step"]*fraction
    offset = left["y_at_label_5"]*(1-fraction)+right["y_at_label_5"]*fraction
    return 5+(y-offset)/slope


def make_plots(data, pixels, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.colors import Normalize
    from matplotlib.patches import Polygon
    font_manager.fontManager.addfont("C:/Windows/Fonts/msyh.ttc")
    family = font_manager.FontProperties(fname="C:/Windows/Fonts/msyh.ttc").get_name()
    plt.rcParams.update({"font.family": family, "font.size": 10, "axes.unicode_minus": False,
                         "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white"})
    shape = data["image"]["shape"]
    px_mm = data["calibration"]["mean_ruler_dpi"]/25.4
    preview = Image.fromarray(pixels[::8, ::8]).convert("L")
    preview.thumbnail((420, 1680), Image.Resampling.LANCZOS)
    cells = data["cells"]
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 8.15), dpi=220)
    fig.subplots_adjust(left=.1, right=.875, top=.955, bottom=.092, wspace=.34)
    norm = Normalize(.1, .65)
    cmap = matplotlib.colormaps["viridis"]
    for axis, c in zip(axes, "RGB"):
        axis.imshow(preview, cmap="gray", vmin=0, vmax=255,
                    extent=[0, shape[1]/px_mm, rulers(data, 4000, shape[0]), rulers(data, 4000, 0)],
                    aspect=data["calibration"]["minor_step_mm"])
        for cell in cells:
            quad = np.array([[1410, 75, 1], [2960, 75, 1], [2960, 1700, 1], [1410, 1700, 1]])@np.array(cell["affine"])
            corners = np.column_stack([quad[:, 0]/px_mm, [rulers(data, *p) for p in quad]])
            score = cell["scores"][c]
            axis.add_patch(Polygon(corners, closed=True, facecolor=cmap(norm(score["weak"])), alpha=.5,
                                   edgecolor="#526c7a", linewidth=.35))
            x, y = cell["position"]
            axis.plot(x/px_mm, rulers(data, x, y), marker="x" if score["white_flag"] else "o",
                      markersize=3, color="#172f3e", markerfacecolor="none", markeredgewidth=.6)
        axis.set_title(c+" 通道", color=PALETTE[c], fontsize=13, pad=9)
        axis.set_xlim(0, shape[1]/px_mm)
        axis.set_ylim(rulers(data, 4000, shape[0]), rulers(data, 4000, 0))
        axis.set_xticks([10, 30, 50]); axis.set_yticks(range(5, 56, 5))
        axis.tick_params(labelsize=9)
        axis.set_xlabel("横向位置 (mm)", fontsize=9)
    axes[0].set_ylabel("标尺读数 (1 格 = 5 mm)", fontsize=10)
    color_axis = fig.add_axes([.918, .15, .017, .68])
    bar = fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), cax=color_axis)
    bar.set_label("归一化 CTF (两方向较弱值)", fontsize=9); bar.ax.tick_params(labelsize=8)
    fig.savefig(folder/"heatmaps.png", dpi=220)
    fig.savefig(folder/"heatmaps.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(7.4, 5.5), dpi=220)
    fig.subplots_adjust(left=.105, right=.975, top=.925, bottom=.11, hspace=.55)
    positions = np.array([c["mm_from_5"] for c in cells])
    xx = np.linspace(0, 245, 180)
    def trend(values):
        return [np.median(values[np.abs(positions-x) <= 15]) if np.sum(np.abs(positions-x) <= 15) >= 3 else np.nan for x in xx]
    for c in "RGB":
        weak = np.array([cell["scores"][c]["weak"] for cell in cells])
        axes[0].scatter(positions, weak, c=PALETTE[c], s=14, alpha=.23)
        axes[0].plot(xx, trend(weak), c=PALETTE[c], lw=1.8, label=c+" 通道")
        for direction, style in [("vertical", "-"), ("horizontal", "--")]:
            values = np.array([cell["scores"][c][direction] for cell in cells])
            axes[1].plot(xx, trend(values), style, color=PALETTE[c], lw=1.4,
                         label=c+(" 竖线 / 横向细节" if direction == "vertical" else " 横线 / 纵向细节"))
    for axis in axes:
        axis.axvspan(125, 200, color="#71898a", alpha=.1)
        axis.set_xlim(0, 245); axis.set_ylim(0, .85)
        axis.set_xlabel('距标尺 "5" 的长度 (mm)', fontsize=10)
        axis.set_ylabel("归一化 CTF", fontsize=10)
        axis.grid(alpha=.18); axis.tick_params(labelsize=9)
    axes[0].set_title("相同细节频率下的 RGB 响应", fontsize=12, loc="left", pad=9)
    axes[0].legend(ncol=3, loc="upper left", frameon=False, fontsize=9)
    axes[1].set_title("方向差异：竖线与横线分别归一化", fontsize=12, loc="left", pad=9)
    axes[1].legend(ncol=3, loc="lower left", frameon=False, fontsize=7.8)
    fig.savefig(folder/"length_profiles.png", dpi=220)
    fig.savefig(folder/"length_profiles.pdf")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 1.95), dpi=220)
    fig.subplots_adjust(left=.095, right=.985, top=.8, bottom=.25, wspace=.32)
    for axis, cell_id in zip(axes, [0, 40]):
        cell = cells[cell_id]
        roi = next(m for m in cell["measurements"] if m["k"] == 22 and m["direction"] == 0)
        for c in "RGB":
            profile = roi["channels"][c]["profile"]
            axis.plot(profile["x"], profile["y"], c=PALETTE[c], lw=1.3)
        axis.set_title(f"单元 {cell_id+1} / 读数 {cell['ruler_read']:.2f}", fontsize=10)
        axis.set_ylim(0, 1.06); axis.set_yticks([0, .5, 1])
        axis.set_xlabel("ROI 横向原像素", fontsize=9); axis.tick_params(labelsize=8)
        axis.grid(alpha=.18)
    axes[0].set_ylabel("ICC Gamma 线性化信号", fontsize=8)
    fig.savefig(folder/"native_profiles.png", dpi=220)
    plt.close(fig)


def report_content(data):
    cells = data["cells"]
    clip = {c: sum(m["channels"][c]["clip_fraction"] >= .01 for cell in cells for m in cell["measurements"] if m["k"] == 22) for c in "RGB"}
    direction = {c: sum(cell["scores"][c]["vertical"] > cell["scores"][c]["horizontal"] for cell in cells) for c in "RGB"}
    fit = [c["fit_rms_px"] for c in cells]
    return {
        "lead": "这次扫描中，标尺读数 30-45 的综合细节对比度较好，建议优先检查 35-45 区段。",
        "length": "用户确认每个小刻度为 5 mm，因此 5 到 10 的实距为 25 mm。读数 30-45 对应距标尺 5 约 125-200 mm；读数 35-45 对应约 150-200 mm。这些是沿卡长度，未换算成离焦高度。",
        "scope": "结果描述这张成品扫描图的相对表现。无法仅凭这张图确认扫描仪的真实光学 DPI、机械歪轴、场曲或镜头色散。",
        "ctf": "对比 USAF 组 3、元素 5 (12.699 lp/mm)。每个通道、每个方向的 CTF 除以同单元低频组 0 元素 2-5 的中位 CTF；综合值取竖线与横线的较小值。归一化 CTF 无量纲，不是 MTF 或 MTF50。",
        "quality": f"在用于比较的 96 个方向 ROI 中，白端触顶比例 >=1% 的数量为 R {clip['R']}/96、G {clip['G']}/96、B {clip['B']}/96。触顶表示编码值达到 255，不能据此断言原始采集已过曝；但会限制绝对光学指标的可信度。",
        "direction": f"竖线响应高于横线的测点为 R {direction['R']}/48、G {direction['G']}/48、B {direction['B']}/48。竖线衡量图像横向细节，横线衡量纵向细节；未据此假定扫描机构的运动方向。",
        "fit": f"48 单元的定位拟合残差 RMS 为 {min(fit):.3f}-{max(fit):.3f} px；每单元使用 28-34 个中低频定位匹配。",
        "gamma": "使用 TIFF 内嵌 Adobe RGB (1998) 的 RGB TRC：Gamma 2.19921875，逐通道执行 (编码值 / 255)^Gamma。ICC 曲线只是输出编码的依据，不能证明扫描软件没有锐化、局部对比度处理或其他非线性。",
        "provenance": "USAF 的 CTF/条纹分离与斜边 SFR 诊断调用本项目的 usaf()、slanted_edge() 函数。重复图案定位、标尺拟合、统计与报告由保存的样本辅助脚本完成，尚未作为此图卡的自动 GUI 分析流程。",
        "sfr": f"辅助调用了 {data['sfr_diagnostics']['attempted_rois']} 个斜边候选；其中 {data['sfr_diagnostics']['returned_without_basic_fatal_flags']} 个未出现基础几何/采样致命标志。但 G 通道边缘角度仅 {data['sfr_diagnostics']['G_angle_percentiles'][0]:.2f}-{data['sfr_diagnostics']['G_angle_percentiles'][2]:.2f} 度，均未达到建议 2-7 度范围，因此报告未用它们给出绝对 MTF50。",
        "next": "下一轮建议输出 RGB 48-bit TIFF，记录扫描分辨率、输出曲线和处理设置，并关闭锐化、降噪及自动对比度。沿用当前图卡比较即可；垫高信息暂不纳入本报告。",
    }


def build_pdf(data, folder, target, content):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
    pdfmetrics.registerFont(TTFont("ReportCN", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    pdfmetrics.registerFont(TTFont("ReportHeading", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=0))
    pdfmetrics.registerFontFamily("ReportCN", normal="ReportCN", bold="ReportHeading")
    ink, muted, accent = colors.HexColor("#183649"), colors.HexColor("#526b7a"), colors.HexColor("#147d86")
    styles = {
        "title": ParagraphStyle("title", fontName="ReportHeading", fontSize=23, leading=31, textColor=ink, spaceAfter=7),
        "h1": ParagraphStyle("h1", fontName="ReportHeading", fontSize=17, leading=24, textColor=ink, spaceAfter=10),
        "h2": ParagraphStyle("h2", fontName="ReportHeading", fontSize=12, leading=18, textColor=accent, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", fontName="ReportCN", fontSize=9.8, leading=15.7, textColor=ink, spaceAfter=7, wordWrap="CJK", alignment=TA_LEFT),
        "small": ParagraphStyle("small", fontName="ReportCN", fontSize=8.2, leading=12.7, textColor=muted, spaceAfter=5, wordWrap="CJK"),
        "tiny": ParagraphStyle("tiny", fontName="ReportCN", fontSize=7.2, leading=10.7, textColor=muted, spaceAfter=4, wordWrap="CJK"),
    }
    def para(value, style="body"):
        return Paragraph(html.escape(str(value)), styles[style])
    def heading(value):
        return para(value, "h2")
    def table(rows, widths, header=False):
        obj = Table([[para(v, "small") for v in row] for row in rows], colWidths=widths, hAlign="LEFT")
        commands = [("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 7),
                    ("RIGHTPADDING", (0,0), (-1,-1), 7), ("TOPPADDING", (0,0), (-1,-1), 6),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 5), ("LINEBELOW", (0,0), (-1,-1), .35, colors.HexColor("#d9e3e9"))]
        if header:
            commands += [("BACKGROUND", (0,0), (-1,0), colors.HexColor("#edf4f7"))]
        obj.setStyle(TableStyle(commands)); return obj
    def picture(name, width):
        with Image.open(folder/name) as im:
            height = width*im.height/im.width
        return RLImage(str(folder/name), width=width, height=height, hAlign="CENTER")
    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#d9e3e9")); canvas.setLineWidth(.4)
        canvas.line(18*mm, 18*mm, 192*mm, 18*mm)
        canvas.setFillColor(muted); canvas.setFont("ReportCN", 7.5)
        canvas.drawString(18*mm, 12*mm, "MUTEX Imatest | 999.tif | 相对图像响应分析")
        canvas.drawRightString(192*mm, 12*mm, f"{doc.page}")
    doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=20*mm, bottomMargin=23*mm, title="MUTEX Imatest - 999 扫描分析报告",
                            author="MUTEX Imatest", creator="MUTEX Imatest core with reproducible sample helper")
    width = 174*mm
    story = [para("扫描图像分析报告", "title"), para("MUTEX Imatest · 999.tif · "+data["generated_at"][:10], "small"),
             heading("优先检查区域"), para(content["lead"]), para(content["length"]), para(content["scope"], "small"),
             heading("文件与采样标定")]
    image = data["image"]
    left, right = data["calibration"]["rulers"]
    story += [table([
        ["原图", f"{image['shape'][1]} × {image['shape'][0]} px；{image['file_bytes']/1e6:.1f} MB；2 页 TIFF"],
        ["实际位深", "RGB uint8，8-bit × 3 = 24-bit；本样本不是 48-bit TIFF"],
        ["设备 / 软件", image["camera"]+" / "+image["software"]],
        ["采样 DPI", f"左标尺 {left['dpi']:.1f}；右标尺 {right['dpi']:.1f}；均值 {data['calibration']['mean_ruler_dpi']:.1f}"],
        ["相互核对", f"用户确认 USAF 为 1:1。组 0 元素 1 周期约 {data['usaf_first_anchor_period_px']:.2f} px，按 1 lp/mm 对应约 {data['usaf_first_anchor_period_px']*25.4:.0f} DPI；XMP ScanRes=3200"],
        ["元数据差异", "TIFF X/YResolution=300 DPI 与实测不符；不作为物理标定。采样 DPI 不等于光学分辨率。"],
    ], [31*mm, 143*mm]), heading("相同频率的相对对比度")]
    rows = [["标尺读数", "单元数", "R", "G", "B"]]
    for item in data["summary"]:
        rows.append(["-".join(map(str, item["readout_range"])), item["count"], *[f"{item['median'][c]:.3f}" for c in "RGB"]])
    story += [table(rows, [50*mm, 28*mm, 32*mm, 32*mm, 32*mm], header=True),
              para(content["ctf"], "small"),
              PageBreak(), para("RGB 相对响应热力图", "h1"),
              para("每个彩色区域代表一个实测单元，没有把未测量位置插值成精确分辨率。颜色越亮，所选细节的相对对比度越高。", "small"),
              picture("heatmaps.png", 167*mm), Spacer(1, 4*mm),
              para("圆圈为比较测点；叉号表示该通道任一方向 ROI 的白端触顶比例 >=1%。横向毫米按实测采样密度近似；纵轴是沿卡长度刻度。", "small"),
              para(content["quality"], "small"),
              PageBreak(), para("长度与方向响应", "h1"),
              para("散点为 48 个单元；曲线是附近 ±15 mm 内至少 3 个单元的中位数，用于显示趋势。灰色区为距刻度 5 约 125-200 mm。", "small"),
              picture("length_profiles.png", width), Spacer(1, 3*mm),
              para(content["direction"]),
              para("RGB 趋势不同：G 在前半段相对较强，R/B 在后半段提升更明显。单张处理后的图像不能把这种差异唯一归因于色散。", "small"),
              heading("原像素剖面核对"), picture("native_profiles.png", width),
              para("上图为组 3 元素 5 的竖线 ROI，直接平均条纹中段原像素。三条暗线的间距约 10 px，与 12.699 lp/mm、约 3,200 DPI 的尺度一致；没有先缩图或透视重采样再测量。", "small"),
              PageBreak(), para("方法、来源与复现", "h1"),
              heading("计算来源"), para(content["provenance"]),
              para(content["fit"], "small"), para(content["gamma"], "small"),
              para(content["sfr"], "small"),
              heading("测量流程")]
    steps = [
        f"1. 读取主 TIFF 页；对 {data['cell_count']} 个重复 USAF 单元按中低频三条纹中心拟合局部仿射坐标。定位变换只用于找到 ROI，不改变 ROI 像素。",
        f"2. 每单元测量 28 个名义频率、2 个方向，共 {data['roi_count']:,} 个 RGB ROI，即 {data['channel_measurement_count']:,} 次通道测量。",
        "3. 沿条纹中段取平均剖面，执行项目 CTF 与暗线分离检测；以同单元/同通道/同方向低频参考归一化。",
        "4. 单独保留质量标志。此次设置 reject_clipping=False 供相对比较；放宽门控不能恢复触顶处丢失的信息。",
    ]
    story += [para(v, "small") for v in steps]
    story += [heading("复现与文件指纹"), para('在项目目录运行：.venv\\Scripts\\python.exe scripts\\analyze_999_scan.py', "small"),
              para('只重新排版已保存测量：追加 --reuse；脚本会先核对原图 SHA-256。辅助绘图/PDF 依赖：pip install -e ".[reports]"。', "small"),
              para("输入 SHA-256: "+image["sha256"][:32]+" "+image["sha256"][32:], "tiny"),
              para("核心源文件 SHA-256、参数、包版本、原像素 ROI 和完整数值保存在 output/analysis/999/analysis.json；measurements.csv 共 8,064 行通道测量。", "small"),
              heading("下一轮采集"), para(content["next"], "small"), heading("方法参考")]
    for title, url in REFERENCES:
        story.append(Paragraph(html.escape(title)+f'<br/><link href="{url}" color="#147d86">{html.escape(url)}</link>', styles["tiny"]))
    story += [para("本报告是工程测量记录，不是 ISO 12233 / FADGI 认证。未获得完整扫描参数、实物印制误差或轴向高度，未推断机械倾角。", "tiny")]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def build_html(data, folder, target, content):
    esc = lambda value: html.escape(str(value), quote=True)
    def image(name, alt):
        encoded = base64.b64encode((folder/name).read_bytes()).decode("ascii")
        return f'<img src="data:image/png;base64,{encoded}" alt="{esc(alt)}">'
    def paragraph(name, cls=""):
        return f'<p class="{cls}">{esc(content[name])}</p>'
    summary = "".join(f'<tr><td>{"-".join(map(str, r["readout_range"]))}</td><td>{r["count"]}</td>'+"".join(f'<td>{r["median"][c]:.3f}</td>' for c in "RGB")+"</tr>" for r in data["summary"])
    cells = "".join(f'<tr><td>{c["id"]+1}</td><td>{c["ruler_read"]:.2f}</td><td>{c["mm_from_5"]:.1f}</td>'+"".join(f'<td>{c["scores"][ch]["weak"]:.4f}{" ×" if c["scores"][ch]["white_flag"] else ""}</td>' for ch in "RGB")+f'<td>{c["fit_rms_px"]:.3f}</td></tr>' for c in data["cells"])
    reference_html = "".join(f'<li><a href="{esc(url)}">{esc(title)}</a></li>' for title, url in REFERENCES)
    encoded_data = base64.b64encode(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")).decode("ascii")
    metadata = data["image"]
    left, right = data["calibration"]["rulers"]
    provenance = esc(json.dumps(data["provenance"], ensure_ascii=False, indent=2))
    target.write_text(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MUTEX Imatest - 999 扫描分析</title>
<style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#edf2f5;color:#183649;font:15px/1.7 "Microsoft YaHei",system-ui,sans-serif}}main{{max-width:1000px;margin:24px auto}}.sheet{{padding:32px 40px;background:white;margin-bottom:18px;border-radius:10px}}h1{{font-size:32px;line-height:1.3;margin:0 0 8px}}h2{{font-size:25px;margin:0 0 15px}}h3{{color:#147d86;font-size:18px;margin:22px 0 8px}}.small{{font-size:13px;color:#526b7a}}.lead{{font-size:19px;padding:15px 20px;border-left:4px solid #147d86;background:#eff7f7}}.warning{{padding:15px 20px;border-left:4px solid #c39132;background:#fff8e9}}.actions{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}}button,.actions a{{font:inherit;color:#147d86;background:white;border:1px solid #9fb6bf;border-radius:5px;padding:8px 14px;cursor:pointer;text-decoration:none}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:9px 10px;text-align:left;border-bottom:1px solid #d9e3e9;vertical-align:top}}thead{{background:#edf4f7}}figure{{margin:14px 0}}figure img{{max-width:100%;display:block;margin:auto}}.heatmap img{{max-height:850px}}figcaption{{font-size:13px;color:#526b7a;margin-top:8px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:15px;font:12px/1.7 Consolas,monospace}}.hash{{overflow-wrap:anywhere;font-family:Consolas,monospace;font-size:12px}}details summary{{cursor:pointer}}a{{color:#147d86}}.table-wrap{{overflow-x:auto}}footer{{font-size:12px;color:#526b7a;margin-top:20px}}
@media(max-width:720px){{main{{margin:0}}.sheet{{padding:22px 18px;border-radius:0}}h1{{font-size:26px}}table{{font-size:12px}}}}
@media print{{@page{{size:A4;margin:18mm}}body{{background:white;font-size:10pt;line-height:1.5}}main{{max-width:none;margin:0}}.sheet{{padding:0;margin:0;border-radius:0;break-after:page}}.sheet:last-child{{break-after:auto}}h1{{font-size:23pt}}h2{{font-size:17pt}}h3{{font-size:12pt;margin-top:14px}}.small,figcaption{{font-size:9pt}}.lead{{font-size:12pt}}.actions{{display:none}}.heatmap img{{max-height:195mm}}figure{{break-inside:avoid}}tr{{break-inside:avoid}}thead{{display:table-header-group}}.table-wrap{{overflow:visible}}}}
</style></head><body><main>
<div class="actions"><button onclick="window.print()">打印 / 另存 PDF</button><a href="data:application/json;base64,{encoded_data}" download="999_scan_analysis.json">下载完整测量 JSON</a></div>
<section class="sheet"><h1>扫描图像分析报告</h1><div class="small">MUTEX Imatest · 999.tif · {esc(data['generated_at'][:10])}</div>
<h3>优先检查区域</h3>{paragraph('lead','lead')}{paragraph('length')}{paragraph('scope','small')}
<h3>文件与采样标定</h3><table><tbody><tr><th>原图</th><td>{metadata['shape'][1]} × {metadata['shape'][0]} px；{metadata['file_bytes']/1e6:.1f} MB；主图与缩略图 2 页 TIFF</td></tr><tr><th>实际位深</th><td>RGB uint8，8-bit × 3 = 24-bit；不是 48-bit TIFF</td></tr><tr><th>设备 / 软件</th><td>{esc(metadata['camera'])}<br>{esc(metadata['software'])}</td></tr><tr><th>采样 DPI</th><td>左标尺 {left['dpi']:.1f}，右标尺 {right['dpi']:.1f}，均值 {data['calibration']['mean_ruler_dpi']:.1f}；用户确认 USAF 为 1:1，粗线周期 {data['usaf_first_anchor_period_px']:.2f} px，对应约 {data['usaf_first_anchor_period_px']*25.4:.0f} DPI</td></tr><tr><th>标定核对</th><td>XMP ScanRes=3200；TIFF X/YResolution=300 与实测不符，不作为物理标定。采样 DPI 不等于光学分辨率。</td></tr></tbody></table>
<h3>相同频率的相对对比度</h3><table><thead><tr><th>标尺读数</th><th>单元数</th><th>R</th><th>G</th><th>B</th></tr></thead><tbody>{summary}</tbody></table>{paragraph('ctf','small')}</section>
<section class="sheet"><h2>RGB 相对响应热力图</h2><p class="small">每个彩色区域代表一个实测单元；颜色越亮，所选细节的相对对比度越高。未把空白位置插值成精确分辨率。</p><figure class="heatmap">{image('heatmaps.png','RGB 相对 CTF 热力图')}<figcaption>圆圈为比较测点；叉号表示该通道任一方向 ROI 白端触顶比例 >=1%。横轴毫米按采样密度近似，纵轴为沿卡长度刻度。</figcaption></figure>{paragraph('quality','warning')}</section>
<section class="sheet"><h2>长度与方向响应</h2><p class="small">散点为 48 个单元；曲线为附近 ±15 mm 内至少 3 个单元的中位数。灰色区为距刻度 5 约 125-200 mm。</p><figure>{image('length_profiles.png','沿卡长度的 RGB 和方向响应')}</figure>{paragraph('direction')}<p class="small">RGB 趋势不同：G 在前半段相对较强，R/B 在后半段提升更明显。单张处理后的图像不能把这种差异唯一归因于色散。</p><h3>原像素剖面核对</h3><figure>{image('native_profiles.png','两处 USAF 三条暗线的原像素剖面')}<figcaption>组 3 元素 5 的竖线 ROI，直接平均条纹中段原像素；三条暗线周期约 10 px，与 12.699 lp/mm 和约 3,200 DPI 一致。没有先缩图或透视重采样再测量。</figcaption></figure></section>
<section class="sheet"><h2>方法、来源与复现</h2><h3>计算来源</h3>{paragraph('provenance')}{paragraph('fit','small')}{paragraph('gamma','small')}{paragraph('sfr','small')}
<h3>测量流程</h3><ol><li>读取主 TIFF 页，通过中低频三条纹中心拟合局部仿射坐标；只用它定位 ROI，不重采样测量像素。</li><li>48 单元 × 28 名义频率 × 2 方向 = 2,688 个 RGB ROI，共 8,064 次通道测量。</li><li>调用项目 USAF 算法，以同单元、同方向、同通道低频 CTF 归一化，再取两方向较弱值。</li><li>此次 reject_clipping=False 用于相对比较；质量标志独立保留，放宽门控不能恢复丢失的信息。</li></ol>
<h3>复现与文件指纹</h3><pre>.venv\\Scripts\\python.exe scripts\\analyze_999_scan.py
# 核对原图 SHA-256 后，用已保存测量重新生成报告
.venv\\Scripts\\python.exe scripts\\analyze_999_scan.py --reuse
# 可选绘图 / PDF 依赖
pip install -e ".[reports]"</pre><p class="hash">输入 SHA-256: {esc(metadata['sha256'])}</p><details><summary>算法源文件、参数版本与运行环境</summary><pre>{provenance}</pre></details>
<h3>下一轮采集</h3>{paragraph('next','small')}<h3>方法参考</h3><ul>{reference_html}</ul>
<details><summary>全部 48 单元的比较数值</summary><p class="small">× 表示白端触顶比例 >=1%；CTF 无量纲。完整 8,064 次通道测量可下载本 HTML 内嵌的 JSON。</p><div class="table-wrap"><table><thead><tr><th>单元</th><th>标尺读数</th><th>距 5 (mm)</th><th>R</th><th>G</th><th>B</th><th>定位 RMS (px)</th></tr></thead><tbody>{cells}</tbody></table></div></details>
<footer>工程测量记录，不是 ISO 12233 / FADGI 认证。未获完整扫描参数、印制误差或轴向高度，未推断机械倾角。HTML 图片与完整测量内嵌，可离线打开和复制。</footer></section>
</main></body></html>''', encoding="utf-8")


def build_reports(data, pixels, folder):
    folder = Path(folder)
    make_plots(data, pixels, folder)
    data["presentation"] = {"script": str(Path(__file__).resolve()),
                            "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                            "html_images_and_data_embedded": True}
    (folder/"analysis.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    content = report_content(data)
    pdf = ROOT/"output"/"pdf"/"999_scan_analysis.pdf"
    html_path = ROOT/"output"/"html"/"999_scan_analysis.html"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(data, folder, pdf, content)
    build_html(data, folder, html_path, content)
    return {"pdf": str(pdf), "html": str(html_path), "json": str(folder/"analysis.json"), "csv": str(folder/"measurements.csv")}
