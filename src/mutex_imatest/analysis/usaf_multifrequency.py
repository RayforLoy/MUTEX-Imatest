"""Native-pixel whole-chart USAF, RGB registration and derived gray analysis.

Resolution is a threshold-qualified, contiguous sequence of three-bar tests.
The highest tested pass and an interpolated CTF crossing are separate values.
An apparent high-frequency revival after an earlier failure is not resolution.
"""
from __future__ import annotations
from collections import defaultdict,Counter
import cv2
import numpy as np
from scipy.signal import find_peaks
from ..models import Measurement
from ..detection import transform_box,local_scale
from ..resolution import frequency_values
from ..utils import check_cancel
from .preprocess import linearize,clipping_fraction
from .rgb_registration import estimate_translation,align_gray
from .targets import usaf_frequency

VERSION="mutex-usaf-multifrequency-2026.10.16-v1"


def is_multifrequency(chart):
    return any(r.kind=="usaf" and r.params.get("multi_frequency") for r in chart.regions if r.enabled)


def measure_bars(image,frequency,minimum_contrast=.03,profile_band=None):
    a=np.asarray(image,float)
    if a.size==0 or not np.isfinite(a).all():raise ValueError("Insufficient aligned pixel overlap")
    band=profile_band or (.25,.75)
    start=max(0,int(np.ceil(a.shape[0]*band[0])));end=min(a.shape[0],int(np.floor(a.shape[0]*band[1])))
    if end-start<2:raise ValueError('Clean template band has insufficient native samples')
    profile=np.mean(a[start:end],axis=0)
    curve={"x":list(range(len(profile))),"y":profile.tolist(),"x_unit":"px","y_unit":"signal"}
    if frequency is None or not 0<frequency<.5:
        return {},["aliasing" if frequency else "missing_frequency"],0,curve
    if len(profile)<9:return {},["insufficient_samples"],0,curve
    trim=max(1,int(len(profile)*.06));p=profile[trim:-trim]
    bright,dark=map(float,np.percentile(p,[90,10]))
    contrast=float((bright-dark)/max(bright+dark,1e-12))
    minima,_=find_peaks(-p,prominence=max((bright-dark)*.12,minimum_contrast*.1),distance=max(1,int(.5/frequency)))
    flags=[]
    if bright-dark<minimum_contrast:flags.append("low_contrast")
    if len(minima)!=3:flags.append("bars_not_separated")
    if frequency>.4:flags.append("aliasing_risk")
    # Keep native measurements; only decimate the stored display profile.
    if len(profile)>128:
        ids=np.unique(np.linspace(0,len(profile)-1,128).astype(int))
        curve["x"]=ids.tolist();curve["y"]=profile[ids].tolist();curve["display_decimated"]=True
    values={"ctf":contrast,"contrast_at_frequency":contrast,"detected_bar_count":int(len(minima)),
            "bright_signal":bright,"dark_signal":dark,"target_frequency":float(frequency)}
    return values,flags,float(min(1,(bright-dark)/.2)),curve


def summarize_curve(rows,threshold=.2,mode="relative",scale=None,height=1):
    ordered=sorted(rows,key=lambda m:m.values.get("target_frequency",float("inf")))
    known=[m for m in ordered if m.metric("target_frequency") is not None and m.metric("ctf") is not None]
    flags=[]
    good=lambda m: not {"clipped","registration_failed","roi_outside","fit_failed","aliasing","rgb_alignment_failed","insufficient_samples"}.intersection(m.flags)
    reference=[m.values["ctf"] for m in known[:3] if good(m) and m.values.get("detected_bar_count")==3 and "low_contrast" not in m.flags]
    if len(reference)<2 or np.median(reference)<.03:
        return {},{"frequency":[],"ctf":[],"response":[],"envelope":[],"pass":[]},["invalid_ctf_reference"],0
    baseline=float(np.median(reference))
    frequencies=[];ctf=[];response=[];envelope=[];passing=[];element_ids=[];running=float("inf")
    first_failure=None;last_pass=None;last_index=None;gap=False
    for m in ordered:
        if 'template_occluded' in m.flags:continue
        f=m.metric("target_frequency");c=m.metric("ctf")
        # Above-Nyquist and undersampled targets define no additional evidence.
        if f is None or f>=.5:continue
        if c is None:
            if last_pass is not None:first_failure=f if first_failure is None else first_failure
            running=0.;continue
        raw=c/baseline if mode=="relative" else c
        usable=good(m)
        separated=m.values.get("detected_bar_count")==3 and "low_contrast" not in m.flags
        if last_index is not None and f/last_index>2**(.5)+1e-5:
            gap=True;running=0.
        if not usable or not separated:running=0.
        else:running=min(running,raw)
        frequencies.append(f);ctf.append(c);response.append(raw if usable and separated else None)
        envelope.append(float(running));passing.append(bool(usable and separated and running>=threshold));element_ids.append(m.region_id)
        if usable and separated and running>=threshold:last_pass=f
        elif last_pass is not None and first_failure is None:first_failure=f
        last_index=f
    if len(frequencies)<3:return {},{},["insufficient_frequency_samples"],0
    if gap:flags.append("frequency_gap")
    if last_pass is None:flags.append("below_lowest_test_frequency")
    elif first_failure is None:flags.append("target_limited")
    if any("clipping_advisory" in m.flags for m in rows):flags.append("clipping_advisory")
    if any("clipped" in m.flags for m in rows):flags.append("strict_clipping_limits_curve")
    if any("transfer_unknown" in m.flags for m in rows):flags.append("transfer_unknown")
    def crossing(t):
        for i,value in enumerate(envelope):
            if value<t:
                if i==0 or envelope[i-1]<t:return None
                # A failed/nonseparated target supplies an upper bound, not a
                # fabricated CTF sample suitable for interpolating a crossing.
                if response[i] is None:return None
                lo,hi=envelope[i-1],value
                if lo==hi:return frequencies[i-1]
                fraction=(lo-t)/(lo-hi)
                return float(np.exp(np.log(frequencies[i-1])*(1-fraction)+np.log(frequencies[i])*fraction))
        return None
    values={"reference_ctf":baseline,"sampled_frequency_count":len(frequencies),"resolution_upper_bound":first_failure,
            "ctf_threshold":threshold,"test_pass_fraction":float(np.mean(passing))}
    values.update(frequency_values("resolution_limit",last_pass,scale,height))
    for key,t in [("ctf50",.5),("ctf20",.2),("ctf10",.1)]:values.update(frequency_values(key,crossing(t),scale,height))
    # Fixed chart frequencies and a stated threshold mode make this score usable
    # across a focus sequence. High frequencies receive greater weight.
    x=np.asarray(frequencies);y=np.asarray(envelope)
    values["usaf_focus_score"]=float(np.trapezoid(np.minimum(y,1.5)*x,x)/max(.5*x[-1]**2,1e-12))
    curve={"frequency":frequencies,"ctf":ctf,"response":response,"envelope":envelope,
           "pass":passing,"element_ids":element_ids,"threshold":threshold,"threshold_mode":mode,
           "reference_ctf":baseline,"resolution_lower_bound":last_pass,"resolution_upper_bound":first_failure,
           "frequency_lp_mm":[f*scale if scale else None for f in frequencies]}
    confidence=float(np.mean([m.confidence for m in known[:3]])*min(1,len(frequencies)/12))
    return values,curve,flags,confidence


def _units(values):
    out={}
    for key in values:
        out[key]="DPI" if key.endswith("_dpi") or key.startswith("sampling_dpi") else "lp/mm" if key.endswith("_lp_mm") or key=="target_lp_mm" else "LW/PH" if key.endswith("_lw_ph") else "LP/PH" if key.endswith("_lp_ph") else "px" if key.endswith("_px") else "µm" if key.endswith("_um") else "%" if key.endswith("_pct") else "cy/px" if key in {"resolution_limit","resolution_upper_bound","ctf50","ctf20","ctf10","target_frequency"} else "count" if key.endswith("count") else "ratio"
    return out


def analyze_whole_chart(source,chart,config,H,registration,cancel=None,progress=None):
    progress=progress or (lambda *a:None)
    groups=defaultdict(list)
    for r in chart.regions:
        if r.enabled and r.kind=="usaf":groups[r.params.get("unit_id",r.id)].append(r)
    channels=["R","G","B","Y","Y_align"] if config.channels=="RGBY" else ["R","G","B"] if config.channels=="RGB" else [config.channels]
    output=[];unit_records=[];height=config.picture_height_px or source.metadata.height
    for index,(unit,regions) in enumerate(groups.items()):
        check_cancel(cancel);progress(18+int(75*index/max(1,len(groups))),f"整卡多频率 {index+1}/{len(groups)}")
        local=registration.get("unit_transforms",{}).get(unit)
        local_H=np.asarray(local["homography"]) if local else np.asarray(H)
        located=local is not None or config.registration!="usaf"
        boxes={r.id:transform_box(r.box,local_H,source.metadata.width,source.metadata.height) for r in regions}
        positions=np.array([[b[0]+b[2]/2,b[1]+b[3]/2] for b,o in boxes.values()])
        center=positions.mean(axis=0).tolist()
        directions=sorted({r.params.get("direction","vertical") for r in regions})
        shifts={"G":{"dx_px":0.,"dy_px":0.,"magnitude_px":0.,"valid":True,"correlation":1.}}
        unit_record={"unit_id":unit,"position":center,"located":located,"directions":{},"rgb_shifts":shifts}
        if located:
            lows=np.array([[b[0],b[1]] for b,o in boxes.values()]);highs=np.array([[b[0]+b[2],b[1]+b[3]] for b,o in boxes.values()])
            pad=int(np.ceil(config.rgb_max_shift_px))+4
            lo=np.maximum(lows.min(axis=0)-pad,0).astype(int);hi=np.minimum(highs.max(axis=0)+pad,[source.metadata.width,source.metadata.height]).astype(int)
            if np.prod(hi-lo)*110>config.budget_bytes()*.7:raise MemoryError("USAF 单元缓冲超过预算，请提高内存预算或缩小单元")
            raw=source.read_roi((*lo,*(hi-lo)));data=linearize(raw,config,source.metadata.is_linear)
            if data.ndim==2:data=np.repeat(data[...,None],3,axis=2)
            coarse=sorted(regions,key=lambda r:r.params.get("frequency_index",0))[:12]
            cb=[boxes[r.id][0] for r in coarse]
            a=np.maximum(np.min([[b[0],b[1]] for b in cb],axis=0)-lo,0).astype(int)
            z=np.minimum(np.max([[b[0]+b[2],b[1]+b[3]] for b in cb],axis=0)-lo,[data.shape[1],data.shape[0]]).astype(int)
            patch=data[a[1]:z[1],a[0]:z[0]]
            for ch,ci in [("R",0),("B",2)]:
                try:shifts[ch]=estimate_translation(patch[...,1],patch[...,ci],config.rgb_max_shift_px)
                except ValueError as exc:shifts[ch]={"valid":False,"reason":str(exc)}
            before=np.einsum("ijk,k->ij",data[...,:3],config.gray_weights) if "Y" in channels else None
            after=None
            if "Y_align" in channels and all(shifts.get(ch,{}).get("valid") for ch in ["R","B"]):
                after,_=align_gray(data,shifts,config.gray_weights)
        unit_rows=[]
        for region in regions:
            check_cancel(cancel)
            direction=region.params.get("direction","vertical");angle=0 if direction=="vertical" else 90
            box,outside=boxes[region.id];x,y,w,h=box;position=(x+w/2,y+h/2)
            normal=np.array([1.,0.]) if angle==0 else np.array([0.,1.])
            scale=local_scale(chart,local_H,position,normal)
            lpmm=usaf_frequency(region.params["group"],region.params["element"])
            # Nominal target geometry supplies cy/px even before physical size
            # confirmation; lp/mm and DPI outputs remain gated by calibration.
            if scale:frequency=lpmm/scale
            else:
                nominal=np.linalg.norm(local_H[:2,0 if angle==0 else 1])/chart.physical_size_mm[0 if angle==0 else 1] if chart.physical_size_mm else None
                frequency=lpmm/nominal if nominal else region.params.get("frequency_cy_px")
            for ch in channels:
                flags=[];values={"target_frequency":frequency,"target_lp_mm":lpmm}
                actual_box=box;curves={};confidence=0
                if not located:flags=["registration_failed"]
                elif region.params.get('template_occluded'):flags=['template_occluded']
                elif outside or min(w,h)<2:flags=["roi_outside"]
                elif ch=="Y_align" and after is None:flags=["rgb_alignment_failed"]
                else:
                    if ch in {"R","B"} and shifts.get(ch,{}).get("valid"):
                        dx,dy=int(round(shifts[ch]["dx_px"])),int(round(shifts[ch]["dy_px"]))
                    else:dx=dy=0
                    xx,yy=x-lo[0]+dx,y-lo[1]+dy
                    actual_box=(x+dx,y+dy,w,h)
                    if xx<0 or yy<0 or xx+w>data.shape[1] or yy+h>data.shape[0]:flags=["roi_outside"]
                    else:
                        plane=before if ch=="Y" else after if ch=="Y_align" else data[...,{"R":0,"G":1,"B":2}[ch]]
                        roi=plane[yy:yy+h,xx:xx+w]
                        if angle==90:roi=roi.T
                        try:
                            band=region.params.get('profile_band')
                            along_axis=1 if angle==0 else 0
                            if band and local_H[along_axis,along_axis]<0:band=[1-band[1],1-band[0]]
                            measured,quality,confidence,curve=measure_bars(roi,frequency,config.minimum_contrast,band)
                            values.update(measured);flags.extend(quality)
                            values["resolved"]=float(values.get("ctf",0)>=config.ctf_threshold and values.get("detected_bar_count")==3)
                            curve["y_unit"]="linear signal" if source.metadata.is_linear or config.transfer!="unknown" else "input signal"
                            curves={"profile":curve}
                        except ValueError:flags.append("insufficient_samples")
                        raw_roi=raw[yy:yy+h,xx:xx+w]
                        clip=clipping_fraction(raw_roi[...,{"R":0,"G":1,"B":2}[ch]]) if ch in {"R","G","B"} and raw_roi.ndim==3 else clipping_fraction(raw_roi)
                        values["clipping_fraction"]=clip
                        if clip>config.maximum_clip_fraction:flags.append("clipped" if config.reject_clipping else "clipping_advisory")
                        if not source.metadata.is_linear and config.transfer=="unknown":flags.append("transfer_unknown")
                        if ch=="Y_align":flags.append("derived_bilinear_resampling")
                if local:values.update(registration_rms_px=local["rms_px"],registration_matches=local["matches"])
                m=Measurement(region.id,region.label,"usaf",ch,position,actual_box,values,_units(values),curves,flags,confidence,VERSION+"/element",angle,scale)
                output.append(m);unit_rows.append(m)
        summaries={}
        for direction in directions:
            angle=0 if direction=="vertical" else 90
            for ch in channels:
                rows=[m for m in unit_rows if m.channel==ch and m.direction_deg==angle]
                scale=next((m.object_scale_px_per_mm for m in rows if m.object_scale_px_per_mm),None)
                if not located:values,curve,flags,confidence={}, {},["registration_failed"],0
                elif ch=="Y_align" and after is None:values,curve,flags,confidence={}, {},["rgb_alignment_failed"],0
                else:values,curve,flags,confidence=summarize_curve(rows,config.ctf_threshold,config.usaf_threshold_mode,scale,height)
                if ch=="Y_align" and located and after is not None:flags.append("derived_bilinear_resampling")
                shift=shifts.get(ch,{})
                if shift.get("valid"):values.update(rgb_shift_px=shift["magnitude_px"],rgb_shift_x_px=shift["dx_px"],rgb_shift_y_px=shift["dy_px"])
                if local:values["registration_rms_px"]=local["rms_px"]
                if chart.calibrated and chart.physical_size_mm:
                    J=local_H[:2,:2]/np.asarray(chart.physical_size_mm)[None,:]
                    values["sampling_dpi_x"]=float(np.linalg.norm(J[:,0])*25.4);values["sampling_dpi_y"]=float(np.linalg.norm(J[:,1])*25.4)
                    if shift.get("valid"):
                        physical=np.linalg.solve(J,[shift["dx_px"],shift["dy_px"]])*1000
                        values["rgb_shift_x_um"],values["rgb_shift_y_um"]=map(float,physical)
                values["clipping_fraction"]=max((m.values.get("clipping_fraction",0) for m in rows),default=0)
                record={"values":values,"curve":curve,"flags":flags,"confidence":confidence,"scale_px_per_mm":scale}
                unit_record["directions"].setdefault(direction,{})[ch]=record
                summaries[(direction,ch)]=record
                summary=Measurement(unit+"-"+direction+"-summary",f"{unit} · {'竖线/横向细节' if angle==0 else '横线/纵向细节'}","usaf_summary",ch,center,(int(center[0])-2,int(center[1])-2,4,4),values,_units(values),
                         {"ctf":{"x":curve.get("frequency",[]),"y":curve.get("ctf",[]),"x_unit":"cy/px","y_unit":"CTF"},
                          "ctf_response":{"x":curve.get("frequency",[]),"y":curve.get("envelope",[]),"x_unit":"cy/px","y_unit":"normalized CTF"}},flags,confidence,VERSION+"/summary",angle,scale)
                output.append(summary)
        # Combined field is the weaker direction, not an average that conceals
        # anisotropy. It also avoids duplicate Delaunay points in the heatmap.
        for ch in channels:
            candidates=[summaries[(d,ch)] for d in directions]
            valid=[r for r in candidates if r["values"].get("resolution_limit") is not None and not {"registration_failed","invalid_ctf_reference","rgb_alignment_failed","insufficient_frequency_samples"}.intersection(r["flags"])]
            if len(valid)==len(directions):
                selected=min(valid,key=lambda r:r["values"].get("resolution_limit_lp_mm") or r["values"]["resolution_limit"])
                values=dict(selected["values"]);flags=list(selected["flags"]);confidence=min(r["confidence"] for r in valid)
                limits=[r["values"].get("resolution_limit_lp_mm") or r["values"]["resolution_limit"] for r in valid]
                values["resolution_anisotropy"]=max(limits)/max(min(limits),1e-12)
                values["usaf_focus_score"]=min(r["values"]["usaf_focus_score"] for r in valid)
            else:values={};flags=["registration_failed" if not located else "invalid_ctf_reference"];confidence=0
            unit_record.setdefault("combined",{})[ch]={"values":values,"flags":flags,"confidence":confidence}
            output.append(Measurement(unit+"-combined-summary",unit+" · 较弱方向","usaf_summary",ch,center,(int(center[0])-2,int(center[1])-2,4,4),values,_units(values),{},flags,confidence,VERSION+"/combined",None))
        for direction in directions+["combined"]:
            records=unit_record["combined"] if direction=="combined" else unit_record["directions"][direction]
            pre,post=records.get("Y",{}).get("values",{}),records.get("Y_align",{}).get("values",{})
            a,b=pre.get("resolution_limit"),post.get("resolution_limit")
            if a and b:post["alignment_gain_pct"]=(b/a-1)*100
        unit_records.append(unit_record)
        if located:del raw,data,patch,before,after
    for m in output:
        if m.kind=="usaf_summary":m.units=_units(m.values)
    summary={"version":VERSION,"units":unit_records,"channels":channels,"threshold":config.ctf_threshold,"threshold_mode":config.usaf_threshold_mode,
             "frequency_indices":sorted({r.params["frequency_index"] for r in chart.regions if "frequency_index" in r.params}),
             "gray_weights":list(config.gray_weights),"picture_height_px":height,"alignment_interpolation":"bilinear",
             "definitions":{"resolution_limit":"Highest contiguous tested three-bar pass at the stated threshold; target-limited values are lower bounds.",
                            "dpi":"Equivalent resolving DPI = 2 × lp/mm × 25.4; different from geometric sampling PPI.",
                            "lw_ph":"2 × cycles/pixel × reference picture height; cropped-image height unless explicitly supplied.",
                            "shift_sign":"R/B feature position minus G; alignment samples R/B at x+dx, y+dy.",
                            "gray":"Weighted RGB in the selected transfer domain; not a calibrated colorimetric luminance.",
                            "focus":"A single image supplies current response only. Best focus requires a bracketed focus sequence."}}
    summary["quality_counts"]=dict(Counter(f for m in output if m.kind=="usaf_summary" and m.direction_deg is None for f in m.flags))
    summary["statistics"]={}
    summary['best_current_location']={}
    summary['focus_availability']={'available':False,'reason':'Single image; use at least five bracketed focus positions for RGB and gray focus peaks and axial offsets.'}
    for ch in channels:
        rows=[u["combined"].get(ch,{}) for u in unit_records]
        summary["statistics"][ch]={}
        for key in ["resolution_limit","resolution_limit_lp_mm","resolution_limit_dpi","resolution_limit_lw_ph","usaf_focus_score"]:
            v=[r["values"][key] for r in rows if r.get("values",{}).get(key) is not None]
            summary["statistics"][ch][key]={"count":len(v),"min":float(np.min(v)),"p10":float(np.percentile(v,10)),"median":float(np.median(v)),"max":float(np.max(v))} if v else {"count":0}
        valid=[u for u in unit_records if u.get('combined',{}).get(ch,{}).get('values',{}).get('resolution_limit') is not None]
        if valid:
            best=max(valid,key=lambda u:u['combined'][ch]['values'].get('resolution_limit_lp_mm') or u['combined'][ch]['values']['resolution_limit'])
            summary['best_current_location'][ch]={'unit_id':best['unit_id'],'position_px':best['position'],'values':best['combined'][ch]['values']}
    return output,summary
