import json,queue
from types import SimpleNamespace
import pytest
from mutex_imatest.diagnostics import JobDiagnostics,log_event,abnormal_exit,safe_context
from mutex_imatest.workers import process_job
from mutex_imatest.config import AnalysisConfig


def test_exception_records_context_resources_cause_chain_and_recent_events(tmp_path):
    events=[]
    with pytest.raises(RuntimeError):
        with JobDiagnostics(tmp_path,{'action':'truth','password':'secret-value'},sink=events.append):
            log_event('REGISTER','已定位 8/9',inliers=18)
            try:raise ValueError('decoder root cause')
            except ValueError as cause:raise RuntimeError('analysis failed') from cause
    text=(tmp_path/'error.log').read_text(encoding='utf-8')
    assert all(v in text for v in ['FULL TRACEBACK','decoder root cause','analysis failed','resources','python','REGISTER'])
    assert 'secret-value' not in text and '[redacted]' in text
    records=[json.loads(line) for line in (tmp_path/'diagnostics.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [r['stage'] for r in records]==['START','REGISTER','ERROR','END']
    assert all('elapsed_s' in r and 'time_utc' in r for r in records)
    assert len(events)==4


def test_failed_decode_worker_keeps_terminal_event_last_and_full_error(tmp_path):
    output=queue.Queue();payload={'action':'analyze','path':str(tmp_path/'missing.tif'),'folder':str(tmp_path/'job'),'config':AnalysisConfig().to_dict()}
    process_job(payload,output,SimpleNamespace(is_set=lambda:False))
    events=[]
    while not output.empty():events.append(output.get_nowait())
    assert events[-1]['type']=='error'
    assert any(e.get('stage')=='ERROR' for e in events)
    text=(tmp_path/'job/error.log').read_text(encoding='utf-8')
    assert 'missing.tif' in text and 'FileNotFoundError' in text and 'memory_mb' in text


def test_abnormal_exit_has_native_windows_code_and_breadcrumbs(tmp_path):
    (tmp_path/'analysis.log').write_text('last completed stage: RAW decode',encoding='utf-8')
    target=abnormal_exit({'folder':str(tmp_path),'action':'analyze','path':'large.tif'},-1073741819)
    text=open(target,encoding='utf-8').read()
    assert '0xC0000005' in text and 'RAW decode' in text and 'native-crash.log' in text


def test_sensitive_context_never_includes_pixel_payloads():
    safe=safe_context({'token':'abc','nested':{'authorization':'bearer'},'pixels':[1,2,3],'list':list(range(100))})
    assert safe['token']=='[redacted]' and 'pixels' not in safe
    assert safe['nested']['authorization']=='[redacted]' and len(safe['list'])==41


def test_finished_worker_drains_a_burst_of_logs_before_completion(qapp,tmp_path):
    from mutex_imatest.workers import WorkerManager
    class Process:
        exitcode=0
        def is_alive(self):return False
        def join(self,timeout=None):pass
    class Output(queue.Queue):
        def close(self):pass
    output=Output()
    for i in range(170):output.put({'type':'log','message':str(i)})
    output.put({'type':'done','result':'result.json'})
    manager=WorkerManager();manager.timer.stop();events=[]
    manager.event.connect(lambda uid,event:events.append(event))
    manager.current={'id':'burst','queue':output,'process':Process(),'cancel':SimpleNamespace(is_set=lambda:False),
                     'payload':{'folder':str(tmp_path)},'finished':False}
    manager._poll()
    assert events[-1]['type']=='done' and not any(e['type']=='error' for e in events)
    assert manager.current is None


def test_log_cleanup_is_idempotent(tmp_path):
    with JobDiagnostics(tmp_path,{'action':'cleanup'}) as journal:journal.event('READ','truth')
    journal.__exit__(None,None,None)
    journal.event('LATE','not emitted after close')
    assert len([json.loads(l) for l in (tmp_path/'diagnostics.jsonl').read_text(encoding='utf-8').splitlines() if json.loads(l)['stage']=='END'])==1


def test_cli_analysis_closes_each_journal_once(tmp_path,qapp):
    import numpy as np
    import tifffile
    from scipy.special import erf
    from mutex_imatest.cli import main
    from mutex_imatest.models import ChartDefinition,Region
    from mutex_imatest.templates import save_chart
    y,x=np.mgrid[:100,:160];a=.2+.6*.5*(1+erf((x-80-.08*y)/1.5))
    path=tmp_path/'truth.tif';tifffile.imwrite(path,np.rint(a*65535).astype(np.uint16))
    chart=tmp_path/'chart.json';save_chart(ChartDefinition('edge','Truth',[Region('e','edge',(.1,.1,.8,.8))]),chart)
    assert main(['analyze',str(path),'--chart',str(chart),'--out',str(tmp_path/'output')])==0
    log=tmp_path/'output/truth/diagnostics.jsonl'
    assert sum(json.loads(l)['stage']=='END' for l in log.read_text(encoding='utf-8').splitlines())==1


def test_preview_close_cancels_an_in_flight_source_open(qapp,monkeypatch,tmp_path):
    import threading
    from mutex_imatest.workers import TileReader
    from mutex_imatest.utils import Cancelled
    entered=threading.Event()
    def blocked(path,config,cancel=None):
        entered.set()
        assert cancel.wait(timeout=3),'TileReader did not propagate cancellation'
        raise Cancelled()
    monkeypatch.setattr('mutex_imatest.imaging.ImageSource',blocked)
    reader=TileReader();reader.start();reader.reset(str(tmp_path/'large.tif'),AnalysisConfig())
    assert entered.wait(timeout=3)
    reader.close()
    assert not reader.isRunning()


def test_keyboard_interrupt_is_cancellation_not_a_crash(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        with JobDiagnostics(tmp_path):raise KeyboardInterrupt()
    assert not (tmp_path/'error.log').exists()
    assert '任务已取消' in (tmp_path/'analysis.log').read_text(encoding='utf-8')


def test_rerun_preserves_previous_error_and_native_stack(tmp_path):
    with pytest.raises(ValueError):
        with JobDiagnostics(tmp_path):raise ValueError('previous failure')
    (tmp_path/'native-crash.log').write_text('previous native stack',encoding='utf-8')
    with JobDiagnostics(tmp_path):pass
    history=next((tmp_path/'.diagnostic-history').iterdir())
    assert 'previous failure' in (history/'error.log').read_text(encoding='utf-8')
    assert (history/'native-crash.log').read_text(encoding='utf-8')=='previous native stack'
    assert not (tmp_path/'error.log').exists()


def test_closed_event_recipient_does_not_interrupt_computation(tmp_path):
    def closed(event):raise OSError('UI recipient closed')
    with JobDiagnostics(tmp_path,sink=closed) as journal:journal.event('COMPUTE','work continues')
    assert 'work continues' in (tmp_path/'analysis.log').read_text(encoding='utf-8')
