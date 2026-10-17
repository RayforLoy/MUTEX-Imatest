"""Build the reviewable open chart library from formulas and pinned SVGs.

Only template/ is read or written. This tool never reads private sample files.
SVG and PDF contain vector targets, whereas PNG is a UI reference only.
"""
from __future__ import annotations
import copy
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from mutex_imatest.models import ChartDefinition, Region
from mutex_imatest.templates import render_source, ensure_qt

ROOT = Path(__file__).resolve().parents[1] / "template"
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
CC0 = "CC0-1.0"
SHARE = "CC-BY-SA-3.0"

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def element(parent, kind, **attrs):
    if kind in {"path","polygon","rect"} and "stroke" not in attrs:attrs["stroke"]="none"
    return ET.SubElement(parent, f"{{{NS}}}{kind}", {k.replace("_", "-"): str(v) for k, v in attrs.items()})

def label(root, x, y, text, size=3, anchor="middle"):
    node = element(root, "text", x=x, y=y, font_family="Arial", font_size=size, text_anchor=anchor, fill="#222")
    node.text = text

def base(title):
    root = ET.Element(f"{{{NS}}}svg", {"width": "297mm", "height": "210mm", "viewBox": "0 0 297 210"})
    element(root, "rect", x=0, y=0, width=297, height=210, fill="white")
    element(root, "metadata").text = "Original mathematical artwork, MUTEX Imatest contributors, 2026; CC0-1.0; not an ISO chart or certification."
    label(root, 148.5, 10, title, 4.2)
    label(root, 148.5, 17, "Original CC0 artwork | print 100% | verify scale | not an ISO-certified chart", 2.5)
    # Nonrepeating corner marks give feature registration an unambiguous phase.
    for k, (x, y) in enumerate([(9, 25), (284, 25), (284, 183), (9, 183)]):
        for bit in range(4):
            if ((k+3) >> bit) & 1:
                element(root, "rect", x=x+bit*1.5, y=y, width=1, height=4, fill="black")
    element(root, "path", d="M 18,196 v -2 M 18,195 h 50 M 68,196 v -2", fill="none", stroke="black", stroke_width="0.3")
    label(root, 43, 200, "50 mm verification bar", 2.3)
    label(root, 284, 200, "CC0-1.0 | MUTEX Imatest", 2.5, "end")
    return root

def region(identifier, kind, box, title, family, **params):
    return Region(identifier, kind, tuple(box), title, dict(auto_detect=True, target_family=family, **params))

def star(root, regions, identifier, cx, cy, diameter, family, cycles=36):
    radius = diameter/2
    for k in range(cycles):
        a, b = 2*math.pi*k/cycles, 2*math.pi*(k+.5)/cycles
        # Angular boundaries remain exact straight rays. The outer circle is
        # approximated with <=0.5 degree chord segments, outside the measured
        # 94%-radius annulus. Polygons also avoid a Qt PDF arc-outline defect.
        arc=np.linspace(a,b,11)
        points=[(cx,cy)]+[(cx+radius*math.cos(t),cy+radius*math.sin(t)) for t in arc]
        element(root,"polygon",points=" ".join(f"{x:.8f},{y:.8f}" for x,y in points),fill="black")
    regions.append(region(identifier, "star", ((cx-radius)/297, (cy-radius)/210, diameter/297, diameter/210),
                          f"西门子星 {identifier} · {cycles} 周期", family, cycles=cycles, pattern="binary", center=[.5, .5]))

def square_edges(root, regions, identifier, cx, cy, side, family):
    angle = math.radians(5)
    c, s = math.cos(angle), math.sin(angle)
    pts = [(cx+c*x-s*y, cy+s*x+c*y) for x,y in [(-side/2,-side/2),(side/2,-side/2),(side/2,side/2),(-side/2,side/2)]]
    element(root, "polygon", points=" ".join(f"{x:.8f},{y:.8f}" for x,y in pts), fill="black")
    # ROIs contain one mid-edge with ample bright/dark margin, no corners.
    for suffix, x, y, width, height in [("H", cx+s*side/2, cy-c*side/2, side*.62, side*.32),
                                         ("V", cx+c*side/2, cy+s*side/2, side*.32, side*.62)]:
        regions.append(region(identifier+"-"+suffix, "edge", ((x-width/2)/297, (y-height/2)/210, width/297, height/210),
                              f"5° 斜边 {identifier} · {suffix}", family))

def wedge(root, regions, identifier, x, y, across, along, horizontal=False):
    # t follows the fan axis; cross section contains exactly 6+30*t cycles.
    # Each stripe boundary is sampled at 513 positions. These remain vector
    # paths; the cross section frequency law is in the JSON, not in a bitmap.
    samples = 513
    ts = np.linspace(0, 1, samples)
    counts = 6+30*ts
    group = element(root, "g")
    width, height = (along, across) if horizontal else (across, along)
    for k in range(-20, 21):
        # Clip the actual vector vertices. Qt SVG Tiny does not implement all
        # SVG clipping operations, so a clipPath-only drawing leaks ink when
        # rendered by the application's thumbnail/PDF renderer.
        left = np.clip(.5 + k/counts,0,1)
        right = np.clip(.5 + (k+.5)/counts,0,1)
        points = []
        for cross, t in list(zip(left, ts)) + list(zip(right[::-1], ts[::-1])):
            points.append((x+along*t, y+across*cross) if horizontal else (x+across*cross, y+along*t))
        element(group, "polygon", points=" ".join(f"{a:.7f},{b:.7f}" for a,b in points), fill="black")
    regions.append(region(identifier, "wedge", (x/297, y/210, width/297, height/210), f"连续频率楔形 {identifier}", "generic_iso12233",
                          direction="horizontal" if horizontal else "vertical", pattern="binary",
                          frequency_law="linear_cycles_across_roi", frequency_samples=[{"t":0,"cycles_across":6},{"t":1,"cycles_across":36}]))
    regions[-1].params.pop("auto_detect")

def pdf_from_svg(svg, pdf, size_mm, title, author):
    ensure_qt()
    from PySide6.QtCore import QByteArray, QRectF, QSizeF, QMarginsF, Qt
    from PySide6.QtGui import QPdfWriter, QPageSize, QPageLayout, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from mutex_imatest.svg_source import read_svg
    text, _ = read_svg(svg)
    writer = QPdfWriter(str(pdf))
    writer.setTitle(title)
    writer.setCreator("MUTEX Imatest public mathematical chart generator")
    writer.setAuthor(author)
    writer.setResolution(600)
    writer.setPageSize(QPageSize(QSizeF(*size_mm), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    painter = QPainter(writer)
    painter.setPen(Qt.PenStyle.NoPen)
    renderer = QSvgRenderer(QByteArray(text.encode()))
    renderer.render(painter, QRectF(0, 0, writer.width(), writer.height()))
    painter.end()

def save(identifier, name, artwork, regions, size=(297,210), license=CC0, author="MUTEX Imatest contributors", notes=""):
    for directory in ["originals", "definitions", "previews"]:
        (ROOT/directory).mkdir(parents=True, exist_ok=True)
    svg = ROOT/"originals"/(identifier+".svg")
    ET.ElementTree(artwork).write(svg, encoding="utf-8", xml_declaration=True)
    png = ROOT/"previews"/(identifier+".png")
    render_source(svg, max_side=1600, output=png)
    pdf_from_svg(svg, svg.with_suffix(".pdf"), size, name, author)
    chart = ChartDefinition("public-"+identifier+"-v1", name, regions, physical_size_mm=size,
                            reference_size=(round(size[0]*10), round(size[1]*10)), calibrated=False,
                            preview="../previews/"+png.name, source_path="../originals/"+svg.name,
                            asset_license=license+"; "+author, notes=notes)
    write_json(ROOT/"definitions"/(identifier+".json"), chart.to_dict())
    return {"id":chart.id, "name":name, "definition":"definitions/"+identifier+".json", "license":license,
            "author":author, "printing_dimensions_mm":list(size), "calibrated_by_default":False}

def originals():
    records = []
    for identifier, name, style in [("generic-siemens-slanted", "通用西门子星图 / 斜边 · 原创", "star"),
                                    ("generic-slanted-edge", "通用斜边 · 3×3 双方向 · 原创", "edge")]:
        root = base("SIEMENS STARS + SLANTED EDGES" if style=="star" else "3 x 3 SLANTED EDGES - H / V")
        regions=[]
        for row, cy in enumerate([48, 103, 158]):
            for col, cx in enumerate([53, 148.5, 244]):
                key = f"{row+1}-{col+1}"
                if style=="star":
                    star(root, regions, "S"+key, cx-8, cy, 32, "siemens_star")
                    square_edges(root, regions, "E"+key, cx+27, cy, 20, "slanted_edge")
                    label(root, cx, cy+23, key+" | 36 cycles | binary CTF", 2.7)
                else:
                    square_edges(root, regions, "E"+key, cx, cy, 30, "slanted_edge")
                    label(root, cx, cy+24, key+" | 5 degrees | H / V", 2.7)
        records.append(save(identifier,name,root,regions,notes="原创 CC0 数学图案。默认未确认打印尺度；全卡与局部均可自动检测，只有与此图配准成功时可保留本图位置。黑白二值星图测 CTF，不能当作正弦 MTF。斜边可测 SFR、MTF、过冲与RGB边缘法线位移；单张照片不提供轴向最佳焦位。"))
    root = base("RESOLUTION / SFR - ISO 12233 STYLE (ORIGINAL)")
    regions=[]
    for key,cx,cy in [("TL",39,45),("TR",258,45),("BL",39,163),("BR",258,163)]:
        square_edges(root,regions,"E-"+key,cx,cy,27,"generic_iso12233")
    star(root,regions,"S-C",148.5,105,46,"generic_iso12233")
    star(root,regions,"S-L",89,105,25,"generic_iso12233")
    star(root,regions,"S-R",208,105,25,"generic_iso12233")
    wedge(root,regions,"W-T",83,31,58,33)
    wedge(root,regions,"W-B",156,145,58,33)
    wedge(root,regions,"W-L",19,78,46,30,True)
    wedge(root,regions,"W-R",248,78,46,30,True)
    label(root,112,69,"6 -> 36 cycles / cross section",2.5)
    label(root,185,183,"6 -> 36 cycles / cross section",2.5)
    label(root,148.5,134,"36 cycles per star | binary CTF",2.6)
    # A digital neutral step scale is a visual / relative response aid only.
    for i in range(12):
        x=160+i*8/1
        level=round(255*i/11)
        element(root,"rect",x=x,y=30,width=8,height=9,fill=f"rgb({level},{level},{level})")
    label(root,208,44,"Digital gray steps - not calibrated reflectance",2.3)
    records.append(save("generic-iso12233-style","通用 ISO12233 风格 · 原创兼容图",root,regions,
                        notes="原创 CC0 风格兼容图，不是 ISO 官方图、不声明 ISO 合规或认证。测量入口兼容整图/局部，陌生卡检测的坐标不沿用本图物理尺寸。含5°正交斜边、36周期二值星和6→36周期/横截线的线性楔形。原生像素提供SFR/MTF、CTF、阈值分辨率、方向差异与RGB位移；lp/mm/DPI需要用户确认打印尺寸或另行标定。灰阶只为相对数字信号观察，不可据此宣称色差/反射率/OECF真值。"))
    return records

def checkerboard():
    """One complete 9 x 7 inner-corner grid, with a text-free white margin.

    The five-degree board rotation gives raw-image corner fits several edge
    phases. Registration marks stay outside the measurement box, so a partial
    paper photo can still contain the complete measurable board.
    """
    root=base("CHECKERBOARD - 9 x 7 INNER CORNERS")
    cx,cy=148.5,105.
    side=16.;cols,rows=10,8;angle=math.radians(5)
    board=element(root,"g",transform=f"rotate(5 {cx} {cy})")
    left,top=cx-cols*side/2,cy-rows*side/2
    for row in range(rows):
        for col in range(cols):
            if (row+col)%2==0:
                element(board,"rect",x=left+col*side,y=top+row*side,width=side,height=side,fill="black")
    # Distinct, original deterministic bit marks avoid a repeated-board-only
    # reference. They are orientation aids, not calibrated encoded fiducials.
    for key,(x,y) in enumerate([(18,34),(264,34),(18,159),(264,159)]):
        bits=np.random.default_rng(1951+key).integers(0,2,(7,7))
        bits[0,:]=1;bits[-1,:]=1;bits[:,0]=1;bits[:,-1]=1
        for row,col in zip(*np.nonzero(bits)):
            element(root,"rect",x=x+col*2,y=y+row*2,width=2,height=2,fill="black")
        label(root,x+7,y+18,f"REF {key+1}",2.3)
    label(root,22,91,"10 x 8",2.8)
    label(root,22,96,"squares",2.8)
    label(root,275,91,"16 mm",2.8)
    label(root,275,96,"nominal",2.8)
    label(root,148.5,188,"Complete board required | 5 degree artwork rotation | check printed square size",2.5)
    half_w=(cols*side*math.cos(angle)+rows*side*math.sin(angle))/2+8
    half_h=(cols*side*math.sin(angle)+rows*side*math.cos(angle))/2+8
    box=((cx-half_w)/297,(cy-half_h)/210,2*half_w/297,2*half_h/210)
    regions=[Region("GRID-9x7","grid",box,"棋盘格 · 9×7 内角点",
                    dict(rows=7,cols=9,square_size_mm=side,board_square_counts=[10,8],
                         board_rotation_deg=5,target_family="checkerboard"))]
    return save("generic-checkerboard","通用棋盘格 · 9×7 内角点 · 原创",root,regions,
                notes="原创 CC0 棋盘格；10×8 方格、9×7 内角点，设计格边长16mm，图案旋转5°。grid ROI含完整棋盘及白边，不含文字/定位辅助标记。默认未校准，需核对打印尺寸。可测63个角点去投影平面后的原生像素残差RMS/最大值和残差曲线；结果同时包含打印/平整度/检测/光学误差，不能当作镜头畸变百分比或相机标定。整卡及包含完整棋盘的局部照片可配准；缺失棋盘角点时拒绝或标记ROI越界，不从部分棋盘补出缺失角点。")

def transform(text):
    H=np.eye(3)
    for kind,args in re.findall(r"(matrix|translate|scale)\s*\(([^)]+)\)",text):
        v=[float(x) for x in re.findall(r"[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?",args)]
        if kind=="matrix":a,b,c,d,e,f=v;M=np.array([[a,c,e],[b,d,f],[0,0,1.]])
        elif kind=="translate":M=np.array([[1,0,v[0]],[0,1,v[1] if len(v)>1 else 0],[0,0,1.]])
        else:M=np.diag([v[0],v[1] if len(v)>1 else v[0],1.])
        H=H@M
    return H

def upstream():
    records=[]
    original=ROOT/"upstream"/"commons-siemens"/"Siemens_star.svg"
    source=original.read_text(encoding="utf-8")
    # Remove one reviewed inert obsolete W3C declaration in this derivative.
    # The upstream bytes stay untouched and the application parser stays strict.
    source=re.sub(r"<!DOCTYPE[^>]+>","",source,flags=re.S)
    root=ET.fromstring(source)
    root.set("width","100mm");root.set("height","100mm")
    white=ET.Element(f"{{{NS}}}rect",dict(x="0",y="0",width="20000",height="20000",fill="white"))
    root.insert(0,white)
    element(root,"metadata").text="Siemens star by Leonhard Wimmer (2006), CC-BY-SA-3.0. MUTEX derivative: white background, 100 mm print size, inert DTD removed; geometry unchanged. https://commons.wikimedia.org/wiki/File:Siemens_star.svg"
    regions=[region("S-16","star",(0,0,1,1),"西门子星 · 16 周期","siemens_star",cycles=16,pattern="binary",center=[.5,.5])]
    entry=save("commons-siemens","开放图卡 · Siemens star · Wimmer",root,regions,(100,100),SHARE,"Leonhard Wimmer; MUTEX adaptation",
               "来源 Wikimedia Commons，Leonhard Wimmer；采用 CC BY-SA 3.0。修改：移除无作用外部DTD、增加白底及100mm打印尺寸；星图几何未变。完整原文件及来源、许可在template/upstream和ATTRIBUTION.md。16个黑瓣＝16黑白周期。未确认实物尺寸，不输出绝对lp/mm/DPI。")
    entry.update(source_page="https://commons.wikimedia.org/wiki/File:Siemens_star.svg",modifications="white background; 100 mm canvas; inert obsolete DTD removed; geometry unchanged")
    records.append(entry)
    original=ROOT/"upstream"/"commons-usaf"/"USAF-1951.svg"
    root=ET.fromstring(original.read_text(encoding="utf-8"))
    width,height=float(root.get("width")),float(root.get("height"))
    size=(width*25.4/90,height*25.4/90)
    root.set("viewBox",f"0 0 {width} {height}")
    root.set("width",f"{size[0]:.9f}mm");root.set("height",f"{size[1]:.9f}mm")
    white=ET.Element(f"{{{NS}}}rect",dict(x="0",y="0",width=str(width),height=str(height),fill="white"));root.insert(0,white)
    regions=[]
    def walk(node,H):
        H=H@transform(node.get("transform",""))
        rects=[child for child in node if child.tag.rsplit("}",1)[-1]=="rect"]
        if len(rects)==3:
            points=[]
            for child in rects:
                x,y,w,h=[float(child.get(k,0)) for k in ["x","y","width","height"]]
                if abs(max(w,h)/min(w,h)-5)>.05:break
                pts=np.array([[x,y,1],[x+w,y,1],[x+w,y+h,1],[x,y+h,1]])@H.T
                points.append(pts[:,:2])
            if len(points)==3:
                widths=[np.ptp(p,axis=0) for p in points]
                minor=min(widths[0]);frequency=1/(2*minor*25.4/90)
                k=round(6*math.log2(frequency))
                if abs(frequency/(2**(k/6))-1)>.025:raise ValueError("USAF drawing frequency mismatch")
                direction="vertical" if widths[0][1]>widths[0][0] else "horizontal"
                center=np.concatenate(points).mean(axis=0);period=2*minor
                bw,bh=(3.2*period,1.6*period) if direction=="vertical" else (1.6*period,3.2*period)
                box=((center[0]-bw/2)/width,(center[1]-bh/2)/height,bw/width,bh/height)
                if min(box[:2])>=0 and box[0]+box[2]<=1 and box[1]+box[3]<=1:
                    group,element=k//6,k%6+1
                    key=f"usaf-g{group}e{element}-{direction}"
                    regions.append(Region(key,"usaf",box,f"USAF {group}/{element} · {direction}",dict(group=group,element=element,direction=direction,
                                          unit_id="commons-usaf",frequency_index=k,multi_frequency=True)))
        for child in node:walk(child,H)
    walk(root,np.eye(3))
    if len(regions)!=48:raise ValueError(f"Unexpected USAF bars: {len(regions)}")
    element(root,"metadata").text="USAF-1951 by Setreset, typography edit Mikhail Ryazanov; CC-BY-SA-3.0. MUTEX derivative: white background, explicit viewBox and legacy 90 px/in physical size; geometry unchanged. https://commons.wikimedia.org/wiki/File:USAF-1951.svg"
    entry=save("commons-usaf","开放图卡 · USAF1951 · Setreset",root,regions,size,SHARE,"Setreset; Mikhail Ryazanov; MUTEX adaptation",
               "来源Wikimedia Commons；Setreset绘制、Mikhail Ryazanov排字修订；CC BY-SA 3.0。原图完整保留。衍生图增加白底/viewBox和旧版Inkscape 90px/in物理尺寸，48组正交三线条的几何未变；覆盖-2/1到1/6。默认未确认实物尺寸；应实测组-2元素1黑线宽2mm确认，再启用绝对lp/mm/DPI。线条只有4个频率组，达到最高测试频率只能标示图卡上限，不代表光学极限。")
    entry.update(source_page="https://commons.wikimedia.org/wiki/File:USAF-1951.svg",modifications="white background; explicit viewBox; legacy 90 px/in physical dimensions; geometry unchanged")
    records.append(entry)
    return records

def manifest(charts):
    files=[]
    for file in sorted(ROOT.rglob("*")):
        if file.is_file() and file.name!="manifest.json":
            files.append(dict(path=file.relative_to(ROOT).as_posix(),bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    write_json(ROOT/"manifest.json",dict(format="MUTEX Public Template Library",version=1,reviewed_on="2026-10-17",charts=charts,files=files))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--manifest-only",action="store_true",help="Re-hash reviewed files after a documentation-only change")
    parser.add_argument("--checkerboard-only",action="store_true",help="Add or rebuild only the checkerboard; keep the five previously reviewed charts byte-for-byte")
    args=parser.parse_args()
    if args.manifest_only:
        records=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))["charts"]
        manifest(records)
        print(f"Updated checksums for {len(records)} public charts")
        return
    if args.checkerboard_only:
        records=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))["charts"]
        addition=checkerboard()
        records=[r for r in records if r['id']!=addition['id']]+[addition]
        manifest(records)
        print(f"Updated checkerboard; library contains {len(records)} public charts")
        return
    # Wedge is supported by the product core, not rasterized into another type.
    records=originals()+upstream()+[checkerboard()]
    manifest(records)
    print(json.dumps([{"id":c["id"],"name":c["name"]} for c in records],ensure_ascii=False,indent=2))

if __name__=="__main__":main()
