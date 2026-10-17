"""Local RGB translations in native image coordinates; G is the reference.

The stored displacement is the location of a feature in R/B minus its location
in G. To align a channel to G we sample it at (x+dx, y+dy). Original channels
are never resampled for their own resolution measurement.
"""
from __future__ import annotations
import cv2
import numpy as np


def _normalize(a):
    a=np.asarray(a,np.float32)
    low,high=np.percentile(a,[5,95])
    if high-low<1e-5:raise ValueError("RGB registration patch has insufficient contrast")
    return np.ascontiguousarray((a-low)/(high-low),np.float32)


def estimate_translation(reference,moving,max_shift=24):
    a,b=_normalize(reference),_normalize(moving)
    if a.shape!=b.shape or min(a.shape)<24:raise ValueError("RGB registration patch is too small")
    # Phase correlation supplies the starting point; ECC refines translation
    # without applying its interpolation to the original channel measurements.
    win=cv2.createHanningWindow((a.shape[1],a.shape[0]),cv2.CV_32F)
    shift,response=cv2.phaseCorrelate(a.copy(),b.copy(),win)
    if not np.isfinite(shift).all() or max(abs(v) for v in shift)>max_shift:shift=(0.,0.)
    warp=np.array([[1,0,shift[0]],[0,1,shift[1]]],np.float32)
    try:
        score,warp=cv2.findTransformECC(a,b,warp,cv2.MOTION_TRANSLATION,
                    (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,80,1e-6),None,5)
    except cv2.error as exc:raise ValueError("RGB translation did not converge") from exc
    dx,dy=map(float,warp[:,2])
    if not np.isfinite([dx,dy,score]).all() or max(abs(dx),abs(dy))>max_shift or score<.8:
        raise ValueError("RGB translation failed its correlation/search checks")
    # Independent residual check uses the overlap only, excluding padded edges.
    yy,xx=np.mgrid[:a.shape[0],:a.shape[1]].astype(np.float32)
    aligned=cv2.remap(b,xx+dx,yy+dy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=np.nan)
    margin=int(np.ceil(max(abs(dx),abs(dy))))+5
    valid=np.isfinite(aligned)
    valid[:margin]=False;valid[-margin:]=False;valid[:,:margin]=False;valid[:,-margin:]=False
    if valid.sum()<100:raise ValueError("RGB translation has insufficient overlap")
    error=float(np.sqrt(np.mean((a[valid]-aligned[valid])**2)))
    return {"dx_px":dx,"dy_px":dy,"magnitude_px":float(np.hypot(dx,dy)),
            "correlation":float(score),"phase_response":float(response),"normalized_rms":error,
            "method":"phase-correlation/ECC-translation","valid":True}


def align_gray(rgb,shifts,weights=(.2126,.7152,.0722)):
    """Return a derived bilinearly resampled gray plane, plus overlap mask."""
    a=np.asarray(rgb);h,w=a.shape[:2]
    yy,xx=np.mgrid[:h,:w].astype(np.float32)
    gray=np.zeros((h,w),np.float64);valid=np.ones((h,w),bool)
    for index,key in enumerate(["R","G","B"]):
        shift=shifts.get(key,{"dx_px":0.,"dy_px":0.,"valid":key=="G"})
        if not shift.get("valid"):raise ValueError("RGB channel alignment is unavailable")
        dx,dy=shift["dx_px"],shift["dy_px"]
        if dx==0 and dy==0:plane=a[...,index]
        else:plane=cv2.remap(a[...,index].astype(np.float64),xx+dx,yy+dy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=np.nan)
        valid&=np.isfinite(plane);gray+=weights[index]*plane
    gray[~valid]=np.nan
    return gray,valid
