"""Measured edge halos: evidence of sharpening/ringing, not processing history."""
from __future__ import annotations
import numpy as np


def _paired_peak(values,noise):
    """Two adjacent profile samples must exceed a noise-aware detection floor."""
    a=np.asarray(values,float)
    if len(a)<2:return 0.
    v=float(max(0,np.max(np.minimum(a[:-1],a[1:]))))
    return v if v>4*noise else 0.


def _edge(profile,center,distance,noise):
    x=np.arange(len(profile));left=(x>=center-distance*1.05)&(x<=center-distance*.75)
    right=(x>=center+distance*.75)&(x<=center+distance*1.05)
    if min(left.sum(),right.sum())<3:return None
    lo,hi=float(np.median(profile[left])),float(np.median(profile[right]))
    step=abs(hi-lo)
    if step<.05:return None
    near_left=profile[(x>=center-distance*.65)&(x<center-.4)]
    near_right=profile[(x>center+.4)&(x<=center+distance*.65)]
    bright=near_right if hi>lo else near_left;dark=near_left if hi>lo else near_right
    return {'overshoot':100*_paired_peak(bright-max(lo,hi),noise)/step,
            'undershoot':100*_paired_peak(min(lo,hi)-dark,noise)/step,'floor':400*noise/step}


def _result(edges):
    if not edges:return {}
    over=float(np.median([e['overshoot'] for e in edges]));under=float(np.median([e['undershoot'] for e in edges]))
    floor=float(np.median([e['floor'] for e in edges]))
    if floor>5:return {}
    return {'sharpening_halo_pct':max(over,under),'halo_overshoot_pct':over,'halo_undershoot_pct':under,
            'halo_noise_floor_pct':floor,'halo_edge_count':len(edges)}


def bar_halos(profile,period,noise=0):
    """Use the four internal coarse-bar edges, excluding the outer white field."""
    p=np.asarray(profile,float)
    if period<40 or len(p)<3*period:return {}
    origin=(len(p)-1)/2
    expected=origin+np.array([-.75,-.25,.25,.75])*period
    derivative=np.abs(np.diff(p));observed=[]
    for pos in expected:
        lo=max(0,int(pos-period*.15));hi=min(len(derivative),int(np.ceil(pos+period*.15)))
        if hi<=lo:return {}
        observed.append(lo+np.argmax(derivative[lo:hi])+.5)
    shifts=np.asarray(observed)-expected
    if np.ptp(shifts)>.16*period:return {}
    edges=[_edge(p,float(center),period*.25,noise) for center in observed]
    if any(e is None for e in edges):return {}
    return _result(edges)


def esf_halos(x,esf):
    p=np.asarray(esf,float);x=np.asarray(x,float)
    if len(p)<40 or x[-1]-x[0]<16:return {}
    tail=np.r_[p[:max(6,len(p)//10)],p[-max(6,len(p)//10):]]
    noise=float(np.median(np.abs(np.diff(tail)))/(.67448975*np.sqrt(2)))
    # The ESF is already an average over aligned native edge rows. Its peak is
    # used only for a halo diagnostic, never to extend a resolution estimate.
    center=int(np.argmax(np.abs(np.diff(p))))+.5
    distance=min(center,len(p)-1-center,.25*len(p))
    edge=_edge(p,center,distance,noise)
    return _result([edge] if edge else [])


def aggregate_bar_halos(rows,reject_clipping=True):
    fatal={'registration_failed','roi_outside','insufficient_samples','template_occluded','bar_geometry_mismatch','ctf_noise_limited'}
    if reject_clipping:fatal.add('clipped')
    valid=[m for m in rows if m.metric('sharpening_halo_pct') is not None and not fatal.intersection(m.flags) and m.values.get('detected_bar_count')==3]
    if len(valid)<2:return {'values':{},'flags':['halo_insufficient_evidence'],'confidence':0,'curve':{}}
    keys=['sharpening_halo_pct','halo_overshoot_pct','halo_undershoot_pct','halo_noise_floor_pct']
    values={k:float(np.median([m.values[k] for m in valid])) for k in keys}
    values['sharpening_halo_pct']=max(values['halo_overshoot_pct'],values['halo_undershoot_pct'])
    values['halo_element_count']=len(valid)
    chosen=min(valid,key=lambda m:abs(m.values['sharpening_halo_pct']-values['sharpening_halo_pct']))
    flags=['sharpening_or_ringing'] if values['sharpening_halo_pct']>=2 else []
    if any('transfer_unknown' in m.flags for m in valid):flags.append('transfer_unknown')
    if any('clipping_advisory' in m.flags for m in valid):flags.append('clipping_advisory')
    curve=dict(chosen.curves['profile']);f=chosen.values['target_frequency']
    full_length=chosen.box_pixels[2 if chosen.direction_deg==0 else 3]
    # Native axis may be quarter-turned; profile coordinates retain its length.
    full_length=curve.get('native_length',full_length)
    curve['x']=[(v-(full_length-1)/2)*f for v in curve['x']];curve['x_unit']='bar periods'
    return {'values':values,'flags':flags,'confidence':min(m.confidence for m in valid),'curve':curve,'source_element':chosen.region_id}
