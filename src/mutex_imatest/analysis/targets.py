from __future__ import annotations
import numpy as np
from scipy.ndimage import map_coordinates, gaussian_filter1d
from .sfr import first_crossing

def usaf_frequency(group,element):
    if not 1<=int(element)<=6: raise ValueError("USAF element must be 1..6")
    return 2.0**(int(group)+(int(element)-1)/6)

def usaf(image,params,config,px_per_mm=None):
    a=np.asarray(image,float)
    direction=params.get("direction","vertical")
    # Average the central portion of the bar length to avoid its end margins.
    profile=np.mean(a[a.shape[0]//4:3*a.shape[0]//4],axis=0) if direction=="vertical" else np.mean(a[:,a.shape[1]//4:3*a.shape[1]//4],axis=1)
    if len(profile)<16: return {"values":{},"flags":["insufficient_samples"],"confidence":0,"curves":{}}
    # User ROI must tightly contain the three-bar element, no lettering.
    trim=max(1,int(len(profile)*.08))
    p=profile[trim:-trim]
    frequency=params.get("frequency_cy_px")
    lpmm=None
    if "group" in params and "element" in params:
        lpmm=usaf_frequency(params["group"],params["element"])
        if px_per_mm: frequency=lpmm/px_per_mm
    if frequency is not None and 0<float(frequency)<.5:
        # Restrict the estimator to the three-bar span rather than blank ROI margins.
        deficit=np.maximum(np.percentile(p,95)-p,0)
        center=float(np.sum(np.arange(len(p))*deficit)/max(deficit.sum(),1e-12))
        half=1.55/float(frequency)
        p=p[max(0,int(np.floor(center-half))):min(len(p),int(np.ceil(center+half))+1)]
    bright=float(np.percentile(p,90));dark=float(np.percentile(p,10))
    contrast=(bright-dark)/max(bright+dark,1e-12)
    from scipy.signal import find_peaks
    minima,_=find_peaks(-p,prominence=max((bright-dark)*.12,config.minimum_contrast*.1))
    flags=[]
    if bright-dark<config.minimum_contrast:flags.append("low_contrast")
    if len(minima)<3:flags.append("bars_not_separated")
    if frequency is None:
        flags.append("missing_frequency")
    elif not 0<float(frequency)<.5: flags.append("aliasing")
    values={"ctf":float(contrast),"resolved":float(contrast>=config.ctf_threshold and len(minima)>=3),"contrast_at_frequency":float(contrast),"detected_bar_count":len(minima)}
    if lpmm is not None: values["target_lp_mm"]=lpmm
    if frequency is not None: values["target_frequency"]=float(frequency)
    return {"values":values,"flags":flags,"confidence":min(1,(bright-dark)/.2),
            "direction_deg":0 if direction=="vertical" else 90,
            "curves":{"profile":{"x":list(range(len(profile))),"y":profile.tolist(),"x_unit":"px","y_unit":"linear signal"}}}


def star(image,params,config):
    """Binary CTF or referenced sine response on original-pixel polar samples.

    Template homography determines the sampling loci, including perspective,
    without rectifying a measurement raster. Each angular sector has its own
    native tangential frequency. Binary CTF is never renamed optical MTF.
    """
    import cv2
    from scipy.ndimage import median_filter
    a=np.asarray(image,float);h,w=a.shape
    cycles=int(params.get('cycles',72));pattern=params.get('pattern','binary')
    if cycles<4 or cycles>1000 or pattern not in {'binary','sinusoidal'}:
        return {'values':{},'flags':['unsupported_pattern'],'confidence':0,'curves':{}}
    center=np.array(params.get('center',[.5,.5]),float)
    M=np.asarray(params.get('_native_homography',[[w-1,0,0],[0,h-1,0],[0,0,1]]),float)
    max_r=min(center[0],center[1],1-center[0],1-center[1])*.94
    points=cv2.perspectiveTransform(np.array([[center,center+[1e-4,0],center+[0,1e-4]]],float),M)[0]
    J=np.column_stack([(points[1]-points[0])/1e-4,(points[2]-points[0])/1e-4])
    singular=np.linalg.svd(J,compute_uv=False)
    if singular[-1]<=0 or singular[0]/singular[-1]>4:
        return {'values':{},'flags':['star_geometry_invalid'],'confidence':0,'curves':{}}
    min_r=max(cycles/(2*np.pi*.46*singular[-1]),max_r*.06)
    if max_r<=min_r*1.12:return {'values':{},'flags':['insufficient_samples'],'confidence':0,'curves':{}}
    radii=np.geomspace(max_r,min_r,80)
    ntheta=max(2048,cycles*32);theta=np.arange(ntheta)*2*np.pi/ntheta
    loci=np.stack([center[0]+radii[:,None]*np.cos(theta),center[1]+radii[:,None]*np.sin(theta)],axis=2)
    xy=cv2.perspectiveTransform(loci.reshape(1,-1,2),M)[0].reshape(len(radii),ntheta,2)
    if np.min(xy[...,0])<0 or np.min(xy[...,1])<0 or np.max(xy[...,0])>w-1 or np.max(xy[...,1])>h-1:
        return {'values':{},'flags':['roi_outside'],'confidence':0,'curves':{}}
    rings=map_coordinates(a,[xy[...,1],xy[...,0]],order=1,mode='nearest')
    # Period / local arc length. Native non-square scale and perspective are
    # accounted for per sector rather than mistaken for optical anisotropy.
    tangent=(np.roll(xy,-1,axis=1)-np.roll(xy,1,axis=1))/(4*np.pi/ntheta)
    local_f=cycles/(2*np.pi*np.maximum(np.linalg.norm(tangent,axis=2),1e-9))
    frequencies=np.median(local_f,axis=1)
    fundamental=2*np.abs(np.mean((rings-rings.mean(axis=1,keepdims=True))*np.exp(-1j*cycles*theta),axis=1))
    hi=np.percentile(rings,90,axis=1);lo=np.percentile(rings,10,axis=1)
    contrast=(hi-lo)/np.maximum(hi+lo,1e-9) if pattern=='binary' else fundamental/np.maximum(rings.mean(axis=1),1e-9)
    coherence=fundamental/np.maximum(hi-lo,1e-9)
    reference=params.get('reference_modulation');flags=[]
    optical=pattern=='sinusoidal' and reference is not None
    if not optical:flags.append('relative_response')
    norm=float(reference) if reference else float(np.median(contrast[:5]))
    if norm<config.minimum_contrast:return {'values':{},'flags':['low_contrast'],'confidence':0,'curves':{}}
    response=contrast/norm
    envelope=np.minimum.accumulate(median_filter(response,size=3,mode='nearest'))
    faithful=coherence>.2
    if np.median(coherence[:5])<.25:
        return {'values':{},'flags':['target_mismatch'],'confidence':0,'curves':{}}
    # A different angular harmonic or false-detail lobe can retain high
    # peak-to-peak contrast after the expected fundamental has disappeared.
    # Such rings remain in diagnostic curves, but cannot establish CTF/MTF
    # threshold crossings, even if their contrast later falls or recovers.
    mismatched=np.flatnonzero(~faithful)
    faithful_end=int(mismatched[0]) if len(mismatched) else len(frequencies)
    if faithful_end<len(frequencies):flags.append('star_frequency_mismatch')
    valid_f=frequencies[:faithful_end];valid_envelope=envelope[:faithful_end]
    def resolution(f,c,faithful):
        last=None
        for i in range(len(f)):
            if c[i]<config.ctf_threshold or not faithful[i]:break
            last=float(f[i])
        return last
    c_at=float(np.interp(config.target_frequency,frequencies,contrast,left=np.nan,right=np.nan))
    values={'contrast_at_frequency':c_at if np.isfinite(c_at) else None,'reference_contrast':float(np.median(contrast[:5])),
            'response50':first_crossing(valid_f,valid_envelope,.5),'target_frequency':config.target_frequency,
            'resolution_limit':resolution(frequencies,envelope,faithful),'star_cycles':cycles,
            'star_coherence':float(np.median(coherence)),'star_faithful_fraction':float(faithful_end/len(frequencies))}
    prefix='mtf' if optical else 'ctf'
    for threshold in [.5,.2,.1]:values[prefix+str(int(threshold*100))]=first_crossing(valid_f,valid_envelope,threshold)
    if values['resolution_limit'] is not None and values['resolution_limit']==frequencies[-1]:flags.append('resolution_chart_limited')
    curves={'star':{'x':frequencies.tolist(),'y':response.tolist(),'x_unit':'cy/px','y_unit':'MTF' if optical else 'relative CTF'},
            'star_contrast':{'x':frequencies.tolist(),'y':contrast.tolist(),'x_unit':'cy/px','y_unit':'modulation'},
            'star_coherence':{'x':frequencies.tolist(),'y':coherence.tolist(),'x_unit':'cy/px','y_unit':'fundamental/peak-to-peak'}}
    limits=[]
    for i in range(8):
        sl=slice(i*ntheta//8,(i+1)*ntheta//8);segment=rings[:,sl]
        high=np.percentile(segment,90,axis=1);low=np.percentile(segment,10,axis=1)
        sc=(high-low)/np.maximum(high+low,1e-9)
        sf=np.median(local_f[:,sl],axis=1)
        snorm=float(np.median(sc[:5]));se=np.minimum.accumulate(median_filter(sc/max(snorm,1e-9),size=3,mode='nearest'))
        limit=resolution(sf,se,faithful)
        if limit is not None:limits.append(limit)
        values[f'sector_{i}_contrast']=float(np.interp(config.target_frequency,sf,sc,left=np.nan,right=np.nan))
        values[f'sector_{i}_resolution_limit']=limit
        curves[f'star_sector_{i}']={'x':sf.tolist(),'y':(sc/max(snorm,1e-9)).tolist(),'x_unit':'cy/px','y_unit':f'relative CTF · {i*45+22.5:g} deg'}
    values['star_anisotropy']=max(limits)/min(limits) if len(limits)==8 and min(limits)>0 else None
    return {'values':values,'flags':flags,'confidence':float(min(1,norm/.2)), 'curves':curves}

