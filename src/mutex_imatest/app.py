from __future__ import annotations
import os,sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from .ui.main_window import MainWindow

def run(paths=None,demo=False):
    QApplication.setOrganizationName("MUTEX")
    QApplication.setApplicationName("MUTEX Imatest")
    app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window=MainWindow()
    icon=Path(__file__).parent/"assets"/"app.ico"
    if icon.exists():window.setWindowIcon(QIcon(str(icon)))
    window.show()
    if paths:QTimer.singleShot(100,lambda:window.import_paths(paths))
    if demo:QTimer.singleShot(200,window.open_demo)
    return app.exec()

