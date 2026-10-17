"""Generate USAF measurement ROIs from actual vector bars, not a raster proxy."""
from __future__ import annotations
from collections import defaultdict
from itertools import combinations
import math
import re
import numpy as np
from .models import Region
from .svg_source import read_svg,svg_dimensions


def detect_svg_usaf(path, group=3, element=5, directions="both",all_frequencies=False):
    if not -2 <= group <= 9 or not 1 <= element <= 6:
        raise ValueError("Invalid USAF group/element")
    if directions not in {"vertical","horizontal","both"}:
        raise ValueError("Invalid USAF directions")
    source_text, tree = read_svg(path)
    view, size = svg_dimensions(tree)
    if any("transform" in n.attrib for n in tree.iter()):
        raise ValueError("USAF 矢量识别暂需展开 SVG 的 transform；仍可手工添加测量区域")
    vx, vy, vw, vh = view
    mm_x, mm_y = size[0]/vw, size[1]/vh
    styles = {}
    for node in tree.iter():
        if node.tag.rsplit("}",1)[-1] == "style":
            for cls, body in re.findall(r"\.([\w-]+)\s*\{([^}]+)\}", "".join(node.itertext())):
                styles[cls] = dict(p.split(":",1) for p in body.split(";") if ":" in p)
    def rectangle(node):
        style = {}
        for cls in node.attrib.get("class","").split():
            style.update(styles.get(cls,{}))
        style.update(p.split(":",1) for p in node.attrib.get("style","").split(";") if ":" in p)
        fill = node.attrib.get("fill",style.get("fill","black")).strip().lower()
        if fill not in {"black","#000","#000000","rgb(0,0,0)"}:
            return None
        tag = node.tag.rsplit("}",1)[-1]
        if tag == "polygon":
            values = re.findall(r"[-+]?(?:\d*\.)?\d+(?:[eE][-+]?\d+)?",node.attrib.get("points",""))
            if len(values) != 8:
                return None
            points = np.array(list(map(float,values))).reshape(-1,2)
            if len(np.unique(points[:,0])) != 2 or len(np.unique(points[:,1])) != 2:
                return None
            lo,hi = points.min(axis=0),points.max(axis=0)
            x,y = lo; w,h = hi-lo
        elif tag == "rect":
            x,y,w,h = [float(node.attrib.get(k,0)) for k in ["x","y","width","height"]]
        else:
            return None
        if min(w,h) <= 0 or not 4.7 < max(w,h)/min(w,h) < 5.3:
            return None
        vertical = h>w
        frequency = 1/(2*(w*mm_x if vertical else h*mm_y))
        k = round(6*math.log2(frequency))
        if not -12 <= k <= 53 or abs(frequency/2**(k/6)-1) > .025:
            return None
        return {"box":(x,y,w,h),"center":np.array([x+w/2,y+h/2]),"vertical":vertical,"k":k}
    units=[]
    for parent in tree.iter():
        if parent.tag.rsplit("}",1)[-1] != "g":
            continue
        by_key=defaultdict(list)
        for node in parent:
            bar=rectangle(node)
            if bar:by_key[(bar["k"],bar["vertical"])].append(bar)
        triplets=[]
        for (k,vertical),bars in by_key.items():
            if len(bars)<3 or len(bars)>18:
                continue
            axis,cross=(0,1) if vertical else (1,0)
            for triple in combinations(bars,3):
                triple=sorted(triple,key=lambda b:b["center"][axis])
                centers=np.array([b["center"] for b in triple])
                gaps=np.diff(centers[:,axis]);period=float(gaps.mean())
                minor=np.mean([b["box"][2 if vertical else 3] for b in triple])
                if period<=0 or max(abs(gaps-period))>.035*period or abs(period/(2*minor)-1)>.035 or np.ptp(centers[:,cross])>.06*period:
                    continue
                triplets.append({"k":k,"direction":"vertical" if vertical else "horizontal", "center":centers.mean(axis=0),"period":period})
        if any(t["k"]==0 for t in triplets) and len(triplets)>=12:
            units.append(triplets)
    regions=[];fiducials=[]
    target_k=6*group+element-1
    for index,triplets in enumerate(units):
        unit=f"svg-usaf-{index+1:03}"
        for t in triplets:
            x,y=t["center"];p=t["period"]
            if 0<=t["k"]<=17:
                fiducials.append({"kind":"usaf","unit_id":unit,"k":t["k"],"direction":t["direction"],
                                  "position":[(x-vx)/vw,(y-vy)/vh],"period_normalized":[p/vw,p/vh]})
            if (not all_frequencies and t["k"]!=target_k) or directions not in {"both",t["direction"]}:
                continue
            w,h=(3.2*p,1.6*p) if t["direction"]=="vertical" else (1.6*p,3.2*p)
            box=((x-w/2-vx)/vw,(y-h/2-vy)/vh,w/vw,h/vh)
            if min(box[:2])<0 or box[0]+box[2]>1 or box[1]+box[3]>1:
                continue
            direction_name="竖线" if t["direction"]=="vertical" else "横线"
            actual_group=t["k"]//6;actual_element=t["k"]%6+1
            suffix=f"-g{actual_group}e{actual_element}" if all_frequencies else ""
            regions.append(Region(f"{unit}-{t['direction']}{suffix}","usaf",box,
                                  f"单元 {index+1:02} · USAF {actual_group}/{actual_element} · {direction_name}",
                                  {"group":actual_group,"element":actual_element,"direction":t["direction"],"unit_id":unit,
                                   "frequency_index":t["k"],"multi_frequency":all_frequencies}))
    if not regions:
        raise ValueError("未找到所选组/元素的完整 USAF 三条纹；可改选频率或手工框选")
    if all_frequencies:
        _reference_bands(source_text,view,regions)
    return regions,fiducials,size


def _reference_bands(source_text,view,regions):
    """Preflight coarse bars against visible SVG ink (including overlaid labels).

    This rendering selects a clean averaging band in the *template*. All CTF
    samples still come exclusively from native captured pixels. Store the band
    in the portable ROI so the private SVG is unnecessary for later analysis.
    Fine targets are not judged from a thumbnail with inadequate sampling.
    """
    from .templates import ensure_qt
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtCore import QByteArray,QRectF
    from PySide6.QtGui import QImage,QPainter
    ensure_qt();renderer=QSvgRenderer(QByteArray(source_text.encode()))
    units=defaultdict(list)
    for r in regions:
        if r.params['frequency_index']<=17:units[r.params['unit_id']].append(r)
    for rows in units.values():
        lo=np.min([r.box[:2] for r in rows],axis=0)
        hi=np.max([[r.box[0]+r.box[2],r.box[1]+r.box[3]] for r in rows],axis=0)
        extent=(hi-lo)*np.array(view[2:]);s=1400/max(extent)
        w,h=np.maximum(1,np.ceil(extent*s).astype(int))
        renderer.setViewBox(QRectF(view[0]+lo[0]*view[2],view[1]+lo[1]*view[3],*extent))
        image=QImage(int(w),int(h),QImage.Format.Format_RGBA8888);image.fill(0xffffffff)
        painter=QPainter(image);renderer.render(painter,QRectF(0,0,int(w),int(h)));painter.end()
        pixels=np.frombuffer(image.constBits(),np.uint8).reshape(h,image.bytesPerLine())[:,:w*4].reshape(h,w,4)[...,:3].mean(axis=2)/255
        for r in rows:
            x,y,bw,bh=r.box
            a=np.rint((np.array([x,y])-lo)/(hi-lo)*[w,h]).astype(int)
            z=np.rint((np.array([x+bw,y+bh])-lo)/(hi-lo)*[w,h]).astype(int)
            patch=pixels[max(0,a[1]):min(h,z[1]),max(0,a[0]):min(w,z[0])]
            if r.params['direction']=='horizontal':patch=patch.T
            if min(patch.shape)<8:continue
            black=(np.array([.6,1.6,2.6])/3.2*patch.shape[1]).astype(int)
            white=(np.array([.12,1.1,2.1,3.08])/3.2*patch.shape[1]).astype(int)
            clean=(patch[:,black].max(axis=1)<.15)&(patch[:,white].min(axis=1)>.85)
            edges=np.diff(np.r_[False,clean,False].astype(int));starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
            if not len(starts) or max(ends-starts)<max(3,.055*len(clean)):
                r.params['template_occluded']=True
                continue
            idx=int(np.argmax(ends-starts));start,end=starts[idx],ends[idx]
            # Avoid rasterized reference boundaries. Wide clean bands use their
            # middle half; a narrow uncovered strip needs all available pixels.
            pad=int((end-start)*.15) if end-start>12 else 1
            r.params['profile_band']=[float((start+pad)/len(clean)),float((end-pad)/len(clean))]
            r.params['template_preflight']='visible SVG three-bar gaps; native image sampling only'
