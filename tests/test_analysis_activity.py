"""Visible animation and per-image submitted-job progress, with real worker QA."""
import copy
from dataclasses import asdict
from pathlib import Path

import cv2
import pytest
from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QListWidgetItem

from mutex_imatest.config import AnalysisConfig
from mutex_imatest.models import ImageMetadata
from mutex_imatest.ui.metric_checklist import ACTIVITY_ROLE, MetricChecklist


class ControlledWorker(QObject):
    """Mirror the real manager's queue and Qt events without an OS process."""
    event=Signal(str,object)
    idle=Signal()
    def __init__(self,parent=None):
        super().__init__(parent)
        self.pending=[];self.current=None;self.submitted=[];self.cancel_count=0
    def submit(self,payload):
        uid=f"controlled-{len(self.submitted)+1}"
        snapshot=copy.deepcopy(payload)
        self.submitted.append((uid,snapshot));self.pending.append((uid,snapshot))
        self._next()
        return uid
    def _next(self):
        if self.current or not self.pending:return
        uid,payload=self.pending.pop(0)
        self.current={"id":uid,"payload":payload}
        self.event.emit(uid,{"type":"started","payload":payload})
    def send(self,uid,event):self.event.emit(uid,copy.deepcopy(event))
    def finish(self,event):
        uid=self.current["id"]
        self.send(uid,event)
        self.current=None;self._next()
        if self.current is None and not self.pending:self.idle.emit()
    def cancel_all(self):
        self.cancel_count+=1;self.pending.clear()
    def close(self):self.current=None;self.pending.clear()


def _activity(view):
    return {view.itemData(i):view.model().item(i).data(ACTIVITY_ROLE)
        for i in range(view.count()) if view.model().item(i).data(ACTIVITY_ROLE)}


def _phase_pixels(view):
    rectangle=view.visualRect(view.model().index(0,0))
    rectangle.setLeft(rectangle.right()-24);rectangle.setBottom(rectangle.top()+24)
    return bytes(view.viewport().grab(rectangle).toImage().constBits())


def _completed(window,index):
    # Controlled transport completion, not a substitute analyzer. The real
    # WorkerManager/product-engine roundtrip is exercised separately below.
    path=window.entries[index]["path"]
    metadata=ImageMetadata(path,20,20,3,"uint8",8,1200,f"controlled-{index}")
    return {"type":"done","metadata":asdict(metadata),"preview":None}


@pytest.fixture
def controlled_window(qtbot,tmp_path,monkeypatch):
    import mutex_imatest.ui.main_window as module
    cv2.setNumThreads(1)
    monkeypatch.setattr(module,"WorkerManager",ControlledWorker)
    window=module.MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    window.config=AnalysisConfig(cache_dir=str(tmp_path/"cache"),transfer="linear")
    window.restore_settings();window.chart_changed();window.show()
    for i in range(2):
        entry={"path":str(tmp_path/f"image-{i}.tif"),"preview":None,"metadata":None,
            "result":None,"result_path":None,"focus_position":None,"focus_unit":None,
            "status":"已导入","snapshot":False}
        window.entries.append(entry);window.images.addItem(QListWidgetItem(f"image-{i}.tif"))
    window.images.setCurrentRow(0)
    try:yield window
    finally:window.close()


def _submit(window,index,keys):
    window.metric_selector.set_checked_keys(keys);window.analysis_selection_changed()
    window.submit_image(index,"analyze")
    return window.worker.submitted[-1][0]


def test_spinner_repaints_real_frames_during_frequent_progress_updates(qtbot):
    view=MetricChecklist();qtbot.addWidget(view);view.resize(340,150)
    view.addItem("MTF50","mtf50");view.addItem("MTF20","mtf20")
    view.set_checked_keys(["mtf50"]);view.show()
    view.set_activity(["mtf50"],"running",35,"原像素测量")
    assert view.activity_timer.isActive()
    first_phase=view.animation_phase;first_pixels=_phase_pixels(view)
    # Faster updates than the animation interval used to restart its timer
    # indefinitely, leaving a technically-active but stationary indicator.
    update=QTimer(view);update.setInterval(10)
    update.timeout.connect(lambda:view.set_activity(["mtf50"],"running",35,"原像素测量"))
    update.start()
    try:
        qtbot.waitUntil(lambda:view.animation_phase!=first_phase,timeout=1200)
        assert _phase_pixels(view)!=first_pixels
        assert set(_activity(view))=={"mtf50"}
        record=_activity(view)["mtf50"]
        assert record["progress"]==35 and "35%" in record["text"] and "共用测量" in record["text"]
        assert "百分比为本图共用测量作业的进度" in view.tooltip_text(0)
        assert view.checked_keys()==["mtf50"]
    finally:update.stop();view.set_activity()
    assert not view.activity_timer.isActive() and not _activity(view)


@pytest.mark.parametrize("state",["queued","cancelled","error",None])
def test_non_running_states_stop_animation_without_changing_checks(qtbot,state):
    view=MetricChecklist();qtbot.addWidget(view);view.addItem("MTF50","mtf50")
    view.set_checked_keys(["mtf50"])
    view.set_activity(["mtf50"],"running",25)
    qtbot.waitUntil(lambda:view.animation_phase!=0,timeout=1000)
    view.set_activity(["mtf50"] if state else [],state,25,"终态说明")
    phase=view.animation_phase
    assert not view.activity_timer.isActive()
    qtbot.wait(180)
    assert view.animation_phase==phase and view.checked_keys()==["mtf50"]
    if state:
        assert _activity(view)["mtf50"]["state"]==state
        assert "终态说明" in view.tooltip_text(0)
    else:assert not _activity(view)


def test_unavailable_and_sequence_rows_never_get_running_animation(qtbot):
    view=MetricChecklist();qtbot.addWidget(view)
    view.addItem("不支持","mtf50");view.model().item(0).setEnabled(False)
    view.addItem("序列分析","best_focus")
    view.set_activity(["mtf50","best_focus","unknown"],"running",15)
    assert not _activity(view)
    assert not view.activity_timer.isActive()


def test_submitted_snapshot_survives_later_check_changes_and_success(controlled_window):
    window=controlled_window;view=window.metric_selector
    first=_submit(window,0,["mtf50","mtf20"])
    assert set(_activity(view))=={"mtf50","mtf20"}
    assert all(v["state"]=="running" for v in _activity(view).values())
    window.worker.send(first,{"type":"progress","value":41,"message":"第一轮测量"})
    window.metric_selector.set_checked_keys(["mtf10"]);window.analysis_selection_changed()
    window.refresh_analysis_activity()
    assert view.checked_keys()==["mtf10"]
    assert set(_activity(view))=={"mtf50","mtf20"}  # Submitted, not current checkboxes.
    assert all(v["progress"]==41 for v in _activity(view).values())
    second=_submit(window,0,["mtf10"])
    assert set(_activity(view))=={"mtf50","mtf20"}
    assert set(window.jobs[first]["metrics"])=={"mtf50","mtf20"}
    assert window.jobs[second]["metrics"]==["mtf10"]
    window.worker.finish(_completed(window,0))
    assert set(_activity(view))=={"mtf10"} and _activity(view)["mtf10"]["state"]=="running"
    assert view.activity_timer.isActive()
    window.worker.finish(_completed(window,0))
    assert not _activity(view) and not view.activity_timer.isActive()
    assert view.checked_keys()==["mtf10"] and window.jobs[first]["state"]==window.jobs[second]["state"]=="done"


def test_queue_switches_only_show_selected_image_snapshot(controlled_window):
    window=controlled_window;view=window.metric_selector
    first=_submit(window,0,["mtf50","mtf20"])
    second=_submit(window,1,["mtf10"])
    window.images.setCurrentRow(1)
    assert set(_activity(view))=={"mtf10"} and _activity(view)["mtf10"]["state"]=="queued"
    assert not view.activity_timer.isActive()
    window.worker.send(first,{"type":"progress","value":61,"message":"图像零测量中"})
    assert _activity(view)["mtf10"]["progress"]==0 and _activity(view)["mtf10"]["message"]==""
    window.images.setCurrentRow(0)
    assert set(_activity(view))=={"mtf50","mtf20"}
    assert all(v["progress"]==61 for v in _activity(view).values()) and view.activity_timer.isActive()
    window.images.setCurrentRow(1)
    window.worker.finish(_completed(window,0))
    assert window.worker.current["id"]==second
    assert _activity(view)["mtf10"]["state"]=="running" and view.activity_timer.isActive()
    window.images.setCurrentRow(0)
    assert not _activity(view) and not view.activity_timer.isActive()
    window.images.setCurrentRow(1);window.worker.finish(_completed(window,1))
    assert not _activity(view) and not view.activity_timer.isActive()
    assert view.checked_keys()==["mtf10"]


def test_cancel_active_and_queued_tasks_stops_right_rows_and_preserves_checks(controlled_window):
    window=controlled_window;view=window.metric_selector
    first=_submit(window,0,["mtf50","mtf20"])
    second=_submit(window,1,["mtf10"])
    window.images.setCurrentRow(1);before=list(view.checked_keys())
    window.cancel_jobs()
    assert window.worker.cancel_count==1 and not window.worker.pending
    assert window.jobs[first]["state"]=="cancelling" and window.jobs[second]["state"]=="cancelled"
    assert window.entries[1]["status"]=="已取消"
    assert set(_activity(view))=={"mtf10"} and _activity(view)["mtf10"]["state"]=="cancelled"
    assert not view.activity_timer.isActive() and view.checked_keys()==before
    window.images.setCurrentRow(0)
    assert set(_activity(view))=={"mtf50","mtf20"}
    assert all(v["state"]=="cancelling" for v in _activity(view).values()) and view.activity_timer.isActive()
    window.worker.finish({"type":"cancelled"})
    assert all(v["state"]=="cancelled" for v in _activity(view).values()) and not view.activity_timer.isActive()
    window.worker.send(first,{"type":"progress","value":99,"message":"迟到进度"})
    assert all(v["state"]=="cancelled" for v in _activity(view).values()) and not view.activity_timer.isActive()
    assert view.checked_keys()==before
    retry=_submit(window,0,["mtf20"])
    assert set(_activity(view))=={"mtf20"} and _activity(view)["mtf20"]["state"]=="running"
    window.worker.finish(_completed(window,0))
    assert window.jobs[retry]["state"]=="done" and not _activity(view)


def test_failure_and_stale_progress_cannot_animate_another_images_job(controlled_window):
    window=controlled_window;view=window.metric_selector
    first=_submit(window,0,["mtf50","mtf20"])
    second=_submit(window,1,["mtf10"])
    checks=list(view.checked_keys())
    window.worker.finish({"type":"error","message":"受控解码失败"})
    assert window.entries[0]["status"]=="需检查" and window.worker.current["id"]==second
    assert set(_activity(view))=={"mtf50","mtf20"}
    assert all(v["state"]=="error" for v in _activity(view).values()) and not view.activity_timer.isActive()
    window.images.setCurrentRow(1)
    assert set(_activity(view))=={"mtf10"} and _activity(view)["mtf10"]["state"]=="running"
    window.worker.send(first,{"type":"progress","value":82,"message":"旧任务迟到事件"})
    assert _activity(view)["mtf10"]["progress"]==0 and _activity(view)["mtf10"]["message"]==""
    assert view.checked_keys()==checks and view.activity_timer.isActive()
    window.worker.finish(_completed(window,1))
    assert not _activity(view) and not view.activity_timer.isActive()


def test_fast_completion_and_preview_jobs_leave_no_running_rows(controlled_window):
    window=controlled_window;view=window.metric_selector
    uid=_submit(window,0,["mtf50"])
    # No event-loop wait: a fast success must stop the indicator even before
    # its first 80 ms frame. Late queued progress may not restart it.
    window.worker.finish(_completed(window,0))
    assert window.jobs[uid]["state"]=="done" and not _activity(view) and not view.activity_timer.isActive()
    window.worker.send(uid,{"type":"progress","value":100,"message":"迟到完成进度"})
    assert not _activity(view) and not view.activity_timer.isActive()
    window.submit_image(0,"preview")
    assert window.worker.current["payload"]["action"]=="preview"
    assert not _activity(view) and not view.activity_timer.isActive()
    window.worker.finish(_completed(window,0))
    assert view.checked_keys()==["mtf50"] and not _activity(view)


def test_changing_template_hides_other_template_activity_and_restores_own_job(controlled_window):
    window=controlled_window;view=window.metric_selector
    original_id=window.current_chart().id
    uid=_submit(window,0,["mtf50","mtf20"])
    window.worker.send(uid,{"type":"progress","value":43,"message":"原模板测量"})
    other=next(i for i,chart in enumerate(window.charts)
        if chart.id!=original_id and any(r.enabled and r.kind=="edge" for r in chart.regions))
    selected_before=list(view.checked_keys())
    window.chart_combo.setCurrentIndex(other)
    assert window.current_chart().id!=original_id
    assert not _activity(view) and not view.activity_timer.isActive()
    window.worker.send(uid,{"type":"progress","value":57,"message":"旧模板继续测量"})
    assert not _activity(view) and not view.activity_timer.isActive()
    window.chart_combo.setCurrentIndex(window.chart_combo.findData(original_id))
    assert set(_activity(view))=={"mtf50","mtf20"} and view.activity_timer.isActive()
    assert all(v["progress"]==57 and v["message"]=="旧模板继续测量" for v in _activity(view).values())
    assert view.checked_keys()==selected_before
    window.worker.finish(_completed(window,0))
    assert not _activity(view) and not view.activity_timer.isActive()


def test_real_product_worker_animates_checked_metrics_then_stops(qtbot,tmp_path):
    import tifffile
    from mutex_imatest.demo import demo_definition,generate_frame
    from mutex_imatest.ui.main_window import MainWindow
    from mutex_imatest.workers import WorkerManager
    cv2.setNumThreads(1)
    chart=demo_definition();pixels,_=generate_frame(chart,.2)
    sample=tmp_path/"real-worker.tif";tifffile.imwrite(sample,pixels,photometric="rgb",metadata=None)
    before=sample.read_bytes()
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    window.config=AnalysisConfig(cache_dir=str(tmp_path/"cache"),transfer="linear")
    window.restore_settings();window.chart_changed();window.show()
    try:
        assert isinstance(window.worker,WorkerManager)
        window.import_paths([str(sample)])
        qtbot.waitUntil(lambda:bool(window.entries[0]["preview"]) and window.worker.current is None,timeout=90000)
        view=window.metric_selector
        assert not _activity(view) and not view.activity_timer.isActive()
        keys={"mtf50","mtf20","ca_r_g_px"}
        view.set_checked_keys(keys);window.analysis_selection_changed()
        qtbot.mouseClick(window.analyze_button,Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda:bool(_activity(view)) and view.activity_timer.isActive(),timeout=10000)
        assert set(_activity(view))==keys
        first_phase=view.animation_phase
        qtbot.waitUntil(lambda:view.animation_phase!=first_phase,timeout=5000)
        assert all(v["state"]=="running" for v in _activity(view).values())
        qtbot.waitUntil(lambda:bool(window.entries[0]["result"]) and window.worker.current is None,timeout=90000)
        result=window.entries[0]["result"]
        assert set(result.analysis_summary["requested_metrics"])==keys and result.analysis_summary["completed"]==3
        assert not _activity(view) and not view.activity_timer.isActive() and set(view.checked_keys())==keys
        final_phase=view.animation_phase;qtbot.wait(180)
        assert view.animation_phase==final_phase and sample.read_bytes()==before
    finally:window.close()
