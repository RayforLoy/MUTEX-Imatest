"""Explain unavailable measurements without changing any measured value.

The viewer, exported coverage maps and result tables share these reasons.
reason_for keeps the historical primary code for counts; reason_codes retains
all applicable causes for point inspection.
"""
from collections import Counter
from .models import FATAL_FLAGS
from .resolution import FREQUENCY_METRICS, metric_key, view_result

REASONS = {
 'outside_image':'图像未覆盖该单元', 'registration_failed':'原像素定位未通过',
 'insufficient_matches':'定位特征不足', 'inconsistent_matches':'定位匹配不一致',
 'registration_residual':'定位残差超过允许范围', 'roi_outside':'测量区域被裁切',
 'invalid_ctf_reference':'低频参考不足', 'directional_resolution_incomplete':'双向连续分辨率证据不完整',
 'bars_not_separated':'三条纹未分离', 'bar_geometry_mismatch':'条纹几何不符',
 'ctf_noise_limited':'条纹信噪比不足', 'low_contrast':'对比信号不足',
 'threshold_bracket_missing':'交点未被相邻有效频点包围',
 'clipped_bracket_unavailable':'剪切后缺少可用交点',
 'above_highest_test_frequency':'图卡频率未覆盖交点',
 'below_lowest_test_frequency':'交点低于最低测试频率', 'frequency_gap':'测试频率断档',
 'missing_ctf_sample':'连续频段中缺少可靠 CTF 样本',
 'missing_calibration':'缺少适用物理标定', 'invalid_edge':'斜边位置或角度不合适',
 'insufficient_samples':'原像素样本不足', 'clipped':'信号剪切',
 'fit_failed':'测量拟合失败', 'halo_insufficient_evidence':'低频边缘证据不足',
 'rgb_alignment_failed':'RGB 配准未通过', 'aliasing':'条纹混叠，无法可靠分辨',
 'missing_frequency':'缺少图案频率定义', 'unsupported_pattern':'当前图案不支持此测量',
 'missing_reference':'缺少所需实测参考值', 'insufficient_frequency_samples':'有效频率样本不足',
 'template_occluded':'模板中的测量图案被遮挡', 'target_mismatch':'实拍图案与模板定义不符',
 'star_geometry_invalid':'西门子星图中心或几何检查未通过',
 'profile_contamination':'条纹剖面有窄浅杂质干扰；已按三线几何排除候选',
 'no_value':'未测得该指标', 'low_confidence':'测量置信度不足',
 'insufficient_contiguous_support':'连续有效频率证据不足',
 'invalid_position':'测点坐标无效',
 'above_sampling_frequency':'响应曲线在采样频率上限前未跨过阈值',
}

REASONS_EN = {
 'outside_image':'This chart unit is outside the image',
 'registration_failed':'Native-pixel registration failed',
 'insufficient_matches':'Too few registration features',
 'inconsistent_matches':'Registration matches are inconsistent',
 'registration_residual':'Registration residual exceeds the allowed range',
 'roi_outside':'The measurement region is cropped',
 'invalid_ctf_reference':'Insufficient low-frequency reference',
 'directional_resolution_incomplete':'Incomplete continuous-resolution evidence in one or both directions',
 'bars_not_separated':'The three bars are not resolved',
 'bar_geometry_mismatch':'Bar geometry does not match the target',
 'ctf_noise_limited':'Insufficient bar signal-to-noise ratio',
 'low_contrast':'Insufficient contrast',
 'threshold_bracket_missing':'The threshold is not bracketed by adjacent valid frequencies',
 'clipped_bracket_unavailable':'No usable threshold bracket remains after clipping exclusion',
 'above_highest_test_frequency':'The chart does not reach the threshold crossing',
 'below_lowest_test_frequency':'The crossing is below the lowest tested frequency',
 'frequency_gap':'A test-frequency gap interrupts the curve',
 'missing_ctf_sample':'A reliable CTF sample is missing from the continuous band',
 'missing_calibration':'The required physical calibration is missing',
 'invalid_edge':'The slanted-edge position or angle is unsuitable',
 'insufficient_samples':'Insufficient native-pixel samples',
 'clipped':'Signal clipping', 'fit_failed':'Measurement fitting failed',
 'halo_insufficient_evidence':'Insufficient low-frequency edge evidence',
 'rgb_alignment_failed':'RGB registration failed',
 'aliasing':'Aliased bars cannot be resolved reliably',
 'missing_frequency':'The pattern frequency is undefined',
 'unsupported_pattern':'The pattern does not support this measurement',
 'missing_reference':'The required measured reference is missing',
 'insufficient_frequency_samples':'Insufficient valid frequency samples',
 'template_occluded':'The measurement pattern is occluded in the template',
 'target_mismatch':'The photographed pattern does not match the template',
 'star_geometry_invalid':'Siemens-star center or geometry validation failed',
 'profile_contamination':'Minor profile contamination: narrow, shallow extra troughs rejected using verified three-bar geometry',
 'no_value':'This metric was not measured', 'low_confidence':'Measurement confidence is too low',
 'insufficient_contiguous_support':'Insufficient continuous valid-frequency evidence',
 'invalid_position':'The measurement coordinates are invalid',
 'above_sampling_frequency':'The response does not cross the threshold within the sampled-frequency range',
}


def reason_description(code, language='zh_CN'):
    mapping = REASONS_EN if str(language).lower().startswith('en') else REASONS
    # Unknown flags remain visible when opening results from another version.
    return mapping.get(code, code)


def _unit_id(measurement):
    unit = measurement.region_id.split('-combined-summary')[0].split('-vertical-summary')[0].split('-horizontal-summary')[0]
    return unit.split('-vertical-')[0].split('-horizontal-')[0]


def _registration_diagnostic(result, measurement):
    return getattr(result, 'registration', {}).get('unit_diagnostics', {}).get(_unit_id(measurement), {})


def _crossing_codes(result, measurement, metric):
    if metric not in {'ctf50', 'ctf20', 'ctf10'} or measurement.metric(metric) is not None:
        return []
    record = next((u for u in getattr(result, 'optical_summary', {}).get('units', [])
                   if u['unit_id'] == _unit_id(measurement)), {})
    selected = record.get('combined', {}).get(measurement.channel, {})
    direction = selected.get('selected_direction') if measurement.direction_deg is None else 'vertical' if measurement.direction_deg == 0 else 'horizontal'
    directions = [direction] if direction else list(record.get('directions', {}))
    reasons = []
    for selected_direction in directions:
        curve = record.get('directions', {}).get(selected_direction, {}).get(measurement.channel, {}).get('curve', {})
        status = curve.get('crossing_status', {}).get(metric)
        if status and status != 'measured':
            reasons.append(status)
    return list(dict.fromkeys(reasons))


def reason_codes(result, measurement, metric, unit=None):
    """All causes affecting this metric/unit; advisory flags are not failures."""
    m = measurement
    diagnostic = _registration_diagnostic(result, m)
    causes = []
    if 'outside_image' in m.flags:
        causes.append('outside_image')
    if 'registration_failed' in m.flags:
        status = diagnostic.get('status')
        causes.append(status if status in {'outside_image', 'insufficient_matches', 'inconsistent_matches', 'registration_residual'} else 'registration_failed')
    causes.extend(flag for flag in m.flags if flag in FATAL_FLAGS and flag not in {'outside_image', 'registration_failed'})
    causes.extend(_crossing_codes(result, m, metric))
    actual = metric_key(metric, unit) if unit else metric
    if (metric in FREQUENCY_METRICS and unit in {'DPI', 'lp/mm'} and m.metric(metric) is not None
            and (not getattr(result, 'template', {}).get('calibrated') or m.metric(actual) is None)):
        causes.append('missing_calibration')
    if metric in {'sampling_dpi_x','sampling_dpi_y'} and not getattr(result,'template',{}).get('calibrated'):
        causes.append('missing_calibration')
    if m.confidence <= .05:
        causes.append('low_confidence')
    if m.metric(actual) is None:
        causes.extend(flag for flag in m.flags if flag in {
            'halo_insufficient_evidence', 'bars_not_separated', 'frequency_gap',
            'below_lowest_test_frequency', 'above_highest_test_frequency',
            'insufficient_contiguous_support', 'threshold_bracket_missing',
            'clipped_bracket_unavailable', 'missing_ctf_sample'})
        if not causes and m.kind=='edge' and metric in {'mtf50','mtf50p','mtf20','mtf10'}:
            import math
            response=m.curves.get('sfr',{}).get('y',[])
            finite=[float(v) for v in response if v is not None and math.isfinite(float(v))]
            threshold={'mtf50':.5,'mtf50p':.5,'mtf20':.2,'mtf10':.1}[metric]
            if metric=='mtf50p' and finite:
                peak=max(finite)
                finite=[v/peak for v in finite] if peak>0 else []
            if finite and min(finite)>threshold:causes.append('above_sampling_frequency')
        if not causes:
            causes.append('no_value')
    return list(dict.fromkeys(causes))


def reason_for(result, m, metric, unit=None):
    """Primary reason for aggregate counts; reason_text provides point detail."""
    causes = reason_codes(result, m, metric, unit)
    return causes[0] if causes else 'no_value'


def reason_text(result, measurement, metric, unit=None, language='zh_CN', *, details=True):
    """Human-readable point rejection text, shared by UI and report exports."""
    causes = reason_codes(result, measurement, metric, unit)
    text = '; '.join(reason_description(code, language) for code in causes)
    if causes==['no_value'] and metric in {'ctf50','ctf20','ctf10'}:
        text=(f'No supported {metric.upper()} threshold crossing; inspect valid response coverage.' if str(language).startswith('en')
              else f'未测得可靠的 {metric.upper()} 阈值交点；请检查有效曲线及频率覆盖。')
    if not details or not causes:
        return text
    english = str(language).lower().startswith('en')
    diagnostic = _registration_diagnostic(result, measurement)
    extra = []
    if any(code in causes for code in {'registration_failed', 'insufficient_matches', 'inconsistent_matches', 'registration_residual'}):
        counts = []
        for key, zh, en in [('visible_fiducials', '可见特征', 'visible features'), ('matches', '匹配', 'matches'), ('inliers', '内点', 'inliers')]:
            if key in diagnostic:
                counts.append(f'{en if english else zh} {diagnostic[key]}')
        if diagnostic.get('rms_px') is not None:
            counts.append(f"RMS {diagnostic['rms_px']:.4g} px")
        if counts:
            extra.append(', '.join(counts))
    if 'clipped' in causes and measurement.metric('clipping_fraction') is not None:
        ratio = measurement.metric('clipping_fraction')
        threshold = getattr(result, 'settings', {}).get('maximum_clip_fraction', .01)
        extra.append((f'clipped pixels {ratio:.3%}; exclusion threshold {threshold:.3%}' if english
                      else f'剪切像素 {ratio:.3%}；排除阈值 {threshold:.3%}'))
    if 'low_confidence' in causes:
        extra.append(f'confidence {measurement.confidence:.3g} ≤ 0.05' if english else f'置信度 {measurement.confidence:.3g} ≤ 0.05')
    if 'missing_calibration' in causes and unit:
        extra.append(f'cannot convert to {unit}' if english else f'无法换算为 {unit}')
    exception = getattr(measurement, 'diagnostics', {}).get('message') or getattr(measurement,'diagnostics',{}).get('exception')
    if isinstance(exception, str) and exception:
        extra.append(exception[:1000])
    return text + (' (' + '; '.join(extra) + ')' if extra else '')


def summarize_audit(result, metrics=None):
    from .analysis_catalog import METRIC_LABELS
    metrics = metrics or result.settings.get('analysis_metrics') or ['resolution_limit', 'ctf50', 'ctf20', 'ctf10', 'sharpening_halo_pct']
    items = []
    for metric in metrics:
        rows = view_result(result, metric).measurements
        for ch in dict.fromkeys(m.channel for m in rows):
            selected = [m for m in rows if m.channel == ch]
            missing = Counter()
            valid = 0
            for m in selected:
                if m.valid and m.confidence > .05 and m.metric(metric) is not None:
                    valid += 1
                else:
                    missing[reason_for(result, m, metric)] += 1
            items.append({'metric': metric, 'name': METRIC_LABELS.get(metric, metric), 'channel': ch, 'valid': valid, 'total': len(selected),
                          'missing_reasons': dict(missing), 'missing_descriptions': {REASONS.get(k, k): v for k, v in missing.items()}})
    return {'version': 'mutex-missing-audit-2', 'registration': dict(Counter(d['status'] for d in result.registration.get('unit_diagnostics', {}).values())),
            'measurement_flags': dict(Counter(f for m in result.measurements for f in m.flags)), 'items': items}
