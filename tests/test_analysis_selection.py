import copy,json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from mutex_imatest.config import AnalysisConfig


def test_checklist_one_click_runs_one_job_and_returns_all_checked_results(qtbot,tmp_path,monkeypatch):
    import tifffile
    from mutex_imatest.demo import demo_definition,generate_frame
    from mutex_imatest.ui.main_window import MainWindow
    chart=demo_definition();pixels,_=generate_frame(chart,.2)
    path=tmp_path/'batch.tif';tifffile.imwrite(path,pixels,photometric='rgb',metadata=None);before=path.read_bytes()
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    window.config=AnalysisConfig(cache_dir=str(tmp_path/'cache'),transfer='linear');window.restore_settings();window.chart_changed()
    window.import_paths([str(path)])
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']) and window.worker.current is None,timeout=90000)
    window.metric_selector.set_checked_keys(['mtf50','mtf20','ca_r_g_px']);window.analysis_selection_changed()
    assert window.analysis_channels.currentText()=='RGB'
    submitted=[];submit=window.worker.submit
    def capture(payload):submitted.append(payload);return submit(payload)
    monkeypatch.setattr(window.worker,'submit',capture)
    qtbot.mouseClick(window.analyze_button,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:bool(window.entries[0]['result']) and window.worker.current is None,timeout=90000)
    result=window.entries[0]['result']
    assert len(submitted)==1 and submitted[0]['action']=='analyze'
    assert result.analysis_summary['requested_metrics']==['ca_r_g_px','mtf50','mtf20']
    assert result.analysis_summary['completed']==3
    assert all(item['status']=='complete' for item in result.analysis_summary['items'])
    assert result.settings['channels']=='RGB' and window.batch_table.rowCount()==7
    assert window.tabs.currentWidget() is window.batch_table
    folder=Path(window.entries[0]['result_path']).parent
    assert json.loads((folder/'analysis-results.json').read_text(encoding='utf-8'))==result.analysis_summary
    assert (folder/'analysis-results.csv').is_file() and path.read_bytes()==before
    row=next(i for i in range(window.batch_table.rowCount()) if window.batch_table.item(i,0).data(Qt.ItemDataRole.UserRole)[0]=='ca_r_g_px')
    window.batch_result_selected(row,0)
    assert window.metric_selector.currentData()=='ca_r_g_px' and window.channel.currentText()=='R'
    assert len(submitted)==1
    window.metric_selector.set_all_checked(False)
    assert not window.analyze_button.isEnabled()
    window.analyze_selected();assert len(submitted)==1
    window.close()


def test_checklist_preferences_and_disabled_checkboxes(qtbot,tmp_path):
    from mutex_imatest.ui.main_window import MainWindow
    window=MainWindow();qtbot.addWidget(window);window.show()
    keys=['mtf50','mtf20'];window.metric_selector.set_checked_keys(keys)
    # The demo's binary stars now support resolution_limit. It has no grid,
    # so a projective residual remains a truly unsupported analysis.
    assert not any(r.kind=='grid' for r in window.current_chart().regions)
    disabled=window.metric_selector.findData('projective_residual_rms_px');item=window.metric_selector.model().item(disabled)
    assert not item.isEnabled() and item.checkState()==Qt.CheckState.Unchecked
    view=window.metric_selector;index=view.model().index(disabled,0);view.scrollTo(index)
    qtbot.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=view.visualRect(index).center())
    assert view.checked_keys()==keys
    window.close()
    reopened=MainWindow();qtbot.addWidget(reopened)
    assert reopened.metric_selector.checked_keys()==keys
    for key in ['best_focus','focus_offset']:assert not reopened.metric_selector.model().item(reopened.metric_selector.findData(key)).isCheckable()
    reopened.close()


def test_batch_request_validation_and_channel_dependencies():
    from mutex_imatest.analysis_catalog import required_channels
    assert required_channels('G',['ca_b_g_px'])=='RGB'
    assert required_channels('RGB',['alignment_gain_pct'])=='RGBY'
    with pytest.raises(ValueError):AnalysisConfig(analysis_metrics=['invented']).validate()
    with pytest.raises(ValueError):AnalysisConfig(analysis_metrics=['best_focus']).validate()
    assert AnalysisConfig(analysis_metrics=['mtf50','mtf50']).validate().analysis_metrics==['mtf50']


def test_alignment_gain_summary_contains_only_the_compared_gray_channel():
    from mutex_imatest.models import AnalysisResult,ImageMetadata,Measurement
    from mutex_imatest.analysis_plan import summarize_selected
    measurements=[Measurement('failed','failed','usaf_summary',ch,(0,0),(0,0,4,4),flags=['registration_failed']) for ch in ['R','G','B','Y']]
    measurements.append(Measurement('gray','gray','usaf_summary','Y_align',(0,0),(0,0,4,4),
                                    {'alignment_gain_pct':12.5},{'alignment_gain_pct':'%'}))
    result=AnalysisResult(ImageMetadata('test.tif',4,4,3,'uint8',8,48,'test'),'test','test',measurements,
                          {'analysis_metrics':['alignment_gain_pct']},
                          {'regions':[{'kind':'usaf','params':{'multi_frequency':True}}]},optical_summary={'units':[]})
    channels=summarize_selected(result)['items'][0]['channels']
    assert len(channels)==1 and channels[0]['channel']=='Y_align'
    assert channels[0]['unit']=='%' and channels[0]['mean']==12.5


def test_batch_engine_opens_image_once_and_preserves_unselected_companion_values(tmp_path,monkeypatch):
    import tifffile
    from mutex_imatest.demo import demo_definition,generate_frame
    import mutex_imatest.analysis.engine as engine
    chart=demo_definition();pixels,_=generate_frame(chart,0);path=tmp_path/'batch.tif';tifffile.imwrite(path,pixels,photometric='rgb',metadata=None)
    opened=[];original=engine.ImageSource
    def source(*args,**kwargs):opened.append(args[0]);return original(*args,**kwargs)
    monkeypatch.setattr(engine,'ImageSource',source)
    config=AnalysisConfig(channels='G',transfer='linear',analysis_metrics=['mtf50','mtf20','ca_b_g_px'],cache_dir=str(tmp_path/'cache'))
    result=engine.analyze(path,chart,config)
    assert len(opened)==1 and result.settings['channels']=='RGB' and config.channels=='G'
    assert result.analysis_summary['requested_metrics']==config.analysis_metrics and result.analysis_summary['completed']==3
    assert any(m.metric('mtf10') is not None for m in result.measurements)


def test_all_selected_reports_and_no_valid_data_are_exported(tmp_path,qtbot):
    import tifffile
    from PIL import Image
    from mutex_imatest.demo import demo_definition,generate_frame
    from mutex_imatest.analysis.engine import analyze
    from mutex_imatest.reports import export_bundle
    from PySide6.QtPdf import QPdfDocument
    chart=demo_definition();pixels,_=generate_frame(chart,0);path=tmp_path/'batch.tif';tifffile.imwrite(path,pixels,photometric='rgb',metadata=None)
    assert any(r.kind=='star' for r in chart.regions) and not any(r.kind=='grid' for r in chart.regions)
    result=analyze(path,chart,AnalysisConfig(channels='RGB',transfer='linear',analysis_metrics=['mtf50','mtf20','ca_b_g_px','projective_residual_rms_px'],cache_dir=str(tmp_path/'cache')))
    preview=tmp_path/'preview.png';Image.fromarray((pixels/257).astype('uint8')).save(preview)
    out=tmp_path/'reports';export_bundle(result,preview,out)
    text=(out/'report.html').read_text(encoding='utf-8')
    assert all(key in text for key in ['mtf50','mtf20','ca_b_g_px','projective_residual_rms_px'])
    assert text.count('data:image/png;base64,')==7 and '<script src=' not in text
    assert (out/'detail-report.html').is_file() and (out/'detail-report.pdf').is_file()
    assert len(list((out/'analyses').glob('*.png')))==7
    table=json.loads((out/'analysis-results.json').read_text(encoding='utf-8'))
    assert table['items'][-1]['metric']=='projective_residual_rms_px'
    assert table['items'][-1]['status']=='unsupported' and table['items'][-1]['reason']
    doc=QPdfDocument(None);assert doc.load(str(out/'report.pdf'))==QPdfDocument.Error.None_;assert doc.pageCount()>=5
    pdf_text='\n'.join(doc.getAllText(i).text() for i in range(doc.pageCount()))
    assert '结果评价' in pdf_text and '参考值' in pdf_text and '评价标准' in pdf_text
    doc.close()
