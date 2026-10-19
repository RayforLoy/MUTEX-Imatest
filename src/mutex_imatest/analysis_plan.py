"""One shared measurement pass, with explicit per-request result summaries."""
from collections import Counter
import csv
import numpy as np
from .analysis_catalog import METRIC_LABELS,RGB_METRICS
from .capabilities import metric_availability
from .resolution import FREQUENCY_METRICS


def summarize_selected(result,metrics=None,unit=None):
    from .evaluation import effective_reference, assess_channel, selected_rows, metric_value
    metrics=result.settings.get('analysis_metrics') if metrics is None else metrics
    if metrics is None:return {}
    available,_=metric_availability(None,result)
    requested=list(dict.fromkeys(metrics));items=[]
    for key in requested:
        display_unit=(unit or result.settings.get('heatmap_unit','cy/px')) if key in FREQUENCY_METRICS else None
        reason=available.get(key,'当前模板不支持此分析')
        rows=selected_rows(result,key)
        channels=[]
        for ch in dict.fromkeys(m.channel for m in rows):
            selected=[m for m in rows if m.channel==ch]
            if not selected:continue
            values=[metric_value(result,m,key,display_unit) for m in selected if m.valid and m.confidence>.05 and metric_value(result,m,key,display_unit) is not None]
            units=display_unit or next((m.units.get(key) for m in selected if m.units.get(key)), 'px' if key in RGB_METRICS else '')
            channels.append({'channel':ch,'total':len(selected),'valid':len(values),'unit':units,
                             'mean':float(np.mean(values)) if values else None,'min':float(min(values)) if values else None,
                             'max':float(max(values)) if values else None,
                             'flags':dict(Counter(flag for m in selected for flag in m.flags))})
            from .analysis_audit import reason_for,reason_codes,reason_text,REASONS
            missing=Counter(reason_for(result,m,key,display_unit) if metric_value(result,m,key,display_unit) is None or not m.valid else 'low_confidence'
                            for m in selected if not (m.valid and m.confidence>.05 and metric_value(result,m,key,display_unit) is not None))
            channels[-1]['missing_reasons']=dict(missing)
            channels[-1]['missing_descriptions']={REASONS.get(k,k):v for k,v in missing.items()}
            channels[-1]['missing_points']=[{'region_id':m.region_id,'label':m.label,'position':list(m.position),
                                            'reason_codes':reason_codes(result,m,key,display_unit),
                                            'reason':reason_text(result,m,key,display_unit)}
                                           for m in selected if not (m.valid and m.confidence>.05 and metric_value(result,m,key,display_unit) is not None)]
            assessment=assess_channel(result,key,selected,display_unit)
            assessment.pop('point_assessments')
            channels[-1]['evaluation']=assessment
        valid=sum(c['valid'] for c in channels)
        items.append({'metric':key,'name':METRIC_LABELS[key],'status':'unsupported' if reason else 'complete' if valid else 'no_valid_data',
                      'reason':reason or ('' if valid else '未得到有效测点，请检查配准、图案和测量质量标志'),
                      'reference':effective_reference(result,key),'channels':channels})
    from .evaluation_catalog import REFERENCE_VERSION
    return {'requested_metrics':requested,'completed':sum(i['status']!='unsupported' for i in items),'items':items,'evaluation_version':REFERENCE_VERSION}


def save_summary(summary,folder):
    from .utils import atomic_json
    from pathlib import Path
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'analysis-results.json',summary)
    with (folder/'analysis-results.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file);writer.writerow(['metric','name','channel','valid','total','mean','min','max','unit','status','reason','flags',
                                               'evaluation','evaluation_text','median','p10','p90','worst','coverage_pct','reference','criteria','basis','rule_version','missing_reasons'])
        for item in summary.get('items',[]):
            for ch in item['channels'] or [{}]:
                evaluation=ch.get('evaluation',{});ref=item.get('reference',{})
                writer.writerow([item['metric'],item['name'],*[ch.get(k,'') for k in ['channel','valid','total','mean','min','max','unit']],item['status'],item['reason'],ch.get('flags',{}),
                                 evaluation.get('label','无法评价'),evaluation.get('text',item['reason']),*[evaluation.get(k) for k in ['median','p10','p90','worst','coverage_pct']],
                                 ref.get('reference',''),ref.get('criteria',''),ref.get('basis',''),ref.get('version',''),ch.get('missing_descriptions',{})])
