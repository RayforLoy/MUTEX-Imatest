from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass,asdict,field
import hashlib,json
import numpy as np
from scipy.interpolate import PchipInterpolator
from .models import plain
from .utils import atomic_json

@dataclass
class FocusPeak:
    region_id:str
    channel:str
    position:tuple
    peak:float|None
    uncertainty:float|None
    confidence:float
    flags:list
    samples:list
    fitted:list=field(default_factory=list)

@dataclass
class FocusResult:
    metric:str
    channel:str
    unit:str
    objective:str
    recommended_position:float|None
    peaks:list[FocusPeak]
    field_model:dict
    objective_curve:dict
    warnings:list
    image_fingerprints:list
    height_calibrated:bool=False
    channel_results:dict=field(default_factory=dict)
    rgb_focus_offsets:dict=field(default_factory=dict)
    evaluation_summary:dict=field(default_factory=dict)
    def to_dict(self):return plain(asdict(self))
    def save(self,path):atomic_json(path,self.to_dict())

def _signature(result):
    relevant={k:result.settings.get(k) for k in ["channels","transfer","gamma","oecf_sha256","oversampling","window","edge_fit","demosaic","measurement_pipeline","algorithm_version","target_frequency","usaf_threshold_mode","ctf_threshold","reject_clipping","maximum_clip_fraction","gray_weights","rgb_max_shift_px"]}
    chart={k:result.template.get(k) for k in ["id","regions","physical_size_mm","calibrated"]}
    return json.dumps({"config":relevant,"chart":chart,"geometry":[result.image.width,result.image.height],
                       "decoder":result.image.decoder},sort_keys=True)

def fit_peak(z,scores,confidence=1):
    z=np.asarray(z,float);scores=np.asarray(scores,float)
    flags=[]
    if len(z)<5:return None,None,0,["insufficient_samples"],[]
    span=float(z[-1]-z[0]);dynamic=float(np.ptp(scores))
    if span<=0 or dynamic<max(abs(float(scores.max()))*.04,1e-6):return None,None,0,["flat_focus_response"],[]
    i=int(np.argmax(scores))
    if i<2 or i>len(z)-3:return None,None,0,["peak_not_bracketed"],[]
    ids=np.arange(i-2,i+3);origin=z[i];scale=max(z[ids[-1]]-z[ids[0]],1e-9)
    t=(z[ids]-origin)/scale;y=scores[ids]
    design=np.column_stack([np.ones(len(t)),t,t*t])
    p=np.linalg.lstsq(design,y,rcond=None)[0]
    if p[2]>=-1e-9:return None,None,0,["nonconcave_peak"],[]
    vertex=-p[1]/(2*p[2]);peak=float(origin+vertex*scale)
    if not z[i-1]<=peak<=z[i+1]:return None,None,0,["fit_outside_bracket"],[]
    predicted=design@p
    rss=float(np.sum((y-predicted)**2))
    r2=1-rss/max(float(np.sum((y-y.mean())**2)),1e-12)
    if r2<.6:return None,None,0,["unstable_peak"],[]
    cov=np.linalg.pinv(design.T@design)*rss/max(1,len(t)-3)
    grad=np.array([0,-1/(2*p[2]),p[1]/(2*p[2]**2)])
    uncertainty=float(np.sqrt(max(0,grad@cov@grad))*scale)
    dense=np.linspace(z[ids[0]],z[ids[-1]],100)
    td=(dense-origin)/scale
    fitted=np.column_stack([dense,p[0]+p[1]*td+p[2]*td*td]).tolist()
    conf=float(np.clip(confidence*r2*np.exp(-uncertainty/max(np.median(np.diff(z)),1e-9)),0,1))
    return peak,uncertainty,conf,flags,fitted


def _focus_candidate(result,m,metric):
    from .resolution import RAW_METRIC_KINDS,MULTI_METRICS
    if result.optical_summary and m.kind=='usaf_summary':
        return m.direction_deg is None and (metric in MULTI_METRICS or metric in m.values)
    if result.optical_summary and m.kind=='usaf' and metric in MULTI_METRICS:return False
    if metric in m.values:return True
    if m.kind not in RAW_METRIC_KINDS.get(metric,set()):return False
    if m.kind=='star' and metric in {'mtf50','mtf50p','mtf20','mtf10','ctf50','ctf20','ctf10'}:
        region=next((r for r in result.template.get('regions',[]) if r['id']==m.region_id),{})
        params=region.get('params',{})
        sine=params.get('pattern')=='sinusoidal' and params.get('reference_modulation') is not None
        return sine if metric.startswith('mtf') else not sine
    return True

def analyze_focus(results,metric="mtf50",channel="G",objective="balanced",height_calibrated=False):
    if channel=='ALL':
        available={m.channel for r in results for m in r.measurements if _focus_candidate(r,m,metric)}
        fits={};errors={}
        for ch in ['R','G','B','Y','Y_align']:
            if ch not in available:continue
            try:fits[ch]=analyze_focus(results,metric,ch,objective,height_calibrated)
            except ValueError as exc:errors[ch]=str(exc)
        if not fits:raise ValueError('各通道均没有可用的焦位序列：'+str(errors))
        base=__import__('copy').deepcopy(fits.get('G',next(iter(fits.values()))))
        base.channel='ALL';base.peaks=[p for f in fits.values() for p in f.peaks]
        base.channel_results={ch:f.to_dict() for ch,f in fits.items()}
        base.warnings.append('各通道分别拟合；综合推荐沿用 G 参考通道。RGB 轴向焦差与单帧横向位移分开报告。')
        if errors:base.warnings.append(str(errors))
        g={p.region_id:p for p in fits.get('G',base).peaks if p.channel=='G' and p.peak is not None and p.confidence>.1}
        for ch in ['R','B']:
            rows=[]
            for p in fits.get(ch,base).peaks:
                ref=g.get(p.region_id)
                if p.channel!=ch or not ref or p.peak is None or p.confidence<=.1:continue
                rows.append({'region_id':p.region_id,'position':p.position,'offset':p.peak-ref.peak,
                             'uncertainty':float(np.hypot(p.uncertainty or 0,ref.uncertainty or 0)),
                             'confidence':min(p.confidence,ref.confidence)})
            base.rgb_focus_offsets[ch+'-G']={'unit':base.unit,'count':len(rows),'median':float(np.median([p['offset'] for p in rows])) if rows else None,'regions':rows}
        from .evaluation import evaluate_focus
        base.evaluation_summary=evaluate_focus(base.to_dict(),results[0].settings)
        return base
    if len(results)<5:raise ValueError("焦位序列至少需要 5 张图像；推荐 7–11 个不同焦位")
    if any(r.focus_position is None for r in results):raise ValueError("每张图像都需要焦位/垫高值（可在文件名写 _z0.20mm）")
    if len({r.focus_unit for r in results})!=1:raise ValueError("序列焦位单位必须一致")
    if len({_signature(r) for r in results})!=1:raise ValueError("序列必须使用相同模板、分辨率、解码器及测量设置；请重新分析")
    unit=results[0].focus_unit
    distinct=sorted({float(r.focus_position) for r in results})
    if len(distinct)<5:raise ValueError("至少需要 5 个不同焦位；重复拍摄可用于降低噪声")
    if objective not in {"balanced","mean","center"}:raise ValueError("Unknown focus objective")
    series=defaultdict(lambda:defaultdict(list))
    positions={}
    for result in results:
        for m in result.measurements:
            if m.channel!=channel or not _focus_candidate(result,m,metric):continue
            # Retain expected regions even when every focus frame is invalid.
            # Their missing peaks belong in the reported coverage denominator.
            series[m.region_id];positions.setdefault(m.region_id,m.position)
            value=m.metric(metric)
            if m.valid and value is not None and value>0:
                series[m.region_id][float(result.focus_position)].append((value,m.confidence))
                positions[m.region_id]=m.position
    peaks=[];curves=[];curve_positions=[]
    for region_id,samples in series.items():
        if not samples:
            peaks.append(FocusPeak(region_id,channel,positions[region_id],None,None,0,['insufficient_samples'],[]))
            continue
        z=np.array(sorted(samples))
        scores=np.array([np.median([v for v,c in samples[vz]]) for vz in z])
        conf=float(np.median([c for values in samples.values() for _,c in values]))
        peak,uncertainty,confidence,flags,fitted=fit_peak(z,scores,conf)
        points=[[float(vz),float(score),len(samples[float(vz)])] for vz,score in zip(z,scores)]
        peaks.append(FocusPeak(region_id,channel,positions[region_id],peak,uncertainty,confidence,flags,points,fitted))
        # Objective uses only ROIs present at every measured position.
        if len(z)==len(distinct) and np.array_equal(z,distinct):
            curves.append(scores/max(scores.max(),1e-12));curve_positions.append(positions[region_id])
    if not peaks:raise ValueError("没有可用于此指标的有效测量区域")
    warnings=["最佳焦位由采样内拟合得到；若峰值未被包围，增加两端采样"]
    recommendation=None;objective_curve={}
    if curves:
        z=np.asarray(distinct)
        dense=np.linspace(z[0],z[-1],500)
        interpolated=np.array([PchipInterpolator(z,c)(dense) for c in curves])
        if objective=="balanced":combined=np.quantile(interpolated,.2,axis=0)
        elif objective=="center":
            width,height=results[0].image.width,results[0].image.height
            distances=np.linalg.norm(np.asarray(curve_positions)/[width,height]-.5,axis=1)
            selected=np.flatnonzero(distances<=max(.25,float(distances.min())+.02))
            combined=interpolated[selected].mean(axis=0)
        else:combined=interpolated.mean(axis=0)
        ix=int(np.argmax(combined))
        if ix==0 or ix==len(dense)-1:warnings.append("综合最优值落在序列边界，未输出推荐焦位")
        else:recommendation=float(dense[ix])
        objective_curve={"x":dense.tolist(),"y":combined.tolist(),"measured_positions":distinct,"roi_count":len(curves)}
    else:warnings.append("没有覆盖全部焦位的公共 ROI，无法给出综合推荐")
    valid=[p for p in peaks if p.peak is not None and p.confidence>.1]
    model={}
    if len(valid)>=6:
        # Field coordinates are chart coordinates, independent of homographic framing.
        import cv2
        H=np.asarray(results[0].registration.get("homography",np.diag([results[0].image.width,results[0].image.height,1])),float)
        xy=cv2.perspectiveTransform(np.array([[p.position for p in valid]],float),np.linalg.inv(H))[0]
        size=results[0].template.get("physical_size_mm")
        calibrated=bool(results[0].template.get("calibrated") and size)
        xy=(xy-.5)*np.asarray(size) if calibrated else (xy-.5)*2
        x,y=xy[:,0],xy[:,1]
        design=np.column_stack([np.ones(len(x)),x,y,x*x+y*y])
        weights=np.sqrt(np.array([p.confidence for p in valid]))
        if np.linalg.matrix_rank(design*weights[:,None])==4:
            coeff=np.linalg.lstsq(design*weights[:,None],np.array([p.peak for p in valid])*weights,rcond=None)[0]
            pred=design@coeff
            residual=np.array([p.peak for p in valid])-pred
            # Reweight large residuals once, retain evidence rather than diagnosing cause.
            scale=1.4826*np.median(abs(residual-np.median(residual)))+1e-9
            weights*=np.sqrt(np.minimum(1,2.5*scale/np.maximum(abs(residual),1e-9)))
            coeff=np.linalg.lstsq(design*weights[:,None],np.array([p.peak for p in valid])*weights,rcond=None)[0]
            residual=np.array([p.peak for p in valid])-design@coeff
            model={"model":"z = c0 + cx*x + cy*y + cr*(x²+y²)","coefficients":coeff.tolist(),
                   "xy_unit":"mm" if calibrated else "normalized field","z_unit":unit,"rms":float(np.sqrt(np.mean(residual**2))),
                   "sample_count":len(valid),"xy":xy.tolist(),"residual":residual.tolist()}
            model["physical_calibration"]=bool(calibrated and height_calibrated and unit in {"mm","um"})
            if model["physical_calibration"]:
                factor=1 if unit=="mm" else .001
                model["apparent_tilt_deg"]=float(np.degrees(np.arctan(np.hypot(coeff[1],coeff[2])*factor)))
        else:warnings.append("ROI 分布不足以分离平面倾斜和径向场曲")
    else:warnings.append("至少 6 个有效、分布充分的 ROI 才拟合倾斜与场曲")
    warnings.append("焦位面差异可能来自图卡、夹持、载台、传感器或镜头；不能单独据此诊断歪轴")
    if not height_calibrated:warnings.append("未声明实测载台/图卡轴向高度，焦位参数不会换算为机械倾角")
    outcome=FocusResult(metric,channel,unit,objective,recommendation,peaks,model,objective_curve,warnings,
                       [r.image.fingerprint for r in results],height_calibrated)
    from .evaluation import evaluate_focus
    outcome.evaluation_summary=evaluate_focus(outcome.to_dict(),results[0].settings)
    return outcome
