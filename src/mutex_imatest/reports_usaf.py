"""Compact, offline whole-card reports; full element data stays in JSON/CSV."""
from __future__ import annotations
from pathlib import Path
import base64,csv,html,json,math,tempfile
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from .resolution import CHANNEL_LABELS,view_result
from .heatmap import heatmap_rgba

COLORS={'R':'#c94348','G':'#13837b','B':'#416dcc','Y':'#9a741d','Y_align':'#9755ad'}
NOTES=[
 '分辨率：自低频开始连续通过三条纹分离和阈值判定的最高已测频率。双向合并取较弱方向；高频混叠回升不算新的分辨率。',
 '阈值支持相对低频 CTF 或绝对输入对比度。CTF50/20/10 仅在有效测量包围阈值时插值；图卡频率受限的值为下界。',
 '等效分辨 DPI = 50.8 × lp/mm，与几何采样 PPI 分开。LW/PH = 2 × cy/px × 参考图像高度；默认是当前裁切图像的高度。',
 'R/B 位移 = 本通道特征位置 − G 特征位置；右 / 下为正。R/G/B 用原像素；对齐灰度使用双线性重采样，可能降低高频响应。',
 '灰度为指定传递域内的加权 RGB，默认权重 0.2126 / 0.7152 / 0.0722；未知 ICC / 输入曲线时不能称为标定亮度或光学 MTF。',
 '单帧仅给出当前清晰度、方向差异和横向 RGB 位移；RGB 最佳焦位、轴向焦差、倾斜与场曲拟合需要至少 5 个包围峰值的焦位。',
 '本次测量含图卡印刷、透射材料、曝光剪切、照明、扫描 / 去马赛克 / 锐化等影响；不能从单帧单独归因于镜头或扫描仪。',
 '热力图白点是实测单元；开启插值时连接相邻测点，外缘颜色延续至测试区域边界，区域外与大空洞透明。边缘颜色为显示估计；所有响应值均来自扫描原像素。']

def fmt(v,digits=4):return '—' if v is None else f'{v:.{digits}g}'

def shift_statistics(result):
    out={}
    for ch in ['R','B']:
        shifts=[u['rgb_shifts'][ch] for u in result.optical_summary['units'] if u['located'] and u['rgb_shifts'].get(ch,{}).get('valid')]
        out[ch]={'count':len(shifts)}
        for key in ['dx_px','dy_px','magnitude_px','correlation']:
            vals=[v[key] for v in shifts if key in v]
            out[ch][key]={'median':float(np.median(vals)),'min':float(min(vals)),'max':float(max(vals))} if vals else {}
    return out

def summary_text(result):
    s=result.optical_summary
    lines=[f'整卡原像素多频率分析 · {Path(result.image.path).name}',f"阈值：{s['threshold']:.3g} · {s['threshold_mode']}；双向取较弱方向",'']
    for ch,stats in s['statistics'].items():
        lines.append(CHANNEL_LABELS[ch])
        for key,name in [('resolution_limit_lp_mm','lp/mm'),('resolution_limit_dpi','等效分辨 DPI'),('resolution_limit_lw_ph','LW/PH')]:
            v=stats.get(key,{})
            lines.append(f"  {name}: 最高 {fmt(v.get('max'))} / 中位 {fmt(v.get('median'))} / P10 {fmt(v.get('p10'))}；有效 {v.get('count',0)}/{len(s['units'])}")
    lines+=['','横向 RGB 位移（相对于 G，像素）：']
    for ch,v in shift_statistics(result).items():
        lines.append(f"{ch}−G: dx 中位 {fmt(v.get('dx_px',{}).get('median'))}, dy 中位 {fmt(v.get('dy_px',{}).get('median'))}, 幅值最大 {fmt(v.get('magnitude_px',{}).get('max'))}；有效 {v['count']}")
    lines+=['','RGB 最佳焦位：本图是单帧，无法确定。请使用“焦位 / 垫高序列”并选择 ALL，获取 RGB 与两种灰度的最佳焦位及 R−G / B−G 轴向焦差。','','质量标志：'+json.dumps(s.get('quality_counts',{}),ensure_ascii=False),'']+NOTES
    return '\n'.join(lines)

def ctf_svg(record,calibrated=True,raw=False,width=680,height=250):
    esc=lambda s:html.escape(str(s),quote=True)
    curves=[(d,ch,r['curve']) for d,channels in record['directions'].items() for ch,r in channels.items() if r.get('curve',{}).get('frequency')]
    xkey='frequency_lp_mm' if calibrated else 'frequency'
    xs=[v for _,_,c in curves for v in c.get(xkey,[]) if v is not None and v>0]
    if not xs:return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><text x="20" y="45">No valid CTF reference</text></svg>'
    xmin,xmax=min(xs),max(xs);ymax=1.1 if not raw else 1.
    left,top,pw,ph=52,33,width-75,height-85
    X=lambda v:left+(math.log(v)-math.log(xmin))/max(math.log(xmax/xmin),1e-9)*pw
    Y=lambda v:top+ph-min(max(v,0),ymax)/ymax*ph
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/>',f'<text x="{left}" y="19" font-size="13" fill="#17394a">{esc(record["unit_id"])} · {"raw CTF" if raw else "CTF / low frequency"} · solid V / dashed H</text>']
    for y in [0,.1,.2,.5,1.]:parts.append(f'<path d="M {left} {Y(y):.2f} h {pw}" stroke="#dde5ed"/><text x="8" y="{Y(y)+4:.2f}" font-size="11">{y:g}</text>')
    for v in np.geomspace(xmin,xmax,6):parts.append(f'<path d="M {X(v):.2f} {top} v {ph}" stroke="#edf1f4"/><text x="{X(v)-12:.2f}" y="{top+ph+19}" font-size="10">{v:.3g}</text>')
    for direction,ch,curve in curves:
        x=curve.get(xkey,[]);y=curve.get('ctf' if raw else 'response',[])
        path='';started=False
        for a,b in zip(x,y):
            if a is None or b is None:started=False;continue
            path+=f'{"L" if started else "M"}{X(a):.2f},{Y(b):.2f} ';started=True
        dash=' stroke-dasharray="5 3"' if direction=='horizontal' else ''
        parts.append(f'<path d="{path}" fill="none" stroke="{COLORS[ch]}" stroke-width="1.7"{dash}/>')
        if not raw:
            p=' '.join(f'{X(a):.2f},{Y(b):.2f}' for a,b in zip(x,curve.get('envelope',[])) if a is not None)
            parts.append(f'<polyline points="{p}" fill="none" stroke="{COLORS[ch]}" opacity="0.25"/>')
    parts.append(f'<text x="{left+pw/2-40}" y="{height-7}" font-size="12">{"lp/mm" if calibrated else "cycles/pixel"} (log scale)</text></svg>')
    return ''.join(parts)

def _font(size):
    try:return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
    except OSError:return ImageFont.load_default()

def create_assets(result,preview,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);assets={}
    base=Image.open(preview).convert('RGBA');base.thumbnail((340,1500))
    values=[m.metric('resolution_limit_lp_mm') for m in view_result(result,'resolution_limit').measurements if m.valid and m.metric('resolution_limit_lp_mm') is not None]
    unit='lp/mm' if values else 'cy/px'
    if not values:values=[m.metric('resolution_limit') for m in view_result(result,'resolution_limit').measurements if m.valid and m.metric('resolution_limit') is not None]
    limits=(min(values),max(values)) if values else (0,1)
    for ch in result.optical_summary['channels']:
        data=heatmap_rgba(result,'resolution_limit',ch,base.width,base.height,unit,interpolate=result.settings.get('interpolate',True),limits=limits)
        im=Image.alpha_composite(base,Image.fromarray(data['rgba']));draw=ImageDraw.Draw(im)
        for pt in data['points']:
            x,y=pt/[result.image.width,result.image.height]*[base.width,base.height];draw.ellipse((x-2,y-2,x+2,y+2),fill='white',outline='#19384a')
        path=folder/f'heatmap_{ch}.png';im.convert('RGB').save(path);assets[ch]=path
    # Vectors are exaggerated only for display; numeric shifts remain pixels.
    im=Image.new('RGB',(650,1000),'white');draw=ImageDraw.Draw(im);x0,y0,w,h=100,70,380,850
    draw.rectangle((x0,y0,x0+w,y0+h),outline='#c7d5df',width=2)
    draw.text((22,15),'R / B 相对 G 位移 · 箭头放大 15 倍',font=_font(21),fill='#15394a')
    for rec in result.optical_summary['units']:
        px,py=np.array(rec['position'])/[result.image.width,result.image.height]*[w,h]+[x0,y0]
        draw.ellipse((px-2,py-2,px+2,py+2),fill='#17394a')
        for ch in ['R','B']:
            s=rec['rgb_shifts'].get(ch,{})
            if not rec['located'] or not s.get('valid'):continue
            qx,qy=px+s['dx_px']*15,py+s['dy_px']*15
            draw.line((px,py,qx,qy),fill=COLORS[ch],width=2);draw.ellipse((qx-3,qy-3,qx+3,qy+3),fill=COLORS[ch])
    draw.text((25,946),'右 / 下为正；位置坐标按幅面归一化显示',font=_font(18),fill='#314b5c')
    path=folder/'rgb_displacement.png';im.save(path);assets['vectors']=path
    return assets,unit,limits

def export_tables(result,folder):
    folder=Path(folder)
    with open(folder/'unit_summary.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['unit','direction','channel','x_px','y_px','lp/mm','equivalent_resolving_DPI','LW/PH','LP/PH','cy/px','CTF50_lp/mm','CTF20_lp/mm','CTF10_lp/mm','RGB_dx_px','RGB_dy_px','sampling_PPI_x','sampling_PPI_y','confidence','flags'])
        for m in result.measurements:
            if m.kind!='usaf_summary':continue
            keys=['resolution_limit_lp_mm','resolution_limit_dpi','resolution_limit_lw_ph','resolution_limit_lp_ph','resolution_limit','ctf50_lp_mm','ctf20_lp_mm','ctf10_lp_mm','rgb_shift_x_px','rgb_shift_y_px','sampling_dpi_x','sampling_dpi_y']
            w.writerow([m.region_id,m.direction_deg,m.channel,*m.position,*[m.values.get(k) for k in keys],m.confidence,';'.join(m.flags)])
    with open(folder/'ctf_curves.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['unit','direction','channel','element','frequency_cy_px','frequency_lp_mm','raw_CTF','threshold_response','monotone_envelope','passes'])
        for u in result.optical_summary['units']:
            for direction,channels in u['directions'].items():
                for ch,rec in channels.items():
                    c=rec.get('curve',{})
                    for i,v in enumerate(c.get('frequency',[])):
                        w.writerow([u['unit_id'],direction,ch,c['element_ids'][i],v,c['frequency_lp_mm'][i],c['ctf'][i],c['response'][i],c['envelope'][i],c['pass'][i]])

def _stat_rows(result):
    return [[CHANNEL_LABELS[ch],str(v.get('resolution_limit',{}).get('count',0)),fmt(v.get('resolution_limit_lp_mm',{}).get('max')),fmt(v.get('resolution_limit_dpi',{}).get('max')),fmt(v.get('resolution_limit_lw_ph',{}).get('max')),fmt(v.get('resolution_limit_lp_mm',{}).get('median')),fmt(v.get('resolution_limit_lp_mm',{}).get('p10'))] for ch,v in result.optical_summary['statistics'].items()]

def export_html(result,preview,path):
    from .reports import _report_title,_report_attachments
    from .reports_evaluation import html_evaluations
    esc=lambda s:html.escape(str(s),quote=True)
    report_title=_report_title(result,'MUTEX Imatest · 整卡多频率 / RGB 光学报告')
    attachment_note=_report_attachments(result,'同目录：result.json 全部原像素测量与设置；measurements.csv 全指标；unit_summary.csv 分辨率 / 位移 / 几何采样；ctf_curves.csv 全曲线。')
    path=Path(path)
    with tempfile.TemporaryDirectory() as temp:
        assets,unit,limits=create_assets(result,preview,temp)
        embed=lambda p:'data:image/png;base64,'+base64.b64encode(Path(p).read_bytes()).decode('ascii')
        maps=''.join(f'<figure><figcaption>{esc(CHANNEL_LABELS[ch])}</figcaption><img src="{embed(assets[ch])}" alt="{esc(ch)} resolution heatmap"></figure>' for ch in result.optical_summary['channels'])
        vectors=embed(assets['vectors'])
    head=['通道','有效单元','最高 lp/mm','最高等效 DPI','最高 LW/PH','中位 lp/mm','P10 lp/mm']
    table=lambda rows:'<table><tbody>'+''.join('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
    rows=_stat_rows(result)
    curves=''.join(f'<details class="unit"><summary>{esc(u["unit_id"])} · '+ ' / '.join(f'{esc(ch)}: {fmt(u.get("combined",{}).get(ch,{}).get("values",{}).get("resolution_limit_lp_mm"))}' for ch in result.optical_summary['channels'])+'</summary><div class="normalized">'+ctf_svg(u,bool(result.template.get('calibrated')))+'<p>细线为保守包络；实线竖纹，虚线横纹。</p></div><div class="raw">'+ctf_svg(u,bool(result.template.get('calibrated')),raw=True)+'</div></details>' for u in result.optical_summary['units'])
    notes=''.join('<li>'+esc(n)+'</li>' for n in NOTES)
    channels=' · '.join(f'<span style="color:{COLORS[c]}">{esc(CHANNEL_LABELS[c])}</span>' for c in result.optical_summary['channels'])
    evaluation_section=html_evaluations(result,unit=unit)
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(report_title)}</title>
<style>body{{font:15px/1.65 "Microsoft YaHei",sans-serif;color:#17394a;background:#f3f6f8;margin:0}}main{{max-width:1260px;margin:25px auto;padding:30px;background:white}}h1{{font-size:27px}}h2{{font-size:20px;margin-top:32px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td{{border:1px solid #dce5eb;padding:9px}}tr:first-child{{background:#e7f2f1;font-weight:bold}}.maps{{display:flex;gap:12px}}figure{{flex:1;margin:0;text-align:center;min-width:0}}figure img{{width:100%;max-height:850px;object-fit:contain}}figcaption{{font-weight:bold;min-height:50px}}details{{border:1px solid #dce5eb;padding:10px;margin:12px 0}}summary{{cursor:pointer}}svg{{max-width:100%;height:auto}}.raw{{display:none}}body.showraw .raw{{display:block}}body.showraw .normalized{{display:none}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:16px}}button{{padding:9px 15px;margin:10px 6px 10px 0;background:#137e80;color:white;border:0;border-radius:5px}}.warning{{background:#fff5d9;padding:15px;border-left:4px solid #cb9b38}}.vectors{{max-height:700px;max-width:100%}}@media print{{body,main{{background:white;margin:0;padding:10px}}button{{display:none}}details{{break-inside:avoid}}}}</style><main>
<h1>{esc(report_title)}</h1><p>{esc(Path(result.image.path).name)} · {result.image.width:,} × {result.image.height:,} · {result.image.bits_per_sample}-bit × {result.image.channels}</p>
<p>算法 {esc(result.settings.get('algorithm_version'))} · {result.elapsed_seconds:.2f} 秒 · 阈值 {result.optical_summary['threshold']:.3g} / {esc(result.optical_summary['threshold_mode'])}</p>
<p class="warning">本图为单帧。RGB 最佳焦位与轴向焦差未测得；请导入至少 5 个包围峰值的焦位后选择 ALL 拟合。未知曲线 / 剪切数据仅用于当前输入响应和相对调焦。</p>
<h2>五通道当前实测分辨率</h2><p>双向取较弱方向。每列“最高”在有效单元中独立取最大值；各单位最高值可能来自不同位置。高于当前测试频率的能力不作外推。</p>{table([head]+rows)}
<h2>全幅分辨率热力图</h2><p>统一色标：{limits[0]:.4g}–{limits[1]:.4g} {unit}（蓝 → 绿 → 黄 → 红）。白点为实测位置；透明区没有受支持插值。</p><div class="maps">{maps}</div>
<h2>RGB 横向位移</h2><img class="vectors" src="{vectors}" alt="RGB displacement vectors"><pre>{esc(json.dumps(shift_statistics(result),ensure_ascii=False,indent=2))}</pre>
<h2>各单元完整 CTF 曲线</h2><p>{channels}</p><button onclick="document.querySelectorAll('details.unit').forEach(x=>x.open=true)">展开所有单元</button><button onclick="document.querySelectorAll('details.unit').forEach(x=>x.open=false)">收起所有单元</button><button onclick="document.body.classList.toggle('showraw')">切换原始 / 归一化 CTF</button>{curves}
<h2>测量定义与质量检查</h2><ol>{notes}</ol><pre>{esc(summary_text(result))}</pre>
{evaluation_section}
<h2>可追溯数据</h2><p>SHA-256: {esc(result.image.fingerprint)}</p><p>{esc(attachment_note)}报告离线自包含，无远程脚本或字体。</p><pre>{esc(json.dumps(result.settings,ensure_ascii=False,indent=2))}</pre>
<p>单位与色差定义参考：Imatest 单位说明（https://www.imatest.com/docs/imatest.html）；横向 / 轴向色差（https://www.imatest.com/imaging/chromatic-aberration/）。本软件独立实现。</p></main></html>'''
    path.write_text(body,encoding='utf-8');return path

def export_pdf(result,preview,path):
    from .reports import _report_title,_report_attachments,_title_font_size
    from .templates import ensure_qt
    from PySide6.QtGui import QPdfWriter,QPainter,QFont,QColor,QImage,QPageSize
    from PySide6.QtCore import QRectF,QByteArray
    from PySide6.QtSvg import QSvgRenderer
    report_title=_report_title(result,'MUTEX Imatest · 整卡多频率 / RGB')
    ensure_qt();pdf=QPdfWriter(str(path));pdf.setResolution(120);pdf.setPageSize(QPageSize(QPageSize.PageSizeId.A4));pdf.setTitle(report_title)
    p=QPainter(pdf);W,H=pdf.width(),pdf.height();margin=35;page=1
    if not p.isActive():raise OSError('Cannot create PDF')
    def text(x,y,w,h,s,size=10,bold=False,color='#17394a'):
        p.setPen(QColor(color));f=QFont('Microsoft YaHei',size);f.setBold(bold);p.setFont(f)
        p.drawText(QRectF(x,y,w,h),int(__import__('PySide6.QtCore',fromlist=['Qt']).Qt.TextFlag.TextWordWrap),str(s))
    def footer():text(margin,H-28,W-2*margin,25,f'MUTEX · {Path(result.image.path).name}    |    {page}',8)
    def new(title):
        nonlocal page
        footer();pdf.newPage();page+=1;text(margin,12,W-2*margin,45,title,17,True)
    def table(rows,y,widths):
        for i,row in enumerate(rows):
            x=margin
            for value,w in zip(row,widths):
                p.fillRect(QRectF(x,y,w,43),QColor('#e7f2f1' if i==0 else '#f7f9fb' if i%2 else '#ffffff'))
                text(x+6,y+5,w-10,36,value,8,i==0);x+=w
            y+=43
        return y
    try:
        text(margin,12,W-2*margin,55,report_title,_title_font_size(report_title,W-2*margin,55,19,device=pdf),True)
        text(margin,73,W-2*margin,65,f'{Path(result.image.path).name} · {result.image.width:,} × {result.image.height:,} · {result.image.bits_per_sample}-bit × {result.image.channels}\n算法 {result.settings.get("algorithm_version")} · {result.elapsed_seconds:.2f} 秒',10)
        text(margin,145,W-2*margin,65,'当前单帧：RGB 最佳焦位与轴向焦差未测得。需至少 5 个包围峰值的焦位，并选择 ALL，才进行五通道独立拟合。',11,True,'#875e22')
        y=table([['通道','有效','最高 lp/mm','最高等效 DPI','最高 LW/PH','中位 lp/mm','P10 lp/mm']]+_stat_rows(result),225,[185,53,112,125,120,110,W-2*margin-705])
        text(margin,y+20,W-2*margin,65,f'双向取较弱方向；各单位的最高值分别取最大。阈值 {result.optical_summary["threshold"]} / {result.optical_summary["threshold_mode"]}。输入曲线 {result.settings.get("transfer")}；LW/PH 参考高度 {result.optical_summary["picture_height_px"]} px。',10)
        y+=100
        for line in NOTES[:5]:text(margin,y,W-2*margin,80,line,10);y+=85
        new('整卡分辨率热力图 · 同一色标')
        with tempfile.TemporaryDirectory() as temp:
            assets,unit,limits=create_assets(result,preview,temp)
            text(margin,70,W-2*margin,45,f'蓝 → 绿 → 黄 → 红：{limits[0]:.4g} – {limits[1]:.4g} {unit}；白点实测，颜色至测试区域边界。',10)
            columns=len(result.optical_summary['channels']);cw=(W-2*margin)/columns
            for i,ch in enumerate(result.optical_summary['channels']):
                text(margin+i*cw,125,cw-8,70,CHANNEL_LABELS[ch],10,True)
                im=QImage(str(assets[ch]));iw=cw-12;ih=iw*im.height()/im.width()
                p.drawImage(QRectF(margin+i*cw,205,iw,min(ih,H-270)),im)
            new('RGB 相对 G 位移与几何采样')
            im=QImage(str(assets['vectors']));p.drawImage(QRectF(margin,82,420,680),im)
            y=85
            for ch,rec in shift_statistics(result).items():
                txt=f'{ch}−G，{rec["count"]} 个测点\ndx 中位 {fmt(rec.get("dx_px",{}).get("median"))} px\ndy 中位 {fmt(rec.get("dy_px",{}).get("median"))} px\n最大幅值 {fmt(rec.get("magnitude_px",{}).get("max"))} px'
                text(480,y,W-520,160,txt,11);y+=180
            values=[m.values for m in view_result(result,'sampling_dpi_x').measurements if m.channel=='G' and m.valid]
            text(480,y,W-520,110,'几何采样 PPI 中位\nX: '+fmt(float(np.median([v['sampling_dpi_x'] for v in values if v.get('sampling_dpi_x')])) if any(v.get('sampling_dpi_x') for v in values) else None)+'\nY: '+fmt(float(np.median([v['sampling_dpi_y'] for v in values if v.get('sampling_dpi_y')])) if any(v.get('sampling_dpi_y') for v in values) else None),11)
            y=805
            for line in NOTES[5:]:text(margin,y,W-2*margin,95,line,10);y+=100
        records=result.optical_summary['units']
        for start in range(0,len(records),6):
            new(f'各单元 CTF 曲线 · {start+1}–{min(start+6,len(records))}')
            text(margin,65,W-2*margin,42,'红 R · 绿 G · 蓝 B · 黄 Y · 紫 对齐灰度；实线竖纹，虚线横纹；细线为判读包络。',9)
            cw=(W-2*margin)/2;rh=(H-160)/3
            for j,rec in enumerate(records[start:start+6]):
                x=margin+(j%2)*cw;y=120+(j//2)*rh
                svg=QSvgRenderer(QByteArray(ctf_svg(rec,bool(result.template.get('calibrated'))).encode()))
                svg.render(p,QRectF(x,y,cw-10,rh-40))
                text(x,y+rh-39,cw-10,35,' / '.join(f'{ch} {fmt(rec.get("combined",{}).get(ch,{}).get("values",{}).get("resolution_limit_lp_mm"))}' for ch in result.optical_summary['channels'])+' lp/mm',8)
        new('质量、定义与可追溯信息')
        note='SHA-256: '+result.image.fingerprint+'\n\n'+_report_attachments(result,'完整元素测量、各方向 CTF 曲线、分辨率上下界与设置已保存到同目录 JSON / CSV。')+' PDF 为汇总；HTML 格式可展开每个单元并切换原始 CTF。'
        text(margin,75,W-2*margin,150,note,_title_font_size(note,W-2*margin,150,10,device=pdf,bold=False))
        text(margin,235,W-2*margin,160,'质量计数（五通道合并方向）：\n'+json.dumps(result.optical_summary.get('quality_counts',{}),ensure_ascii=False),10)
        y=430
        for line in NOTES:
            text(margin,y,W-2*margin,72,line,9);y+=77
        footer()
        from .reports_evaluation import append_pdf_evaluations
        append_pdf_evaluations(pdf,p,result,unit=unit)
    finally:p.end()
    if not Path(path).is_file() or Path(path).stat().st_size<1000:raise OSError('PDF export failed')
    return Path(path)
