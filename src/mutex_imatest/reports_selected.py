"""Compact offline HTML/PDF for every checked analysis from one measurement."""
from pathlib import Path
import base64,html,tempfile
from contextlib import nullcontext
from .analysis_plan import summarize_selected,save_summary

STATUS={'complete':'已生成','no_valid_data':'无有效数据','unsupported':'不支持'}


def export_selected(result,preview,folder,unit='cy/px',pdf=True,html_report=True,*,include_data=True,include_images=True,basename='report'):
    from .reports import export_overlay
    from .export_plan import report_basename
    basename=report_basename(basename);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    unit=unit if unit in {'cy/px','lp/mm','DPI','LW/PH','LP/PH'} else 'cy/px'
    summary=summarize_selected(result,result.analysis_summary['requested_metrics'],unit)
    if include_data:
        from .evaluation import save_evaluation
        save_summary(summary,folder)
        save_evaluation(result,folder,summary['requested_metrics'],unit)
    with (nullcontext(folder/'analyses') if include_images else tempfile.TemporaryDirectory(prefix='mutex-report-images-')) as image_folder:
        assets=Path(image_folder);assets.mkdir(exist_ok=True);images={}
        for rec in summary['items']:
            valid=[c for c in rec['channels'] if c['valid']]
            limits=(min(c['min'] for c in valid),max(c['max'] for c in valid)) if valid else None
            for ch in valid:
                path=assets/(rec['metric']+'--'+ch['channel']+'.png')
                export_overlay(result,preview,path,rec['metric'],ch['channel'],ch['unit'],limits=limits)
                images[(rec['metric'],ch['channel'])]=path
        if html_report:_html(result,summary,images,folder/(basename+'.html'),unit)
        if pdf:_pdf(result,summary,images,folder/(basename+'.pdf'),unit)
    return summary


def _rows(summary):
    for rec in summary['items']:
        for ch in rec['channels'] or [{}]:
            yield rec,ch,[rec['name'],ch.get('channel','—'),f"{ch.get('valid',0)} / {ch.get('total',0)}",
                          f"{ch['mean']:.5g}" if ch.get('mean') is not None else '—',
                          f"{ch['max']:.5g}" if ch.get('max') is not None else '—',ch.get('unit',''),
                          STATUS[rec['status']] if ch.get('valid') else '无有效数据' if not rec['reason'] else STATUS[rec['status']]]


def _html(result,summary,images,path,unit='cy/px'):
    from .reports import _report_title,_report_attachments
    from .reports_evaluation import html_evaluations
    esc=lambda text:html.escape(str(text),quote=True)
    report_title=_report_title(result,'MUTEX Imatest · 所选分析结果')
    attachment_note=_report_attachments(result,'完整测量、CTF / SFR 曲线与参数另存于 detail-report.html / detail-report.pdf、result.json 和 measurements.csv；所选结果表见 analysis-results.csv。')
    table=''.join('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in row)+'</tr>' for rec,ch,row in _rows(summary))
    sections=[]
    for rec in summary['items']:
        maps=[]
        for ch in rec['channels']:
            image=images.get((rec['metric'],ch['channel']))
            if image:
                encoded=base64.b64encode(image.read_bytes()).decode('ascii')
                maps.append(f'<figure><figcaption>{esc(ch["channel"])} · {esc(ch["unit"])} · {ch["valid"]} 个有效测点</figcaption><img src="data:image/png;base64,{encoded}" alt="{esc(rec["name"])} {esc(ch["channel"])}"></figure>')
        missing_rows=[]
        for ch in rec['channels']:
            for point in ch.get('missing_points',[]):
                missing_rows.append('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in [point['label'] or point['region_id'],ch['channel'],point['reason']])+'</tr>')
        if not maps and not missing_rows:continue
        reasons=rec['reason'] or '蓝 → 绿 → 黄 → 红；同一分析的通道共用色标。白点实测，灰色斜线为未测得；仅相邻有效区域间插值，颜色延伸至区域边界。'
        flags='；'.join(ch['channel']+': '+', '.join(f'{k}={v}' for k,v in ch['flags'].items()) for ch in rec['channels'] if ch['flags'])
        failures=('<details class="missing-points"><summary>未通过 / 未测得点的具体原因</summary><table><thead><tr><th>区域</th><th>通道</th><th>原因</th></tr></thead><tbody>'+''.join(missing_rows)+'</tbody></table></details>') if missing_rows else ''
        sections.append(f'<section id="{esc(rec["metric"])}"><h2>{esc(rec["name"])}</h2><p>{esc(reasons)}</p><div class="maps">{"".join(maps)}</div>{failures}<details><summary>质量标志</summary><p>{esc(flags or "无区域级标志")}</p></details></section>')
    warnings=''.join('<li>'+esc(s)+'</li>' for s in result.warnings)
    evaluation_section=html_evaluations(result,summary['requested_metrics'],unit)
    text=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(report_title)}</title>
<style>body{{margin:0;background:#edf2f5;color:#193343;font:14px/1.65 "Microsoft YaHei",system-ui,sans-serif}}main{{max-width:1200px;margin:24px auto;padding:30px;background:white}}h1{{margin:0;color:#124c59}}h2{{font-size:20px}}table{{border-collapse:collapse;width:100%;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid #dae4e9;text-align:left}}th{{background:#e9f3f3}}.maps{{display:flex;gap:14px}}figure{{margin:8px 0;flex:1;min-width:0}}figure img{{display:block;width:100%;max-height:800px;object-fit:contain}}figcaption{{font-weight:bold;color:#126b74}}section{{border-top:2px solid #dbe9eb;margin-top:30px;padding-top:10px}}details{{font-size:12px;color:#58717d}}.warning{{background:#fff7e5;padding:12px 20px}}.fingerprint{{overflow-wrap:anywhere;font-size:12px}}@media print{{body{{background:white}}main{{margin:0;padding:0}}section{{break-before:page}}tr,figure{{break-inside:avoid}}}}@media(max-width:650px){{main{{padding:12px}}.maps{{flex-wrap:wrap}}figure{{min-width:45%}}}}</style></head>
<body><main><h1>{esc(report_title)}</h1><p>{esc(Path(result.image.path).name)} · {esc(result.chart_name)} · v{esc(result.app_version)}<br>一次测量，勾选 {len(summary['requested_metrics'])} 项。通道与单位分别列出；无效结果保留原因。</p>
<table><thead><tr>{''.join('<th>'+s+'</th>' for s in ['分析项目','通道','有效 / 总数','均值','最大值','单位','状态'])}</tr></thead><tbody>{table}</tbody></table>
<p>{esc(attachment_note)}</p>
<div class="warning"><ul>{warnings}</ul><p>CTF 为条纹对比度；输入曲线未知时不能当作光学 MTF。单张图不提供轴向最佳焦位。</p></div>
{evaluation_section}
{''.join(sections)}<p class="fingerprint">输入 SHA-256：{esc(result.image.fingerprint)}</p></main></body></html>'''
    path.write_text(text,encoding='utf-8')


def _pdf(result,summary,images,path,unit='cy/px'):
    from .reports import _report_title,_report_attachments,_title_font_size
    from .templates import ensure_qt
    ensure_qt()
    from PySide6.QtCore import QRectF,QRect,Qt
    from PySide6.QtGui import QPdfWriter,QPageSize,QPainter,QColor,QFont,QImage,QFontMetrics
    report_title=_report_title(result,'MUTEX Imatest · 所选分析结果')
    writer=QPdfWriter(str(path));writer.setResolution(120);writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4));writer.setTitle(report_title)
    painter=QPainter(writer)
    if not painter.isActive():raise OSError('Cannot create selected-analysis PDF')
    w,h=writer.width(),writer.height();margin=32;content=w-2*margin;page=1
    def text(rect,value,size=10,bold=False,color='#193343',elide=False):
        font=QFont('Microsoft YaHei',size);font.setBold(bold);painter.setFont(font);painter.setPen(QColor(color))
        if elide:value=QFontMetrics(font).elidedText(str(value),Qt.TextElideMode.ElideRight,int(rect.width()))
        painter.drawText(rect,int(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter|Qt.TextFlag.TextWordWrap),str(value))
    def footer():text(QRectF(margin,h-26,content,22),f'MUTEX · {Path(result.image.path).name}  |  所选分析  |  {page}',8)
    def new_page():
        nonlocal page
        footer();writer.newPage();page+=1
    try:
        text(QRectF(margin,12,content,48),report_title,_title_font_size(report_title,content,48,device=writer),True)
        text(QRectF(margin,70,content,48),f'{Path(result.image.path).name} · {result.chart_name} · v{result.app_version}',10)
        text(QRectF(margin,125,content,50),f'一次测量，勾选 {len(summary["requested_metrics"])} 项。均值和最大值均来自有效测点；未测得不填零。',10)
        widths=[.30,.09,.13,.12,.12,.10,.14];heads=['分析项目','通道','有效 / 总数','均值','最大值','单位','状态'];y=195
        def row(values,header=False):
            nonlocal y
            if header:painter.fillRect(QRectF(margin,y,content,34),QColor('#e6f1f1'))
            x=margin
            for value,fraction in zip(values,widths):
                text(QRectF(x+4,y,content*fraction-8,34),value,8,header,elide=True);x+=content*fraction
            y+=34
        row(heads,True)
        for rec,ch,values in _rows(summary):
            if y>h-125:new_page();y=30;row(heads,True)
            row(values)
        note=_report_attachments(result,'完整曲线、原始测量和质量标志另见 detail-report.pdf 与 JSON / CSV。')+' CTF 不等同光学 MTF；单张图不能确定轴向焦位。'
        note_height=QFontMetrics(QFont('Microsoft YaHei',9),writer).boundingRect(QRect(0,0,int(content),10000),int(Qt.TextFlag.TextWordWrap),note).height()+15
        if y+note_height>h-50:new_page();y=30
        text(QRectF(margin,y+10,content,note_height),note,9)
        for rec in summary['items']:
            channels=[ch for ch in rec['channels'] if (rec['metric'],ch['channel']) in images]
            if not channels:continue
            new_page();text(QRectF(margin,15,content,55),rec['name'],17,True)
            text(QRectF(margin,77,content,60),rec['reason'] or '同一分析的通道共用色标；白点实测，灰色斜线为未测得；仅相邻有效区域间插值，颜色至区域边界。',10)
            n=max(1,len(channels));gap=12;cw=(content-gap*(n-1))/n
            for i,ch in enumerate(channels):
                x=margin+i*(cw+gap)
                text(QRectF(x,148,cw,38),ch['channel']+' · '+ch['unit'],10,True)
                info=f"有效 {ch['valid']} / {ch['total']}\n均值 {ch['mean']:.4g}；最大 {ch['max']:.4g}" if ch['valid'] else '未测得有效值'
                text(QRectF(x,190,cw,65),info,8)
                image_path=images.get((rec['metric'],ch['channel']))
                if image_path:
                    image=QImage(str(image_path));scale=min(cw/image.width(),(h-310)/image.height());iw,ih=image.width()*scale,image.height()*scale
                    painter.drawImage(QRectF(x+(cw-iw)/2,270,iw,ih),image)
        for rec in summary['items']:
            missing=[(ch['channel'],point) for ch in rec['channels'] for point in ch.get('missing_points',[])]
            if not missing:continue
            new_page();text(QRectF(margin,15,content,55),rec['name']+' · 未通过 / 未测得点',15,True);y=83
            font=QFont('Microsoft YaHei',9);metrics=QFontMetrics(font,writer)
            for channel,point in missing:
                line=f"{point['label'] or point['region_id']} · {channel}：{point['reason']}"
                height=max(25,metrics.boundingRect(QRect(0,0,int(content),10000),int(Qt.TextFlag.TextWordWrap),line).height()+10)
                if y+height>h-48:new_page();text(QRectF(margin,15,content,55),rec['name']+' · 原因（续）',15,True);y=83
                text(QRectF(margin,y,content,height),line,9);y+=height
        footer()
        from .reports_evaluation import append_pdf_evaluations
        append_pdf_evaluations(writer,painter,result,summary['requested_metrics'],unit)
    finally:painter.end()
    if not path.exists() or path.stat().st_size<1000:raise OSError('Selected-analysis PDF export failed')
