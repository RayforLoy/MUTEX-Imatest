"""Why a selected metric has no value, kept separate from capability support."""
from collections import Counter
from .resolution import view_result

REASONS={'outside_image':'图像未覆盖该单元','registration_failed':'原像素定位未通过','insufficient_matches':'定位特征不足',
 'roi_outside':'测量区域被裁切','invalid_ctf_reference':'低频参考不足','directional_resolution_incomplete':'双向连续分辨率证据不完整',
 'bars_not_separated':'三条纹未分离','bar_geometry_mismatch':'条纹几何不符','ctf_noise_limited':'条纹信噪比不足',
 'low_contrast':'对比信号不足','threshold_bracket_missing':'交点未被相邻有效频点包围',
 'clipped_bracket_unavailable':'剪切后缺少可用交点','above_highest_test_frequency':'图卡频率未覆盖交点',
 'below_lowest_test_frequency':'交点低于最低测试频率','frequency_gap':'测试频率断档','missing_calibration':'缺少适用物理标定',
 'invalid_edge':'斜边位置或角度不合适','insufficient_samples':'原像素样本不足','clipped':'信号剪切',
 'fit_failed':'测量拟合失败','halo_insufficient_evidence':'低频边缘证据不足','rgb_alignment_failed':'RGB 配准未通过',
 'no_value':'未测得该指标','low_confidence':'测量置信度不足','insufficient_contiguous_support':'连续有效频率证据不足'}


def reason_for(result,m,metric):
    unit=m.region_id.split('-combined-summary')[0].split('-vertical-summary')[0].split('-horizontal-summary')[0]
    unit=unit.split('-vertical-')[0].split('-horizontal-')[0]
    diagnostic=result.registration.get('unit_diagnostics',{}).get(unit,{})
    if 'outside_image' in m.flags:return 'outside_image'
    if 'registration_failed' in m.flags:
        return 'outside_image' if diagnostic.get('status')=='outside_image' else 'insufficient_matches' if diagnostic.get('status')=='insufficient_matches' else 'registration_failed'
    for reason in ['roi_outside','invalid_ctf_reference','invalid_edge','insufficient_samples','clipped','fit_failed','rgb_alignment_failed','halo_insufficient_evidence']:
        if reason in m.flags:return reason
    if metric in {'ctf50','ctf20','ctf10'}:
        record=next((u for u in result.optical_summary.get('units',[]) if u['unit_id']==unit),{})
        selected=record.get('combined',{}).get(m.channel,{})
        direction=selected.get('selected_direction') if m.direction_deg is None else 'vertical' if m.direction_deg==0 else 'horizontal'
        curve=record.get('directions',{}).get(direction,{}).get(m.channel,{}).get('curve',{})
        if curve.get('crossing_status',{}).get(metric):return curve['crossing_status'][metric]
    for reason in ['bar_geometry_mismatch','ctf_noise_limited','bars_not_separated','low_contrast','insufficient_contiguous_support','below_lowest_test_frequency','frequency_gap','directional_resolution_incomplete']:
        if reason in m.flags:return reason
    return 'low_confidence' if m.confidence<=.05 else 'no_value'


def summarize_audit(result,metrics=None):
    from .analysis_catalog import METRIC_LABELS
    metrics=metrics or result.settings.get('analysis_metrics') or ['resolution_limit','ctf50','ctf20','ctf10','sharpening_halo_pct']
    items=[]
    for metric in metrics:
        rows=view_result(result,metric).measurements
        for ch in dict.fromkeys(m.channel for m in rows):
            selected=[m for m in rows if m.channel==ch];missing=Counter();valid=0
            for m in selected:
                if m.valid and m.confidence>.05 and m.metric(metric) is not None:valid+=1
                else:missing[reason_for(result,m,metric)]+=1
            items.append({'metric':metric,'name':METRIC_LABELS.get(metric,metric),'channel':ch,'valid':valid,'total':len(selected),
                          'missing_reasons':dict(missing),'missing_descriptions':{REASONS.get(k,k):v for k,v in missing.items()}})
    return {'version':'mutex-missing-audit-1','registration':dict(Counter(d['status'] for d in result.registration.get('unit_diagnostics',{}).values())),
            'measurement_flags':dict(Counter(f for m in result.measurements for f in m.flags)),'items':items}
