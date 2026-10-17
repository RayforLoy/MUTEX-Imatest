from __future__ import annotations
import argparse,json,multiprocessing,sys,time
from pathlib import Path
def main():
    ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from mutex_imatest.ui.main_window import MainWindow
    from mutex_imatest.models import AnalysisResult
    from mutex_imatest.focus import analyze_focus
    p=argparse.ArgumentParser();p.add_argument("--out",default=str(ROOT/"validation"));p.add_argument("--headless",action="store_true");ns=p.parse_args()
    if ns.headless:
        import os;os.environ["QT_QPA_PLATFORM"]="offscreen"
    folder=Path(ns.out);folder.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app.setStyle("Fusion");window=MainWindow();window.persist_preferences=False;window.resize(1580,1020);window.show()
    from mutex_imatest.config import AnalysisConfig
    window.config=AnalysisConfig(transfer="linear",channels="RGB",cache_dir=str(folder/"cache"))
    window.restore_settings()
    results=list((ROOT/"samples"/"demo"/"results").glob("*.json"))
    if not results:results=[ROOT/"samples"/"demo"/"initial-result.json"]
    for path in results:window.add_result(AnalysisResult.load(path),str(path))
    start=time.monotonic()
    def check():
        if all(e["preview"] for e in window.entries) and not window.worker.current:
            window.images.setCurrentRow(min(4,len(window.entries)-1));window.mode.setCurrentIndex(1);window.update_visuals()
            QTimer.singleShot(500,finish)
        elif time.monotonic()-start>120:
            (folder/"gui-error.txt").write_text(window.logs.toPlainText(),encoding="utf-8");window.close();app.exit(1)
        else:QTimer.singleShot(300,check)
    def finish():
        window.grab().save(str(folder/"desktop-professional.png"))
        window.mode.setCurrentIndex(0);window.grab().save(str(folder/"desktop-simple.png"))
        if len(window.entries)>=5:
            focus=analyze_focus([e["result"] for e in window.entries],height_calibrated=True)
            window.focus_data=focus.to_dict();window.show_focus();window.grab().save(str(folder/"desktop-focus.png"))
        (folder/"gui-smoke.json").write_text(json.dumps({"entries":len(window.entries),"analyzed":sum(bool(e["result"]) for e in window.entries),"table_rows":window.table.rowCount(),"logs":window.logs.toPlainText()},ensure_ascii=False,indent=2),encoding="utf-8")
        window.close();app.quit()
    QTimer.singleShot(500,check)
    return app.exec()
if __name__=="__main__":multiprocessing.freeze_support();raise SystemExit(main())

