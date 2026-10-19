"""Explain measured results without conflating validity and acceptance.

Functions are read-only. Raw measurements and their quality flags are never
changed. Assessments can therefore be added to old result files without redoing
the optical measurements. Custom targets always carry their units and version.
"""
from __future__ import annotations
from collections import Counter
import csv
import math
from pathlib import Path
import numpy as np
from .analysis_catalog import METRIC_LABELS, SEQUENCE_METRICS
from .evaluation_catalog import REFERENCES, REFERENCE_VERSION, reference_for, reference_text
from .resolution import FREQUENCY_METRICS, MULTI_METRICS, PAIRED_SHIFT_METRICS, RAW_METRIC_KINDS, metric_key, view_result

STATUS_LABELS = {'good':'工程参考良好', 'watch':'建议留意', 'poor':'建议改善',
                 'pass':'符合自定义目标', 'fail':'未达自定义目标', 'limited':'结论受限',
                 'informational':'结果解读', 'needs_target':'待设目标', 'unavailable':'无法评价'}
STATUS_COLORS = {'good':'#147565', 'pass':'#147565', 'watch':'#986200', 'poor':'#b33c35',
                 'fail':'#b33c35', 'limited':'#936500', 'informational':'#285875',
                 'needs_target':'#5a6c7a', 'unavailable':'#798793'}
RULE_NOTE = '先检查测量有效性，再解释数值。工程建议不是 ISO / 厂商合格线；本帧最高值仅作相对参考。自定义目标不构成标准认证。'
FREQUENCY_UNITS = {'cy/px','lp/mm','DPI','LW/PH','LP/PH'}
RESPONSE_METRICS = FREQUENCY_METRICS | {'usaf_focus_score','mtf_area','information_capacity_1d',
    'sharpening_halo_pct',
    'contrast_at_frequency','mtf_nyquist','overshoot_pct','undershoot_pct','alignment_gain_pct',
    'relative_illumination_min_pct','corner_illumination_pct','illumination_nonuniformity_pct','spatial_snr_db'}
CAUTIONS = {
    'profile_contamination':'原剖面含窄浅污染假谷；三线几何核验后排除候选，仍需检查图卡洁净度',
    'clipping_advisory':'保留了剪切信号，只适合受限比较',
    'aliasing_risk':'存在混叠风险', 'bars_not_separated':'条纹未可靠分离',
    'bar_geometry_mismatch':'暗条间距或位置与靶频率不符','ctf_noise_limited':'内部条纹起伏未通过噪声检查',
    'ctf_segment_after_clipping':'交点由剪切点之后相邻且未剪切的频点实测，未跨剪切点插值',
    'frequency_gap':'测试频率不连续', 'target_limited':'达到图卡测试上限，只是实测下界',
    'above_highest_test_frequency':'超过图卡测试上限', 'below_lowest_test_frequency':'低于图卡频率覆盖',
    'mtf50_above_nyquist':'MTF50 超过采样奈奎斯特参考，应检查锐化 / 混叠',
    'strict_clipping_limits_curve':'部分测试频率因剪切排除，曲线覆盖受限',
    'unstable_peak':'焦位峰值拟合不稳定', 'peak_not_bracketed':'未包围焦位峰值',
}


def validate_limits(limits):
    if not isinstance(limits, dict):
        raise ValueError('评价目标必须是按测量项目索引的对象')
    for key, goal in limits.items():
        if key not in REFERENCES or not isinstance(goal, dict):
            raise ValueError('未知评价项目或目标格式')
        if set(goal)-{'min','max','unit','absolute','note'}:
            raise ValueError('未知评价目标字段')
        if not any(k in goal for k in ('min','max')):
            raise ValueError('评价目标需要下限或上限')
        for bound in ('min','max'):
            if bound in goal and (isinstance(goal[bound], bool) or not isinstance(goal[bound], (float,int)) or not math.isfinite(goal[bound])):
                raise ValueError('评价目标必须为有限数值')
        if goal.get('min',-math.inf)>goal.get('max',math.inf):
            raise ValueError('评价下限不能大于上限')
        if key in FREQUENCY_METRICS and goal.get('unit') not in FREQUENCY_UNITS:
            raise ValueError('频率目标需要明确 cy/px、lp/mm、DPI、LW/PH 或 LP/PH 单位')
        if 'absolute' in goal and not isinstance(goal['absolute'],bool):
            raise ValueError('绝对值评价开关必须为布尔值')
        if not isinstance(goal.get('note',''),str) or len(goal.get('note',''))>1000:
            raise ValueError('评价目标说明过长或格式无效')
        if 'unit' in goal and (not isinstance(goal['unit'],str) or len(goal['unit'])>80):
            raise ValueError('评价目标单位无效')
        if key not in FREQUENCY_METRICS:
            allowed={'', 'native', REFERENCES[key].unit}
            if key in SEQUENCE_METRICS:allowed|={'mm','um','index','focus unit'}
            if goal.get('unit','native') not in allowed:
                raise ValueError('非频率目标请使用该项目原生单位')
    return limits


def native_unit(result, key):
    unit = REFERENCES[key].unit
    if key in SEQUENCE_METRICS:return result.focus_unit
    if unit:return unit
    return {'usaf_focus_score':'ratio','mtf_area':'ratio','information_capacity_1d':'bits/px'}.get(key,'')


def goal_unit(result,key,goal):
    unit=goal.get('unit')
    return native_unit(result,key) if unit in {None,'','native','focus unit'} else unit


def metric_value(result, measurement, key, unit=None):
    """Convert targets point by point, keeping local magnification differences."""
    if key not in FREQUENCY_METRICS:
        value=measurement.metric(key)
        if key in SEQUENCE_METRICS and value is not None and unit not in {None,'','native','focus unit',result.focus_unit}:
            factor={('mm','um'):1000,('um','mm'):.001}.get((result.focus_unit,unit))
            return value*factor if factor else None
        return value
    unit=unit or 'cy/px'
    if unit in {'lp/mm','DPI'} and not result.template.get('calibrated'):
        return None
    actual=measurement.metric(metric_key(key,unit))
    if actual is not None:return actual
    value=measurement.metric(key)
    if value is None:return None
    height=result.settings.get('picture_height_px') or result.optical_summary.get('picture_height_px') or result.image.height
    scale=measurement.object_scale_px_per_mm
    if unit=='LW/PH':return value*2*height
    if unit=='LP/PH':return value*height
    if unit in {'lp/mm','DPI'}:return value*scale*(50.8 if unit=='DPI' else 1) if scale else None
    return value if unit=='cy/px' else None


def effective_reference(result, key):
    ref=reference_for(key)
    goal=result.settings.get('evaluation_limits',{}).get(key)
    if goal:
        validate_limits({key:goal})
        unit=goal_unit(result,key,goal)
        bounds=[]
        if 'min' in goal:bounds.append(f"≥ {goal['min']:.6g}")
        if 'max' in goal:bounds.append(f"≤ {goal['max']:.6g}")
        ref.update(default_reference=ref['reference'], default_criteria=ref['criteria'],
                   reference=('绝对值 ' if goal.get('absolute',REFERENCES[key].absolute) else '')+' 且 '.join(bounds)+' '+unit,
                   criteria='用户目标；每个有效测点逐一检查，任何无效 / 受限点都不能被汇总为全部通过。'+goal.get('note',''),
                   basis='用户自定义目标（非标准认证）', goal=dict(goal), goal_unit=unit)
    if key=='clipping_fraction' and not goal:
        threshold=result.settings.get('maximum_clip_fraction',.01)
        ref['criteria']=f'当前排除阈值 {threshold:g}（{threshold*100:g}%）；0 为无剪切，0–阈值提示，超过阈值建议重测。'+ref['criteria']
    if ref['bands'] and not result.settings.get('evaluation_engineering',True) and not goal:
        ref['basis']='工程分档已关闭；仅显示定义和结果'
    return ref


def selected_rows(result, key):
    view=view_result(result,key,result.settings.get('report_usaf_direction','both'),result.settings.get('report_frequency_index'))
    rows=view.measurements
    if key in PAIRED_SHIFT_METRICS:rows=[m for m in rows if m.channel==PAIRED_SHIFT_METRICS[key]]
    if key=='alignment_gain_pct':rows=[m for m in rows if m.channel=='Y_align']
    kinds={'edge','usaf_summary'} if key in PAIRED_SHIFT_METRICS else RAW_METRIC_KINDS.get(key)
    if result.optical_summary and key in MULTI_METRICS and kinds is not None:
        kinds=set(kinds)|{'usaf_summary'}
    if key in SEQUENCE_METRICS:return [m for m in rows if key in m.values]
    return [m for m in rows if key in m.values or (not m.valid and (kinds is None or m.kind in kinds))]


def _limitations(result, key, m):
    frequency_warnings={'target_limited','above_highest_test_frequency','below_lowest_test_frequency','frequency_gap','bars_not_separated'}
    notes=[]
    for flag,text in CAUTIONS.items():
        if flag not in m.flags:continue
        if flag=='profile_contamination' and key not in RESPONSE_METRICS:continue
        if flag in frequency_warnings and key not in FREQUENCY_METRICS|{'resolution_anisotropy','star_anisotropy'}:continue
        if flag in {'clipping_advisory','strict_clipping_limits_curve','aliasing_risk','mtf50_above_nyquist'} and key not in RESPONSE_METRICS:continue
        notes.append(text)
    if key in RESPONSE_METRICS and result.settings.get('transfer','unknown')=='unknown' and not result.image.is_linear:
        notes.append('输入曲线未知；仅解释编码信号响应')
    if key.startswith('dynamic_range_snr'):
        lower=key.removesuffix('_stops')+'_lower_bound'
        if m.values.get(lower):notes.append('未跨过噪声阈值；档数只是实测下界')
    if key=='encircled_r80_px' and 'finite_target_size' in m.flags:
        notes.append('有限点源大小会扩大包围能量半径')
    if key in FREQUENCY_METRICS and (m.metric(key) or 0)>.5:
        notes.append('阈值频率高于 0.5 cy/px；不能等同已确认可分辨细节')
    return list(dict.fromkeys(notes))


def _group(m):
    # No cross-pattern or cross-direction relative ranking.
    return m.kind,m.method,m.direction_deg


def assess_measurement(result, m, key, unit=None, best=None):
    spec=REFERENCES[key];unit=unit or native_unit(result,key)
    if key in FREQUENCY_METRICS:unit=unit or 'cy/px'
    value=metric_value(result,m,key,unit)
    base={'metric':key,'channel':m.channel,'region_id':m.region_id,'value':value,'unit':unit,
          'status':'unavailable','label':STATUS_LABELS['unavailable'],'text':'','limitations':[], 'rule_version':REFERENCE_VERSION}
    if not m.valid or m.confidence<=.05:
        from .analysis_audit import reason_text
        base['text']=reason_text(result,m,key,unit)
        return base
    if value is None:
        from .analysis_audit import reason_text
        base['text']=reason_text(result,m,key,unit)+'；未测得不填零。'
        return base
    if key in {'sampling_dpi_x','sampling_dpi_y'} and not result.template.get('calibrated'):
        base['text']='物理尺寸未标定，无法评价几何 PPI。'
        return base
    goal=result.settings.get('evaluation_limits',{}).get(key)
    status='needs_target';text=f'实测 {value:.6g} {unit}；没有通用合格线，请按用途设置目标。'
    if key in {'delta_e_76','white_balance_delta_ab','edge_noise_rms','veiling_glare_pct','color_moire_pct','encircled_r80_px'}:
        text=f'实测 {value:.6g} {unit}；同条件通常越低越接近参考，未设目标不给绝对等级。'
    if key in {'sampling_dpi_x','sampling_dpi_y'}:
        text=f'实测几何采样 {value:.6g} PPI；未设采样密度要求，不能据此评价实际分辨率。'
    if key.startswith('dynamic_range_snr'):
        text=f'在声明 SNR 阈值下实测 {value:.6g} 档；无统一优秀档数，需同方法基准或自定义下限。'
    if key=='oecf_gamma':text=f'编码幂律斜率 {value:.6g}；需和期望编码曲线比较，线性编码参考为 1。'
    if key=='outer_ring_radius_px':text=f'外环半径 {value:.6g} px；尺寸没有高低优劣，未设标称半径目标。'
    if key=='mean':text=f'ROI 平均信号 {value:.6g}；需结合灰块参考、曝光及剪切，均值较大不一定较好。'
    if key=='mtf_nyquist':text=f'0.5 cy/px 处响应 {value:.6g}；高低不能单独判优劣，请同时检查锐化与混叠。'
    if goal:
        validate_limits({key:goal})
        target_unit=goal_unit(result,key,goal)
        judged=metric_value(result,m,key,target_unit)
        if judged is None:
            status='limited';text=f'目标单位 {target_unit} 缺少所需标定，不能判定是否达标。'
        else:
            judged=abs(judged) if goal.get('absolute',spec.absolute) else judged
            passed=goal.get('min',-math.inf)<=judged<=goal.get('max',math.inf)
            status='pass' if passed else 'fail'
            text=f"按{'绝对值 ' if goal.get('absolute',spec.absolute) else ''}{judged:.6g} {target_unit} 检查用户目标；"+('达到所设范围。' if passed else '超出所设范围。')
        base['goal']=dict(goal)
    elif spec.bands and result.settings.get('evaluation_engineering',True):
        judged=abs(value) if spec.absolute else abs(value-100) if spec.mode=='distance100' else value
        good,warn=spec.bands
        status=('good' if judged>=good else 'watch' if judged>=warn else 'poor') if spec.mode=='high' else ('good' if judged<=good else 'watch' if judged<=warn else 'poor')
        text=f'{value:.6g} {unit}；按 MUTEX 工程建议解释，非行业合格线。'
    elif spec.mode=='relative_high':
        status='informational'
        if best is not None and best>0:
            ratio=value/best;base.update(relative_to_best=ratio, reference_best=best)
            text=f'本帧同通道、同图案 / 方法 / 方向最高 {best:.6g} {unit}；当前为其 {ratio*100:.1f}%。这是场内相对比较。'
        else:text='有效响应；同条件通常越高越好。当前没有可比较的同组参考，不给绝对等级。'
    elif spec.mode=='change':
        status='informational'
        text=('变化较小（|变化| ≤ 2%，工程提示）' if abs(value)<=2 else '对齐后数值提高' if value>0 else '对齐后数值下降')+'；重采样及重复测量差异尚未排除。'
    elif spec.mode=='candidates':
        status='watch' if value>0 else 'informational'
        text=f'{value:g} 个候选；'+('需重复暗平场确认，不能据此判永久缺陷。' if value>0 else '仅表示本次阈值下未发现，不是传感器无缺陷证明。')
    elif spec.mode=='clipping':
        threshold=result.settings.get('maximum_clip_fraction',.01)
        status='informational' if value==0 else 'watch' if value<=threshold else 'poor'
        text=f'剪切 {100*value:.4g}%；当前排除阈值 {100*threshold:.4g}%。'+('本区域无剪切。' if value==0 else '信号已丢失，请结合曝光和图卡高反差检查。')
    elif spec.mode in {'focus','focus_offset'}:
        status='informational' if spec.mode=='focus' else 'needs_target'
        text='已得到采样内的最佳焦位；坐标本身没有优劣，需结合场间跨度及拟合不确定度。' if spec.mode=='focus' else '已得到相对 G 的轴向焦位差；未设置允许焦深，不按步数给合格结论。'
    if key in {'rgb_shift_px','rgb_shift_x_px','rgb_shift_y_px'} and m.channel=='G':
        status='informational';text='G 是位移参考，0 由定义得到；不是独立的通道配准质量或验收通过证明。'
    if key in {'best_focus','focus_offset'} and m.diagnostics.get('uncertainty') is not None:
        uncertainty=float(m.diagnostics['uncertainty']);base['fit_uncertainty']=uncertainty
        text+=f' 拟合不确定度 {uncertainty:.4g} {result.focus_unit}（不含载台 / 图卡系统误差）。'
    numeric_status=status
    limitations=_limitations(result,key,m)
    lower_bound=(key=='resolution_limit' and 'target_limited' in m.flags) or (
        key.startswith('dynamic_range_snr') and m.values.get(key.removesuffix('_stops')+'_lower_bound'))
    if goal and lower_bound and status=='fail':
        judged=metric_value(result,m,key,goal_unit(result,key,goal))
        # A measured lower bound below a minimum says nothing about the true
        # upper extent. It must never be called a failed minimum requirement.
        if judged is not None and 'min' in goal and judged<goal['min'] and not (goal.get('max') is not None and judged>goal['max']):
            status='limited';text+=' 此数值为下界，尚不能判断真实能力是否低于所设下限。'
    if goal and key in {'best_focus','focus_offset'} and m.diagnostics.get('uncertainty') is not None:
        uncertainty=float(m.diagnostics['uncertainty'])
        target_unit=goal_unit(result,key,goal)
        uncertainty*= {('mm','um'):1000,('um','mm'):.001}.get((result.focus_unit,target_unit),1)
        judged=metric_value(result,m,key,target_unit)
        if judged is not None:
            low,high=(max(0,abs(judged)-uncertainty),abs(judged)+uncertainty) if goal.get('absolute',spec.absolute) else (judged-uncertainty,judged+uncertainty)
            if low<=goal.get('min',-math.inf)<=high or low<=goal.get('max',math.inf)<=high:
                limitations.append('拟合不确定度范围触及用户限值；不能确定是否达标')
                if status in {'pass','fail'}:status='limited'
    if limitations:
        base['numeric_status']=numeric_status
        # Missing quantitative prerequisites prevent *both* pass and fail.
        # The sole exception is a trustworthy lower bound already above an
        # upper limit: the unmeasured extent cannot bring it back under that limit.
        bound_only={CAUTIONS['target_limited'],'未跨过噪声阈值；档数只是实测下界'}
        upper_violation=False
        if goal and lower_bound and 'max' in goal:
            judged=metric_value(result,m,key,goal_unit(result,key,goal))
            upper_violation=judged is not None and judged>goal['max']
        status='fail' if upper_violation and set(limitations)<=bound_only else 'limited'
    base.update(status=status,label=STATUS_LABELS[status],text=text,limitations=limitations)
    return base


def assess_channel(result, key, rows, unit=None):
    unit=unit or native_unit(result,key)
    if key in FREQUENCY_METRICS:unit=unit or 'cy/px'
    best={};group_count=Counter()
    for m in rows:
        value=metric_value(result,m,key,unit)
        if m.valid and m.confidence>.05 and value is not None:
            group=_group(m);best[group]=max(best.get(group,-math.inf),value);group_count[group]+=1
    assessments=[assess_measurement(result,m,key,unit,best.get(_group(m)) if group_count[_group(m)]>=2 else None) for m in rows]
    usable=[a for a in assessments if a['status']!='unavailable' and a['value'] is not None]
    values=[a['value'] for a in usable];counts=Counter(a['status'] for a in assessments)
    limitations=Counter(note for a in assessments for note in a['limitations'])
    total=len(rows);valid=len(usable)
    priority=['fail','poor','limited','watch','needs_target','informational','good','pass']
    status=next((s for s in priority if counts[s]),'unavailable')
    if valid and counts['unavailable'] and status not in {'fail','poor'}:status='limited'
    label=STATUS_LABELS[status]
    if status=='unavailable':text='没有可评价测点；保留原因，不用零代替缺失结果。'
    else:
        details='；'.join(f'{STATUS_LABELS[s]} {n} 点' for s,n in counts.items())
        text=f'有效 {valid}/{total}；{details}。最差测点参与评价，均值不替代逐点评价。'
    spec=REFERENCES[key]
    worst=None
    if values:
        if spec.mode in {'low','distance100','clipping','candidates'} or spec.absolute or key in {
                'delta_e_76','white_balance_delta_ab','edge_noise_rms','veiling_glare_pct','color_moire_pct','encircled_r80_px'}:
            worst=max(values,key=lambda v:abs(v-100) if spec.mode=='distance100' else abs(v) if spec.absolute else v)
        elif spec.mode in {'high','relative_high'} or key.startswith('dynamic_range_snr'):worst=min(values)
    goal=result.settings.get('evaluation_limits',{}).get(key)
    if goal and values:
        # Worst goal violation, evaluated in each point's target units.
        def violation(m):
            v=metric_value(result,m,key,goal.get('unit'))
            if v is None:return -math.inf
            v=abs(v) if goal.get('absolute',spec.absolute) else v
            return max(goal.get('min',-math.inf)-v,v-goal.get('max',math.inf))
        candidates=[m for m,a in zip(rows,assessments) if a['status']!='unavailable' and a['value'] is not None]
        if candidates:worst=metric_value(result,max(candidates,key=violation),key,unit)
    from .analysis_audit import reason_for,REASONS
    missing=Counter(('missing_calibration' if key in FREQUENCY_METRICS and unit in {'lp/mm','DPI'} and m.valid and m.metric(key) is not None
                     else reason_for(result,m,key)) for m,a in zip(rows,assessments) if a['status']=='unavailable')
    return {'status':status,'label':label,'text':text,'valid':valid,'total':total,'unit':unit,
            'missing_reasons':dict(missing),'missing_descriptions':{REASONS.get(k,k):v for k,v in missing.items()},
            'coverage_pct':100*valid/total if total else 0,'counts':dict(counts),'limitations':dict(limitations),
            'median':float(np.median(values)) if values else None,'p10':float(np.percentile(values,10)) if values else None,
            'p90':float(np.percentile(values,90)) if values else None,'worst':worst,
            'min':min(values) if values else None,'max':max(values) if values else None,
            'point_assessments':assessments}


def evaluate_result(result, metrics=None, unit=None, *, include_points=False):
    from .capabilities import metric_availability
    available,_=metric_availability(None,result)
    metrics=list(dict.fromkeys(metrics if metrics is not None else METRIC_LABELS))
    items=[]
    for key in metrics:
        if key not in REFERENCES:continue
        rows=selected_rows(result,key);channels=[]
        for ch in dict.fromkeys(m.channel for m in rows):
            evaluation=assess_channel(result,key,[m for m in rows if m.channel==ch],unit if key in FREQUENCY_METRICS else None)
            if not include_points:evaluation.pop('point_assessments')
            channels.append({'channel':ch,**evaluation})
        reason=available.get(key,'当前模板不具备此测量条件')
        if rows and key in SEQUENCE_METRICS:reason=''
        items.append({'metric':key,'name':METRIC_LABELS[key],'reference':effective_reference(result,key),
                      'reason':reason or ('' if channels else '未得到该项目测量；需要相应图案、参考或序列。'), 'channels':channels})
    return {'version':REFERENCE_VERSION,'note':RULE_NOTE,'engineering_enabled':result.settings.get('evaluation_engineering',True),
            'custom_limits':result.settings.get('evaluation_limits',{}),'items':items}


def channel_text(evaluation):
    lines=[evaluation['label']+'：'+evaluation['text']]
    if evaluation.get('median') is not None:
        lines.append(f"中位数 {evaluation['median']:.6g}；范围 {evaluation['min']:.6g}–{evaluation['max']:.6g} {evaluation['unit']}；有效覆盖 {evaluation['coverage_pct']:.1f}%")
    lines.extend('限制：'+note+f'（{n} 点）' for note,n in evaluation.get('limitations',{}).items())
    return '\n'.join(lines)


def measurement_text(result, measurement, key, unit=None):
    if key not in REFERENCES:return ''
    a=assess_measurement(result,measurement,key,unit)
    return a['label']+'：'+a['text']+''.join('\n限制：'+s for s in a['limitations'])


def evaluate_focus(data, settings=None):
    """Assess a focus sequence, preserving failed peaks in the denominator."""
    from .models import AnalysisResult, ImageMetadata, Measurement
    rows=[];unit=data['unit']
    offsets={ch:{r['region_id']:r for r in rec.get('regions',[])} for ch,rec in data.get('rgb_focus_offsets',{}).items()}
    for p in data['peaks']:
        valid=p['peak'] is not None and p['confidence']>.1 and not p['flags']
        diag={'uncertainty':p.get('uncertainty')}
        rows.append(Measurement(p['region_id'],p['region_id'],'focus',p['channel'],p['position'],(0,0,1,1),
                                {'best_focus':p['peak']},{'best_focus':unit},flags=[] if valid else ['fit_failed',*p['flags']],
                                confidence=p['confidence'],diagnostics=diag))
        if data.get('channel')=='ALL' and p['channel'] in {'R','B'}:
            offset=offsets.get(p['channel']+'-G',{}).get(p['region_id'])
            rows.append(Measurement(p['region_id'],p['region_id'],'focus',p['channel'],p['position'],(0,0,1,1),
                                    {'focus_offset':offset.get('offset') if offset else None},{'focus_offset':unit},
                                    flags=[] if valid and offset else ['missing_reference'],confidence=p['confidence'],
                                    diagnostics={'uncertainty':offset.get('uncertainty') if offset else None}))
    result=AnalysisResult(ImageMetadata('focus-sequence',1,1,3,'float64',64,0,''),'focus-sequence','focus-sequence',
                          rows,settings or {},{},focus_unit=unit)
    assessment=evaluate_result(result,['best_focus','focus_offset'])
    spans={}
    for ch in dict.fromkeys(p['channel'] for p in data['peaks']):
        peaks=[p['peak'] for p in data['peaks'] if p['channel']==ch and p['peak'] is not None and p['confidence']>.1 and not p['flags']]
        spans[ch]={'span':max(peaks)-min(peaks) if peaks else None,'valid':len(peaks),
                   'total':sum(p['channel']==ch for p in data['peaks']),'unit':unit}
    assessment.update(channel_spans=spans,recommended_position=data.get('recommended_position'),
                      height_calibrated=data.get('height_calibrated',False),
                      sequence_note='峰值不确定度仅为拟合估计，未覆盖载台、图卡和重复性误差。场间跨度没有通用合格线。')
    return assessment


def save_evaluation(result, directory, metrics=None, unit=None):
    from .utils import atomic_json
    folder=Path(directory);folder.mkdir(parents=True,exist_ok=True)
    data=evaluate_result(result,metrics,unit,include_points=True)
    atomic_json(folder/'evaluation-results.json',data)
    with (folder/'evaluation-results.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file)
        writer.writerow(['metric','name','channel','region_id','value','unit','evaluation','explanation','limitations','reference','criteria','basis','rule_version'])
        for item in data['items']:
            ref=item['reference']
            for ch in item['channels'] or [{}]:
                for a in ch.get('point_assessments') or [{}]:
                    writer.writerow([item['metric'],item['name'],ch.get('channel',''),a.get('region_id',''),a.get('value'),a.get('unit',''),
                                     a.get('label','无法评价'),a.get('text',item['reason']),'；'.join(a.get('limitations',[])),
                                     ref['reference'],ref['criteria'],ref['basis'],REFERENCE_VERSION])
    return data
