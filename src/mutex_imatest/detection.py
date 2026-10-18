from __future__ import annotations
import numpy as np
import cv2

def suggest_edges(rgb,max_count=48):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY) if rgb.ndim==3 else rgb
    h,w=gray.shape
    blur=cv2.GaussianBlur(gray,(5,5),1)
    edges=cv2.Canny(blur,40,100)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=45,minLineLength=max(30,min(w,h)//30),maxLineGap=5)
    if lines is None: return []
    candidates=[]
    for x1,y1,x2,y2 in np.asarray(lines).reshape(-1,4):
        length=float(np.hypot(x2-x1,y2-y1))
        angle=abs(np.degrees(np.arctan2(y2-y1,x2-x1)))%90
        slant=min(angle,90-angle)
        if not .6<=slant<=16: continue
        cx=(x1+x2)/2;cy=(y1+y2)/2
        half_l=min(length*.3,70)
        horizontal=abs(x2-x1)>abs(y2-y1)
        bw,bh=(2*half_l,48) if horizontal else (48,2*half_l)
        x=max(0,cx-bw/2);y=max(0,cy-bh/2)
        bw=min(bw,w-x);bh=min(bh,h-y)
        if min(bw,bh)<28: continue
        box=(x/w,y/h,bw/w,bh/h)
        if any(np.hypot((x+bw/2)/w-(b[0]+b[2]/2),(y+bh/2)/h-(b[1]+b[3]/2))<.045 for _,b in candidates): continue
        candidates.append((length,box))
    return [b for _,b in sorted(candidates,reverse=True)[:max_count]]

def register_chart(chart,source,config):
    if config.registration=="auto_chart":
        from .chart_targets import register_auto_chart
        return register_auto_chart(chart,source,config)
    if config.registration=="usaf":
        from .usaf_registration import register_usaf
        return register_usaf(chart,source,config)
    iw,ih=source.metadata.width,source.metadata.height
    H=np.array([[iw,0,0],[0,ih,0],[0,0,1]],float)
    status={"method":"full_frame_scale","verified":False,"warning":"默认假设图卡铺满画面。裁切或留白时，请使用四点配准。"}
    if config.registration=="anchors":
        if not config.anchors or len(config.anchors)!=4: raise ValueError("Four chart-corner anchors required")
        points=np.asarray(config.anchors,float)
        if points.shape!=(4,2) or not np.all(np.isfinite(points)): raise ValueError("Invalid anchors")
        area=abs(cv2.contourArea(points.astype(np.float32)))
        if area<iw*ih*.001: raise ValueError("Registration corners have insufficient area")
        H=cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),points.astype(np.float32))
        status={"method":"four_corner_homography","verified":True,"anchors":points.tolist(),"warning":"在原生像素上测量；未重采样 ROI"}
    elif config.registration=="features":
        if not chart.preview: raise ValueError("Feature registration requires chart thumbnail")
        ref=cv2.imread(str(chart.preview),cv2.IMREAD_GRAYSCALE)
        if ref is None: raise ValueError("Cannot load chart thumbnail")
        rgb=source.preview(2048); image=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        orb=cv2.ORB_create(nfeatures=8000)
        kr,dr=orb.detectAndCompute(ref,None);ki,di=orb.detectAndCompute(image,None)
        if dr is None or di is None: raise ValueError("Not enough chart features; use manual corners")
        matches=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(dr,di,k=2)
        matches=[m for pair in matches if len(pair)==2 for m,n in [pair] if m.distance<.72*n.distance]
        if len(matches)<12: raise ValueError("Not enough reliable chart matches; use manual corners")
        src=np.array([kr[m.queryIdx].pt for m in matches],np.float32)
        dst=np.array([ki[m.trainIdx].pt for m in matches],np.float32)
        M,inliers=cv2.findHomography(src,dst,cv2.RANSAC,3)
        if M is None or int(inliers.sum())<10: raise ValueError("Registration failed; repeated chart patterns may be ambiguous")
        H=np.diag([iw/image.shape[1],ih/image.shape[0],1])@M@np.diag([ref.shape[1],ref.shape[0],1])
        status={"method":"orb_homography","verified":False,"inliers":int(inliers.sum()),"warning":"重复图案可能错配，请在叠加预览上检查"}
    status["homography"]=H.tolist()
    return H,status

def transform_box(box,H,width,height):
    x,y,w,h=box
    corners=np.array([[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]],np.float64)
    transformed=cv2.perspectiveTransform(corners,H)[0]
    lo=np.floor(transformed.min(axis=0)).astype(int); hi=np.ceil(transformed.max(axis=0)).astype(int)
    outside=bool(np.any(lo<0) or hi[0]>width or hi[1]>height)
    lo=np.maximum(lo,0);hi=np.minimum(hi,[width,height])
    return (int(lo[0]),int(lo[1]),int(hi[0]-lo[0]),int(hi[1]-lo[1])),outside

def usaf_native_axes(H,position,direction):
    """Map template bar axes to native ROI axes without resampling pixels."""
    point=cv2.perspectiveTransform(np.array([[position]],np.float64),np.linalg.inv(H))[0,0]
    axis=0 if direction=="vertical" else 1
    step=np.eye(2)*1e-5
    projected=cv2.perspectiveTransform(np.array([[point,point+step[axis],point+step[1-axis]]],np.float64),H)[0]
    normal=projected[1]-projected[0]
    native_axis=int(abs(normal[1])>abs(normal[0]))
    reverse_length=bool((projected[2]-projected[0])[1-native_axis]<0)
    return ("horizontal" if native_axis else "vertical"),reverse_length


def local_scale(chart,H,position,normal):
    if not chart.calibrated or not chart.physical_size_mm: return None
    inv=np.linalg.inv(H)
    point=cv2.perspectiveTransform(np.array([[position]],np.float64),inv)[0,0]
    eps=1e-5
    points=np.array([[point,point+[eps,0],point+[0,eps]]],np.float64)
    projected=cv2.perspectiveTransform(points,H)[0]
    J=np.column_stack([(projected[1]-projected[0])/(eps*chart.physical_size_mm[0]),
                       (projected[2]-projected[0])/(eps*chart.physical_size_mm[1])])
    # Spatial frequencies are covectors: f_object = J.T @ f_image.
    return float(np.linalg.norm(J.T@np.asarray(normal,float)))
