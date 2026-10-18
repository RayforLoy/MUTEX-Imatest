from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.fft import rfft, rfftfreq, next_fast_len
from scipy.special import erf

def first_crossing(x,y,threshold):
    x=np.asarray(x); y=np.asarray(y)
    if len(y) and y[0]==threshold:return float(x[0])
    indices=np.flatnonzero((y[:-1]>=threshold)&(y[1:]<=threshold))
    if not len(indices): return None
    i=int(indices[0])
    if y[i]==y[i+1]:return float(x[i])
    return float(x[i]+(threshold-y[i])*(x[i+1]-x[i])/(y[i+1]-y[i]))

def robust_polyfit(y,x,degree):
    mask=np.isfinite(x)
    if mask.sum()<12: raise ValueError("Too few edge rows")
    for _ in range(5):
        p=np.polyfit(y[mask],x[mask],degree)
        residual=x-np.polyval(p,y)
        scale=1.4826*np.median(np.abs(residual[mask]-np.median(residual[mask])))+.025
        new=mask & (np.abs(residual)<max(.35,3*scale))
        if new.sum()<12 or np.array_equal(new,mask): break
        mask=new
    return p,mask,residual

def slanted_edge(image,config):
    """Oversampled native-pixel ESF; derivative response corrected, no ROI warping.
    Engineering SFR implementation, not a claim of ISO 12233 certification."""
    a=np.asarray(image,dtype=np.float64)
    flags=[]
    if a.ndim!=2 or min(a.shape)<32 or not np.all(np.isfinite(a)):
        return {"flags":["invalid_edge"],"confidence":0,"values":{},"curves":{}}
    gx=np.mean(np.abs(np.diff(a,axis=1))); gy=np.mean(np.abs(np.diff(a,axis=0)))
    transposed=gy>gx
    if transposed: a=a.T
    h,w=a.shape
    smooth=gaussian_filter1d(a,.7,axis=1)
    gradient=np.diff(smooth,axis=1)
    left=np.median(a[:,:max(3,w//8)]); right=np.median(a[:,-max(3,w//8):])
    contrast=abs(right-left)
    if contrast<config.minimum_contrast: flags.append("low_contrast")
    sign=1 if right>=left else -1
    gradient=gradient*sign
    rough=np.argmax(gradient[:,3:-3],axis=1)+3
    center=float(np.median(rough))
    locations=np.full(h,np.nan)
    row_contrasts=[]
    for row,j in enumerate(rough):
        if abs(j-center)>max(8,h*.4): continue
        lo=max(1,j-5); hi=min(w-2,j+6)
        g=np.maximum(gradient[row,lo:hi],0)
        if np.sum(g)>1e-8:
            locations[row]=np.sum((np.arange(lo,hi)+.5)*g)/np.sum(g)
        row_contrasts.append(float(np.max(a[row])-np.min(a[row])))
    degree=2 if config.edge_fit=="quadratic" else 1
    try: poly,mask,residual=robust_polyfit(np.arange(h),locations,degree)
    except ValueError: return {"flags":["invalid_edge"],"confidence":0,"values":{"contrast":contrast},"curves":{}}
    ym=(h-1)/2
    slope=float(np.polyval(np.polyder(poly),ym)); edge_center=float(np.polyval(poly,ym))
    angle=float(np.degrees(np.arctan(abs(slope))))
    if angle<.4 or angle>18 or not 5<edge_center<w-5: flags.append("invalid_edge")
    if not 2<=angle<=7: flags.append("edge_angle_advisory")
    rms=float(np.sqrt(np.mean(residual[mask]**2)))
    if rms>.35: flags.append("edge_fit_residual")
    row_centers=np.polyval(poly,np.arange(h))
    extent=min(float(np.min(row_centers)),float(w-1-np.max(row_centers)))/np.sqrt(1+slope*slope)-2
    if extent<8: flags.append("invalid_edge"); extent=max(2,extent)
    extent=min(extent,256)
    dx=1/config.oversampling
    half=int(extent/dx)
    bins=2*half
    distances=(np.arange(w)[None,:]-row_centers[:,None])/np.sqrt(1+slope*slope)
    indices=np.floor(distances/dx+half).astype(np.int64)
    good=(indices>=0)&(indices<bins)&mask[:,None]
    counts=np.bincount(indices[good],minlength=bins)
    sums=np.bincount(indices[good],weights=a[good],minlength=bins)
    have=counts>0
    if have.sum()<max(16,int(.85*bins)): flags.append("insufficient_samples")
    if have.sum()<4: return {"flags":list(set(flags+["invalid_edge"])),"confidence":0,"values":{},"curves":{}}
    esf=np.interp(np.arange(bins),np.flatnonzero(have),sums[have]/counts[have])
    x=(np.arange(bins)-half+.5)*dx
    lsf=np.diff(esf)/dx
    # Center the window on the edge; wide enough to retain the optical response.
    center_lsf=(len(lsf)-1)/2
    edge_peak=float(np.argmax(np.abs(gaussian_filter1d(lsf,1))))
    window_len=len(lsf)
    winx=(np.arange(window_len)-edge_peak)/(max(edge_peak,window_len-1-edge_peak)+1)
    window=.54+.46*np.cos(np.pi*winx) if config.window=="hamming" else .5+.5*np.cos(np.pi*winx)
    lsf_win=lsf*window
    nfft=next_fast_len(max(2048,len(lsf_win)*8))
    freq=rfftfreq(nfft,dx)
    response=np.abs(rfft(lsf_win,nfft))
    response/=max(response[0],1e-12)
    correction=np.ones_like(freq)
    arg=np.pi*freq*dx
    nonzero=arg!=0
    correction[nonzero]=np.minimum(arg[nonzero]/np.maximum(np.sin(arg[nonzero]),1e-9),10)
    response*=correction
    usable=freq<=.5
    f=freq[usable]; mtf=response[usable]
    peak=float(np.max(mtf))
    values={"mtf50":first_crossing(f,mtf,.5),"mtf50p":first_crossing(f,mtf/peak,.5),
            "mtf20":first_crossing(f,mtf,.2),"mtf10":first_crossing(f,mtf,.1),
            "mtf_nyquist":float(mtf[-1]),"contrast":float(contrast),"edge_angle_deg":angle,
            "edge_fit_rms_px":rms,"mtf_peak":peak,
            "overshoot_pct":float(max(0,(np.max(esf)-max(left,right))/max(contrast,1e-9))*100),
            "undershoot_pct":float(max(0,(min(left,right)-np.min(esf))/max(contrast,1e-9))*100),
            "esf_empty_fraction":float(1-have.mean())}
    if values["mtf50"] is None: flags.append("mtf50_above_nyquist")
    if peak>1.08: flags.append("sharpening_or_ringing")
    from .sharpening import esf_halos
    values.update(esf_halos(x,esf))
    if values.get('sharpening_halo_pct',0)>=2 and 'sharpening_or_ringing' not in flags:flags.append('sharpening_or_ringing')
    if values["mtf_nyquist"]>.3: flags.append("aliasing_risk")
    # Direction is the edge normal; RGB shifts are one-dimensional projections.
    normal=np.array([1,-slope]) if not transposed else np.array([-slope,1])
    normal=normal/np.linalg.norm(normal)
    local_center=np.array([edge_center,ym]) if not transposed else np.array([ym,edge_center])
    confidence=float(np.clip(mask.mean()*np.exp(-rms)*min(1,contrast/.15)*(have.mean()),0,1))
    return {"values":values,"curves":{"sfr":{"x":f.tolist(),"y":mtf.tolist(),"x_unit":"cy/px","y_unit":"response"},
          "esf":{"x":x.tolist(),"y":esf.tolist(),"x_unit":"px","y_unit":"linear signal"},
          "lsf":{"x":((x[:-1]+x[1:])/2).tolist(),"y":lsf.tolist(),"x_unit":"px","y_unit":"signal/px"}},
          "flags":flags,"confidence":confidence,"direction_deg":float(np.degrees(np.arctan2(normal[1],normal[0]))),
          "edge_center":local_center.tolist(),"normal":normal.tolist()}
