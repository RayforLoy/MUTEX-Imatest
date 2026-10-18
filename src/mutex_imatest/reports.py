from __future__ import annotations
from pathlib import Path
import base64, csv, html, json
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from .heatmap import heatmap_rgba
from .models import plain

from .resolution import FREQUENCY_METRICS as _FREQUENCY_METRICS,metric_key,PAIRED_SHIFT_METRICS

def _report_metric(metric, unit):
    return metric_key(metric,unit)

def _report_title(result,default):
    return result.settings.get('report_title') or default

def _report_attachments(result,default):
    return result.settings.get('report_attachments_note',default)

def _title_font_size(value,width,height,maximum=20,device=None,bold=True):
    from PySide6.QtCore import QRect,Qt
    from PySide6.QtGui import QFont,QFontMetrics
    for size in range(maximum,7,-1):
        font=QFont('Microsoft YaHei',size);font.setBold(bold)
        metrics=QFontMetrics(font,device) if device is not None else QFontMetrics(font)
        if metrics.boundingRect(QRect(0,0,int(width),int(height)),int(Qt.TextFlag.TextWordWrap),str(value)).height()<=height:return size
    return 8

def _report_unit(result, metric, unit):
    if metric in PAIRED_SHIFT_METRICS and result.optical_summary:return 'px'
    if metric in _FREQUENCY_METRICS:
        return unit
    return next((m.units[metric] for m in result.measurements if m.units.get(metric)), "")

def export_html(result, preview, path, metric="mtf50", channel="G", unit="cy/px"):
    """Export a portable offline report with an embedded heatmap and all values.

    User-controlled filenames, labels, settings and flags are escaped. The HTML
    has no external scripts, fonts or images and can be opened or printed offline.
    """
    if result.optical_summary:
        from .reports_usaf import export_html as full_html
        return full_html(result,preview,path)
    import tempfile
    esc = lambda value: html.escape(str(value), quote=True)
    report_title=_report_title(result,'MUTEX Imatest · 光学测量报告')
    attachment_note=_report_attachments(result,'完整曲线与原始数值请保留同次导出的 result.json 和 measurements.csv。')
    actual = _report_metric(metric, unit)
    display_unit = _report_unit(result, metric, unit)
    coverage_note='区域之间插值，外缘颜色延续至有效测试区域边界' if result.settings.get('interpolate',True) else '仅在各有效测试区域内填色，区域间留空'
    with tempfile.TemporaryDirectory() as temp:
        overlay = Path(temp) / "overlay.png"
        data = export_overlay(result, preview, overlay, metric, channel, unit)
        encoded = base64.b64encode(overlay.read_bytes()).decode("ascii")
    warnings = list(dict.fromkeys(result.image.warnings + result.warnings))
    warnings_html = "".join(f"<li>{esc(w)}</li>" for w in warnings) or "<li>没有报告级提示；请同时检查各测点标志。</li>"
    rows = []
    for m in result.measurements:
        value = m.metric(actual)
        details = "".join(
            f"<tr><th>{esc(key)}</th><td>{esc(json.dumps(plain(v), ensure_ascii=False))}</td><td>{esc(m.units.get(key, ''))}</td></tr>"
            for key, v in m.values.items()
        )
        flag_text = "; ".join(m.flags) or "无质量标志"
        diagnostic_html=(f'<details><summary>几何 / 缺陷诊断</summary><pre>{esc(json.dumps(plain(m.diagnostics),ensure_ascii=False,indent=2))}</pre></details>' if m.diagnostics else '')
        value_text = f"{value:.6g}" if value is not None else "未测得"
        rows.append(
            f'<tr data-valid="{int(m.valid)}" data-channel="{esc(m.channel)}">'
            f'<td>{esc(m.label)}<small>{esc(m.region_id)} / {esc(m.kind)}</small></td>'
            f'<td>{esc(m.channel)}</td><td>{m.position[0]:.2f}, {m.position[1]:.2f}</td>'
            f'<td>{value_text}</td>'
        )
        rows[-1] += (
            f'<td>{esc("有效" if m.valid else "无效")} / {m.confidence:.2f}<small>{esc(flag_text)}</small></td>'
            f'<td><details><summary>全部指标</summary><p>ROI (px): {esc(m.box_pixels)}<br>方法：{esc(m.method)}</p>'
            f'<table><tbody>{details}</tbody></table>{diagnostic_html}</details></td></tr>'
        )
    settings = esc(json.dumps(plain(result.settings), ensure_ascii=False, indent=2))
    registration = esc(json.dumps(plain(result.registration), ensure_ascii=False, indent=2))
    focus = "未填写" if result.focus_position is None else f"{result.focus_position:g} {result.focus_unit}"
    valid = sum(m.valid for m in result.measurements)
    from .reports_curves import html_curves
    from .reports_evaluation import html_evaluations
    native_curves=html_curves(result)
    evaluation_section=html_evaluations(result,unit=unit)
    content = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(report_title)} - {esc(Path(result.image.path).name)}</title>
<style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{margin:0;background:#edf2f5;color:#193343;font:15px/1.65 "Microsoft YaHei",system-ui,sans-serif}}
main{{max-width:1120px;margin:32px auto;padding:36px;background:white;border-radius:12px}}h1{{font-size:28px;margin:0 0 6px}}h2{{font-size:20px;margin-top:28px}}
.sub,small{{color:#586e7c}}small{{display:block;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}}
.card{{padding:14px;background:#f1f6f8;border-radius:6px}}.card strong{{display:block;font-size:20px}}figure{{margin:16px 0}}figure img{{display:block;max-width:100%;max-height:720px;margin:auto;object-fit:contain}}figcaption{{color:#586e7c;font-size:13px}}
.warning{{border-left:4px solid #c39132;padding:12px 18px;background:#fff8e9}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;padding:10px 8px;border-bottom:1px solid #d9e3e9;vertical-align:top}}thead{{background:#edf4f7}}details table{{min-width:280px}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.6 Consolas,monospace;background:#f3f6f8;padding:16px}}.fingerprint{{overflow-wrap:anywhere;font-size:12px}}.controls{{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:14px}}input,select,button{{font:inherit;padding:6px 10px;border:1px solid #a9bdc9;border-radius:4px;background:white}}button{{cursor:pointer}}footer{{margin-top:28px;color:#586e7c;font-size:12px}}
.curve-region{{border-top:1px solid #d9e3e9;margin-top:24px;padding-top:12px;overflow-wrap:anywhere}}.curve-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.native-curve{{margin:0;min-width:0;break-inside:avoid}}.native-curve.primary{{grid-column:1/-1}}.native-curve svg{{display:block;width:100%;height:auto}}.native-curve figcaption{{overflow-wrap:anywhere}}td,h1,h2,h3{{overflow-wrap:anywhere}}
@media(max-width:720px){{main{{margin:0;padding:20px}}.cards{{grid-template-columns:repeat(2,1fr)}}}}
@media print{{@page{{size:A4;margin:16mm}}body{{background:white}}main{{max-width:none;margin:0;padding:0}}.controls{{display:none}}.table-wrap{{overflow:visible}}thead{{display:table-header-group}}tr,figure,.card{{break-inside:avoid}}figure img{{max-height:170mm}}details>summary{{display:none}}details>*{{display:block}}}}
</style></head><body><main>
<h1>{esc(report_title)}</h1><div class="sub">{esc(Path(result.image.path).name)} · {esc(result.chart_name)} · v{esc(result.app_version)}</div>
<div class="cards"><div class="card">原图尺寸<strong>{result.image.width} × {result.image.height}</strong></div><div class="card">有效测量<strong>{valid} / {len(result.measurements)}</strong></div><div class="card">位深 / 解码<strong>{result.image.bits_per_sample}-bit / {esc(result.image.dtype)}</strong></div><div class="card">焦位<strong>{esc(focus)}</strong></div></div>
<p>设备：{esc(result.image.camera or '未记录')}；解码器：{esc(result.image.decoder)}；图卡 ID：{esc(result.chart_id)}。<br>所选指标：{esc(actual)} / {esc(channel)} / {esc(display_unit or '无量纲')}；显示测点 {len(data['values'])} 个。</p>
<h2>热力图</h2><figure><img src="data:image/png;base64,{encoded}" alt="原图预览与测量热力图"><figcaption>图例范围 {data['low']:.6g} - {data['high']:.6g} {esc(display_unit)}。白点为实测位置；灰色斜线为当前指标未测得，不代表零；{coverage_note}，不跨缺失测点连接，区域外透明。颜色为显示估计，不增加实测点。没有有效测点时不会生成有意义的色彩覆盖。</figcaption></figure>
<h2>质量提示</h2><div class="warning"><ul>{warnings_html}</ul><p>CTF 是条纹对比度响应，不能直接当作 MTF。输入曲线、剪切、配准和物理尺寸影响测量；单张图像不能独立确认机械歪轴。</p></div>
{evaluation_section}
{native_curves}
<h2>测量明细</h2><div class="controls"><label>查找 <input id="search" type="search" placeholder="区域 / 标志 / 指标"></label><label>通道 <select id="channel"><option value="">全部</option>{''.join(f'<option>{esc(c)}</option>' for c in sorted({m.channel for m in result.measurements}))}</select></label><label><input id="valid" type="checkbox">仅有效测量</label><button type="button" onclick="window.print()">打印 / 浏览器另存 PDF</button></div>
<div class="table-wrap"><table id="measurements"><thead><tr><th>区域 / 类型</th><th>通道</th><th>中心 (px)</th><th>{esc(actual)}<small>{esc(display_unit)}</small></th><th>有效性 / 置信度 / 标志</th><th>原始指标</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>可追溯信息</h2><p class="fingerprint">输入 SHA-256：{esc(result.image.fingerprint)}</p><details><summary>测量设置</summary><pre>{settings}</pre></details><details><summary>配准设置</summary><pre>{registration}</pre></details>
<footer>离线自包含 HTML，图像和数据保存在本文件内。可直接打开、复制到另一台电脑，或打印。{esc(attachment_note)}</footer>
</main><script>
function filterRows(){{const q=document.getElementById('search').value.toLowerCase(),c=document.getElementById('channel').value,v=document.getElementById('valid').checked;document.querySelectorAll('#measurements>tbody>tr').forEach(r=>{{r.hidden=(c&&r.dataset.channel!==c)||(v&&r.dataset.valid!=='1')||!r.textContent.toLowerCase().includes(q)}})}}
['search','channel','valid'].forEach(id=>document.getElementById(id).addEventListener('input',filterRows));
</script></body></html>'''
    Path(path).write_text(content, encoding="utf-8")
    return Path(path)

def export_csv(result,path):
    with open(path,"w",newline="",encoding="utf-8-sig") as f:
        writer=csv.writer(f)
        writer.writerow(["image","sha256","chart","region","kind","channel","x_px","y_px","valid","confidence","flags","metric","value","unit","method"])
        for m in result.measurements:
            for key,value in m.values.items():
                writer.writerow([result.image.path,result.image.fingerprint,result.chart_id,m.label,m.kind,m.channel,*m.position,m.valid,m.confidence,";".join(m.flags),key,plain(value),m.units.get(key,""),m.method])

def export_overlay(result,preview,path,metric="mtf50",channel="G",unit="cy/px",alpha=.48,limits=None):
    if metric in PAIRED_SHIFT_METRICS:channel=PAIRED_SHIFT_METRICS[metric];unit='px'
    image=Image.open(preview).convert("RGBA")
    data=heatmap_rgba(result,metric,channel,image.width,image.height,unit,alpha,interpolate=result.settings.get('interpolate',True),limits=limits)
    overlay=Image.fromarray(data["rgba"],"RGBA")
    image=Image.alpha_composite(image,overlay)
    draw=ImageDraw.Draw(image)
    try:font=ImageFont.truetype("C:/Windows/Fonts/msyh.ttc",max(12,image.width//110))
    except OSError:font=ImageFont.load_default()
    for point,value in zip(data["points"],data["values"]):
        x=point[0]*image.width/result.image.width;y=point[1]*image.height/result.image.height
        draw.ellipse((x-5,y-5,x+5,y+5),fill="white",outline="#1b394c",width=2)
        draw.text((x+8,y-18),f"{value:.3g}",fill="#102a43",font=font,stroke_width=1,stroke_fill="white")
    low,high=data['limits']
    label=f"{metric} · {channel} · {_report_unit(result,metric,unit)}  {low:.3g} - {high:.3g}"
    draw.rectangle((0,0,image.width,60 if data['missing_count'] else 32),fill=(255,255,255,230))
    draw.text((10,4),label,fill="#102a43",font=font)
    if data['missing_count']:
        draw.text((10,32),f"有效测点 {len(data['values'])}/{len(data['regions'])}；灰色斜线：当前指标未测得；仅相邻有效区域间插值",fill='#596a76',font=font)
    image.convert("RGB").save(path)
    return data

def export_pdf(result,preview,path,metric="mtf50",channel="G",unit="cy/px"):
    if result.optical_summary:
        from .reports_usaf import export_pdf as full_pdf
        return full_pdf(result,preview,path)
    from .reports_curves import render_mixed_pdf
    return render_mixed_pdf(result,preview,path,metric,channel,unit)

def export_bundle(result,preview,directory,metric="mtf50",channel="G",unit="cy/px",pdf=True,html=True,*,
                  include_data=True,include_images=True,include_detail=True,basename='report',title=None):
    """Export with legacy defaults; optional desktop choices only narrow outputs.

    ``basename`` is a filename stem, never a path. HTML/PDF always embed the
    necessary images, including when standalone PNG files are not requested.
    """
    from .export_plan import report_basename
    basename=report_basename(basename)
    if not (pdf or html):raise ValueError('请至少选择一种报告格式')
    import copy
    from .evaluation import evaluate_result
    # Export current rule snapshots while preserving the caller's measurements
    # and any historical assessment stored in an imported result file.
    result=copy.copy(result)
    result.evaluation_summary=evaluate_result(result,result.analysis_summary.get('requested_metrics'),unit)
    if result.analysis_summary:
        from .analysis_plan import summarize_selected
        result.analysis_summary=summarize_selected(result,result.analysis_summary['requested_metrics'],unit)
    folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
    if include_data:result.save(folder/"result.json");export_csv(result,folder/"measurements.csv")
    if result.optical_summary:
        from .reports_usaf import export_tables,create_assets,summary_text
        if include_data:
            export_tables(result,folder)
            (folder/'summary.txt').write_text(summary_text(result),encoding='utf-8')
        if include_images:create_assets(result,preview,folder)
    if include_images:export_overlay(result,preview,folder/"heatmap.png",metric,channel,unit)
    import copy
    rendered=copy.copy(result);rendered.settings=dict(result.settings)
    if title is not None:
        rendered.settings.pop('report_title',None)
        if title.strip():rendered.settings['report_title']=title.strip()
    detail_name='detail-report' if basename=='report' else basename+'-详细'
    note=[]
    if result.analysis_summary and include_detail:
        note.append('完整测量与曲线报告：'+' / '.join(detail_name+suffix for suffix,chosen in [('.html',html),('.pdf',pdf)] if chosen))
    if include_data:
        note.append('原始测量与设置：result.json、measurements.csv'+('；所选项目汇总：analysis-results.csv' if result.analysis_summary else '')+
                    ('；分辨率 / 位移：unit_summary.csv；完整曲线：ctf_curves.csv' if result.optical_summary else '')+
                    '；逐点评价与参考标准：evaluation-results.json、evaluation-results.csv')
    if include_images:note.append('独立热力图 PNG 与本报告保存在同一文件夹内')
    rendered.settings['report_attachments_note']='。'.join(note)+'。' if note else '本次仅导出报告，未附独立原始数据、图像或详细报告。'
    if result.analysis_summary:
        from .reports_selected import export_selected
        export_selected(rendered,preview,folder,unit,pdf,html,include_data=include_data,include_images=include_images,basename=basename)
        if include_detail:
            details=copy.copy(rendered);details.analysis_summary={}
            if title:details.settings=dict(rendered.settings,report_title=title+' · 详细测量')
            if html:export_html(details,preview,folder/(detail_name+'.html'),metric,channel,unit)
            if pdf:export_pdf(details,preview,folder/(detail_name+'.pdf'),metric,channel,unit)
    else:
        if html:export_html(rendered,preview,folder/(basename+'.html'),metric,channel,unit)
        if pdf:export_pdf(rendered,preview,folder/(basename+'.pdf'),metric,channel,unit)
    if include_data:
        from .evaluation import save_evaluation
        save_evaluation(result,folder,unit=unit)
    return folder
