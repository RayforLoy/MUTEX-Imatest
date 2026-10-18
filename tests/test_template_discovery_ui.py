"""Background template authoring keeps UI edits and source generations apart."""
import copy
import queue
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject,Signal,Qt
from mutex_imatest.models import ChartDefinition,Region
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.templates import save_chart,load_chart


class ControlledWorker(QObject):
    """Keep completion under test control, without starting an OS process."""
    event=Signal(str,object)
    def __init__(self,parent=None):
        super().__init__(parent);self.submitted=[];self.close_count=0
    def submit(self,payload):
        uid=f'discovery-{len(self.submitted)+1}'
        self.submitted.append((uid,copy.deepcopy(payload)))
        return uid
    def close(self):self.close_count+=1


def chart_source(tmp_path,key='a'):
    from PIL import Image
    preview=tmp_path/f'{key}-preview.png';Image.new('RGB',(160,120),'white').save(preview)
    return ChartDefinition(key,f'图卡 {key}',[
        Region(f'{key}-manual','edge',(.1,.15,.2,.3),'手工斜边',{'operator_note':'保留参数'},enabled=False)],
        physical_size_mm=(210,297),reference_size=(160,120),calibrated=True,
        preview=str(preview),source_path=str(tmp_path/f'{key}.pdf'),source_page=0,notes='用户原有备注')


@pytest.fixture
def editor_setup(qtbot,tmp_path,monkeypatch):
    import mutex_imatest.ui.template_editor as module
    monkeypatch.setattr(module,'WorkerManager',ControlledWorker)
    monkeypatch.setattr(module,'AnalysisConfig',lambda:AnalysisConfig(cache_dir=str(tmp_path/'cache')))
    original=chart_source(tmp_path)
    editor=module.TemplateEditor(original);qtbot.addWidget(editor);editor.show()
    return editor,original,module


def prepared_file(tmp_path,chart,key='candidate'):
    prepared=copy.deepcopy(chart)
    prepared.regions.append(Region(key,'star',(.5,.3,.3,.4),'检测星图',
                                   {'cycles':72,'pattern':'binary','discovery_generated':True}))
    prepared.notes+='；检测完成'
    target=tmp_path/f'{key}.json';save_chart(prepared,target)
    return target


def test_discovery_submits_once_freezes_roi_editing_and_retains_calibration(editor_setup,qtbot,tmp_path):
    editor,original,_=editor_setup
    editor.table.selectRow(0)
    qtbot.mouseClick(editor.detect_targets_button,Qt.MouseButton.LeftButton)
    uid,payload=editor.target_worker.submitted[0]
    editor.detect_targets()  # Re-entrant requests do not enqueue a second pass.
    assert len(editor.target_worker.submitted)==1 and editor.target_job==uid
    assert payload['action']=='prepare_targets' and payload['chart']['id']==original.id
    assert Path(payload['folder']).is_relative_to(tmp_path/'cache')
    controls=[editor.detect_targets_button,editor.canvas,editor.table,editor.save_button,editor.export_button,*editor.roi_buttons]
    assert all(not control.isEnabled() for control in controls)

    before=editor.chart.to_dict()
    # Guard methods too: a queued canvas/table signal must not bypass disabled
    # buttons and have its edit silently overwritten by the eventual result.
    editor.delete_region();editor.duplicate_region();editor.add_region((.2,.2,.1,.1))
    editor.edit_region();editor.add_grid();editor.detect_usaf();editor.detect_full_usaf()
    editor.save();editor.export()
    assert editor.chart.to_dict()==before
    assert not list((tmp_path/'charts').glob('*.json'))

    # Dimensions and the user-facing name remain editable while the worker
    # authors candidate ROIs; completion must not replace these newer values.
    editor.name.setText('操作员修改后的名称')
    editor.width.setValue(222.5);editor.height.setValue(333.75);editor.calibrated.setChecked(False)
    editor.target_worker.event.emit(uid,{'type':'progress','message':'正在识别候选星图','value':50})
    assert '正在识别候选星图' in editor.target_info.text()
    prepared=prepared_file(tmp_path,ChartDefinition.from_dict(payload['chart']))
    editor.target_worker.event.emit(uid,{'type':'done','prepared_chart':str(prepared)})
    assert editor.target_job is None and all(control.isEnabled() for control in controls)
    updated=editor.updated()
    assert updated.name=='操作员修改后的名称' and updated.physical_size_mm==(222.5,333.75)
    assert not updated.calibrated
    assert [r.id for r in updated.regions]==['a-manual','candidate']
    manual=updated.regions[0]
    assert not manual.enabled and manual.params=={'operator_note':'保留参数'}
    assert original.physical_size_mm==(210,297) and original.calibrated
    assert len(original.regions)==1 and editor.table.rowCount()==2
    editor.reject()


def test_replacing_pdf_cancels_old_job_and_ignores_its_late_result(editor_setup,monkeypatch,tmp_path):
    editor,original,module=editor_setup
    editor.detect_targets();old_uid,_=editor.target_worker.submitted[0]
    old_result=prepared_file(tmp_path,original,'old-source-candidate')
    new_source=chart_source(tmp_path,'b')
    monkeypatch.setattr(module.QFileDialog,'getOpenFileName',lambda *args,**kwargs:(new_source.source_path,'PDF'))
    imports=[]
    def import_new(path,page):
        imports.append((path,page));return copy.deepcopy(new_source)
    monkeypatch.setattr(module,'import_source',import_new)
    editor.open_source()
    assert imports==[(new_source.source_path,0)]
    assert editor.target_worker.close_count==1 and len(editor.target_worker.submitted)==2
    new_uid,new_payload=editor.target_worker.submitted[-1]
    assert new_uid!=old_uid and editor.target_job==new_uid
    assert new_payload['chart']['id']=='b' and editor.chart.id=='b'
    assert not editor.calibrated.isChecked() and not editor.save_button.isEnabled()

    # A result already in the Qt event queue for the cancelled process must not
    # replace B or clear B's still-active job.
    editor.target_worker.event.emit(old_uid,{'type':'done','prepared_chart':str(old_result)})
    assert editor.chart.id=='b' and [r.id for r in editor.chart.regions]==['b-manual']
    assert editor.target_job==new_uid and not editor.save_button.isEnabled()
    new_result=prepared_file(tmp_path,ChartDefinition.from_dict(new_payload['chart']),'new-source-candidate')
    editor.target_worker.event.emit(new_uid,{'type':'done','prepared_chart':str(new_result)})
    assert editor.target_job is None and editor.save_button.isEnabled()
    assert [r.id for r in editor.chart.regions]==['b-manual','new-source-candidate']
    assert editor.chart.source_path==new_source.source_path
    editor.reject()


@pytest.mark.parametrize('terminal',[{'type':'error','message':'无法读取缩略图'},{'type':'cancelled'}])
def test_failed_or_cancelled_discovery_restores_controls_without_changing_regions(editor_setup,terminal):
    editor,_,_=editor_setup
    editor.detect_targets();uid,_=editor.target_worker.submitted[0]
    before=editor.chart.to_dict()
    editor.target_worker.event.emit(uid,terminal)
    assert editor.target_job is None and editor.chart.to_dict()==before
    assert all(control.isEnabled() for control in [editor.canvas,editor.table,editor.save_button,editor.export_button,*editor.roi_buttons])
    assert '未生成自动区域' in editor.target_info.text()
    editor.reject()


def test_prepare_targets_worker_serializes_definition_without_decoding_capture(tmp_path,monkeypatch):
    from mutex_imatest.workers import process_job
    chart=chart_source(tmp_path);seen=[]
    def prepare(incoming):
        seen.append(incoming)
        assert isinstance(incoming,ChartDefinition) and incoming.id==chart.id
        incoming.regions.append(Region('worker-star','star',(.5,.2,.2,.3),params={'cycles':48,'pattern':'binary'}))
        return incoming
    def unexpected_image(*args,**kwargs):raise AssertionError('template discovery decoded an image capture')
    monkeypatch.setattr('mutex_imatest.chart_targets.prepare_chart_targets',prepare)
    monkeypatch.setattr('mutex_imatest.imaging.ImageSource',unexpected_image)
    output=queue.Queue();folder=tmp_path/'worker-output'
    process_job({'action':'prepare_targets','chart':chart.to_dict(),'config':AnalysisConfig(cache_dir=str(tmp_path/'cache')).to_dict(),
                 'folder':str(folder)},output,SimpleNamespace(is_set=lambda:False))
    events=[]
    while not output.empty():events.append(output.get_nowait())
    assert len(seen)==1 and [e['type'] for e in events if e['type']!='log']==['progress','done']
    assert {'START','PROGRESS','END'}<={e['stage'] for e in events if e['type']=='log'}
    prepared=load_chart(events[-1]['prepared_chart'])
    assert Path(events[-1]['prepared_chart'])==folder/'prepared-chart.json'
    assert [r.id for r in prepared.regions]==['a-manual','worker-star']
    assert prepared.physical_size_mm==chart.physical_size_mm and prepared.calibrated==chart.calibrated
    assert prepared.source_path==chart.source_path and len(chart.regions)==1
    assert {p.name for p in folder.iterdir()}=={'prepared-chart.json','analysis.log','diagnostics.jsonl','native-crash.log'}
