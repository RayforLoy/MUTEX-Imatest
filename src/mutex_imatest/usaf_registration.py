"""Register repeated vector USAF charts and refine each unit on native pixels.

Preview pixels are used only for global localization. CTF remains exclusively
in analysis.engine, reading original precision ROIs through ImageSource.
"""
from __future__ import annotations
from collections import defaultdict
import cv2
import numpy as np
from scipy.spatial import cKDTree
from .utils import check_cancel


def _triplets(gray):
    gray=np.ascontiguousarray(gray)
    low,high=np.percentile(gray,[5,95])
    if high-low<12:return []
    threshold=min(220,low+.6*(high-low))
    _,labels,stats,centers=cv2.connectedComponentsWithStats(np.uint8(gray<threshold)*255,8)
    bars=[]
    for i,(x,y,w,h,area) in enumerate(stats):
        if i==0 or min(w,h)<2 or area<12 or area/(w*h)<.62 or not 3.1<max(w,h)/min(w,h)<8.5:continue
        bars.append((float(centers[i,0]),float(centers[i,1]),int(x),int(y),int(w),int(h)))
    del labels
    groups=[];seen=set()
    for direction in [0,1]:
        subset=[b for b in bars if (b[5]>b[4])==(direction==0)]
        subset.sort(key=lambda b:b[direction])
        axis=np.array([b[direction] for b in subset])
        for b in subset:
            minor,major=(b[4],b[5]) if direction==0 else (b[5],b[4])
            begin,end=np.searchsorted(axis,[b[direction]+1.4*minor,b[direction]+3.6*minor])
            def compatible(c):
                cm,cl=(c[4],c[5]) if direction==0 else (c[5],c[4])
                return abs(c[1-direction]-b[1-direction])<max(2,.1*major) and .65<cm/minor<1.5 and .78<cl/major<1.25
            for c in subset[begin:end]:
                if not compatible(c):continue
                gap=c[direction]-b[direction]
                lo,hi=np.searchsorted(axis,[c[direction]+.88*gap,c[direction]+1.12*gap])
                for d in subset[lo:hi]:
                    if not compatible(d):continue
                    period=(d[direction]-b[direction])/2
                    if not 1.8<major/period<3.25:continue
                    x=min(t[2] for t in [b,c,d]);y=min(t[3] for t in [b,c,d])
                    w=max(t[2]+t[4] for t in [b,c,d])-x;h=max(t[3]+t[5] for t in [b,c,d])-y
                    key=(x//3,y//3,direction)
                    if key in seen:continue
                    seen.add(key)
                    groups.append({"center":np.array([x+w/2,y+h/2]),"period":period,"direction":direction})
    return groups


def _gray(pixels):
    a=pixels[...,min(1,pixels.shape[2]-1)] if pixels.ndim==3 else pixels
    if a.dtype==np.uint8:return a
    if np.issubdtype(a.dtype,np.integer):return np.clip(a.astype(np.float32)*255/np.iinfo(a.dtype).max,0,255).astype(np.uint8)
    return np.clip(a*255,0,255).astype(np.uint8)


def _columns(points,count):
    cv2.setRNGSeed(18)
    _,labels,_=cv2.kmeans(points[:,0:1].astype(np.float32),count,None,
                          (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,100,.01),10,cv2.KMEANS_PP_CENTERS)
    columns=[points[labels.ravel()==i] for i in range(count)]
    return sorted(columns,key=lambda p:np.median(p[:,0]))


def _project(points,H):
    return cv2.perspectiveTransform(np.asarray(points,np.float64)[None],H)[0]


def _global(chart,source,preview):
    from .utils import atomic_json
    def diagnostic(**values):
        debug.update(values)
        atomic_json(config_path,debug)
    config_path=source.config.cache_path()/f"usaf-registration-{source.fingerprint[:12]}.json"
    debug={}
    anchors=np.array([f["position"] for f in chart.fiducials if f.get("kind")=="usaf" and f["k"]==0 and f["direction"]=="vertical"])
    if len(anchors)<6:raise ValueError("USAF 配准需要至少 6 个重复单元；可使用四点配准")
    count=len(np.unique(np.round(anchors[:,0],3)))
    if not 2<=count<=8:raise ValueError("USAF 自动配准暂需 2-8 列重复单元；可使用四点配准")
    candidates=[g for g in _triplets(preview) if g["direction"]==0]
    if not candidates:raise ValueError("没有找到完整的低频 USAF 三条纹，无法配准")
    periods=np.array([g["period"] for g in candidates])
    minimum=max(4,min(12,len(anchors)//3))
    coarse=None
    for p in sorted(periods,reverse=True):
        chosen=np.abs(periods/p-1)<.045
        if chosen.sum()>=minimum:
            coarse=[g for g,yes in zip(candidates,chosen) if yes];break
    if coarse is None:raise ValueError("完整的低频 USAF 单元不足，无法建立图卡坐标")
    p0=float(np.median([g["period"] for g in coarse]))
    points=np.array([g["center"] for g in coarse])
    columns=_columns(points,count)
    if any(len(c)<2 for c in columns):raise ValueError("USAF 列覆盖不足，请使用四点配准")
    slopes=[np.polyfit(c[:,1],c[:,0],1)[0] for c in columns if len(c)>=3]
    shear=float(np.median(slopes)) if slopes else 0
    x_centers=np.array([np.median(c[:,0]-shear*c[:,1]) for c in columns])
    target_step=np.median([d for c in columns for d in np.diff(np.sort(c[:,1])) if d>5*p0])
    if not np.isfinite(target_step):raise ValueError("USAF 行间距无法可靠估计")
    diagnostic(source_anchors=anchors.tolist(),image_coarse_points=points.tolist(),period=p0,
               detected_periods=sorted(periods.tolist(),reverse=True),columns=[c.tolist() for c in columns],
               shear=shear,x_centers=x_centers.tolist(),target_step=float(target_step))
    tree=cKDTree(points);hypotheses={}
    for sign_x,sign_y in [(1,1),(1,-1),(-1,1),(-1,-1)]:
        src=anchors*[sign_x,sign_y]
        src_cols=_columns(src,count)
        source_step=np.median([d for c in src_cols for d in np.diff(np.sort(c[:,1])) if d>1e-5])
        sy=target_step/source_step
        sx=np.median(np.diff(x_centers)/np.diff([np.median(c[:,0]) for c in src_cols]))
        tx=float(np.median(x_centers-sx*np.array([np.median(c[:,0]) for c in src_cols])))
        offsets=sorted({round(float(q-sy*p),1) for p in src_cols[0][:,1] for q in columns[0][:,1]})
        for ty in offsets:
            check_cancel(getattr(source,"cancel",None))
            initial=np.array([[sx*sign_x,shear*sy*sign_y,tx+shear*ty],[0,sy*sign_y,ty],[0,0,1]],float)
            projected=_project(anchors,initial)
            distance,indices=tree.query(projected)
            mask=distance<max(3,p0*.45)
            if mask.sum()<max(6,len(anchors)//3):continue
            fit,inliers=cv2.estimateAffine2D(anchors[mask],points[indices[mask]],method=cv2.RANSAC,ransacReprojThreshold=2.5,maxIters=1000,confidence=.995)
            if fit is None or inliers.sum()<6:continue
            H=np.vstack([fit,[0,0,1]])
            projected=_project(anchors,H)
            inside=(projected[:,0]>=0)&(projected[:,0]<preview.shape[1])&(projected[:,1]>=0)&(projected[:,1]<preview.shape[0])
            distance,indices=tree.query(projected)
            good=inside&(distance<max(3,p0*.3))
            if good.sum()<max(6,len(anchors)//3):continue
            page=_project(np.array([[0,0],[preview.shape[1],0],[preview.shape[1],preview.shape[0]],[0,preview.shape[0]]]),np.linalg.inv(H))
            if page.min()<-.1 or page.max()>1.1:continue
            key=tuple(np.round(H[:2,2]/3).astype(int))+(sign_x,sign_y)
            hypotheses[key]=(int(good.sum()),float(np.median(distance[good])),H)
    diagnostic(hypotheses=[{"matched":a,"residual":b,"H":c.tolist()} for a,b,c in hypotheses.values()])
    if not hypotheses:raise ValueError("重复 USAF 与矢量模板不匹配；请核对图卡版本和方向")
    # Resolve repetitive-row shifts by comparing the actual ruler/lettering ink.
    if chart.source_path and str(chart.source_path).lower().endswith(".svg"):
        from .templates import render_source
        image,_,_=render_source(chart.source_path,max_side=4096)
        from PySide6.QtGui import QImage
        image=image.convertToFormat(QImage.Format.Format_Grayscale8)
        ref=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()].copy()
    else:
        from pathlib import Path
        ref=cv2.imdecode(np.frombuffer(Path(chart.preview).read_bytes(),np.uint8),cv2.IMREAD_GRAYSCALE)
    if ref is None:raise ValueError("Cannot read chart reference thumbnail")
    target=cv2.GaussianBlur(preview,(0,0),1.1).astype(np.float32)
    xx=np.arange(preview.shape[1])[None,:]
    ruler_mask=(xx<x_centers[0]-7*p0)|(xx>x_centers[-1]+7*p0)
    scored=[]
    for matched,residual,H in sorted(hypotheses.values(),key=lambda a:(-a[0],a[1]))[:16]:
        check_cancel(getattr(source,"cancel",None))
        warp=H@np.diag([1/ref.shape[1],1/ref.shape[0],1])
        expected=cv2.warpPerspective(ref,warp,(preview.shape[1],preview.shape[0]),borderValue=255)
        expected=cv2.GaussianBlur(expected,(0,0),1.1).astype(np.float32)
        ink=(expected<235)|(target<235)
        mask=ruler_mask&ink
        if mask.sum()<500:mask=ink
        a,b=expected[mask],target[mask]
        a=a-a.mean();b=b-b.mean()
        correlation=float(np.dot(a,b)/max(np.linalg.norm(a)*np.linalg.norm(b),1e-9))
        scored.append((correlation,matched,residual,H))
    scored.sort(key=lambda a:a[0],reverse=True)
    diagnostic(ink_scores=[{"correlation":a,"matched":b,"residual":c,"H":d.tolist()} for a,b,c,d in scored])
    correlation,matched,residual,H=scored[0]
    if correlation<.12:raise ValueError("USAF 标尺/文字配准置信度不足，请使用四点配准")
    native=np.diag([source.metadata.width/preview.shape[1],source.metadata.height/preview.shape[0],1])@H
    return native,{"coarse_matches":matched,"preview_rms_proxy_px":residual,"reference_ink_correlation":correlation,
                   "runner_up_correlation":scored[1][0] if len(scored)>1 else None,"coarse_period_preview_px":p0}


def register_usaf(chart,source,config):
    preview=_gray(source.preview(4096))
    H,status=_global(chart,source,preview)
    groups=defaultdict(list)
    for f in chart.fiducials:
        if f.get("kind")=="usaf":groups[f["unit_id"]].append(f)
    transforms={}
    for unit,fiducials in groups.items():
        check_cancel(getattr(source,"cancel",None))
        locations=_project([f["position"] for f in fiducials],H)
        first=next(f for f in fiducials if f["k"]==0 and f["direction"]=="vertical")
        point=np.array(first["position"])
        p0=float(np.linalg.norm(_project([point,point+[first["period_normalized"][0],0]],H)[1]-_project([point],H)[0]))
        lo=np.maximum(np.floor(locations.min(axis=0)-2*p0),0).astype(int)
        hi=np.minimum(np.ceil(locations.max(axis=0)+2*p0),[source.metadata.width,source.metadata.height]).astype(int)
        if min(hi-lo)<16:continue
        raw=source.read_roi((*lo,*(hi-lo)))
        detected=_triplets(_gray(raw))
        del raw
        P=[];Q=[]
        for f,prediction in zip(fiducials,locations):
            direction=int(f["direction"]=="horizontal")
            source_point=np.array(f["position"])
            delta=np.array([f["period_normalized"][0],0]) if direction==0 else np.array([0,f["period_normalized"][1]])
            projected=_project([source_point,source_point+delta],H)
            period=float(np.linalg.norm(projected[1]-projected[0]))
            candidates=[d for d in detected if d["direction"]==direction and abs(d["period"]/period-1)<.12
                        and np.linalg.norm(d["center"]+lo-prediction)<max(35,.75*p0)]
            if candidates:
                chosen=min(candidates,key=lambda d:np.linalg.norm(d["center"]+lo-prediction))
                P.append(f["position"]);Q.append(chosen["center"]+lo)
        if len(P)<10:continue
        fit,inliers=cv2.estimateAffine2D(np.array(P),np.array(Q),method=cv2.RANSAC,ransacReprojThreshold=2.5,maxIters=2000,confidence=.999)
        if fit is None or inliers.sum()<10:continue
        keep=inliers.ravel().astype(bool)
        design=np.column_stack([P,np.ones(len(P))])
        local=np.linalg.lstsq(design[keep],np.array(Q)[keep],rcond=None)[0]
        residual=np.linalg.norm(design@local-Q,axis=1)
        rms=float(np.sqrt(np.mean(residual[keep]**2)))
        if rms>1.8:continue
        transforms[unit]={"homography":np.vstack([local.T,[0,0,1]]).tolist(),"matches":int(keep.sum()),"rms_px":rms}
    if not transforms:raise ValueError("USAF 局部定位未通过；没有可安全测量的区域")
    status.update(method="vector_usaf_native_refinement",verified=False,homography=H.tolist(),unit_transforms=transforms,
                  warning=f"USAF 矢量定位：{len(transforms)}/{len(groups)} 单元通过原像素局部拟合。重复图案的绝对单元编号仍需核对标尺；未重采样测量像素。")
    return H,status
