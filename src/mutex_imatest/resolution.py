"""Frequency units and view selection for native multi-frequency USAF results."""
from __future__ import annotations
import copy

FREQUENCY_METRICS={"mtf50","mtf50p","mtf20","mtf10","ctf50","ctf20","ctf10","response50","resolution_limit"}
FREQUENCY_METRICS.update({'texture_mtf50','texture_mtf10','log_mtf50','log_mtf10','log_ctf50','log_ctf10'})
MULTI_METRICS={"resolution_limit","ctf50","ctf20","ctf10","usaf_focus_score","rgb_shift_px",
               "rgb_shift_x_px","rgb_shift_y_px","alignment_gain_pct","sampling_dpi_x","sampling_dpi_y",
               "resolution_anisotropy","registration_rms_px","clipping_fraction"}
CHANNEL_LABELS={"R":"R","G":"G","B":"B","Y":"灰度 · RGB 对齐前","Y_align":"灰度 · RGB 对齐后"}
PAIRED_SHIFT_METRICS={'ca_r_g_px':'R','ca_b_g_px':'B'}
RGB_SHIFT_METRICS={'rgb_shift_px','rgb_shift_x_px','rgb_shift_y_px',*PAIRED_SHIFT_METRICS}
RAW_METRIC_KINDS={**{key:{'edge','star'} for key in ['mtf50','mtf50p','mtf20','mtf10']},
                  **{key:{'star','wedge'} for key in ['ctf50','ctf20','ctf10','resolution_limit']},
                  **{key:{'edge'} for key in ['mtf_nyquist','overshoot_pct','undershoot_pct','edge_fit_rms_px']},
                  'star_anisotropy':{'star'},'wedge_alias_fraction':{'wedge'},
                  'contrast_at_frequency':{'usaf','star','wedge'},'mean':{'flat','step'},
                  'spatial_snr_db':{'flat'},'delta_e_2000':{'color'},
                  'projective_residual_rms_px':{'grid'}}
from .analysis_catalog import EXTENDED_METRICS
RAW_METRIC_KINDS.update({key:spec[1] for key,spec in EXTENDED_METRICS.items()})


def metric_key(metric,unit):
    suffix={"lp/mm":"_lp_mm","LW/PH":"_lw_ph","LP/PH":"_lp_ph","DPI":"_dpi"}.get(unit,"")
    return metric+suffix if metric in FREQUENCY_METRICS else metric


def frequency_values(name,frequency,scale,height):
    values={name:frequency,name+"_lw_ph":2*frequency*height if frequency is not None else None,
            name+"_lp_ph":frequency*height if frequency is not None else None,
            name+"_lp_mm":frequency*scale if frequency is not None and scale else None,
            name+"_dpi":frequency*scale*50.8 if frequency is not None and scale else None}
    return values


def view_result(result,metric,direction="both",frequency_index=None):
    """Select one value per unit/channel. Full raw results remain unchanged."""
    if result is None:return result
    if not result.optical_summary:
        if direction=='both':return result
        filtered=copy.copy(result);angle=0 if direction=='vertical' else 90
        filtered.measurements=[m for m in result.measurements if m.kind!='usaf' or m.direction_deg==angle]
        return filtered
    filtered=copy.copy(result)
    target=0 if direction=="vertical" else 90 if direction=="horizontal" else None
    if metric=='sharpening_halo_pct':
        from .models import Measurement
        rows=[]
        for u in result.optical_summary.get('units',[]):
            records=u.get('sharpening',{}) if target is None else {ch:r.get('sharpening',{}) for ch,r in u['directions'].get(direction,{}).items()}
            for ch,record in records.items():
                if not record:continue
                location_flag='outside_image' if result.registration.get('unit_diagnostics',{}).get(u['unit_id'],{}).get('status')=='outside_image' else 'registration_failed'
                flags=record['flags'] if u.get('located') else [location_flag]
                x,y=u['position'];v=record['values']
                rows.append(Measurement(u['unit_id']+('-combined-summary' if target is None else '-'+direction+'-summary'),u['unit_id']+' · 锐化 / 振铃','usaf_summary',ch,(x,y),(int(x)-2,int(y)-2,4,4),
                    v,{k:'%' if k.endswith('_pct') else 'count' for k in v},{'halo_profile':record.get('curve',{})},flags,record['confidence'],'native-coarse-bar-internal-halos',target))
        rows.extend(m for m in result.measurements if m.kind=='edge')
    elif metric in RGB_SHIFT_METRICS:
        from .models import Measurement
        rows=[]
        channels=[PAIRED_SHIFT_METRICS[metric]] if metric in PAIRED_SHIFT_METRICS else ['R','G','B']
        for u in result.optical_summary.get('units',[]):
            for ch in channels:
                shift=u.get('rgb_shifts',{}).get(ch,{})
                location_flag='outside_image' if result.registration.get('unit_diagnostics',{}).get(u['unit_id'],{}).get('status')=='outside_image' else 'registration_failed'
                flags=[location_flag] if not u.get('located') else ['rgb_alignment_failed'] if not shift.get('valid') else []
                values={key:shift.get(value) for key,value in [('rgb_shift_px','magnitude_px'),('rgb_shift_x_px','dx_px'),('rgb_shift_y_px','dy_px')]}
                if metric in PAIRED_SHIFT_METRICS:values[metric]=shift.get('magnitude_px')
                values['rgb_registration_correlation']=shift.get('correlation');values['rgb_registration_rms']=shift.get('normalized_rms')
                x,y=u['position']
                rows.append(Measurement(u['unit_id']+'-combined-summary',u['unit_id']+' · RGB 位移','usaf_summary',ch,(x,y),(int(x)-2,int(y)-2,4,4),values,
                                        {key:'px' if key.endswith('_px') else 'ratio' for key in values},{},flags,float(shift.get('correlation',0)),'phase-correlation/ECC-translation; independent RGB validity',None))
    elif metric in MULTI_METRICS:
        rows=[m for m in result.measurements if m.kind=="usaf_summary" and m.direction_deg==target]
        rows.extend(m for m in result.measurements if m.kind not in {'usaf','usaf_summary'} and metric in m.values)
    else:
        rows=[m for m in result.measurements if m.kind!="usaf_summary" and
              (metric in m.values or m.kind in RAW_METRIC_KINDS.get(metric,set()))]
        if target is not None:rows=[m for m in rows if m.direction_deg==target]
        indices=result.optical_summary.get("frequency_indices",[])
        selected=frequency_index if frequency_index in indices else (22 if 22 in indices else indices[len(indices)//2] if indices else None)
        roi_indices={r["id"]:r.get("params",{}).get("frequency_index") for r in result.template.get("regions",[])}
        rows=[m for m in rows if m.kind!='usaf' or roi_indices.get(m.region_id)==selected]
    filtered.measurements=rows
    filtered.settings=dict(result.settings,report_usaf_direction=direction,report_frequency_index=frequency_index)
    return filtered
