"""Presentation changes must retain measurements, identifiers and user text."""
import json
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QLabel,QComboBox,QPushButton,
    QLineEdit,QListWidget,QTableWidget,QTableWidgetItem,QDialog)
from mutex_imatest.ui.preferences import UiPreferences,load_preferences,save_preferences
from mutex_imatest.ui.i18n import install_ui,resolve_language,tr,metric_description
from mutex_imatest.ui.i18n_catalog import METRICS_EN
from mutex_imatest.analysis_catalog import METRIC_LABELS,METRIC_DESCRIPTIONS


@pytest.mark.parametrize('locale,expected',[('zh_CN','zh_CN'),('zh_TW','zh_CN'),('en_US','en'),('fr_FR','en')])
def test_follow_system_language_with_explicit_overrides(locale,expected):
    assert resolve_language('system',locale)==expected
    assert resolve_language('zh_CN',locale)=='zh_CN'
    assert resolve_language('en',locale)=='en'


def test_display_preferences_are_separate_and_validated(tmp_path):
    path=tmp_path/'standalone-ui-preferences.json'
    assert load_preferences(path)==UiPreferences()
    settings=UiPreferences('en','dark');save_preferences(settings,path)
    assert load_preferences(path)==settings
    assert set(json.loads(path.read_text()))=={'language','theme'}
    path.write_text('{"language":"invalid"}',encoding='utf-8')
    assert load_preferences(path)==UiPreferences()
    with pytest.raises(ValueError):save_preferences(UiPreferences('en','invalid'),path)


def test_all_selectable_metrics_have_english_names_and_help():
    assert set(METRICS_EN)==set(METRIC_LABELS)
    for key in METRIC_LABELS:
        assert tr(METRIC_LABELS[key],'en')==METRICS_EN[key][0]
        assert tr(METRIC_DESCRIPTIONS[key],'en')==METRICS_EN[key][1]
        assert metric_description(key,'en')
        assert not any('\u3400'<=c<='\u9fff' for c in METRICS_EN[key][0]+METRICS_EN[key][1])


def test_english_assessment_reference_covers_all_metrics_and_exact_user_goals():
    from mutex_imatest.ui.evaluation_dialog import english_reference_html,english_reference_summary
    from mutex_imatest.evaluation_catalog import reference_for
    for key in METRICS_EN:
        rendered=english_reference_html(key)
        assert 'Assessment criteria' in rendered and not any('\u3400'<=c<='\u9fff' for c in rendered)
    ref=reference_for('mtf50');ref.update(goal={'min':.123456,'unit':'DPI'},goal_unit='DPI')
    assert '≥ 0.123456 DPI' in english_reference_summary('mtf50',ref)


def test_translation_preserves_numeric_data_units_html_and_paths():
    text='<p>已分析 · 19/51 有效</p><a href="https://example.com/path">参考值</a>'
    translated=tr(text,'en')
    assert '19/51' in translated and 'href="https://example.com/path"' in translated
    assert 'Analyzed' in translated and 'Reference' in translated
    path=r'D:\源图像\图像队列 (3).tif'
    assert tr('报告文件名：'+path,'en').endswith(path)


def test_runtime_switch_preserves_identifiers_user_inputs_and_selection(qapp,qtbot):
    window=QWidget();window.persist_preferences=False;qtbot.addWidget(window)
    layout=QVBoxLayout(window)
    title=QLabel('图像队列');layout.addWidget(title)
    combo=QComboBox();combo.addItem('扫描仪','scanner');combo.addItem('相机翻拍','camera');combo.setCurrentIndex(1);layout.addWidget(combo)
    edit=QLineEdit('图像队列');edit.setPlaceholderText('图卡名称');layout.addWidget(edit)
    updates=[];combo.currentIndexChanged.connect(updates.append)
    preferences=UiPreferences('zh_CN','light');controller=install_ui(qapp,window,preferences)
    controller.set_language('en')
    assert preferences.language=='en' and controller.preferences is preferences
    assert title.text()=='Image queue' and combo.currentText()=='Camera capture'
    assert combo.currentData()=='camera' and combo.currentIndex()==1 and not updates
    assert edit.text()=='图像队列' and edit.placeholderText()=='Chart name'
    title.setText('任务完成');controller.refresh();qapp.processEvents()
    assert title.text()=='Task complete'
    controller.set_language('zh_CN')
    assert title.text()=='任务完成' and combo.currentText()=='相机翻拍'


def test_chart_names_and_file_queue_first_line_are_never_translated(qapp,qtbot):
    from mutex_imatest.ui.template_widgets import TemplateComboBox
    from types import SimpleNamespace
    window=QWidget();window.persist_preferences=False;qtbot.addWidget(window)
    window.charts=[SimpleNamespace(name='星图')];window.entries=[{'path':r'D:\图像队列 (3).tif'}]
    layout=QVBoxLayout(window)
    chart=TemplateComboBox();chart.addItem('星图','user-star');layout.addWidget(chart)
    files=QListWidget();files.addItem('图像队列 (3).tif\n已分析 · 19/51 有效');layout.addWidget(files)
    info=QLabel('图卡名称：星图');layout.addWidget(info)
    controller=install_ui(qapp,window,UiPreferences('en','light'))
    assert chart.currentText()=='星图'
    assert files.item(0).text()=='图像队列 (3).tif\nAnalyzed · 19/51 Valid'
    assert info.text()=='Chart name：星图'
    controller.set_language('zh_CN')
    assert files.item(0).text()=='图像队列 (3).tif\n已分析 · 19/51 有效'


def test_readonly_table_translates_status_without_changing_values(qapp,qtbot):
    window=QWidget();window.persist_preferences=False;qtbot.addWidget(window)
    layout=QVBoxLayout(window);table=QTableWidget(1,3);layout.addWidget(table)
    table.setEditTriggers(table.EditTrigger.NoEditTriggers)
    table.setHorizontalHeaderLabels(['区域','指标','状态'])
    for i,value in enumerate(['星图自定义','0.12345 cy/px','质量校验未通过']):table.setItem(0,i,QTableWidgetItem(value))
    controller=install_ui(qapp,window,UiPreferences('en','light'))
    assert table.item(0,0).text()=='星图自定义'
    assert table.item(0,1).text()=='0.12345 cy/px'
    assert table.item(0,2).text()=='Quality checks failed'
    table.item(0,2).setText('信号剪切');controller.refresh();qapp.processEvents()
    assert table.item(0,2).text()=='Signal clipping'
    controller.set_language('zh_CN')
    assert table.item(0,2).text()=='信号剪切'


def test_theme_switch_palette_and_painted_list_contrast(qapp,qtbot):
    from mutex_imatest.ui.metric_checklist import MetricChecklist
    from mutex_imatest.ui.style import chrome_colors
    window=QWidget();window.persist_preferences=False;qtbot.addWidget(window)
    layout=QVBoxLayout(window);metrics=MetricChecklist();metrics.addItem('MTF50','mtf50');metrics.addItem('MTF20','mtf20');metrics.model().item(1).setEnabled(False);layout.addWidget(metrics)
    controller=install_ui(qapp,window,UiPreferences('en','dark'))
    assert window.palette().color(QPalette.ColorRole.Window).lightness()<40
    assert window.palette().color(QPalette.ColorRole.Text).lightness()>190
    colors=chrome_colors();assert colors['enabled']!=colors['disabled']
    assert colors['base']!=colors['disabled_base']
    window.show();qapp.processEvents();assert not metrics.grab().isNull()
    controller.set_theme('light')
    assert window.palette().color(QPalette.ColorRole.Window).name()=='#f4f6fa'
    assert window.palette().color(QPalette.ColorRole.Text).name()=='#20394a'


def test_new_dialog_and_dynamic_help_follow_active_language(qapp,qtbot):
    window=QWidget();window.persist_preferences=False;qtbot.addWidget(window)
    controller=install_ui(qapp,window,UiPreferences('en','dark'))
    dialog=QDialog(window);qtbot.addWidget(dialog);dialog.setWindowTitle('导出报告')
    layout=QVBoxLayout(dialog);title=QLabel('报告文件名');layout.addWidget(title)
    combo=QComboBox();combo.addItem('扫描仪','scanner');combo.addItem('相机翻拍','camera');layout.addWidget(combo)
    combo.currentIndexChanged.connect(lambda _:title.setText('信号剪切'))
    dialog.show();qapp.processEvents()
    assert dialog.windowTitle()=='Export report' and title.text()=='Report filename'
    assert dialog.palette().color(QPalette.ColorRole.Base).lightness()<60
    combo.setCurrentIndex(1);qapp.processEvents()
    assert title.text()=='Signal clipping' and combo.currentData()=='camera'
    controller.set_language('zh_CN');assert title.text()=='信号剪切'


def test_refresh_requests_are_coalesced(qapp,qtbot,monkeypatch):
    window=QWidget();window.persist_preferences=False;qtbot.addWidget(window)
    controller=install_ui(qapp,window,UiPreferences('en','light'))
    calls=[];original=controller.translate_tree
    def observe(*args,**kwargs):calls.append(True);return original(*args,**kwargs)
    monkeypatch.setattr(controller,'translate_tree',observe)
    for _ in range(40):controller.refresh()
    qapp.processEvents();assert len(calls)==1
