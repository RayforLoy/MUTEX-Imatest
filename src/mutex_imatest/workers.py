from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import multiprocessing as mp
import queue, traceback,uuid,os,shutil,time,threading
from PIL import Image
from .utils import Cancelled,atomic_json

def process_job(payload,output_queue,cancel):
    from .diagnostics import JobDiagnostics,job_context,background_error
    from types import SimpleNamespace
    completion=[]
    def send(event):
        if event['type'] in {'done','error','cancelled'}:completion.append(event)
        else:output_queue.put(event)
    try:
        with JobDiagnostics(payload['folder'],job_context(payload),sink=output_queue.put) as journal:
            _process_job(payload,SimpleNamespace(put=send),cancel,journal)
        for event in completion:output_queue.put(event)
    except Exception as exc:
        try:log=background_error(exc,job_context(payload))
        except Exception:log='Diagnostic folder could not be written'
        output_queue.put({'type':'error','message':str(exc),'log':log})


def _process_job(payload,output_queue,cancel,journal):
    try:
        import cv2
        cv2.setNumThreads(1)
        from .config import AnalysisConfig
        from .models import ChartDefinition
        from .imaging import ImageSource
        config=AnalysisConfig.from_dict(payload["config"]).validate()
        folder=Path(payload["folder"]);folder.mkdir(parents=True,exist_ok=True)
        def progress(value,message):
            if not cancel.is_set():
                journal.progress(value,message)
                output_queue.put({"type":"progress","value":value,"message":message})
        if payload['action']=='lab':
            from .lab import run_workflow
            run_workflow(payload['spec'],folder,config,cancel,progress)
            output_queue.put({'type':'done','lab_result':str(folder/'lab-result.json'),'report':str(folder/'report.html')});return
        if payload['action']=='prepare_profile':
            from .official_charts import prepare_profile
            from .templates import save_chart
            progress(10,'准备图卡兼容配置及参考文件')
            with ImageSource(payload['path'],config,cancel,progress) as source:
                chart=prepare_profile(source,payload['profile'],preview_path=folder/'profile-preview.png',**payload.get('options',{}))
            target=folder/'profile-chart.json';save_chart(chart,target)
            output_queue.put({'type':'done','profile_chart':str(target)});return
        if payload["action"]=="demo":
            from .demo import generate_demo
            progress(5,"生成已知真值的合成验证样本")
            chart,paths=generate_demo(folder/"samples")
            output_queue.put({"type":"done","demo_paths":[str(p) for p in paths],"chart":str(folder/"samples"/"chart.json")})
            return
        if payload["action"]=="focus":
            from .models import AnalysisResult
            from .focus import analyze_focus
            result=analyze_focus([AnalysisResult.load(p) for p in payload["results"]],payload["metric"],payload["channel"],payload["objective"],payload.get("height_calibrated",False))
            target=folder/"focus.json";result.save(target)
            output_queue.put({"type":"done","focus":str(target)});return
        if payload['action']=='gray_export':
            from .models import AnalysisResult
            from .gray_export import export_gray
            destination=export_gray(AnalysisResult.load(payload['result']),payload['destination'],cancel,progress)
            output_queue.put({'type':'done','exported':str(destination)});return
        if payload['action']=='preview_orientation':
            from .preview_orientation import match_preview_orientation
            progress(15,'匹配模板缩略图方向')
            matched=match_preview_orientation(payload['preview'],ChartDefinition.from_dict(payload['chart']),cancel)
            output_queue.put({'type':'done','preview_orientation':matched});return
        if payload['action']=='prepare_targets':
            from .chart_targets import prepare_chart_targets
            from .templates import save_chart
            progress(10,'识别图卡星图与斜边，请稍候')
            chart=prepare_chart_targets(ChartDefinition.from_dict(payload['chart']))
            target=folder/'prepared-chart.json';save_chart(chart,target)
            output_queue.put({'type':'done','prepared_chart':str(target)});return
        image_path=payload.get("path")
        if payload.get("snapshot"):
            from .utils import check_cancel
            from .watcher import can_read_complete
            original=Path(image_path);before=original.stat()
            if [before.st_size,before.st_mtime_ns]!=payload["expected_stat"] or not can_read_complete(original):
                raise ValueError("采集文件已更新或仍在写入，跳过旧事件；等待下一次稳定文件")
            cache_root=config.cache_path()/"jobs"
            snapshot_bytes=sum(p.stat().st_size for p in cache_root.rglob("snapshot/*") if p.is_file())
            if snapshot_bytes+before.st_size>config.cache_gb*2**30:raise OSError("采集快照已达预算，请保存需要的源文件并清理历史作业，或提高缓存上限")
            if shutil.disk_usage(folder).free<before.st_size*1.2:raise OSError("缓存磁盘剩余空间不足以保存采集快照")
            snap=folder/"snapshot"/original.name;snap.parent.mkdir(exist_ok=True)
            partial=snap.with_suffix(snap.suffix+".partial")
            progress(1,"保存只读采集快照，支持同名文件连续调焦")
            with open(original,"rb") as src,open(partial,"wb") as dst:
                while block:=src.read(8*2**20):check_cancel(cancel);dst.write(block)
            after=original.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                partial.unlink(missing_ok=True);raise ValueError("文件复制时发生变化，请等待下一次稳定采集")
            os.replace(partial,snap);image_path=str(snap)
        with ImageSource(image_path,config,cancel,progress) as source:
            if payload.get("snapshot"):source.metadata.original_path=payload["path"]
            if payload.get("expected_fingerprint") and source.metadata.fingerprint!=payload["expected_fingerprint"]:
                raise ValueError("源文件指纹与已保存测量不一致，请重新分析或恢复原文件")
            preview=folder/"preview.png"
            Image.fromarray(source.preview()).save(preview)
            output_queue.put({"type":"preview","preview":str(preview),"metadata":asdict(source.metadata),"native_cache":source.native_cache()})
            if payload["action"]=="analyze":
                from .analysis.engine import analyze_source
                chart=ChartDefinition.from_dict(payload["chart"])
                result=analyze_source(source,chart,config,cancel,progress,payload.get("focus_position"),payload.get("focus_unit"))
                target=folder/"result.json";result.save(target)
                if result.analysis_summary:
                    from .analysis_plan import save_summary
                    save_summary(result.analysis_summary,folder)
                output_queue.put({"type":"done","result":str(target),"preview":str(preview)})
            else:output_queue.put({"type":"done","preview":str(preview),"metadata":asdict(source.metadata)})
    except Cancelled:
        journal.cancelled=True;output_queue.put({"type":"cancelled"})
    except Exception as exc:
        journal.error(exc)
        output_queue.put({"type":"error","message":str(exc),"log":str(Path(payload["folder"])/"error.log")})

from PySide6.QtCore import QObject,Signal,QTimer,QThread
class WorkerManager(QObject):
    event=Signal(str,object)
    idle=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.context=mp.get_context("spawn");self.pending=[];self.current=None
        self.timer=QTimer(self);self.timer.timeout.connect(self._poll);self.timer.start(80)
    def submit(self,payload):
        uid=uuid.uuid4().hex;payload=dict(payload,job_id=uid);self.pending.append((uid,payload));self._next();return uid
    def _next(self):
        if self.current or not self.pending:return
        uid,payload=self.pending.pop(0)
        output=self.context.Queue();cancel=self.context.Event()
        process=self.context.Process(target=process_job,args=(payload,output,cancel),daemon=True)
        process.start()
        self.current={"id":uid,"process":process,"queue":output,"cancel":cancel,"payload":payload,"finished":False}
        self.event.emit(uid,{"type":"started","payload":payload})
    def _poll(self):
        if not self.current:return
        current=self.current
        for _ in range(100):
            try:event=current["queue"].get_nowait()
            except queue.Empty:break
            self.event.emit(current["id"],event)
            # A completion handler may close the dialog/manager synchronously.
            # Its queue is then closed; do not resume polling the stale job.
            if self.current is not current:return
            if event["type"] in {"done","error","cancelled"}:current["finished"]=True
        if not current["process"].is_alive():
            if not current["finished"]:
                # Queue feeder can lag process termination; a short bounded get resolves the race.
                deadline=time.monotonic()+.25
                while not current['finished'] and time.monotonic()<deadline:
                    try:event=current['queue'].get(timeout=.02)
                    except queue.Empty:continue
                    self.event.emit(current['id'],event)
                    if self.current is not current:return
                    current['finished']=event['type'] in {'done','error','cancelled'}
                if not current["finished"]:
                    if current['cancel'].is_set():self.event.emit(current['id'],{'type':'cancelled'})
                    else:
                        from .diagnostics import abnormal_exit
                        log=abnormal_exit(current['payload'],current['process'].exitcode)
                        self.event.emit(current["id"],{"type":"error","message":f"分析进程异常退出（代码 {current['process'].exitcode}），请查看完整诊断日志",'log':log})
            current["process"].join(timeout=.1);current["queue"].close()
            self.current=None;self._next()
            if not self.current and not self.pending:self.idle.emit()
    def cancel_all(self):
        self.pending.clear()
        if self.current:
            self.current["cancel"].set()
            # Native RAW decoding cannot always interrupt; terminate only our worker process.
            QTimer.singleShot(2000,self._terminate_cancelled)
    def _terminate_cancelled(self):
        if self.current and self.current["cancel"].is_set() and self.current["process"].is_alive():
            self.current["process"].terminate()
    def close(self):
        self.pending.clear()
        if self.current:
            self.current["cancel"].set()
            self.current["process"].join(timeout=.5)
            if self.current["process"].is_alive():self.current["process"].terminate();self.current["process"].join(timeout=2)
            self.current["queue"].close();self.current=None

class TileReader(QThread):
    ready=Signal(object)
    error=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.requests=queue.Queue();self.stopping=False;self.generation=0;self.cancel_event=threading.Event()
    def reset(self,path,config,metadata=None,native_cache=None):
        self.cancel_event.set();self.cancel_event=threading.Event()
        self.generation+=1
        self.requests.put(("source",self.generation,path,config,metadata,native_cache,self.cancel_event))
        return self.generation
    def request(self,generation,key,box,level):
        self.requests.put(("tile",generation,key,box,level))
    def run(self):
        source=None;generation=0
        from .imaging import ImageSource
        while not self.stopping:
            try:request=self.requests.get(timeout=.2)
            except queue.Empty:continue
            if request[0]=="stop":break
            if request[0]=="source":
                if request[1]!=self.generation:continue
                if source:source.close()
                try:
                    source=ImageSource.from_cached_raw(request[4],request[3],request[5]) if request[5] else ImageSource(request[2],request[3],cancel=request[6])
                    source.cancel=request[6]
                    generation=request[1]
                except Exception as exc:
                    if self.stopping or request[1]!=self.generation:continue
                    from .diagnostics import background_error
                    log=background_error(exc,{'action':'tile-open','path':request[2]})
                    source=None;self.error.emit(str(exc)+'；诊断日志：'+log)
            elif source is not None and request[1]==generation==self.generation:
                _,gen,key,box,level=request
                try:self.ready.emit({"generation":gen,"key":key,"box":box,"level":level,"pixels":source.tile(*box,level)})
                except Exception as exc:
                    from .diagnostics import background_error
                    if self.stopping or request[1]!=self.generation:continue
                    log=background_error(exc,{'action':'tile-read','path':str(getattr(source,'path','unknown')),'box':box,'level':level})
                    self.error.emit(str(exc)+'；诊断日志：'+log)
        if source:source.close()
    def close(self):
        self.stopping=True;self.cancel_event.set();self.requests.put(("stop",));self.wait(3000)
