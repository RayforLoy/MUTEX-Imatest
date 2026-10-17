from pathlib import Path
import json
import pytest
from PySide6.QtCore import Qt,QRect,QEvent
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication,QToolTip
from mutex_imatest.export_plan import ExportOptions,export_report,report_basename,default_basename


def selected_result(tmp_path):
    from PIL import Image
    from mutex_imatest.models import AnalysisResult,ImageMetadata,Measurement,ChartDefinition,Region
    from mutex_imatest.analysis_plan import summarize_selected
    preview=tmp_path/'preview.png';Image.new('RGB',(240,160),'#eeeeee').save(preview)
    image=ImageMetadata('原图.tif',240,160,3,'uint16',16,230400,'f'*64,decoder='test')
    chart=ChartDefinition('edge','合成斜边',[Region('edge','edge',(.2,.2,.5,.5))])
    rows=[Measurement('edge','斜边','edge',ch,(120,80),(80,40,80,80),values={'mtf50':.2,'mtf20':.3},units={'mtf50':'cy/px','mtf20':'cy/px'}) for ch in ['R','G','B']]
    result=AnalysisResult(image,chart.id,chart.name,rows,{'analysis_metrics':['mtf50','mtf20']},chart.to_dict())
    result.analysis_summary=summarize_selected(result)
    return result,preview


def test_export_filename_rules_block_traversal_and_windows_devices():
    assert report_basename('照片.pdf')=='照片'
    assert report_basename('扫描 001.v2')=='扫描 001.v2'
    for name in ['', '..', '../a','..\\a','a/b','a\\b','a:b','a<test>','CON','con.txt','NUL.pdf','COM1.any','COM¹','LPT9','CON .txt','a.',' a','a ','a\nname','x'*101]:
        with pytest.raises(ValueError):report_basename(name)
    assert default_basename('C:/test/扫描.tif')=='扫描'
    assert default_basename('C:/test/CON.tif')=='分析报告'


def test_html_only_is_self_contained_and_has_exactly_one_named_file(tmp_path):
    result,preview=selected_result(tmp_path);before=json.dumps(result.to_dict(),ensure_ascii=False)
    options=ExportOptions(tmp_path/'exports','自选报告.html','html','自定义 <标题> & 测量',False,False,False)
    folder=export_report(result,preview,options)
    assert folder==tmp_path/'exports'/'自选报告'
    assert [p.name for p in folder.iterdir()]==['自选报告.html']
    text=(folder/'自选报告.html').read_text(encoding='utf-8')
    assert text.count('data:image/png;base64,')==6
    assert '<h1>自定义 &lt;标题&gt; &amp; 测量</h1>' in text
    assert '本次仅导出报告' in text and 'detail-report.html' not in text
    assert json.dumps(result.to_dict(),ensure_ascii=False)==before


@pytest.mark.parametrize('format,expected',[('pdf',{'.pdf'}),('both',{'.pdf','.html'})])
def test_selected_formats_and_attachments_stay_in_one_folder(tmp_path,qapp,format,expected):
    result,preview=selected_result(tmp_path)
    options=ExportOptions(tmp_path/'exports','命名报告',format,'测试报告',True,True,True)
    folder=export_report(result,preview,options,focus_data={'unit':'mm','example':[0,1,2]})
    assert {p.suffix for p in folder.glob('命名报告.*')}==expected
    assert {p.suffix for p in folder.glob('命名报告-详细.*')}==expected
    assert {'result.json','measurements.csv','analysis-results.json','analysis-results.csv','heatmap.png','focus-series.json','export-manifest.json',
            'evaluation-results.csv','evaluation-results.json'}<={p.name for p in folder.iterdir()}
    assert len(list((folder/'analyses').glob('*.png')))==6
    manifest=json.loads((folder/'export-manifest.json').read_text(encoding='utf-8'))
    assert manifest['formats']==(['pdf'] if format=='pdf' else ['html','pdf'])
    assert all((folder/p).is_file() and not Path(p).is_absolute() for p in manifest['files'])
    assert list((tmp_path/'exports').iterdir())==[folder]
    from PySide6.QtPdf import QPdfDocument
    document=QPdfDocument(None);assert document.load(str(folder/'命名报告.pdf'))==QPdfDocument.Error.None_
    assert document.pageCount()>=4
    assert '评价标准' in '\n'.join(document.getAllText(i).text() for i in range(document.pageCount()))
    assert '测试报告' in document.metaData(QPdfDocument.MetaDataField.Title)
    document.close()


def test_existing_report_is_preserved_and_new_names_are_numbered(tmp_path):
    result,preview=selected_result(tmp_path);parent=tmp_path/'exports';old=parent/'原图';old.mkdir(parents=True)
    (old/'原图.html').write_text('existing',encoding='utf-8')
    options=ExportOptions(parent,'原图','html',include_data=False,include_images=False,include_detail=False)
    assert export_report(result,preview,options)==parent/'原图 (2)'
    assert export_report(result,preview,options)==parent/'原图 (3)'
    assert (old/'原图.html').read_text(encoding='utf-8')=='existing'
    assert sorted(p.name for p in parent.iterdir())==['原图','原图 (2)','原图 (3)']


def test_invalid_options_and_failed_export_do_not_leave_partial_reports(tmp_path,monkeypatch):
    result,preview=selected_result(tmp_path);parent=tmp_path/'exports'
    with pytest.raises(ValueError):export_report(result,preview,ExportOptions(parent,'../escape'))
    assert not parent.exists()
    parent.mkdir();sentinel=parent/'existing';sentinel.mkdir();(sentinel/'keep.txt').write_text('keep')
    def fail(result,preview,folder,*args,**kwargs):
        (folder/'partial.html').write_text('partial');raise OSError('simulated write failure')
    monkeypatch.setattr('mutex_imatest.reports.export_bundle',fail)
    with pytest.raises(OSError,match='simulated'):export_report(result,preview,ExportOptions(parent,'new'))
    assert list(parent.iterdir())==[sentinel] and (sentinel/'keep.txt').read_text()=='keep'


def test_export_dialog_cancel_and_accept_do_not_write_files(qtbot,tmp_path):
    from mutex_imatest.ui.export_dialog import ExportDialog
    folder=tmp_path/'not-created';dialog=ExportDialog(tmp_path/'输入.tif',directory=folder);qtbot.addWidget(dialog)
    assert dialog.basename.text()=='输入' and dialog.options is None
    dialog.reject();assert dialog.options is None and not folder.exists()
    dialog.basename.setText('../outside');dialog.accept()
    assert dialog.options is None and dialog.error.text() and not folder.exists()
    dialog.basename.setText('报告.pdf');dialog.format.setCurrentIndex(dialog.format.findData('html'))
    dialog.title.setText('扫描仪报告');dialog.include_data.setChecked(False);dialog.accept()
    assert dialog.options.basename=='报告' and dialog.options.format=='html' and not dialog.options.include_data
    assert dialog.options.title=='扫描仪报告' and not folder.exists()


def test_all_metrics_have_hover_help_including_disabled_reason(qtbot):
    from mutex_imatest.analysis_catalog import METRICS,METRIC_DESCRIPTIONS
    from mutex_imatest.ui.metric_checklist import MetricChecklist
    from mutex_imatest.ui.availability import set_availability
    view=MetricChecklist();qtbot.addWidget(view)
    for name,key in METRICS:view.addItem(name,key)
    assert all(key in METRIC_DESCRIPTIONS and len(METRIC_DESCRIPTIONS[key])>30 for _,key in METRICS)
    for i,(name,key) in enumerate(METRICS):
        set_availability(view,i,True);assert METRIC_DESCRIPTIONS[key] in view.tooltip_text(i)
    row=view.findData('best_focus');set_availability(view,row,False,'需要至少 5 个不同焦位')
    view.set_status(row,'尚未运行焦位序列')
    text=view.tooltip_text(row)
    assert '需要至少 5 个不同焦位' in text and '尚未运行焦位序列' in text and '单张图像不能确定' in text
    view.resize(320,500);view.show();index=view.model().index(row,0);view.scrollTo(index)
    rect=view.visualRect(index)
    event=QHelpEvent(QEvent.Type.ToolTip,rect.center(),view.viewport().mapToGlobal(rect.center()))
    assert QApplication.sendEvent(view.viewport(),event)
    assert '需要至少 5 个不同焦位' in QToolTip.text()
    QToolTip.hideText()


def test_long_pdf_title_fits_using_actual_pdf_resolution(qapp,tmp_path):
    from PySide6.QtGui import QPdfWriter,QFont,QFontMetrics,QPageSize
    from mutex_imatest.reports import _title_font_size
    writer=QPdfWriter(str(tmp_path/'title.pdf'));writer.setResolution(120);writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    title='中文长标题导出报告与完整测量结果'*5+' · 详细测量'
    width=writer.width()-60;size=_title_font_size(title,width,48,device=writer)
    font=QFont('Microsoft YaHei',size);font.setBold(True)
    bounds=QFontMetrics(font,writer).boundingRect(QRect(0,0,width,48),int(Qt.TextFlag.TextWordWrap),title)
    assert bounds.height()<=48


def export_window(qtbot,tmp_path,monkeypatch):
    """Populate a small native result without opening an operating-system dialog."""
    from mutex_imatest.ui.main_window import MainWindow
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    result,preview=selected_result(tmp_path)
    window.entries=[{'path':result.image.path,'preview':str(preview),'metadata':result.image,
                     'result':result,'result_path':None,'focus_position':None,'focus_unit':'index','status':'已分析'}]
    window.current_index=0
    window.metric_selector.blockSignals(True)
    window.metric_selector.setCurrentIndex(window.metric_selector.findData('mtf50'))
    window.metric_selector.blockSignals(False)
    errors=[];monkeypatch.setattr(window,'message_error',lambda message:errors.append(str(message)))
    return window,errors


def test_main_window_export_cancel_writes_no_files(qtbot,tmp_path,monkeypatch):
    from mutex_imatest.ui.export_dialog import ExportDialog
    window,errors=export_window(qtbot,tmp_path,monkeypatch)
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    def cancelled(dialog):
        dialog.options=None
        return 0
    def unexpected_export(*args,**kwargs):raise AssertionError('cancelled export called report writer')
    monkeypatch.setattr(ExportDialog,'exec',cancelled)
    monkeypatch.setattr('mutex_imatest.export_plan.export_report',unexpected_export)
    window.export_current()
    assert not errors
    assert {p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}==before
    assert not hasattr(window,'report_directory')
    window.close()


@pytest.mark.parametrize('attachments',[False,True])
def test_main_window_export_pdf_honors_filename_and_attachment_choices(qtbot,tmp_path,monkeypatch,attachments):
    from mutex_imatest.ui.export_dialog import ExportDialog
    from PySide6.QtPdf import QPdfDocument
    window,errors=export_window(qtbot,tmp_path,monkeypatch)
    parent=tmp_path/'report-output'
    options=ExportOptions(parent,'手机局部回归.pdf','pdf','自选测量报告',attachments,attachments,attachments).validate()
    window.focus_data={'unit':'mm','positions':[0,1,2]}
    def accepted(dialog):
        dialog.options=options
        return 1
    monkeypatch.setattr(ExportDialog,'exec',accepted)
    window.export_current()
    assert not errors
    folder=parent/'手机局部回归'
    assert list(parent.iterdir())==[folder]
    expected={'手机局部回归.pdf'}
    if attachments:
        expected|={'手机局部回归-详细.pdf','result.json','measurements.csv','analysis-results.json','analysis-results.csv',
                   'focus-series.json','export-manifest.json','heatmap.png','analyses','evaluation-results.csv','evaluation-results.json'}
        assert len(list((folder/'analyses').glob('*.png')))==6
        assert json.loads((folder/'focus-series.json').read_text(encoding='utf-8'))==window.focus_data
    assert {p.name for p in folder.iterdir()}==expected
    document=QPdfDocument(None);assert document.load(str(folder/'手机局部回归.pdf'))==QPdfDocument.Error.None_
    assert document.pageCount()>=4 and document.metaData(QPdfDocument.MetaDataField.Title)=='自选测量报告'
    assert '评价标准' in '\n'.join(document.getAllText(i).text() for i in range(document.pageCount()))
    document.close()
    assert window.report_directory==parent
    assert str(folder) in window.status_text.text()
    assert window.entries[0]['result'].settings=={'analysis_metrics':['mtf50','mtf20']}
    window.close()
