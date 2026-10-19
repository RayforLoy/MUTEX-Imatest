"""Offline native curve plots shared by mixed-target HTML and PDF reports.

Curves keep their recorded axes and sample gaps. Channels are overlaid only
when the region, curve key and both axis units agree. Failed measurements may
still contain useful diagnostic curves; these are drawn with dashed strokes.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass,field
import html
import math


COLORS={'R':'#c94747','G':'#168357','B':'#326bc1','Y':'#a97808','Y_align':'#8f4caa'}
CURVE_NAMES={'sfr':'斜边 SFR','esf':'边缘扩展函数 ESF','lsf':'线扩展函数 LSF',
 'star':'西门子星图响应','star_contrast':'星图原始对比度','star_coherence':'星图基频一致性',
 'wedge':'楔形 CTF 响应','wedge_contrast':'楔形原始对比度','wedge_coherence':'楔形基频一致性',
 'wedge_separation':'楔形预期条纹分离','wedge_bar_count':'楔形检测条数','wedge_expected_bars':'楔形预期条数',
 'profile':'原始条纹剖面','line':'均匀块残差剖面',
 'noise_spectrum':'空间噪声频谱','texture_spectrum':'纹理功率谱','encircled':'包围能量',
 'grid_residual':'几何标记残差','ctf':'条纹 CTF','ctf_response':'条纹相对 CTF'}
ORDER=['sfr','star','wedge','profile','line','encircled','texture_spectrum','grid_residual',
       'esf','lsf','star_contrast','star_coherence',*[f'star_sector_{i}' for i in range(8)],
       'wedge_contrast','wedge_coherence','wedge_separation','wedge_bar_count','wedge_expected_bars','noise_spectrum']
KIND_NAMES={'edge':'斜边','star':'西门子星图','wedge':'分辨率楔形','usaf':'USAF',
            'flat':'均匀块','step':'灰阶块','color':'色块','grid':'几何格','point':'点像','texture':'纹理'}
CURVE_NOTE='曲线使用其原始坐标和单位，不受热力图单位选择影响。同一区域合并通道；缺失样本不补零、不跨空缺连线。虚线为无效测量的诊断曲线，不能据此恢复有效结果。'
CURVE_NAMES.update({'oecf':'编码 OECF','linear_response':'线性灰阶响应','scene_snr':'场景参考信噪比',
 'radial_nps':'二维径向噪声功率谱','illumination_grid':'照度网格','radial_distortion':'径向畸变','radial_residual':'径向拟合残差',
 'texture_response':'参考纹理响应','log_frequency_response':'对数频率响应','edge_nps':'斜边两侧噪声谱','ring_profile':'同心圆径向轮廓'})
KIND_NAMES.update({'dot':'点阵','logf':'对数频率','flare':'遮光眩光','rings':'同心圆','tone_summary':'灰阶 / 动态范围汇总'})


def curve_name(key):
    if key.startswith('star_sector_'):
        try:
            index=int(key.rsplit('_',1)[1])
            return f'星图扇区 {index+1} · {index*45+22.5:g}°'
        except ValueError:pass
    return CURVE_NAMES.get(key,key)


@dataclass
class CurveSeries:
    channel: str
    valid: bool
    segments: list[list[tuple[float,float]]]


@dataclass
class CurvePlot:
    key: str
    x_unit: str
    y_unit: str
    series: list[CurveSeries]=field(default_factory=list)


@dataclass
class CurveRegion:
    region_id: str
    kind: str
    label: str
    measurements: list=field(default_factory=list)
    plots: list[CurvePlot]=field(default_factory=list)
    skipped: list[str]=field(default_factory=list)


def _segments(curve):
    if not isinstance(curve,dict):return [],'曲线格式无效'
    xs,ys=curve.get('x',[]),curve.get('y',[])
    try:
        if len(xs)!=len(ys):return [],'曲线坐标长度不一致'
    except TypeError:return [],'曲线坐标无效'
    output=[];segment=[];count=0
    for x,y in zip(xs,ys):
        try:
            point=float(x),float(y)
            finite=all(math.isfinite(v) for v in point)
        except (TypeError,ValueError,OverflowError):finite=False
        if finite:segment.append(point);count+=1
        else:
            if segment:output.append(segment);segment=[]
    if segment:output.append(segment)
    return (output,'') if count>=2 else ([], '曲线有效采样不足')


def collect_regions(result):
    groups=OrderedDict()
    for measurement in result.measurements:
        key=measurement.region_id,measurement.kind
        if key not in groups:groups[key]=CurveRegion(measurement.region_id,measurement.kind,measurement.label or measurement.region_id)
        groups[key].measurements.append(measurement)
    for region in groups.values():
        plots=OrderedDict()
        for measurement in region.measurements:
            for key,curve in (measurement.curves or {}).items():
                segments,reason=_segments(curve)
                if not segments:
                    region.skipped.append(f'{measurement.channel} / {key}：{reason}');continue
                units=str(curve.get('x_unit','')),str(curve.get('y_unit',''))
                plot=plots.setdefault((key,*units),CurvePlot(key,*units))
                plot.series.append(CurveSeries(measurement.channel,measurement.valid,segments))
        region.plots=sorted(plots.values(),key=lambda plot:(ORDER.index(plot.key) if plot.key in ORDER else len(ORDER),plot.key,plot.x_unit,plot.y_unit))
    return list(groups.values())


def status_lines(region,result=None,metric=None,unit=None):
    """Merge identical channel failures, without allocating empty curve pages."""
    groups=OrderedDict()
    for m in region.measurements:
        status=('有效' if m.valid else '无效')+f'；置信度 {m.confidence:.2f}'
        from .analysis_audit import reason_description,reason_text
        if result is not None and metric and (not m.valid or m.confidence<=.05 or m.metric(metric) is None):
            status+='；'+reason_text(result,m,metric,unit)
            if m.flags:status+=' ['+' / '.join(m.flags)+']'
        else:
            status+='；'+(' / '.join(reason_description(flag)+' ['+flag+']' if reason_description(flag)!=flag else flag for flag in m.flags) if m.flags else '无质量标志')
        if not m.curves:status+='；未保存曲线'
        if not m.valid and m.method and ': ' in m.method:status+='；'+m.method.split(': ',1)[1]
        groups.setdefault(status,[]).append(m.channel)
    lines=[' / '.join(channels)+'：'+status for status,channels in groups.items()]
    return lines+list(dict.fromkeys(region.skipped))


def curve_svg(plot,width=760,height=290):
    """Draw every stored finite sample, preserving gaps, into inert inline SVG."""
    esc=lambda value:html.escape(str(value),quote=True)
    points=[point for series in plot.series for segment in series.segments for point in segment]
    if not points:return ''
    xmin=min(p[0] for p in points);xmax=max(p[0] for p in points)
    ymin=min(p[1] for p in points);ymax=max(p[1] for p in points)
    if xmax==xmin:xmin-=.5;xmax+=.5
    padding=max((ymax-ymin)*.08,abs(ymax)*.025,1e-4)
    ymin,ymax=ymin-padding,ymax+padding
    if min(p[1] for p in points)>=0:ymin=0.
    # Legends have enough space for RGB and both grayscale channels at the
    # smaller PDF panel size. The original units are repeated in the caption.
    left,top,right,bottom=64,62,20,53
    pw,ph=max(80,width-left-right),max(60,height-top-bottom)
    X=lambda value:left+(value-xmin)/(xmax-xmin)*pw
    Y=lambda value:top+ph-(value-ymin)/(ymax-ymin)*ph
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" data-curve="{esc(plot.key)}" data-series-count="{len(plot.series)}" data-x-unit="{esc(plot.x_unit)}" data-y-unit="{esc(plot.y_unit)}">',
           f'<title>{esc(curve_name(plot.key))} · X: {esc(plot.x_unit)} · Y: {esc(plot.y_unit)}</title>',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<text x="{left}" y="19" font-family="Microsoft YaHei,sans-serif" font-size="14" font-weight="bold" fill="#17394a">{esc(curve_name(plot.key))}</text>']
    legend_x=left
    for i,series in enumerate(plot.series):
        color=COLORS.get(series.channel,'#506779');label=series.channel+(' *' if not series.valid else '')
        x=legend_x+i*68;y=40
        parts.append(f'<path d="M{x} {y-4}h17" stroke="{color}" stroke-width="2"'+(' stroke-dasharray="4 3"' if not series.valid else '')+'/>'+
                     f'<text x="{x+22}" y="{y}" font-family="sans-serif" font-size="11" fill="#244655">{esc(label)}</text>')
    for i in range(5):
        x=xmin+(xmax-xmin)*i/4;y=ymin+(ymax-ymin)*i/4
        parts.append(f'<path d="M{X(x):.3f} {top}v{ph}" stroke="#e5edf1"/><path d="M{left} {Y(y):.3f}h{pw}" stroke="#e5edf1"/>')
        parts.append(f'<text x="{X(x):.3f}" y="{top+ph+18}" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#526b77">{x:.3g}</text>')
        parts.append(f'<text x="{left-8}" y="{Y(y)+4:.3f}" text-anchor="end" font-family="sans-serif" font-size="10" fill="#526b77">{y:.3g}</text>')
    parts.append(f'<path d="M{left} {top}v{ph}h{pw}" fill="none" stroke="#67808d"/>')
    for series in plot.series:
        color=COLORS.get(series.channel,'#506779')
        for segment in series.segments:
            if len(segment)==1:
                x,y=segment[0];parts.append(f'<circle cx="{X(x):.3f}" cy="{Y(y):.3f}" r="2" fill="{color}" data-channel="{esc(series.channel)}"/>')
            else:
                path=' '.join(('M' if i==0 else 'L')+f'{X(x):.3f},{Y(y):.3f}' for i,(x,y) in enumerate(segment))
                parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.8" data-channel="{esc(series.channel)}"'+(' stroke-dasharray="5 3"' if not series.valid else '')+'/>')
    # SVG title contains full units even if a custom long unit needs shortening
    # on an axis; normal native units fit without shortening.
    short=lambda value:value if len(value)<=40 else value[:37]+'...'
    parts.append(f'<text x="{left+pw/2:.3f}" y="{height-9}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#244655">{esc(short(plot.x_unit) or "无单位")}</text>')
    parts.append(f'<text transform="translate(14 {top+ph/2:.3f}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#244655">{esc(short(plot.y_unit) or "无单位")}</text></svg>')
    return ''.join(parts)


def html_curves(result):
    esc=lambda value:html.escape(str(value),quote=True)
    regions=collect_regions(result);with_curves=[region for region in regions if region.plots]
    sections=[]
    for region in with_curves:
        figures=[]
        for index,plot in enumerate(region.plots):
            figures.append(f'<figure class="native-curve {"primary" if index==0 else "diagnostic"}">{curve_svg(plot)}<figcaption>{esc(plot.key)} · X: {esc(plot.x_unit or "无单位")} · Y: {esc(plot.y_unit or "无单位")}</figcaption></figure>')
        sections.append(f'<section class="curve-region" data-region="{esc(region.region_id)}"><h3>{esc(region.label)}<small>{esc(region.region_id)} · {esc(KIND_NAMES.get(region.kind,region.kind))}</small></h3><p>{"<br>".join(esc(line) for line in status_lines(region))}</p><div class="curve-grid">{"".join(figures)}</div></section>')
    note=f'共 {len(regions)} 个区域，{len(with_curves)} 个区域含原生曲线。其余区域不生成空图，测量明细保留通道、标志和未测得原因。'
    return f'<h2>原生曲线与诊断</h2><p>{esc(note)}<br>{esc(CURVE_NOTE)}</p>'+''.join(sections)


def render_mixed_pdf(result,preview,path,metric,channel,unit):
    """Render overview, compact region details and all available native curves."""
    from pathlib import Path
    import tempfile
    from .reports import export_overlay,_report_metric,_report_unit,_report_title,_report_attachments
    from .templates import ensure_qt
    ensure_qt()
    from PySide6.QtCore import QRectF,QPointF,QByteArray,Qt
    from PySide6.QtGui import QPdfWriter,QPainter,QFont,QColor,QImage,QPageSize,QTextLayout,QTextOption,QFontMetrics
    from PySide6.QtSvg import QSvgRenderer
    writer=QPdfWriter(str(path));writer.setResolution(120);writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setTitle(_report_title(result,'MUTEX Imatest · 光学测量报告'));writer.setCreator('MUTEX Imatest')
    painter=QPainter(writer)
    if not painter.isActive():raise OSError('Cannot create mixed-target PDF')
    width,height=writer.width(),writer.height();margin=32;content=width-2*margin;bottom=height-48
    y=18.;page=1;continuation='测量概览（续）'
    def footer():
        painter.setPen(QColor('#617886'));font=QFont('Microsoft YaHei',8);painter.setFont(font)
        title=f'MUTEX · {Path(result.image.path).name}  |  {page}'
        title=QFontMetrics(font,writer).elidedText(title,Qt.TextElideMode.ElideMiddle,int(content))
        painter.drawText(QRectF(margin,height-29,content,23),int(Qt.AlignmentFlag.AlignVCenter),title)
    def new_page(title=None):
        nonlocal page,y
        footer();writer.newPage();page+=1;y=18.
        if title:paragraph(title,15,True)
    def ensure(required):
        if y+required>bottom:new_page(continuation)
    def paragraph(value,size=9,bold=False,color='#193343',gap=7):
        nonlocal y
        font=QFont('Microsoft YaHei',size);font.setBold(bold)
        # QTextLayout uses this PDF device's actual 120 DPI and can break a
        # long ASCII flag or filename even when it contains no whitespace.
        for raw_line in str(value).split('\n'):
            layout=QTextLayout(raw_line or ' ',font,writer);option=QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);layout.setTextOption(option)
            lines=[];layout.beginLayout()
            while True:
                line=layout.createLine()
                if not line.isValid():break
                line.setLineWidth(content);line.setPosition(QPointF(0,0));lines.append(line)
            layout.endLayout()
            for line in lines:
                ensure(line.height()+3)
                painter.setFont(font);painter.setPen(QColor(color));line.draw(painter,QPointF(margin,y));y+=line.height()+1
        y+=gap
    def chart(plot,x,top,w,h):
        # A continuation-page heading may leave a bold painter font behind;
        # SVG text without an explicit weight must start from a regular font.
        painter.setFont(QFont('Microsoft YaHei',9))
        renderer=QSvgRenderer(QByteArray(curve_svg(plot,int(w),int(h)).encode('utf-8')))
        if not renderer.isValid():raise ValueError('Native curve SVG could not be rendered')
        renderer.render(painter,QRectF(x,top,w,h))
    regions=collect_regions(result)
    try:
        paragraph(_report_title(result,'MUTEX Imatest · 光学测量报告'),18,True)
        paragraph(f'{Path(result.image.path).name} · {result.image.width} × {result.image.height} · {result.image.dtype} · {result.image.decoder}',10)
        paragraph(f'图卡：{result.chart_name}；指标：{metric} / {channel} / {_report_unit(result,metric,unit)}',10)
        with tempfile.TemporaryDirectory(prefix='mutex-report-') as temporary:
            target=Path(temporary)/'overlay.png';export_overlay(result,preview,target,metric,channel,unit)
            image=QImage(str(target));scale=min(content/max(1,image.width()),height*.44/max(1,image.height()))
            iw,ih=image.width()*scale,image.height()*scale;ensure(ih+8)
            painter.drawImage(QRectF(margin+(content-iw)/2,y,iw,ih),image);y+=ih+12
        paragraph(f'有效测量：{sum(m.valid for m in result.measurements)} / {len(result.measurements)}；插值只用于有实测点覆盖的范围。',10)
        paragraph(f'焦位：{result.focus_position if result.focus_position is not None else "未填写"} {result.focus_unit}',9)
        for warning in dict.fromkeys([*result.image.warnings,*result.warnings]):paragraph(warning,9,color='#805d2b')
        continuation='测量明细（续）';new_page('测量明细与可追溯信息')
        paragraph('SHA-256: '+result.image.fingerprint,8)
        paragraph('算法：'+str(result.settings.get('algorithm_version','unknown')),8)
        paragraph(_report_attachments(result,'完整原始数据与设置请保留同次导出的 result.json 和 measurements.csv。'),8)
        paragraph(CURVE_NOTE,9)
        actual=_report_metric(metric,unit)
        display_unit=_report_unit(result,metric,unit)
        common={'edge':['mtf50','mtf50p','mtf20','mtf10','mtf_nyquist','overshoot_pct','undershoot_pct','edge_fit_rms_px'],
                'star':['resolution_limit','ctf50','ctf20','ctf10','mtf50','mtf20','mtf10','star_anisotropy'],
                'wedge':['resolution_limit','ctf50','ctf20','ctf10','wedge_alias_fraction']}
        for region in regions:
            ensure(100)
            paragraph(f'{region.label} [{region.region_id}] · {KIND_NAMES.get(region.kind,region.kind)}',10,True)
            for line in status_lines(region,result,metric,unit):paragraph(line,8,gap=3)
            for m in region.measurements:
                keys=list(dict.fromkeys([actual,*common.get(region.kind,[])]))
                values=[f'{key}={m.metric(key):.5g} {m.units.get(key, display_unit if key==actual else "")}' for key in keys if m.metric(key) is not None]
                if values:paragraph(m.channel+'：'+'；'.join(values),8,gap=4)
            y+=5
        for region in regions:
            if not region.plots:continue
            continuation=f'原生曲线（续） · {region.label[:120]}'+('...' if len(region.label)>120 else '')+f' [{region.region_id}]'
            new_page(f'原生曲线 · {region.label} [{region.region_id}]')
            paragraph(KIND_NAMES.get(region.kind,region.kind)+'；同一区域按通道叠加，坐标和单位保持原生值。',9)
            for line in status_lines(region,result,metric,unit):paragraph(line,8,gap=3)
            ensure(300);chart(region.plots[0],margin,y,content,290);y+=302
            diagnostics=region.plots[1:];gap=16;cw=(content-gap)/2
            for start in range(0,len(diagnostics),2):
                ensure(245)
                for column,plot in enumerate(diagnostics[start:start+2]):chart(plot,margin+column*(cw+gap),y,cw,230)
                y+=245
        footer()
        from .reports_evaluation import append_pdf_evaluations
        append_pdf_evaluations(writer,painter,result,unit=unit)
    finally:painter.end()
    target=Path(path)
    if not target.exists() or target.stat().st_size<1000:raise OSError('Mixed-target PDF export failed')
    return target
