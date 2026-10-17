"""Discrete display orientation; measurement coordinates remain native pixels."""
from dataclasses import dataclass,asdict,replace
from pathlib import Path
import numpy as np


@dataclass(frozen=True)
class PreviewOrientation:
    quarter_turns:int=0
    flip_horizontal:bool=False
    flip_vertical:bool=False

    def __post_init__(self):
        if type(self.quarter_turns) is not int or not 0<=self.quarter_turns<4:raise ValueError('预览旋转只能为 0、90、180 或 270 度')
        if type(self.flip_horizontal) is not bool or type(self.flip_vertical) is not bool:raise ValueError('Invalid preview reflection')

    def matrix(self):
        rotations=[[[1,0],[0,1]],[[0,-1],[1,0]],[[-1,0],[0,-1]],[[0,1],[-1,0]]]
        return np.diag([-1 if self.flip_horizontal else 1,-1 if self.flip_vertical else 1])@np.array(rotations[self.quarter_turns])

    def rotated(self,step):
        # Reflections are in screen axes, so a quarter turn swaps their axes.
        return PreviewOrientation((self.quarter_turns+step)%4,
                                  self.flip_vertical if step%2 else self.flip_horizontal,
                                  self.flip_horizontal if step%2 else self.flip_vertical)

    def mirrored(self,axis):
        if axis not in {'horizontal','vertical'}:raise ValueError('Invalid reflection axis')
        name='flip_'+axis
        return replace(self,**{name:not getattr(self,name)})

    def to_dict(self):return asdict(self)

    @classmethod
    def from_dict(cls,data=None):return cls(**(data or {}))

    def description(self):
        parts=[f'{self.quarter_turns*90}°']
        if self.flip_horizontal:parts.append('左右镜像')
        if self.flip_vertical:parts.append('上下镜像')
        return ' · '.join(parts)


def orientation_from_homography(homography):
    """Choose a quarter-turn/reflection that restores the template axis order."""
    H=np.asarray(homography,float)
    if H.shape!=(3,3) or not np.isfinite(H).all():raise ValueError('缺少有效模板配准')
    p=H@np.array([.5,.5,1.])
    if abs(p[2])<1e-12:raise ValueError('Invalid template projection')
    J=(H[:2,:2]*p[2]-np.outer(p[:2],H[2,:2]))/p[2]**2
    lengths=np.linalg.norm(J,axis=0)
    if min(lengths)<1e-9 or abs(np.linalg.det(J))/np.prod(lengths)<.2:raise ValueError('模板坐标轴退化，无法判断预览方向')
    axes=J/lengths
    choices={}
    for q in range(4):
        for h in [False,True]:
            for v in [False,True]:
                candidate=PreviewOrientation(q,h,v);M=candidate.matrix()
                cost=(min(q,4-q),h+v,q,h)
                key=tuple(M.ravel())
                if key not in choices or cost<choices[key][1]:choices[key]=(candidate,cost)
    ranked=sorted(choices.values(),key=lambda x:(-float(np.trace(x[0].matrix()@axes)),x[1]))
    best=ranked[0][0]
    if float(np.trace(best.matrix()@axes))-float(np.trace(ranked[1][0].matrix()@axes))<.1:
        raise ValueError('图像方向接近 45°，无法可靠选择 90° 方向；请手工旋转')
    return best


def match_preview_orientation(preview,chart,cancel=None):
    """Match cached thumbnails only; no full-resolution decode or measurement."""
    import cv2
    from .utils import check_cancel

    def read_gray(path):
        image=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_GRAYSCALE)
        if image is None:raise ValueError('无法读取模板或图像缩略图')
        scale=min(1.,1600/max(image.shape))
        return cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA) if scale<1 else image

    target=read_gray(preview)
    if chart.preview and Path(chart.preview).is_file():reference=read_gray(chart.preview)
    elif chart.source_path and Path(chart.source_path).is_file():
        from .templates import render_source
        from PySide6.QtGui import QImage
        image,_,_=render_source(chart.source_path,max_side=1600,page=chart.source_page)
        image=image.convertToFormat(QImage.Format.Format_Grayscale8)
        reference=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()].copy()
    else:raise ValueError('模板没有可匹配的缩略图；请先完成配准或使用手工方向按钮')
    orb=cv2.ORB_create(nfeatures=7000,edgeThreshold=16,fastThreshold=10)
    target_points,target_desc=orb.detectAndCompute(target,None)
    if target_desc is None:raise ValueError('图像缩略图特征不足，请手工调整方向')
    candidates=[]
    for mirror in [False,True]:
        check_cancel(cancel)
        ref=np.ascontiguousarray(reference[:,::-1] if mirror else reference)
        points,desc=orb.detectAndCompute(ref,None)
        if desc is None:continue
        pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc,target_desc,k=2)
        matches=sorted([m for pair in pairs if len(pair)==2 for m,n in [pair] if m.distance<.70*n.distance],key=lambda m:m.distance)
        used=set();unique=[]
        for m in matches:
            if m.trainIdx not in used:unique.append(m);used.add(m.trainIdx)
        if len(unique)<12:continue
        src=np.array([points[m.queryIdx].pt for m in unique],np.float32)
        dst=np.array([target_points[m.trainIdx].pt for m in unique],np.float32)
        M,inliers=cv2.findHomography(src,dst,cv2.RANSAC,3,maxIters=5000)
        if M is None or inliers.sum()<12:continue
        keep=inliers.ravel().astype(bool)
        if np.prod(np.ptp(src[keep],axis=0)/[ref.shape[1],ref.shape[0]])<.01:continue
        expected=cv2.warpPerspective(ref,M,(target.shape[1],target.shape[0]),borderValue=255)
        coverage=cv2.warpPerspective(np.full_like(ref,255),M,(target.shape[1],target.shape[0]))>250
        a=cv2.GaussianBlur(expected,(0,0),1).astype(float);b=cv2.GaussianBlur(target,(0,0),1).astype(float)
        mask=coverage&((a<235)|(b<235))
        if mask.sum()<500:continue
        av=a[mask]-a[mask].mean();bv=b[mask]-b[mask].mean()
        correlation=float(av@bv/max(np.linalg.norm(av)*np.linalg.norm(bv),1e-9))
        reflection=np.array([[-1,0,ref.shape[1]-1],[0,1,0],[0,0,1]]) if mirror else np.eye(3)
        H=M@reflection@np.diag([ref.shape[1],ref.shape[0],1])
        try:orientation=orientation_from_homography(H)
        except ValueError:continue
        candidates.append({'orientation':orientation.to_dict(),'correlation':correlation,'inliers':int(inliers.sum()),'method':'thumbnail_feature_orientation'})
    if not candidates:raise ValueError('模板缩略图匹配失败，请先完成配准或手工调整方向')
    candidates.sort(key=lambda r:r['correlation'],reverse=True);best=candidates[0]
    if best['correlation']<.3 or any(r['orientation']!=best['orientation'] and best['correlation']-r['correlation']<.04 for r in candidates[1:]):
        raise ValueError('模板方向匹配不够明确，预览保持原方向；请先完成配准或手工调整')
    return best
