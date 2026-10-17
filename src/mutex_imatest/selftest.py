from __future__ import annotations
from pathlib import Path
import json,os,time
def run(out,headless=True):
    if headless:os.environ["QT_QPA_PLATFORM"]="offscreen"
    from PySide6.QtCore import QTimer,QSize
    from PySide6.QtWidgets import QApplication
    from PySide6.QtPdf import QPdfDocument
    from .ui.main_window import MainWindow
    from .config import AnalysisConfig
    from .reports import export_bundle
    from .cli import environment_info
    folder=Path(out).resolve();folder.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([]);app.setStyle("Fusion")
    window=MainWindow();window.resize(1580,1020);window.persist_preferences=False
    window.config=AnalysisConfig(transfer="linear",channels="RGB",cache_dir=str(folder/"cache"))
    window.restore_settings();window.show()
    state={"stage":"analyze","started":time.monotonic()};errors=[]
    def fail(message):
        errors.append(message);finish(False)
    def poll():
        try:
            if time.monotonic()-state["started"]>240:fail("Selftest timed out");return
            if any(e["status"]=="需检查" for e in window.entries):fail(window.logs.toPlainText());return
            if state["stage"]=="analyze" and len(window.entries)==9 and all(e["result"] for e in window.entries) and not window.worker.current:
                window.images.clearSelection();window.images.setCurrentRow(0)
                payload={"action":"focus","config":window.snapshot_config().to_dict(),"folder":window.folder_for_job(),
                         "results":[e["result_path"] for e in window.entries],"metric":"mtf50","channel":"G","objective":"balanced","height_calibrated":True}
                uid=window.worker.submit(payload);window.jobs[uid]={"action":"focus"}
                state["stage"]="focus"
            elif state["stage"]=="focus" and window.focus_data and not window.worker.current:
                assert sum(p["peak"] is not None for p in window.focus_data["peaks"])>=6
                assert window.focus_data["unit"]=="mm"
                assert "apparent_tilt_deg" in window.focus_data["field_model"]
                window.mode.setCurrentIndex(0);window.show_focus()
                state["stage"]="capture";QTimer.singleShot(700,capture);return
            QTimer.singleShot(250,poll)
        except Exception as exc:fail(str(exc))
    def capture():
        try:
            window.grab().save(str(folder/"focus-map.png"))
            window.metric_selector.setCurrentIndex(window.metric_selector.findData("mtf50"))
            window.select_region("edge-0-0");window.mode.setCurrentIndex(0)
            window.grab().save(str(folder/"simple-mode.png"))
            window.mode.setCurrentIndex(1)
            window.compare.setCurrentIndex(window.compare.findData(2))
            QTimer.singleShot(700,capture_compare)
        except Exception as exc:fail(str(exc))
    def capture_compare():
        try:
            assert len(window.curve.listDataItems())>=4
            window.grab().save(str(folder/"professional-compare.png"))
            e=window.entries[0]
            export_bundle(e["result"],e["preview"],folder/"report")
            focus=window.focus_overlay_result(e["result"])
            export_bundle(focus,e["preview"],folder/"focus-report","best_focus","G",window.focus_data["unit"])
            from .utils import atomic_json
            atomic_json(folder/"focus-report"/"focus-series.json",window.focus_data)
            doc=QPdfDocument(None)
            assert doc.load(str(folder/"report"/"report.pdf"))==QPdfDocument.Error.None_
            assert doc.pageCount()>=2
            doc.render(0,QSize(900,1270)).save(str(folder/"report-page-1.png"));doc.close()
            # Exercise the native crypto bindings in the frozen executable,
            # with a synthetic chart and a public test-only passphrase.
            from tempfile import TemporaryDirectory
            from zipfile import ZipFile
            from .chart_package import export_chart_package,load_chart_package,inspect_chart_package
            with TemporaryDirectory(prefix='template-selftest-',dir=folder) as temporary:
                target=Path(temporary)/'synthetic.mxtpl';chart=window.current_chart()
                export_chart_package(chart,target,'MUTEX-public-selftest-0.5')
                recovered=load_chart_package(target,'MUTEX-public-selftest-0.5',cache_dir=Path(temporary)/'cache')
                assert recovered.id==chart.id and len(recovered.regions)==len(chart.regions)
                assert recovered.source_path is None and Path(recovered.preview).is_file()
                with ZipFile(target) as archive:assert set(archive.namelist())=={'manifest.json','encrypted.bin'}
                state['encrypted_template']={'passed':True,'rois':len(recovered.regions),'manifest':inspect_chart_package(target)}
            window.update_evaluation(e['result'],'mtf50','G')
            assert all(text in window.evaluation_detail.toPlainText() for text in ['参考值','评价标准','有效'])
            window.tabs.setCurrentWidget(window.evaluation_detail);app.processEvents()
            assert window.grab().save(str(folder/'evaluation-reference.png'))
            from .ui.evaluation_dialog import EvaluationDialog
            goals_config=AnalysisConfig.from_dict(window.config.to_dict())
            goals_config.evaluation_limits={'mean':{'max':1e-7,'unit':'native'}}
            goals=EvaluationDialog(goals_config,'mean',window);goals.show();app.processEvents()
            assert goals.grab().save(str(folder/'evaluation-goals.png'))
            goals.accept();assert goals.limits['mean']['max']==1e-7
            state['measurement_evaluation']={'passed':True,'small_goal_preserved':goals.limits['mean']['max']}
            # Verify both new surfaces and the actual spawn-based workbench path
            # in the frozen app, not only imports in the development interpreter.
            from .ui.iq_workbench import ProfileDialog,WorkbenchDialog
            profile=ProfileDialog(window.config,e['path'],window);profile.show();app.processEvents()
            assert profile.profile.count()>=35
            profile.grab().save(str(folder/'official-chart-setup.png'));profile.reject()
            lab=WorkbenchDialog(window.config,[e['path']],window);lab.show();app.processEvents()
            assert lab.workflow.count()>=13
            lab.grab().save(str(folder/'iq-workbench.png'));lab.reject()
            from .workers import WorkerManager
            manager=WorkerManager(window);state['lab_manager']=manager
            def lab_event(uid,event):
                try:
                    if event['type']=='error':fail(event['message'])
                    elif event['type']=='done' and event.get('lab_result'):
                        data=json.loads(Path(event['lab_result']).read_text(encoding='utf-8'))
                        assert abs(data['output']['ssim']-1)<1e-10 and data['output']['identical']
                        state['iq_workbench']={'passed':True,'profiles':35,'workflows':13,'spawn_compare_ssim':data['output']['ssim']}
                        finish(True)
                except Exception as exc:fail(str(exc))
            manager.event.connect(lab_event)
            state['stage']='iq-lab'
            manager.submit({'action':'lab','config':window.config.to_dict(),'folder':str(folder/'iq-lab'),
                            'spec':{'workflow':'compare','files':[e['path']]*2,'parameters':{'roi':[0,0,128,128]}}})
            QTimer.singleShot(250,poll)
        except Exception as exc:fail(str(exc))
    def finish(success):
        from .templates import available_charts
        from .bundled_templates import bundled_charts
        templates=available_charts();bundled=bundled_charts()
        data={"passed":success,"environment":environment_info(),"images":len(window.entries),
              "valid_measurements":sum(sum(m.valid for m in e["result"].measurements) for e in window.entries if e["result"]),
              "focus_peak_count":sum(p["peak"] is not None for p in window.focus_data["peaks"]) if window.focus_data else 0,
              "encrypted_template":state.get('encrypted_template'),
              'iq_workbench':state.get('iq_workbench'),
              'measurement_evaluation':state.get('measurement_evaluation'),
              'templates':{'total':len(templates),'bundled':[{'id':c.id,'name':c.name,'regions':len(c.regions),'source_absent':not c.source_path,'preview_exists':bool(c.preview and Path(c.preview).is_file())} for c in bundled]},
              "errors":errors,"logs":window.logs.toPlainText(),"elapsed_seconds":time.monotonic()-state["started"]}
        (folder/"selftest.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        if state.get('lab_manager'):state['lab_manager'].close()
        window.close();app.exit(0 if success else 1)
    QTimer.singleShot(100,window.open_demo);QTimer.singleShot(500,poll)
    code=app.exec();print("Selftest", "passed" if code==0 else "failed", "→",folder)
    return code

