"""Binary wedge CTF using known template geometry and original image samples.

No square-wave CTF-to-MTF conversion is performed. A frequency is accepted for
the resolution threshold only while the expected bars remain separated; later
alias lobes do not become renewed resolution.
"""
from __future__ import annotations
import cv2
import numpy as np
from scipy.ndimage import map_coordinates,gaussian_filter1d
from scipy.signal import find_peaks
from .sfr import first_crossing


def wedge(image,params,config):
    a=np.asarray(image,float);h,w=a.shape
    samples=params.get('frequency_samples',[])
    if len(samples)<2:return {'values':{},'flags':['missing_frequency'],'confidence':0,'curves':{}}
    t_ref=np.array([s['t'] for s in samples],float)
    c_ref=np.array([s['cycles_across'] for s in samples],float)
    if not np.all(np.isfinite(t_ref)) or not np.all(np.isfinite(c_ref)) or np.any(c_ref<=0) or np.any(np.diff(t_ref)<=0):
        return {'values':{},'flags':['unsupported_pattern'],'confidence':0,'curves':{}}
    vertical=params.get('direction','vertical')=='vertical'
    matrix=np.asarray(params.get('_native_homography',[[w,0,0],[0,h,0],[0,0,1]]),float)
    ts=np.linspace(max(.025,t_ref[0]),min(.975,t_ref[-1]),80)
    frequencies=[];contrasts=[];separated=[];coherences=[];counts=[];expected=[]
    for t in ts:
        cycles=float(np.interp(t,t_ref,c_ref))
        endpoints=np.array([[[0,t],[1,t]]] if vertical else [[[t,0],[t,1]]],float)
        ends=cv2.perspectiveTransform(endpoints,matrix)[0]
        span=float(np.linalg.norm(ends[1]-ends[0]))
        f=cycles/max(span,1e-9)
        if not .001<f<=.48:continue
        band_start=float(np.interp(t,t_ref,[s.get('band_start',.14) for s in samples]))
        band_end=float(np.interp(t,t_ref,[s.get('band_end',.86) for s in samples]))
        band_width=band_end-band_start
        if not 0<band_width<=1:continue
        n=max(64,int(np.ceil(span*band_width)))
        u=np.linspace(band_start,band_end,n)
        # Bilinear samples follow a known section in original image space;
        # no rectified raster is passed to the measurement algorithm.
        xy=np.array([np.column_stack([u,np.full(n,t)]) if vertical else np.column_stack([np.full(n,t),u])],float)
        mapped=cv2.perspectiveTransform(xy,matrix)[0]
        p=map_coordinates(a,[mapped[:,1],mapped[:,0]],order=1,mode='nearest')
        if len(p)<24:continue
        hi,lo=np.percentile(p,[90,10]);contrast=float((hi-lo)/max(hi+lo,1e-9))
        exp=cycles*band_width
        peaks,_=find_peaks(-gaussian_filter1d(p,.35),prominence=max((hi-lo)*.18,.01),distance=max(1,int(.6*n/max(exp,1))))
        good=abs(len(peaks)-exp)<=max(1.5,exp*.2) and contrast>=config.minimum_contrast
        # Correlation with the known fundamental rejects resolved-looking
        # structures at a wrong (aliased) frequency.
        p0=p-np.polyval(np.polyfit(u,p,1),u)
        fundamental=2*abs(np.mean(p0*np.exp(-2j*np.pi*cycles*u)))
        coherence=float(fundamental/max(hi-lo,1e-9))
        good=good and coherence>.20
        frequencies.append(f);contrasts.append(contrast);separated.append(bool(good));coherences.append(coherence);counts.append(len(peaks));expected.append(exp)
    if len(frequencies)<8:return {'values':{},'flags':['insufficient_frequency_samples'],'confidence':0,'curves':{}}
    order=np.argsort(frequencies);f=np.asarray(frequencies)[order];c=np.asarray(contrasts)[order]
    separated=np.asarray(separated)[order];coherences=np.asarray(coherences)[order]
    reference=float(np.median(c[:max(3,len(c)//12)]))
    if reference<config.minimum_contrast:return {'values':{},'flags':['low_contrast'],'confidence':0,'curves':{}}
    response=c/reference
    # Three-point median suppresses individual pixel phase spikes. The
    # monotone envelope prevents later false-detail/moire lobes being counted.
    from scipy.ndimage import median_filter
    envelope=np.minimum.accumulate(median_filter(response,size=3,mode='nearest'))
    strict=separated&(envelope>=config.ctf_threshold)
    bad=np.flatnonzero(~separated)
    faithful_end=int(bad[0]) if len(bad) else len(f)
    last=None
    for i,ok in enumerate(strict):
        if not ok:break
        if ok:last=float(f[i])
    flags=['relative_response']
    if params.get('frequency_geometry_source')=='reference_raster_estimated':flags.append('reference_frequency_approximate')
    if any(~separated):flags.append('wedge_aliasing_detected')
    if faithful_end<3:flags.append('target_mismatch')
    if last is not None and strict.all():flags.append('resolution_chart_limited')
    value_at=float(np.interp(config.target_frequency,f,c,left=np.nan,right=np.nan))
    values={'ctf50':first_crossing(f[:faithful_end],envelope[:faithful_end],.5),'ctf20':first_crossing(f[:faithful_end],envelope[:faithful_end],.2),
            'ctf10':first_crossing(f[:faithful_end],envelope[:faithful_end],.1),'resolution_limit':last,
            'reference_contrast':reference,'contrast_at_frequency':value_at if np.isfinite(value_at) else None,
            'target_frequency':config.target_frequency,'wedge_valid_fraction':float(separated.mean()),
            'wedge_alias_fraction':float(1-separated.mean())}
    curves={'wedge':{'x':f.tolist(),'y':response.tolist(),'x_unit':'cy/px','y_unit':'relative CTF'},
            'wedge_contrast':{'x':f.tolist(),'y':c.tolist(),'x_unit':'cy/px','y_unit':'modulation'},
            'wedge_coherence':{'x':f.tolist(),'y':coherences.tolist(),'x_unit':'cy/px','y_unit':'fundamental/peak-to-peak'},
            'wedge_separation':{'x':f.tolist(),'y':separated.astype(float).tolist(),'x_unit':'cy/px','y_unit':'expected bars separated'},
            'wedge_bar_count':{'x':f.tolist(),'y':np.asarray(counts)[order].tolist(),'x_unit':'cy/px','y_unit':'detected bars'},
            'wedge_expected_bars':{'x':f.tolist(),'y':np.asarray(expected)[order].tolist(),'x_unit':'cy/px','y_unit':'expected bars'}}
    return {'values':values,'flags':flags,'confidence':float(min(1,reference/.2)),
            'direction_deg':0 if vertical else 90,'curves':curves}
