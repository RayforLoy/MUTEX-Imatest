"""Local job telemetry, useful progress and reproducible failure reports."""
from __future__ import annotations
from collections import Counter,deque
from contextvars import ContextVar
from datetime import datetime,timezone
from pathlib import Path
import faulthandler,importlib.metadata,json,os,platform,sys,time,traceback,uuid
import psutil
from . import __version__
from .models import plain

_active=ContextVar('mutex_diagnostics',default=None)


def safe_context(value):
    if isinstance(value,dict):
        return {str(k):'[redacted]' if any(s in str(k).lower() for s in ['password','token','secret','authorization']) else safe_context(v)
                for k,v in value.items() if k not in {'pixels','image_data'}}
    if isinstance(value,(tuple,list)):
        return [safe_context(v) for v in value[:40]]+(['[remaining items omitted]'] if len(value)>40 else [])
    if isinstance(value,(str,int,float,bool)) or value is None:return plain(value)
    return str(value)


def job_context(payload):
    result={k:payload.get(k) for k in ['job_id','action','path','config','focus_position','focus_unit','expected_fingerprint'] if k in payload}
    chart=payload.get('chart',{})
    if chart:result['chart']={k:chart.get(k) for k in ['id','name','physical_size_mm','calibrated','source_path']}
    if chart:result['chart'].update(regions=len(chart.get('regions',[])),kinds=dict(Counter(r.get('kind') for r in chart.get('regions',[]))))
    return safe_context(result)


def environment_snapshot(folder):
    versions={}
    for name in ['numpy','scipy','opencv-python-headless','PySide6','rawpy','tifffile','pyvips','imagecodecs']:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            module=sys.modules.get({'opencv-python-headless':'cv2','PySide6':'PySide6'}.get(name,name))
            versions[name]=getattr(module,'__version__','not loaded / metadata unavailable')
    resources={}
    try:
        memory=psutil.virtual_memory();process=psutil.Process()
        resources={'rss_bytes':process.memory_info().rss,'available_ram_bytes':memory.available,'total_ram_bytes':memory.total,
                   'disk_free_bytes':psutil.disk_usage(str(folder)).free,'threads':process.num_threads()}
    except (OSError,psutil.Error):pass
    return {'application':__version__,'python':sys.version,'executable':sys.executable,'frozen':bool(getattr(sys,'frozen',False)),
            'os':platform.platform(),'architecture':platform.machine(),'pid':os.getpid(),'dependencies':versions,'resources':resources}


class JobDiagnostics:
    def __init__(self,folder,context=None,sink=None,console=False):
        self.folder=Path(folder);self.context=safe_context(context or {});self.sink=sink;self.console=console
        self.job_id=self.context.get('job_id') or uuid.uuid4().hex
        self.events=deque(maxlen=160);self.started=time.monotonic();self.failed=False;self.cancelled=False
        self.records=0;self.last_progress=None;self.last_progress_at=0
        self.closed=False
    def __enter__(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        previous=[self.folder/name for name in ['analysis.log','diagnostics.jsonl','error.log','native-crash.log'] if (self.folder/name).is_file()]
        if previous:
            history=self.folder/'.diagnostic-history'/(datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+self.job_id[:8])
            if not history.resolve().is_relative_to(self.folder.resolve()):raise ValueError('Diagnostic history must remain inside the job folder')
            history.mkdir(parents=True,exist_ok=False)
            for path in previous:path.replace(history/path.name)
        self.text=(self.folder/'analysis.log').open('w',encoding='utf-8',buffering=1)
        self.structured=(self.folder/'diagnostics.jsonl').open('w',encoding='utf-8',buffering=1)
        self.native=(self.folder/'native-crash.log').open('w',encoding='utf-8',buffering=1)
        self.was_fault_enabled=faulthandler.is_enabled()
        try:faulthandler.enable(file=self.native,all_threads=True)
        except (RuntimeError,OSError):pass
        self.token=_active.set(self)
        self.event('START',f'任务 {self.job_id[:8]} · {self.context.get("action","analysis")}',context=self.context,environment=environment_snapshot(self.folder))
        return self
    def event(self,stage,message,level='INFO',**details):
        if self.closed:return
        record={'time_utc':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),'elapsed_s':round(time.monotonic()-self.started,3),
                'job_id':self.job_id,'level':level,'stage':stage,'message':str(message),'details':safe_context(details)}
        self.events.append(record);self.records+=1
        line=f'T+{record["elapsed_s"]:08.3f}s | {stage:<10} | {message}'
        if self.records<=20000 or level in {'ERROR','WARNING'}:
            try:self.text.write(line+'\n');self.structured.write(json.dumps(record,ensure_ascii=False)+'\n')
            except (OSError,ValueError):pass
        if self.sink:
            try:self.sink({'type':'log','message':line,'stage':stage,'level':level})
            except (OSError,ValueError,EOFError,RuntimeError):pass
        if self.console and sys.stderr is not None:
            try:print(line,file=sys.stderr,flush=True)
            except (OSError,ValueError):pass
    def progress(self,value,message):
        now=time.monotonic()
        if message!=self.last_progress and (now-self.last_progress_at>.1 or value in {0,100}):
            self.event('PROGRESS',f'{value:3d}% · {message}',progress=value)
            self.last_progress=message;self.last_progress_at=now
    def error(self,exc):
        self.failed=True
        self.event('ERROR',f'{type(exc).__name__}: {exc}',level='ERROR')
        report={'job_id':self.job_id,'context':self.context,'environment':environment_snapshot(self.folder),'recent_events':list(self.events),
                'exception_type':type(exc).__name__,'exception':str(exc),'traceback':''.join(traceback.format_exception(type(exc),exc,exc.__traceback__))}
        try:
            (self.folder/'error.log').write_text('MUTEX Imatest diagnostic failure report\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n\nFULL TRACEBACK\n'+report['traceback'],encoding='utf-8')
        except OSError:pass
    def __exit__(self,kind,exc,tb):
        if self.closed:return False
        if exc is not None:
            from .utils import Cancelled
            if isinstance(exc,(Cancelled,KeyboardInterrupt)):self.cancelled=True
            else:self.error(exc)
        self.event('END','任务已取消' if self.cancelled else '任务失败，详见 error.log / native-crash.log' if self.failed else '任务完成',environment=environment_snapshot(self.folder))
        _active.reset(self.token)
        try:
            if self.was_fault_enabled and sys.stderr is not None:faulthandler.enable(file=sys.stderr,all_threads=True)
            else:faulthandler.disable()
        except (RuntimeError,OSError):pass
        for stream in [self.text,self.structured,self.native]:stream.close()
        self.closed=True
        return False


def log_event(stage,message,**details):
    journal=_active.get()
    if journal is not None:journal.event(stage,message,**details)


def abnormal_exit(payload,exitcode):
    folder=Path(payload['folder']);folder.mkdir(parents=True,exist_ok=True)
    recent=''
    try:recent='\n'.join((folder/'analysis.log').read_text(encoding='utf-8').splitlines()[-100:])
    except OSError:pass
    data={'exitcode':exitcode,'exitcode_hex':f'0x{exitcode&0xffffffff:08X}' if exitcode is not None else None,
          'context':job_context(payload),'environment':environment_snapshot(folder),
          'native_crash_file':str(folder/'native-crash.log'),'recent_log':recent}
    target=folder/'error.log'
    try:target.write_text('Analysis worker exited without a completion event\n'+json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    except OSError:pass
    return str(target)


def background_error(exc,context=None):
    import platformdirs
    folder=Path(platformdirs.user_log_dir('MUTEX Imatest','MUTEX'))
    target=folder/'ui-errors.log'
    try:
        folder.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.stat().st_size>8*2**20:target.replace(folder/'ui-errors.previous.log')
        with target.open('a',encoding='utf-8') as stream:
            stream.write(datetime.now(timezone.utc).isoformat()+'\n'+json.dumps({'context':safe_context(context),'environment':environment_snapshot(folder)},ensure_ascii=False)+'\n')
            stream.write(''.join(traceback.format_exception(type(exc),exc,exc.__traceback__))+'\n')
    except OSError:pass
    return str(target)
