"""Reference-assisted and chart-independent target discovery.

Only the small registration preview is used for discovery. The analysis engine
always reads measurements from the original image. No private artwork is built
into this module, and an unmatched generic template never supplies a scale.
"""
from __future__ import annotations
import copy
import cv2
import numpy as np
from scipy.ndimage import map_coordinates
from .models import Region


def _gray(image):
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image


def _star_signature(gray, cx, cy, radius):
    theta=np.arange(2048)*2*np.pi/2048
    profiles=map_coordinates(gray.astype(np.float32),
        [cy+np.array([.55,.7,.82])[:,None]*radius*np.sin(theta),
         cx+np.array([.55,.7,.82])[:,None]*radius*np.cos(theta)],order=1,mode='nearest')
    profiles-=profiles.mean(axis=1,keepdims=True)
    spectrum=np.abs(np.fft.rfft(profiles,axis=1))
    score=spectrum.mean(axis=0);score[:8]=0;score[181:]=0
    cycles=int(np.argmax(score))
    energy=np.sum(spectrum[:,8:181]**2,axis=1)
    concentration=float(np.mean(spectrum[:,cycles]**2/np.maximum(energy,1e-9)))
    agree=int(np.sum(np.argmax(spectrum[:,8:181],axis=1)+8==cycles))
    return cycles,concentration,agree


def _radial_centers(gray,max_count):
    """Intersect radial edge segments; works without a circular outline."""
    h,w=gray.shape
    lines=cv2.HoughLinesP(cv2.Canny(cv2.GaussianBlur(gray,(3,3),.6),35,90),1,np.pi/360,
        threshold=20,minLineLength=max(15,int(min(w,h)*.025)),maxLineGap=3)
    if lines is None:return []
    lines=np.asarray(lines).reshape(-1,4).astype(float)
    vector=lines[:,2:]-lines[:,:2];length=np.linalg.norm(vector,axis=1)
    order=np.argsort(length)[-900:];lines=lines[order];vector=vector[order];length=length[order]
    normals=np.column_stack([-vector[:,1],vector[:,0]])/length[:,None]
    ds=np.sum(normals*lines[:,:2],axis=1)
    i,j=np.triu_indices(len(lines),1);det=normals[i,0]*normals[j,1]-normals[i,1]*normals[j,0]
    safe=abs(det)>.3;i=i[safe];j=j[safe];det=det[safe]
    cx=(ds[i]*normals[j,1]-normals[i,1]*ds[j])/det
    cy=(normals[i,0]*ds[j]-ds[i]*normals[j,0])/det
    valid=(cx>10)&(cx<w-10)&(cy>10)&(cy<h-10)
    # Limit extrapolation to avoid arbitrary intersections of unrelated marks.
    p=np.column_stack([cx,cy]);mi=(lines[i,:2]+lines[i,2:])/2;mj=(lines[j,:2]+lines[j,2:])/2
    valid&=(np.linalg.norm(p-mi,axis=1)<length[i]*1.25)&(np.linalg.norm(p-mj,axis=1)<length[j]*1.25)
    cx=cx[valid];cy=cy[valid]
    if not len(cx):return []
    cell=max(3,int(min(w,h)/350));gw=int(np.ceil(w/cell));gh=int(np.ceil(h/cell))
    hist=np.bincount((cy//cell).astype(int)*gw+(cx//cell).astype(int),minlength=gw*gh).reshape(gh,gw).astype(float)
    hist=cv2.GaussianBlur(hist,(3,3),.6)
    candidates=[]
    for _ in range(min(max_count*2,180)):
        iy,ix=np.unravel_index(np.argmax(hist),hist.shape)
        if hist[iy,ix]<2:break
        point=np.array([(ix+.5)*cell,(iy+.5)*cell])
        yy,xx=np.ogrid[:gh,:gw];hist[(xx-ix)**2+(yy-iy)**2<(max(8,min(w,h)*.02)/cell)**2]=0
        keep=abs(normals@point-ds)<cell*1.8
        if keep.sum()<8:continue
        for k in range(3):
            point=np.linalg.lstsq(normals[keep],ds[keep],rcond=None)[0]
            keep=abs(normals@point-ds)<max(1.5,cell*.6)
            if keep.sum()<8:break
        if keep.sum()<8:continue
        radius=float(np.percentile(np.maximum(np.linalg.norm(lines[keep,:2]-point,axis=1),np.linalg.norm(lines[keep,2:]-point,axis=1)),75))
        if radius<18:continue
        candidates.append((float(point[0]),float(point[1]),radius))
    return candidates


def detect_stars(image,max_count=128):
    """Find complete binary/sinusoidal stars by circular boundary + harmonics.

    An isolated circular logo is not accepted: the same angular harmonic must
    dominate at three radii. Cropped stars are intentionally not accepted.
    """
    gray=_gray(image);h,w=gray.shape
    if min(h,w)<96:return []
    output=[]
    for cx,cy,r in _radial_centers(gray,max_count):
        choices=[]
        for factor in [.7,.85,1.,1.08]:
            radius=r*factor
            if min(cx-radius,cy-radius,w-1-cx-radius,h-1-cy-radius)<2:continue
            cycles,concentration,agree=_star_signature(gray,cx,cy,radius)
            if cycles>=12 and concentration>=.42 and agree==3:choices.append((radius,cycles,concentration))
        if not choices:continue
        radius,cycles,concentration=max(choices,key=lambda c:c[0])
        output.append(dict(cx=cx,cy=cy,radius=radius*.9,cycles=cycles,confidence=concentration))
    circles=cv2.HoughCircles(cv2.GaussianBlur(gray,(5,5),1),cv2.HOUGH_GRADIENT,
        dp=1.2,minDist=max(20,min(w,h)*.035),param1=100,param2=33,
        minRadius=max(16,int(min(w,h)*.018)),maxRadius=int(min(w,h)*.48))
    for cx,cy,r in np.asarray(circles).reshape(-1,3) if circles is not None else []:
        if min(cx-r,cy-r,w-1-cx-r,h-1-cy-r)<2:continue
        cycles,concentration,agree=_star_signature(gray,cx,cy,r)
        if cycles<12 or concentration<.42 or agree<3:continue
        if any(np.hypot(cx-c['cx'],cy-c['cy'])<max(r,c['radius'])*.65 for c in output):continue
        output.append(dict(cx=float(cx),cy=float(cy),radius=float(r),cycles=cycles,confidence=concentration))
        if len(output)>=max_count:break
    # Repeated grids often have incomplete circle votes because wedges touch
    # the boundary. Infer grid centers from verified stars, then independently
    # validate the same harmonic at every additional complete location.
    def clusters(values,tolerance):
        groups=[]
        for value in sorted(values):
            if groups and value-np.mean(groups[-1])<tolerance:groups[-1].append(value)
            else:groups.append([value])
        return [float(np.mean(g)) for g in groups]
    if len(output)>=4:
        r=float(np.median([c['radius'] for c in output]));xs=clusters([c['cx'] for c in output],r*.5);ys=clusters([c['cy'] for c in output],r*.5)
        if len(xs)>1 and len(ys)>1:
            for cy in ys:
                for cx in xs:
                    if len(output)>=max_count:break
                    if min(cx-r,cy-r,w-1-cx-r,h-1-cy-r)<2:continue
                    if any(np.hypot(cx-c['cx'],cy-c['cy'])<r*.7 for c in output):continue
                    cycles,concentration,agree=_star_signature(gray,cx,cy,r)
                    if cycles>=12 and concentration>=.42 and agree==3:output.append(dict(cx=cx,cy=cy,radius=r,cycles=cycles,confidence=concentration))
    if not output:return []
    ys=clusters([c['cy'] for c in output],float(np.median([c['radius'] for c in output]))*.5)
    return sorted(output,key=lambda c:(int(np.argmin(abs(np.array(ys)-c['cy']))),c['cx']))


def discover_regions(image,max_edges=40,max_stars=128):
    """Return conservative native-coordinate target candidates in a preview."""
    from .detection import suggest_edges
    from .analysis.sfr import slanted_edge
    from .config import AnalysisConfig
    gray=_gray(image);h,w=gray.shape;regions=[]
    stars=detect_stars(image,max_stars)
    for i,c in enumerate(stars):
        # Exclude boundary/registration marks and retain the complete star disk.
        r=c['radius']*.92;x=(c['cx']-r)/w;y=(c['cy']-r)/h
        regions.append(Region(f'star-{i+1:03d}','star',(x,y,2*r/w,2*r/h),f'西门子星 {i+1}',
            {'cycles':c['cycles'],'pattern':'binary','center':[.5,.5],
             'detected_confidence':c['confidence'],'auto_detect':True}))
        regions[-1].params['discovery_generated']=True
    # Hough suggestions include lettering and wedges. Reject multiple-edge
    # strips by the native SFR fit and by polarity consistency across rows.
    for box in suggest_edges(image,max_count=max_edges*5):
        x,y,bw,bh=box;cx=(x+bw/2)*w;cy=(y+bh/2)*h
        if any(np.hypot(cx-c['cx'],cy-c['cy'])<c['radius']*1.1 for c in stars):continue
        crop=gray[int(y*h):int((y+bh)*h),int(x*w):int((x+bw)*w)].astype(float)/255
        result=slanted_edge(crop,AnalysisConfig(reject_clipping=False))
        values=result.get('values',{})
        if result.get('confidence',0)<.6 or 'invalid_edge' in result.get('flags',[]):continue
        if values.get('edge_fit_rms_px',10)>.32 or values.get('contrast',0)<.2:continue
        if values.get('esf_empty_fraction',1)>.1:continue
        # A clean edge has predominantly one significant gradient per row.
        a=crop.T if np.mean(abs(np.diff(crop,axis=0)))>np.mean(abs(np.diff(crop,axis=1))) else crop
        g=np.diff(cv2.GaussianBlur(a,(5,1),.8),axis=1)
        polarity=np.sign(np.median(a[:,-4:])-np.median(a[:,:4]))
        unwanted=np.sum(np.maximum(-g*polarity,0),axis=1)
        wanted=np.sum(np.maximum(g*polarity,0),axis=1)
        if np.median(unwanted/np.maximum(wanted,1e-6))>.12:continue
        regions.append(Region(f'edge-{sum(r.kind=="edge" for r in regions)+1:03d}','edge',box,
            f'斜边 {sum(r.kind=="edge" for r in regions)+1}',{'auto_detect':True,'discovery_generated':True}))
        if sum(r.kind=='edge' for r in regions)>=max_edges:break
    return regions


def prepare_chart_targets(chart,max_side=2400):
    """Author a reusable ROI definition from its local preview, not a sample."""
    if not chart.preview:raise ValueError('图卡需要预览缩略图才能寻找测量区域')
    image=cv2.imread(str(chart.preview),cv2.IMREAD_COLOR)
    if image is None:raise ValueError('无法读取图卡缩略图')
    if max(image.shape[:2])>max_side:image=cv2.resize(image,None,fx=max_side/max(image.shape[:2]),fy=max_side/max(image.shape[:2]))
    result=copy.deepcopy(chart)
    # Generic templates also use auto_detect to permit an unknown-card
    # fallback. Their precise authored ROIs, and all manual/wedge ROIs, stay.
    def generated(r):return r.kind in {'star','edge'} and (r.params.get('discovery_generated') or (r.params.get('auto_detect') and not r.params.get('target_family')))
    retained=[r for r in result.regions if not generated(r)]
    candidates=discover_regions(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    ids={r.id for r in retained}
    for r in candidates:
        x,y,w,h=r.box
        duplicate=False
        for old in retained:
            if old.kind!=r.kind:continue
            ox,oy,ow,oh=old.box
            intersection=max(0,min(x+w,ox+ow)-max(x,ox))*max(0,min(y+h,oy+oh)-max(y,oy))
            if intersection/max(min(w*h,ow*oh),1e-12)>.7:
                duplicate=True;break
        if duplicate:continue
        if r.id in ids:r.id='detected-'+r.id
        while r.id in ids:r.id='detected-'+r.id
        ids.add(r.id);retained.append(r)
    result.regions=retained
    result.notes+='\n自动生成的星图/斜边区域。星图为二值CTF；斜边需检查剪切、曲线和打印质量。支持整卡或局部参考匹配。'
    return result


def reference_wedge_samples(chart,box,direction='vertical',count=80):
    """Author wedge frequency geometry from a high-quality reference preview.

    This describes the artwork, never a captured sample. Frequencies are the
    number of black/white periods across the entire normalized ROI section.
    """
    from scipy.signal import find_peaks
    a=cv2.imread(str(chart.preview),cv2.IMREAD_GRAYSCALE)
    if a is None:raise ValueError('无法读取图卡缩略图')
    hh,ww=a.shape;x,y,w,h=box
    a=a[int(y*hh):int((y+h)*hh),int(x*ww):int((x+w)*ww)].astype(float)/255
    if direction=='horizontal':a=a.T
    output=[]
    for t in np.linspace(.035,.965,count):
        row=min(len(a)-1,int(t*len(a)));p=a[max(0,row-1):row+2].mean(axis=0)
        # Margins can contain labels; use the center 70% of the wedge width.
        lo=int(len(p)*.15);hi=int(len(p)*.85);v=p[lo:hi]
        indices,_=find_peaks(-v,prominence=max((np.percentile(v,90)-np.percentile(v,10))*.35,.1),distance=2)
        if len(indices)<3:continue
        periods=np.diff(indices)
        median=float(np.median(periods))
        if np.std(periods)/max(median,1e-9)>.25:continue
        output.append({'t':float(t),'cycles_across':float(len(p)/median),
                       'band_start':float(max(0,(lo+indices[0]-median*.4)/len(p))),
                       'band_end':float(min(1,(lo+indices[-1]+median*.4)/len(p)))})
    if len(output)<8:raise ValueError('参考楔形条纹不足，需高分辨率缩略图或明确的频率几何')
    return output


def target_physical_scale(chart,region,native_homography):
    """Convert polar/cross-section cy/px using the same sampling geometry.

    Slanted edges use frequency covectors instead. A wedge is measured along
    its known cross section; a star is measured along a circular arc. Neither
    should inherit an unrelated horizontal image-axis scale after rotation.
    """
    if not chart.calibrated or not chart.physical_size_mm:return None
    M=np.asarray(native_homography,float)
    physical=np.asarray(chart.physical_size_mm)*np.asarray(region.box[2:])
    if region.kind=='wedge':
        vertical=region.params.get('direction','vertical')=='vertical'
        loci=np.array([[[0,.5],[1,.5]]] if vertical else [[[.5,0],[.5,1]]],float)
        p=cv2.perspectiveTransform(loci,M)[0]
        return float(np.linalg.norm(p[1]-p[0])/physical[0 if vertical else 1])
    if region.kind=='star':
        # The authoring box must describe a physically circular star. An
        # arbitrarily rectangular pattern has no single ring lp/mm scale.
        if abs(physical[0]/physical[1]-1)>.04:return None
        center=np.array(region.params.get('center',[.5,.5]),float)
        p=cv2.perspectiveTransform(np.array([[center,center+[1e-4,0],center+[0,1e-4]]],float),M)[0]
        J=np.column_stack([(p[1]-p[0])/1e-4,(p[2]-p[0])/1e-4])
        theta=np.arange(128)*2*np.pi/128;tangent=np.stack([-np.sin(theta),np.cos(theta)])
        return float(np.median(np.linalg.norm(J@tangent,axis=0))/np.mean(physical))
    return None


def _feature_match(ref,image):
    """SIFT matches reference to an arbitrary visible crop; mirror is explicit."""
    detector=cv2.SIFT_create(nfeatures=14000,contrastThreshold=.025,edgeThreshold=14)
    ki,di=detector.detectAndCompute(image,None)
    if di is None:return None
    best=None
    for reflected in [False,True]:
        r=cv2.flip(ref,1) if reflected else ref
        kr,dr=detector.detectAndCompute(r,None)
        if dr is None:continue
        matches=cv2.BFMatcher(cv2.NORM_L2).knnMatch(dr,di,k=2)
        matches=[m for pair in matches if len(pair)==2 for m,n in [pair] if m.distance<.67*n.distance]
        if len(matches)<12:continue
        # Reciprocal uniqueness protects repeated star grids from an arbitrary
        # many-to-one homography. Residuals alone do not establish correctness.
        unique={}
        for m in sorted(matches,key=lambda m:m.distance):unique.setdefault(m.trainIdx,m)
        matches=list(unique.values())
        if len(matches)<12:continue
        src=np.array([kr[m.queryIdx].pt for m in matches],np.float32)
        dst=np.array([ki[m.trainIdx].pt for m in matches],np.float32)
        M,mask=cv2.findHomography(src,dst,cv2.USAC_MAGSAC,2.5,maxIters=10000,confidence=.999)
        if M is None or mask is None:continue
        mask=mask.ravel().astype(bool);count=int(mask.sum())
        if count<12 or count/len(matches)<.22:continue
        hull=cv2.convexHull(dst[mask]);area=float(cv2.contourArea(hull))/(image.shape[0]*image.shape[1])
        if area<.035:continue
        predicted=cv2.perspectiveTransform(src[mask,None,:],M)[:,0]
        rms=float(np.sqrt(np.mean(np.sum((predicted-dst[mask])**2,axis=1))))
        if rms>2:continue
        if reflected:M=M@np.array([[-1,0,ref.shape[1]-1],[0,1,0],[0,0,1]],float)
        candidate=(count*area/(.2+rms),M,count,rms,area,reflected)
        if best is None or candidate[0]>best[0]:best=candidate
    return best


def register_auto_chart(chart,source,config):
    image=_gray(source.preview(2600));iw,ih=source.metadata.width,source.metadata.height
    ref=cv2.imread(str(chart.preview),cv2.IMREAD_GRAYSCALE) if chart.preview else None
    match=_feature_match(ref,image) if ref is not None else None
    if match:
        _,M,count,rms,area,reflected=match
        H=np.diag([iw/image.shape[1],ih/image.shape[0],1])@M@np.diag([ref.shape[1],ref.shape[0],1])
        # A finite, convex chart projection is required even if most of the
        # chart lies outside the image. Partial coverage is reported separately.
        corners=cv2.perspectiveTransform(np.array([[[0,0],[1,0],[1,1],[0,1]]],float),H)[0]
        if not np.isfinite(corners).all() or not cv2.isContourConvex(corners.astype(np.float32)):
            raise ValueError('图卡配准投影无效，请改用四点或局部候选模式')
        visible=[];outside=[]
        from .detection import transform_box
        for r in chart.regions:
            box,cropped=transform_box(r.box,H,iw,ih)
            (outside if cropped or min(box[2:])<4 else visible).append(r.id)
        status={'method':'reference_sift_partial_homography','verified':True,'inliers':count,
                'rms_px':rms*iw/image.shape[1],'reference_mirrored':reflected,
                'match_image_area_fraction':area,'visible_regions':visible,'outside_regions':outside,
                'coverage':len(visible)/max(1,len(chart.regions)),
                'warning':'参考图局部配准；仅测完整可见ROI，未对原图重采样。重复星图单元的绝对编号需结合邻近唯一图案核验。',
                'homography':H.tolist()}
        return H,status
    if any(r.params.get('auto_detect') for r in chart.regions):
        regions=discover_regions(cv2.cvtColor(image,cv2.COLOR_GRAY2RGB))
        if not regions:raise ValueError('未能匹配图卡，也没有找到完整可测的星图或干净斜边；请使用手工ROI或四点配准')
        H=np.diag([iw,ih,1.])
        status={'method':'generic_detected_targets','verified':False,'homography':H.tolist(),
            'detected_regions':[dict(id=r.id,kind=r.kind,box=r.box,label=r.label,params=r.params,enabled=r.enabled) for r in regions],
            'coverage':None,'warning':'未匹配参考图；按当前图像独立检测候选星图/斜边，本次禁用物理尺度。请检查ROI。'}
        return H,status
    raise ValueError('无法可靠配准该图卡或局部。请用通用候选模式/手工ROI；不会假设整卡铺满照片')
