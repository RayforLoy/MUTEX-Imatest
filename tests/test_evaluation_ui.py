import copy
from PySide6.QtCore import Qt
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.models import AnalysisResult,ImageMetadata,Measurement


def test_reference_dialog_preserves_separate_metric_goals_and_their_units(qtbot):
    from mutex_imatest.ui.evaluation_dialog import EvaluationDialog
    config=AnalysisConfig();dialog=EvaluationDialog(config,'mtf50');qtbot.addWidget(dialog)
    dialog.mode.setCurrentIndex(dialog.mode.findData('minimum'));dialog.lower.setValue(1200)
    dialog.unit.setCurrentIndex(dialog.unit.findData('DPI'));dialog.note.setText('客户翻拍要求')
    dialog.metric_selector.setCurrentIndex(dialog.metric_selector.findData('rgb_shift_x_px'))
    dialog.mode.setCurrentIndex(dialog.mode.findData('maximum'));dialog.upper.setValue(.4);dialog.absolute.setChecked(True)
    dialog.metric_selector.setCurrentIndex(dialog.metric_selector.findData('mtf50'))
    assert dialog.lower.value()==1200 and dialog.unit.currentData()=='DPI'
    dialog.accept()
    assert dialog.result()==dialog.DialogCode.Accepted
    assert dialog.limits['mtf50']['min']==1200 and dialog.limits['mtf50']['note']=='客户翻拍要求'
    assert dialog.limits['rgb_shift_x_px']['max']==.4 and dialog.limits['rgb_shift_x_px']['absolute']
    assert not config.evaluation_limits


def test_reference_dialog_exports_and_imports_exact_goals(qtbot,tmp_path,monkeypatch):
    from mutex_imatest.ui.evaluation_dialog import EvaluationDialog
    from PySide6.QtWidgets import QFileDialog
    config=AnalysisConfig(evaluation_limits={'ctf20':{'min':50.8,'unit':'DPI','note':'目标'}})
    path=tmp_path/'goals.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args:(str(path),''))
    dialog=EvaluationDialog(config,'ctf20');qtbot.addWidget(dialog);dialog.export_limits()
    other=EvaluationDialog(AnalysisConfig(),'ctf20');qtbot.addWidget(other)
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args:(str(path),''))
    other.import_limits()
    assert other.limits==dialog.limits and other.lower.value()==50.8
    other.reset_current();other.accept();assert not other.limits


def test_reference_tooltips_include_disabled_projects_and_result_evaluation_panel(qtbot):
    from mutex_imatest.ui.main_window import MainWindow
    from mutex_imatest.analysis_plan import summarize_selected
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    for i in range(window.metric_selector.count()):
        text=window.metric_selector.tooltip_text(i)
        assert '参考值' in text and '评价标准' in text and '适用条件' in text
    rows=[Measurement(str(i),str(i),'edge','R',(40,40),(10,10,60,60),{'ca_r_g_px':v},{'ca_r_g_px':'px'}) for i,v in enumerate([.1,2.])]
    result=AnalysisResult(ImageMetadata('fixture.tif',100,100,3,'uint16',16,0,'fixture',is_linear=True),'edge','edge',rows,
                          {'transfer':'linear','analysis_metrics':['ca_r_g_px']},
                          {'regions':[{'kind':'edge','id':'one','box':[0,0,1,1]}]})
    before=copy.deepcopy(result.to_dict());window.populate_analysis_results(result)
    assert window.batch_table.item(0,9).text()=='建议改善'
    assert window.batch_table.item(0,8).text()=='2'
    assert '理想 0 px' in window.batch_table.item(0,10).text()
    window.update_evaluation(result,'ca_r_g_px','R')
    assert '建议改善' in window.evaluation_badge.text()
    assert all(s in window.evaluation_detail.toPlainText() for s in ['参考值','评价标准','非行业合格线','有效 2/2','最差测点'])
    assert result.to_dict()==before
    window.close()


def test_evaluation_goals_round_trip_through_old_and_new_config():
    old=AnalysisConfig.from_dict({'channels':'RGB'}).validate()
    assert old.evaluation_engineering and old.evaluation_limits=={}
    old.evaluation_limits={'mtf50':{'min':.2,'unit':'cy/px'}}
    other=AnalysisConfig.from_dict(old.to_dict()).validate()
    assert other.evaluation_limits==old.evaluation_limits


def test_viewing_goals_does_not_round_or_clamp_imported_values(qtbot):
    from mutex_imatest.ui.evaluation_dialog import EvaluationDialog
    goals={'mean':{'max':1e-7,'unit':'native'},'spatial_snr_db':{'min':40.1234567891234,'unit':'native'},
           'sampling_dpi_x':{'max':10**20,'unit':'native'}}
    dialog=EvaluationDialog(AnalysisConfig(evaluation_limits=goals),'mean');qtbot.addWidget(dialog)
    for key in goals:dialog.metric_selector.setCurrentIndex(dialog.metric_selector.findData(key))
    dialog.accept()
    for key,goal in goals.items():
        for bound in ('min','max'):
            if bound in goal:assert dialog.limits[key][bound]==goal[bound]


def test_goal_dialog_renders_with_native_qt_paint_metrics(qtbot,tmp_path):
    from PySide6.QtGui import QPaintDevice
    from mutex_imatest.ui.evaluation_dialog import EvaluationDialog
    dialog=EvaluationDialog(AnalysisConfig(),'mtf50');qtbot.addWidget(dialog)
    assert callable(dialog.metric)
    assert dialog.metric(QPaintDevice.PaintDeviceMetric.PdmDpiX)>0
    dialog.show();qtbot.waitExposed(dialog)
    assert dialog.grab().save(str(tmp_path/'goals-dialog.png'))
    dialog.reject()
