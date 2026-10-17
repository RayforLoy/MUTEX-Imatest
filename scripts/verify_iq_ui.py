"""Render the IQ setup surfaces without touching the user's active desktop."""
from pathlib import Path
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.fonts import configure_fonts
from mutex_imatest.ui.style import STYLE
from mutex_imatest.ui.iq_workbench import ProfileDialog, WorkbenchDialog


def main():
    app=QApplication([]);configure_fonts();app.setStyleSheet(STYLE)
    out=Path(__file__).resolve().parents[1]/'validation/iq-ui';out.mkdir(parents=True,exist_ok=True)
    profile=ProfileDialog(AnalysisConfig(transfer='linear'))
    profile.profile.setCurrentIndex(profile.profile.findData('colorgray44'))
    profile.show();app.processEvents()
    assert profile.grab().save(str(out/'official-chart-setup.png'))
    profile.reject()
    lab=WorkbenchDialog(AnalysisConfig(transfer='linear'))
    lab.workflow.setCurrentIndex(lab.workflow.findData('ptc'))
    lab.show();app.processEvents()
    assert lab.grab().save(str(out/'iq-workbench.png'))
    lab.reject();app.processEvents()
    print(out)


if __name__=='__main__':main()
