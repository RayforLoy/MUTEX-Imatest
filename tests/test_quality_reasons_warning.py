"""Point diagnoses and completion warnings must preserve the optical evidence."""
import copy
import json
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from mutex_imatest.analysis_audit import REASONS, REASONS_EN, reason_codes, reason_text
from mutex_imatest.heatmap import heatmap_data
from mutex_imatest.models import AnalysisResult, ImageMetadata, Measurement, FATAL_FLAGS


def make_result(rows=(), **extra):
    return AnalysisResult(ImageMetadata('sample.tif',100,100,3,'uint16',16,100,'fixture'),
                          'fixture','fixture',list(rows),{'maximum_clip_fraction':.01},{},**extra)


def point(**extra):
    return Measurement('u-combined-summary','unit','edge','G',(50,50),(20,20,60,60),**extra)


def test_all_fatal_causes_have_readable_bilingual_explanations_and_are_retained():
    assert FATAL_FLAGS <= REASONS.keys() and FATAL_FLAGS <= REASONS_EN.keys()
    m=point(values={'mtf50':.25,'clipping_fraction':.125},flags=['clipped','invalid_edge','insufficient_samples'],confidence=.01)
    result=make_result([m]);before=copy.deepcopy(result.to_dict())
    assert reason_codes(result,m,'mtf50')==['clipped','invalid_edge','insufficient_samples','low_confidence']
    text=reason_text(result,m,'mtf50')
    assert all(term in text for term in ['信号剪切','斜边位置或角度','原像素样本不足','12.500%','1.000%'])
    data=heatmap_data(result,'mtf50',width=101,height=101)
    assert data['values'].size==0 and np.isnan(data['field'][50,50])
    assert data['regions'][0]['reason']==text and data['regions'][0]['value']==.25
    assert 'Signal clipping' in data['regions'][0]['reason_en']
    assert result.to_dict()==before


def test_ctf_missing_reason_uses_saved_crossing_evidence_instead_of_a_generic_failure():
    m=point(values={'ctf20':None})
    m.kind='usaf_summary'
    unit={'unit_id':'u','combined':{'G':{'selected_direction':'horizontal'}},
          'directions':{'horizontal':{'G':{'curve':{'crossing_status':{'ctf20':'ctf_noise_limited'}}}}}}
    result=make_result([m],optical_summary={'units':[unit]})
    assert reason_codes(result,m,'ctf20')==['ctf_noise_limited']
    assert reason_text(result,m,'ctf20')=='条纹信噪比不足'
    unit['directions']['horizontal']['G']['curve']['crossing_status']['ctf20']='above_highest_test_frequency'
    assert '图卡频率未覆盖交点' in reason_text(result,m,'ctf20')


def test_registration_details_physical_units_and_sampling_range_are_distinct():
    m=point(flags=['registration_failed'],confidence=0)
    result=make_result([m],registration={'unit_diagnostics':{'u':{'status':'insufficient_matches','visible_fiducials':6,'matches':5}}})
    text=reason_text(result,m,'mtf50')
    assert '定位特征不足' in text and '可见特征 6' in text and '匹配 5' in text
    m.flags=[];m.confidence=1;m.values={'mtf50':.25}
    assert reason_text(result,m,'mtf50','cy/px')==''
    assert reason_codes(result,m,'mtf50','DPI')==['missing_calibration']
    m.values={'mtf20':None};m.curves={'sfr':{'x':[0,.25,.5],'y':[1,.8,.3]}}
    assert reason_codes(result,m,'mtf20')==['above_sampling_frequency']


def test_contamination_is_an_advisory_and_never_hides_a_measured_value():
    m=point(values={'mtf50':.25},flags=['profile_contamination'])
    result=make_result([m]);data=heatmap_data(result,'mtf50',width=101,height=101)
    assert reason_codes(result,m,'mtf50')==[] and data['regions'][0]['usable']
    assert data['values'].tolist()==[.25]


def test_exported_html_and_png_keep_the_same_point_reason(tmp_path):
    from mutex_imatest.reports import export_overlay, export_html
    bad=point(values={'mtf50':.25},flags=['aliasing','target_mismatch'])
    bad.label='<script>chart</script>'
    result=make_result([bad]);preview=tmp_path/'preview.png';Image.new('RGB',(101,101),'white').save(preview)
    data=export_overlay(result,preview,tmp_path/'overlay.png')
    metadata=json.loads(Image.open(tmp_path/'overlay.png').info['MUTEX missing measurements'])
    assert metadata[0]['reason']==data['regions'][0]['reason']
    target=export_html(result,preview,tmp_path/'report.html')
    text=target.read_text(encoding='utf-8')
    assert '条纹混叠' in text and '实拍图案与模板定义不符' in text
    assert '<script>chart</script>' not in text and '&lt;script&gt;chart&lt;/script&gt;' in text


def test_sharpening_completion_warning_is_modeless_and_batch_deduplicated(qtbot):
    from mutex_imatest.ui.quality_warning import SharpeningWarningController
    edge=point(values={'mtf50':.25},flags=['sharpening_or_ringing'])
    result=make_result([edge]);controller=SharpeningWarningController(language='zh_CN')
    shown=[];controller.warning_shown.connect(shown.append)
    assert controller.jobs_idle() is None  # Opening old results does not warn.
    assert controller.register(result,'job-a','first.tif')
    assert not controller.register(result,'job-a','first.tif')
    assert controller.register(result,'job-b','second.tif')
    dialog=controller.jobs_idle();qtbot.addWidget(dialog)
    assert dialog.isVisible() and not dialog.isModal() and dialog.windowModality()==Qt.WindowModality.NonModal
    assert '检测到锐化，测量结果可能不可靠' in dialog.text()
    assert '不能证明图像的处理历史' in dialog.informativeText()
    assert '2 张图像' in dialog.informativeText() and len(shown)==1
    assert controller.jobs_idle() is None
    dialog.accept();qtbot.waitUntil(lambda:controller.dialog is None)
    assert controller.register(result,'job-c','first.tif')  # New analysis can warn again.
    second=controller.jobs_idle();qtbot.addWidget(second);assert len(shown)==2
    second.accept()


def test_failed_or_unsupported_evidence_and_cancelled_batches_do_not_warn(qtbot):
    from mutex_imatest.ui.quality_warning import SharpeningWarningController, sharpening_evidence
    edge=point(flags=['invalid_edge','sharpening_or_ringing'],confidence=0)
    result=make_result([edge]);controller=SharpeningWarningController(language='en')
    assert not sharpening_evidence(result)['supported']
    assert not controller.register(result,'failed-evidence') and controller.jobs_idle() is None
    edge.flags=['sharpening_or_ringing'];edge.confidence=1
    assert controller.register(result,'successful')
    controller.discard_pending();assert controller.jobs_idle() is None
    assert controller.register(result,'next-successful')
    dialog=controller.jobs_idle();qtbot.addWidget(dialog)
    assert 'measurement results may be unreliable' in dialog.text()
    assert 'not proof of processing history' in dialog.informativeText()
    dialog.accept()


def test_diagnostics_summary_halo_evidence_can_warn_without_sfr_peak_boost():
    from mutex_imatest.ui.quality_warning import sharpening_evidence
    result=make_result(diagnostics_summary={'sharpening':{'valid_halo_regions':10,'halo_regions_ge_2pct':4,'sfr_peak_boost_regions':0}})
    evidence=sharpening_evidence(result)
    assert evidence['detected'] and evidence['halo_regions']==4 and evidence['sfr_regions']==0


def test_clear_image_invalidates_tiles_and_viewer_can_load_again(qtbot,config,tmp_path):
    from mutex_imatest.ui.viewer import ImageViewer
    path=tmp_path/'image.png';Image.new('RGB',(100,100),'white').save(path)
    viewer=ImageViewer();qtbot.addWidget(viewer);viewer.show()
    metadata=make_result().image;metadata.path=str(path)
    try:
        viewer.load(path,metadata,config);previous=viewer.generation
        viewer.pending.add((0,0,0));viewer.clear_image()
        assert viewer.generation>previous and viewer.metadata is None and viewer.result is None
        assert not viewer.scene().items() and not viewer.pending and viewer.reader.isRunning()
        viewer.load(path,metadata,config)
        assert viewer.metadata is metadata and viewer.preview_item is not None
    finally:viewer.close_reader()


def test_open_notice_can_change_language_without_a_new_warning(qtbot):
    from PySide6.QtTest import QSignalSpy
    from mutex_imatest.ui.quality_warning import SharpeningWarningController
    language={'value':'zh_CN'}
    controller=SharpeningWarningController(language=lambda:language['value'])
    spy=QSignalSpy(controller.warning_shown)
    controller.register(make_result([point(values={'mtf50':.2},flags=['sharpening_or_ringing'])]),'new')
    dialog=controller.jobs_idle();qtbot.addWidget(dialog)
    assert '测量结果可能不可靠' in dialog.text()
    language['value']='en';controller.retranslate()
    assert 'may be unreliable' in dialog.text() and spy.count()==1
    language['value']='zh_CN';controller.retranslate()
    assert '测量结果可能不可靠' in dialog.text() and spy.count()==1
    dialog.accept()


def test_real_gui_analysis_warns_once_but_new_analysis_warns_again(qtbot,tmp_path):
    from PySide6.QtTest import QSignalSpy
    from scipy.special import erf
    from scipy.ndimage import gaussian_filter
    import tifffile
    from mutex_imatest.models import ChartDefinition,Region
    from mutex_imatest.ui.main_window import MainWindow
    y,x=np.mgrid[:192,:192]
    a=.25+.5*.5*(1+erf((x-96-.075*(y-96))/1.7))
    a=a+(a-gaussian_filter(a,2))
    pixels=np.repeat(np.round(a[...,None]*65535).astype(np.uint16),3,axis=2)
    path=tmp_path/'sharp-edge.tif';tifffile.imwrite(path,pixels,photometric='rgb',metadata=None)
    before=path.read_bytes()
    window=MainWindow();window.persist_preferences=False;qtbot.addWidget(window);window.show()
    chart=ChartDefinition('notice-fixture','notice fixture',[Region('edge','edge',(.1,.1,.8,.8))])
    window.charts=[chart];window.refresh_charts(chart.id);window.chart_changed()
    window.transfer.setCurrentIndex(window.transfer.findData('linear'))
    window.import_paths([str(path)])
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']) and window.worker.current is None,timeout=30000)
    window.metric_selector.set_checked_keys(['sharpening_halo_pct']);window.analysis_selection_changed()
    spy=QSignalSpy(window.sharpening_warning.warning_shown)
    window.analyze_selected()
    qtbot.waitUntil(lambda:spy.count()==1 and window.worker.current is None,timeout=90000)
    assert window.entries[0]['result'].diagnostics_summary['sharpening']['halo_regions_ge_2pct']>0
    dialog=window.sharpening_warning.dialog
    assert dialog.isVisible() and dialog.windowModality()==Qt.WindowModality.NonModal
    dialog.accept();window.display_entry(0);window.jobs_idle()
    assert spy.count()==1
    window.analyze_selected()
    qtbot.waitUntil(lambda:spy.count()==2 and window.worker.current is None,timeout=90000)
    assert path.read_bytes()==before
    window.close()
