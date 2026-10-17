import copy
import json
import math
import pytest
from mutex_imatest.models import AnalysisResult, ImageMetadata, Measurement
from mutex_imatest.analysis_catalog import METRIC_LABELS
from mutex_imatest.evaluation_catalog import REFERENCES, reference_text
from mutex_imatest.evaluation import (assess_channel,assess_measurement,evaluate_result,
    validate_limits,metric_value,effective_reference,evaluate_focus)


def sample(value,key='rgb_shift_x_px',channel='R',**kwargs):
    return Measurement(str(value),str(value),'edge',channel,(50,50),(20,20,60,60),{key:value},
                       {key:'cy/px' if key.startswith('mtf') else 'px'},**kwargs)


def result(rows,**settings):
    return AnalysisResult(ImageMetadata('reference-fixture.tif',200,1000,3,'uint16',16,0,'fixture',is_linear=True),
                          'fixture','fixture',rows,{'transfer':'linear',**settings},
                          {'id':'fixture','name':'fixture','calibrated':True,'physical_size_mm':[20,100],
                           'regions':[{'id':'edge','kind':'edge','box':[0,0,1,1]}]},focus_unit='mm')


def test_every_measurement_has_substantive_reference_and_criteria():
    assert set(REFERENCES)==set(METRIC_LABELS)
    for key,spec in REFERENCES.items():
        assert len(spec.reference)>=5
        assert all(len(getattr(spec,field))>=10 for field in ['criteria','prerequisites','action'])
        assert '参考值' in reference_text(key) and '适用条件' in reference_text(key)
        if spec.bands:assert 'MUTEX' in spec.criteria
    assert '0.5 cy/px' in REFERENCES['mtf50'].reference
    assert '合格' in REFERENCES['ctf50'].reference
    assert not REFERENCES['mtf50'].bands and not REFERENCES['mtf_nyquist'].bands
    assert not REFERENCES['veiling_glare_pct'].bands
    assert REFERENCES['delta_e_76'].bands is None


def test_worst_point_is_not_hidden_by_mean_and_signed_components_preserved():
    rows=[sample(.01),sample(-.1),sample(-2.)];r=result(rows)
    assessment=assess_channel(r,'rgb_shift_x_px',rows)
    assert assessment['status']=='poor' and assessment['worst']==-2
    assert assessment['median']==-.1 and assessment['counts']=={'good':2,'poor':1}
    assert assessment['point_assessments'][-1]['value']==-2
    assert 'MUTEX' in assessment['point_assessments'][-1]['text']


@pytest.mark.parametrize('value,status',[(.25,'good'),(.25001,'watch'),(.75,'watch'),(.75001,'poor'),(-.75,'watch')])
def test_engineering_band_boundaries_are_explicit_and_absolute(value,status):
    m=sample(value);assert assess_measurement(result([m]),m,'rgb_shift_x_px')['status']==status


def test_quality_gates_override_numerical_pass_and_invalid_points_remain_in_coverage():
    rows=[sample(.2,'mtf50'),sample(.2,'mtf50',flags=['clipped']),sample(.2,'mtf50',confidence=.01)]
    r=result(rows,evaluation_limits={'mtf50':{'min':.1,'unit':'cy/px'}})
    a=assess_channel(r,'mtf50',rows)
    assert a['status']=='limited' and a['counts']=={'pass':1,'unavailable':2}
    assert a['valid']==1 and a['total']==3 and a['coverage_pct']==pytest.approx(100/3)
    r.image.is_linear=False;r.settings['transfer']='unknown'
    a=assess_measurement(r,rows[0],'mtf50')
    assert a['status']=='limited' and a['numeric_status']=='pass'
    assert '输入曲线未知' in ' '.join(a['limitations'])
    r.settings['evaluation_limits']['mtf50']['min']=.3
    assert assess_measurement(r,rows[0],'mtf50')['status']=='limited'
    assert assess_measurement(r,rows[0],'mtf50')['numeric_status']=='fail'
    r.image.is_linear=True;r.settings['transfer']='linear';rows[0].flags=['clipping_advisory']
    assert assess_measurement(r,rows[0],'mtf50')['status']=='limited'


def test_targets_use_each_local_scale_and_are_invariant_to_display_unit():
    rows=[sample(.2,'mtf50',object_scale_px_per_mm=100),sample(.2,'mtf50',object_scale_px_per_mm=200)]
    r=result(rows,evaluation_limits={'mtf50':{'min':1500.,'unit':'DPI'}})
    before=json.dumps(r.to_dict(),sort_keys=True)
    a=assess_channel(r,'mtf50',rows,'cy/px');b=assess_channel(r,'mtf50',rows,'DPI')
    assert a['counts']==b['counts']=={'fail':1,'pass':1}
    assert b['point_assessments'][0]['value']==pytest.approx(1016)
    assert b['point_assessments'][1]['value']==pytest.approx(2032)
    assert b['worst']==pytest.approx(1016)
    assert json.dumps(r.to_dict(),sort_keys=True)==before
    r.template['calibrated']=False
    assert assess_measurement(r,rows[0],'mtf50','cy/px')['status']=='limited'
    assert metric_value(r,rows[0],'mtf50','DPI') is None


@pytest.mark.parametrize('bound,goal,status',[(1,{'min':16},'limited'),(1,{'min':12},'limited'),(1,{'max':10},'fail'),(0,{'min':12},'pass')])
def test_dynamic_range_lower_bounds_cannot_be_assigned_exact_acceptance(bound,goal,status):
    key='dynamic_range_snr10_stops';m=sample(14,key);m.kind='tone_summary'
    m.values['dynamic_range_snr10_lower_bound']=bound
    r=result([m],evaluation_limits={key:{**goal,'unit':'native'}})
    a=assess_measurement(r,m,key)
    assert a['status']==status
    if bound:assert '下界' in ' '.join(a['limitations'])


def test_target_limited_resolution_does_not_fail_an_untested_minimum():
    m=sample(.3,'resolution_limit',flags=['target_limited']);m.kind='star'
    r=result([m],evaluation_limits={'resolution_limit':{'min':.4,'unit':'cy/px'}})
    assert assess_measurement(r,m,'resolution_limit')['status']=='limited'
    # The unrelated sampling-density diagnostic is not itself target-limited.
    m.values['sampling_dpi_x']=3200
    a=assess_measurement(r,m,'sampling_dpi_x')
    assert a['status']=='needs_target' and not a['limitations']


def test_relative_reference_is_not_shared_across_pattern_or_direction_or_channel():
    rows=[sample(.1,'mtf50'),sample(.2,'mtf50')]
    rows.append(sample(.4,'mtf50'));rows[-1].kind='star'
    r=result(rows);a=assess_channel(r,'mtf50',rows)
    assert a['point_assessments'][0]['relative_to_best']==.5
    assert a['point_assessments'][1]['relative_to_best']==1
    assert 'relative_to_best' not in a['point_assessments'][2]
    assert a['status']=='informational'
    rows[1].direction_deg=90
    assert 'relative_to_best' not in assess_channel(r,'mtf50',rows)['point_assessments'][0]
    assert assess_measurement(r,sample(.8,'mtf_nyquist'),'mtf_nyquist')['status']=='needs_target'


def test_frequencies_above_nyquist_get_sampling_warning_not_automatic_excellence():
    m=sample(.6,'mtf10');r=result([m],evaluation_limits={'mtf10':{'min':.3,'unit':'cy/px'}})
    a=assess_measurement(r,m,'mtf10')
    assert a['status']=='limited' and '0.5 cy/px' in ' '.join(a['limitations'])


def test_engineering_grades_can_be_disabled_and_user_targets_take_precedence():
    m=sample(1.5);r=result([m],evaluation_engineering=False)
    assert assess_measurement(r,m,'rgb_shift_x_px')['status']=='needs_target'
    r.settings['evaluation_limits']={'rgb_shift_x_px':{'max':2,'absolute':True,'unit':'native'}}
    assert assess_measurement(r,m,'rgb_shift_x_px')['status']=='pass'
    assert 'px' in effective_reference(r,'rgb_shift_x_px')['reference']
    r.settings['evaluation_engineering']=True
    assert assess_measurement(r,m,'rgb_shift_x_px')['status']=='pass'


def test_signed_displacement_and_distortion_goals_default_to_magnitude():
    for key in ['rgb_shift_x_px','radial_distortion_max_pct']:
        m=sample(-3,key);r=result([m],evaluation_limits={key:{'max':.5,'unit':'native'}})
        assert assess_measurement(r,m,key)['status']=='fail'
        assert '绝对值' in effective_reference(r,key)['reference']
        r.settings['evaluation_limits'][key]['absolute']=False
        assert assess_measurement(r,m,key)['status']=='pass'


@pytest.mark.parametrize('limits',[
    {'mtf50':{'min':.1}}, {'not-a-metric':{'min':0}}, {'mean':{}},
    {'mean':{'min':2,'max':1}}, {'mean':{'min':math.nan}}, {'mean':{'min':True}},
    {'mean':{'max':1,'unit':'mm'}}, {'mtf50':{'min':.1,'unit':'PPI'}},
    {'mtf50':{'min':.1,'unit':'cy/px','command':'execute'}},
])
def test_invalid_or_ambiguous_targets_are_rejected(limits):
    with pytest.raises(ValueError):validate_limits(limits)


def test_old_results_can_be_evaluated_without_remeasurement_or_mutation(tmp_path):
    from mutex_imatest.evaluation import save_evaluation
    m=sample(.2,'mtf50');r=result([m]);old=r.to_dict();old.pop('evaluation_summary')
    loaded=AnalysisResult.from_dict(old);before=copy.deepcopy(loaded.to_dict())
    all_results=evaluate_result(loaded)
    assert len(all_results['items'])==64
    assert all_results['version'] and all(item['reference']['criteria'] for item in all_results['items'])
    assert not next(item for item in all_results['items'] if item['metric']=='best_focus')['channels']
    save_evaluation(loaded,tmp_path,['mtf50','rgb_shift_px'])
    assert loaded.to_dict()==before
    assert (tmp_path/'evaluation-results.json').is_file() and 'reference' in (tmp_path/'evaluation-results.csv').read_text(encoding='utf-8-sig')


def test_old_native_frequency_records_keep_summary_when_changing_display_units():
    from mutex_imatest.analysis_plan import summarize_selected
    m=sample(.2,'mtf50',object_scale_px_per_mm=100);r=result([m],analysis_metrics=['mtf50'])
    for unit,expected in [('LW/PH',400),('LP/PH',200),('DPI',1016),('lp/mm',20)]:
        ch=summarize_selected(r,unit=unit)['items'][0]['channels'][0]
        assert ch['valid']==1 and ch['mean']==pytest.approx(expected)
        assert ch['evaluation']['median']==pytest.approx(expected)


@pytest.mark.parametrize('key',['resolution_limit','ctf50'])
@pytest.mark.parametrize('direction,angle',[('both',None),('vertical',0),('horizontal',90)])
def test_failed_whole_card_units_remain_in_frequency_coverage(key,direction,angle):
    from mutex_imatest.analysis_plan import summarize_selected
    rows=[sample(.2,key,channel='G'),sample(.3,key,channel='G'),
          Measurement('missing','missing','usaf_summary','G',(150,50),(120,20,60,60),
                      flags=['registration_failed'])]
    for index,m in enumerate(rows):
        m.kind='usaf_summary';m.region_id=str(index);m.direction_deg=angle
    rows.append(Measurement('raw','raw','usaf','G',(50,50),(20,20,60,60),
                            {'contrast_at_frequency':.8},direction_deg=angle))
    r=result(rows,analysis_metrics=[key],report_usaf_direction=direction)
    r.optical_summary={'units':[],'frequency_indices':[1]}
    before=copy.deepcopy(r.to_dict())
    evaluated=evaluate_result(r,[key])['items'][0]['channels'][0]
    selected=summarize_selected(r)['items'][0]['channels'][0]
    for assessment in [evaluated,selected['evaluation']]:
        assert assessment['valid']==2 and assessment['total']==3
        assert assessment['coverage_pct']==pytest.approx(200/3)
        assert assessment['counts']['unavailable']==1
    assert selected['valid']==2 and selected['total']==3
    assert r.to_dict()==before


def test_counts_and_signed_illumination_do_not_claim_unverified_quality():
    m=sample(0,'hot_pixel_count');r=result([m]);assert assess_measurement(r,m,'hot_pixel_count')['status']=='informational'
    m.values['hot_pixel_count']=2
    assert assess_measurement(r,m,'hot_pixel_count')['status']=='watch'
    m.values['corner_illumination_pct']=130
    assert assess_measurement(r,m,'corner_illumination_pct')['status']=='poor'
    assert assess_measurement(r,sample(-.6,'corner_falloff_ev'),'corner_falloff_ev')['status']=='poor'


def test_focus_peak_coverage_and_uncertainty_do_not_invent_axial_acceptance():
    def peak(id,ch,z,conf=1,flags=None):return {'region_id':id,'channel':ch,'position':[0,0],'peak':z,'uncertainty':.2,'confidence':conf,'flags':flags or []}
    data={'channel':'ALL','unit':'mm','peaks':[peak('a','G',0),peak('b','G',None,0,['peak_not_bracketed']),peak('a','R',.1)],
          'rgb_focus_offsets':{'R-G':{'regions':[{'region_id':'a','offset':.1,'uncertainty':.2}]}},'recommended_position':0}
    a=evaluate_focus(data,{'evaluation_limits':{'focus_offset':{'min':-.2,'max':.2,'unit':'mm'}}})
    assert a['channel_spans']['G']['valid']==1 and a['channel_spans']['G']['total']==2
    best=next(i for i in a['items'] if i['metric']=='best_focus')
    assert next(c for c in best['channels'] if c['channel']=='G')['status']=='limited'
    offset=next(i for i in a['items'] if i['metric']=='focus_offset')['channels'][0]
    assert offset['status']=='limited' and any('不确定度' in s for s in offset['limitations'])


def test_focus_unit_conversion_and_unconvertible_index_targets():
    m=sample(.1,'focus_offset',diagnostics={'uncertainty':.001})
    r=result([m],evaluation_limits={'focus_offset':{'max':200,'unit':'um','absolute':True}})
    a=assess_measurement(r,m,'focus_offset')
    assert a['status']=='pass' and '100 um' in a['text']
    r.focus_unit='index'
    assert assess_measurement(r,m,'focus_offset')['status']=='limited'


def test_regions_invalid_at_every_focus_are_kept_in_peak_coverage():
    from mutex_imatest.focus import analyze_focus
    frames=[]
    for z in [-2,-1,0,1,2]:
        good=sample(1-.1*z*z,'mtf50',channel='G');good.region_id='good'
        bad=Measurement('bad','bad','edge','G',(150,50),(120,20,60,60),flags=['clipped'])
        r=result([good,bad]);r.focus_position=z;frames.append(r)
    f=analyze_focus(frames)
    assert len(f.peaks)==2
    failed=next(p for p in f.peaks if p.region_id=='bad')
    assert failed.peak is None and failed.confidence==0 and failed.flags
    ch=f.evaluation_summary['items'][0]['channels'][0]
    assert ch['valid']==1 and ch['total']==2 and ch['coverage_pct']==50
