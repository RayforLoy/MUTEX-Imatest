from pathlib import Path
from dataclasses import asdict
from PySide6.QtCore import Qt
from mutex_imatest.ui.main_window import MainWindow
from mutex_imatest.ui.template_editor import TemplateEditor
from mutex_imatest.templates import builtin_chart


def test_selecting_and_reopening_usaf_chart_restores_applicable_view(qtbot,monkeypatch):
    from mutex_imatest.models import ChartDefinition,Region
    import mutex_imatest.ui.main_window as module
    chart=ChartDefinition("usaf-restart","USAF",[Region("u","usaf",(.1,.1,.1,.1))],fiducials=[{"kind":"usaf"}])
    monkeypatch.setattr(module,"available_charts",lambda:[builtin_chart(),chart])
    window=MainWindow();qtbot.addWidget(window)
    window.chart_combo.setCurrentIndex(1)
    assert window.metric_selector.currentData()=="contrast_at_frequency"
    assert window.registration.currentData()=="usaf"
    for metric in ["mtf50","ctf50"]:
        assert not window.metric_selector.model().item(window.metric_selector.findData(metric)).isEnabled()
    window.clipping_policy.setCurrentIndex(window.clipping_policy.findData(False))
    assert not window.snapshot_config().reject_clipping
    window.close()
    reopened=MainWindow();qtbot.addWidget(reopened)
    assert reopened.current_chart().id==chart.id
    assert reopened.metric_selector.currentData()=="contrast_at_frequency"
    assert reopened.registration.currentData()=="usaf"
    assert reopened.clipping_policy.currentData() is False
    reopened.chart_combo.setCurrentIndex(0)
    assert reopened.metric_selector.model().item(reopened.metric_selector.findData("mtf50")).isEnabled()
    assert reopened.registration.currentData()=="template"
    reopened.close()


def test_usaf_strict_to_relative_focus_reanalyzes_and_preserves_flags(qtbot,tmp_path):
    import numpy as np,tifffile
    from mutex_imatest.models import ChartDefinition,Region
    from mutex_imatest.config import AnalysisConfig
    from mutex_imatest.heatmap import heatmap_data
    pixels=np.full((200,200,3),255,np.uint8);regions=[]
    for row in range(3):
        for col in range(3):
            x,y=20+col*60,20+row*60
            for bar in range(3):pixels[y+3:y+29,x+4+bar*8:x+8+bar*8]=0
            regions.append(Region(f"u{row}{col}","usaf",(x/200,y/200,32/200,32/200),params={"frequency_cy_px":.125}))
    chart=ChartDefinition("clipped-usaf","USAF clipped",regions)
    path=tmp_path/"scan.tif";tifffile.imwrite(path,pixels,photometric="rgb",metadata=None)
    before=path.read_bytes()
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    window.charts=[chart];window.refresh_charts(chart.id)
    window.config=AnalysisConfig(transfer="unknown",cache_dir=str(tmp_path/"cache"),reject_clipping=True)
    window.restore_settings();window.chart_changed()
    assert window.clipping_policy.isVisible() and not window.advanced.isVisible()
    window.import_paths([str(path)],analyze=True)
    qtbot.waitUntil(lambda:bool(window.entries[0]["result"]),timeout=90000)
    strict=window.entries[0]["result"]
    assert len(strict.measurements)==9 and all("clipped" in m.flags and not m.valid for m in strict.measurements)
    assert "9 点因信号剪切" in window.warning.text()
    assert window.relative_focus_button.isVisible()
    assert window.metric_selector.currentData()=="contrast_at_frequency"
    assert not np.isfinite(heatmap_data(strict,"contrast_at_frequency",width=100)["field"]).any()
    qtbot.mouseClick(window.relative_focus_button,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:bool(window.entries[0]["result"]) and window.entries[0]["result"] is not strict,timeout=90000)
    relative=window.entries[0]["result"]
    assert all(m.valid and "clipping_advisory" in m.flags and "transfer_unknown" in m.flags for m in relative.measurements)
    assert np.isfinite(heatmap_data(relative,"contrast_at_frequency",width=100)["field"]).any()
    assert relative.settings["reject_clipping"] is False and relative.settings["transfer"]=="unknown"
    assert relative.image.fingerprint==strict.image.fingerprint
    assert [m.values for m in relative.measurements]==[m.values for m in strict.measurements]
    assert "9 点保留剪切提示" in window.warning.text() and not window.relative_focus_button.isVisible()
    assert path.read_bytes()==before
    window.close()

def test_window_mode_and_template_editor(qtbot):
    window=MainWindow();qtbot.addWidget(window);window.show()
    assert not window.advanced.isVisible()
    window.mode.setCurrentIndex(1)
    assert window.advanced.isVisible()
    editor=TemplateEditor(builtin_chart(),window);qtbot.addWidget(editor);editor.show()
    assert editor.table.rowCount()==16
    window.close()

def test_usaf_direction_view_does_not_replace_source_measurements(qtbot):
    from mutex_imatest.models import ImageMetadata,Measurement,AnalysisResult
    window=MainWindow();qtbot.addWidget(window)
    rows=[Measurement(str(i),str(i),"usaf","G",(20+i,30),(0,0,32,32),direction_deg=i*90) for i in range(2)]
    result=AnalysisResult(ImageMetadata("x",100,100,3,"uint8",8,1,"hash"),"c","c",rows,{}, {})
    window.usaf_direction.setCurrentIndex(window.usaf_direction.findData("horizontal"))
    filtered=window.direction_result(result)
    assert [m.direction_deg for m in filtered.measurements]==[90]
    assert len(result.measurements)==2 and "report_usaf_direction" not in result.settings
    assert filtered.settings["report_usaf_direction"]=="horizontal"
    window.close()

def test_watch_overwritten_filename_preserves_previous_capture(qtbot,tmp_path):
    import tifffile,numpy as np
    from mutex_imatest.demo import demo_definition,generate_frame
    from mutex_imatest.config import AnalysisConfig
    path=tmp_path/"capture.tif";chart=demo_definition()
    first,_=generate_frame(chart,0);second,_=generate_frame(chart,.7)
    tifffile.imwrite(path,first,photometric="rgb",metadata=None)
    window=MainWindow();qtbot.addWidget(window);window.show()
    window.config=AnalysisConfig(transfer="linear",cache_dir=str(tmp_path/"cache"))
    window.transfer.setCurrentIndex(window.transfer.findData("linear"))
    window.watch_file(str(path))
    qtbot.waitUntil(lambda:len(window.entries)==1 and bool(window.entries[0]["result"]),timeout=90000)
    preserved=Path(window.entries[0]["path"]);before=preserved.read_bytes()
    tifffile.imwrite(path,second,photometric="rgb",metadata=None)
    window.watch_file(str(path))
    qtbot.waitUntil(lambda:len(window.entries)==2 and bool(window.entries[1]["result"]),timeout=90000)
    assert preserved.read_bytes()==before
    assert window.entries[0]["result"].image.fingerprint!=window.entries[1]["result"].image.fingerprint
    assert window.entries[0]["result"].image.original_path==str(path)
    window.close()

def test_gui_worker_analyzes_image(qtbot,tmp_path):
    import tifffile
    from mutex_imatest.demo import demo_definition,generate_frame
    from mutex_imatest.config import AnalysisConfig
    chart=demo_definition();pixels,_=generate_frame(chart,.2)
    path=tmp_path/"scan_z+0.20mm.tif";tifffile.imwrite(path,pixels,photometric="rgb",metadata=None)
    window=MainWindow();qtbot.addWidget(window);window.show()
    window.config=AnalysisConfig(cache_dir=str(tmp_path/"cache"),transfer="linear")
    window.transfer.setCurrentIndex(window.transfer.findData("linear"));window.analysis_channels.setCurrentText("RGB")
    window.import_paths([str(path)],analyze=True)
    qtbot.waitUntil(lambda:bool(window.entries and window.entries[0]["result"]),timeout=90000)
    assert window.entries[0]["result"].measurements[0].valid
    assert window.entries[0]["result"].focus_position==.2
    assert window.entries[0]["result"].focus_unit=="mm"
    assert window.table.rowCount()>0
    window.entries.append(dict(window.entries[0]))
    window.refresh_compare();window.compare.setCurrentIndex(window.compare.findData(1))
    assert len(window.curve.listDataItems())==4
    window.compare.setCurrentIndex(0)
    assert len(window.curve.listDataItems())==3
    window.close()

