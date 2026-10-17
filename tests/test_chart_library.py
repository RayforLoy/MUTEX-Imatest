import copy,hashlib,json
from pathlib import Path
import numpy as np
from mutex_imatest.models import ChartDefinition,Region,AnalysisResult,ImageMetadata,Measurement
from mutex_imatest.chart_library import consolidate,recognizes
from mutex_imatest import templates
from mutex_imatest.templates import save_chart,available_charts
from mutex_imatest.resolution import view_result
from mutex_imatest.heatmap import heatmap_data


def variants(tmp_path):
    source=tmp_path/'card.svg';source.write_text('<svg/>',encoding='utf-8')
    r=Region('u-v','usaf',(.1,.1,.1,.1),'V',{'unit_id':'u','group':3,'element':5,'direction':'vertical'})
    a=ChartDefinition('single','card',[r],(210,297),calibrated=True,source_path=str(source))
    h=copy.deepcopy(r);h.id='u-h';h.params['direction']='horizontal';h.box=(.3,.1,.1,.1)
    b=ChartDefinition('both','card',[copy.deepcopy(r),h],(210,297),calibrated=True,source_path=str(source))
    c=copy.deepcopy(b);c.id='whole';c.name='card · 整卡多频率'
    for row in c.regions:row.id+='-g3e5';row.params.update(multi_frequency=True,frequency_index=22,profile_band=[.2,.8])
    fine=copy.deepcopy(c.regions[0]);fine.id='u-v-g3e6';fine.box=(.1,.3,.08,.08);fine.params.update(element=6,frequency_index=23);c.regions.append(fine)
    b.regions.append(Region('extra-edge','edge',(.7,.7,.1,.1),'手工斜边'))
    return a,b,c


def test_merge_keeps_full_frequency_manual_rois_calibration_and_aliases(tmp_path):
    charts=variants(tmp_path);merged=consolidate(charts)
    assert len(merged)==1
    c=merged[0];assert c.id=='whole' and c.name=='card' and c.calibrated
    assert len(c.regions)==4 and {r.kind for r in c.regions}=={'edge','usaf'}
    assert {r.params.get('frequency_index') for r in c.regions if r.kind=='usaf'}=={22,23}
    assert recognizes(c,'single') and recognizes(c,'both')
    assert len(charts[0].regions)==1 and charts[2].name.endswith('整卡多频率')


def test_library_consolidation_is_backed_up_idempotent_and_leaves_source(tmp_path):
    charts=variants(tmp_path);root=templates.library_dir();original={}
    for c in charts:
        path=root/(c.id+'.json');save_chart(c,path);original[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    source=Path(charts[0].source_path).read_bytes()
    result=available_charts();assert len(result)==2+len(templates.public_charts()) and result[1].id=='whole'
    assert [p.name for p in root.glob('*.json')]==['whole.json']
    manifests=list((root/'backups').glob('*/manifest.json'));assert len(manifests)==1
    for name,digest in original.items():assert hashlib.sha256((manifests[0].parent/name).read_bytes()).hexdigest()==digest
    assert Path(charts[0].source_path).read_bytes()==source
    assert len(available_charts())==2+len(templates.public_charts()) and len(list((root/'backups').glob('*/manifest.json')))==1


def test_different_calibrations_pages_and_deliberate_names_are_not_merged(tmp_path):
    a,b,c=variants(tmp_path);b.physical_size_mm=(100,100);c.source_page=1
    assert len(consolidate([a,b,c]))==3
    b=copy.deepcopy(a);b.id='custom';b.name='Independent calibration experiment'
    assert len(consolidate([a,b]))==2


def shift_result():
    regions=[Region('x','usaf',(.1,.1,.1,.1),params={'multi_frequency':True,'unit_id':'u','group':0,'element':1})]
    chart=ChartDefinition('whole','whole',regions)
    rows=[Measurement('u-combined-summary','u','usaf_summary',ch,(25,25),(23,23,4,4),{},flags=['invalid_ctf_reference']) for ch in ['R','G','B']]
    units=[]
    for i,pt in enumerate([(25,25),(75,25),(50,75)]):
        units.append({'unit_id':'u' if i==0 else 'u'+str(i),'position':pt,'located':i<2,
                      'rgb_shifts':{'R':{'dx_px':3.,'dy_px':4.,'magnitude_px':5.,'correlation':.99,'valid':True},
                                    'G':{'dx_px':0.,'dy_px':0.,'magnitude_px':0.,'correlation':1.,'valid':True},
                                    'B':{'dx_px':-2.,'dy_px':0.,'magnitude_px':2.,'correlation':.99,'valid':True}}})
    return AnalysisResult(ImageMetadata('missing',100,100,3,'uint8',8,1,'hash'),'whole','whole',rows,{},chart.to_dict(),optical_summary={'units':units})


def test_fixed_rgb_pairs_use_independent_shift_quality_and_do_not_mutate_result():
    from mutex_imatest.reports import _report_unit
    result=shift_result();before=result.to_dict()
    for metric,ch,value in [('ca_r_g_px','R',5.),('ca_b_g_px','B',2.)]:
        view=view_result(result,metric)
        assert len(view.measurements)==3 and {m.channel for m in view.measurements}=={ch}
        assert sum(m.valid for m in view.measurements)==2
        data=heatmap_data(result,metric,'G',width=50,height=50)
        assert data['values'].tolist()==[value,value]
        assert data['unit']==_report_unit(result,metric,'cy/px')=='px'
    assert result.to_dict()==before


def test_capabilities_require_supported_patterns_and_rgb_input(tmp_path):
    from mutex_imatest.capabilities import metric_availability
    a,b,c=variants(tmp_path)
    single,full=metric_availability(a,configured_channels='RGBY')
    assert not full and single['ca_r_g_px'] and 'mtf50' not in single
    assert single['contrast_at_frequency']=='' and single['best_focus']
    available,full=metric_availability(c,configured_channels='G')
    assert full and available['ca_r_g_px']==available['ca_b_g_px']==''
    assert available['alignment_gain_pct']
    result=shift_result();result.image.channels=1
    available,_=metric_availability(c,result)
    assert all(available[key] for key in ['ca_r_g_px','ca_b_g_px','rgb_shift_px'])
    step=ChartDefinition('step','step',[Region('step','step',(.1,.1,.2,.2))])
    available,_=metric_availability(step)
    assert available['mean']=='' and 'spatial_snr_db' not in available


def test_failed_mixed_pattern_measurements_keep_quality_flags_in_view():
    result=shift_result()
    failed=Measurement('flat','flat','flat','G',(20,20),(10,10,20,20),flags=['registration_failed'])
    result.measurements.append(failed)
    view=view_result(result,'mean')
    assert view.measurements==[failed] and not view.measurements[0].valid


def test_old_result_template_does_not_reintroduce_retired_library_entries(qtbot,tmp_path):
    from mutex_imatest.ui.main_window import MainWindow
    a,b,c=variants(tmp_path)
    for chart in [a,b,c]:save_chart(chart,templates.library_dir()/(chart.id+'.json'))
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.config.cache_dir=str(tmp_path/'cache')
    result=AnalysisResult(ImageMetadata('missing-file.tif',100,100,3,'uint8',8,1,'hash'),a.id,a.name,[],{},a.to_dict())
    window.add_result(result)
    assert window.chart_combo.count()==2+len(templates.public_charts()) and window.current_chart().id=='whole'
    assert window.config.chart_id=='whole' and result.chart_id=='single' and result.template['id']=='single'
    window.close()
