"""The halo view must select its own evidence when resolution is missing."""
from PIL import Image
from mutex_imatest.models import AnalysisResult,ChartDefinition,Measurement,Region


def test_halo_detail_and_profile_use_independent_halo_measurement(qtbot,tmp_path):
    from mutex_imatest.ui.main_window import MainWindow
    path=tmp_path/'fixture.png';Image.new('RGB',(100,100),'white').save(path)
    chart=ChartDefinition('halo','Halo',[Region('u-bars','usaf',(.2,.2,.6,.6),params={
        'unit_id':'u','multi_frequency':True,'frequency_index':22,'group':3,'element':5})])
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    window.charts=[chart];window.refresh_charts(chart.id);window.import_paths([str(path)])
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']) and window.worker.current is None,timeout=30000)
    raw=Measurement('u-combined-summary','u','usaf_summary','G',(50,50),(20,20,60,60),
                    {'resolution_limit':None},flags=['invalid_ctf_reference'])
    halo={'values':{'sharpening_halo_pct':3.25,'halo_overshoot_pct':3.25,'halo_undershoot_pct':1.1,
                    'halo_noise_floor_pct':.2,'halo_element_count':3},'flags':['sharpening_or_ringing'],
          'confidence':1,'curve':{'x':[-1,0,1],'y':[.2,.82,.8]}}
    unit={'unit_id':'u','position':(50,50),'located':True,'rgb_shifts':{},'sharpening':{'G':halo},
          'directions':{d:{'G':{'sharpening':halo}} for d in ['vertical','horizontal']}}
    summary={'units':[unit],'threshold':.2,'threshold_mode':'relative','statistics':{},'frequency_indices':[22]}
    result=AnalysisResult(window.entries[0]['metadata'],chart.id,chart.name,[raw],{},chart.to_dict(),
                          registration={'homography':[[100,0,0],[0,100,0],[0,0,1]]},optical_summary=summary)
    window.entries[0]['result']=result
    window.metric_selector.setCurrentIndex(window.metric_selector.findData('sharpening_halo_pct'))
    for direction in ['both','vertical','horizontal']:
        window.usaf_direction.setCurrentIndex(window.usaf_direction.findData(direction))
        selected=window.direction_result(result).measurements[0]
        window.select_region(selected.region_id)
        assert '3.25 %' in window.detail.toPlainText()
        assert '可检出亮侧光晕' in window.detail.toPlainText()
        assert '低频参考不足' not in window.detail.toPlainText()
        assert len(window.curve.listDataItems())==1
    assert raw.values=={'resolution_limit':None}
    window.close()
