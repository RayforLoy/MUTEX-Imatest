import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
from pathlib import Path
from mutex_imatest.config import AnalysisConfig
@pytest.fixture(autouse=True)
def isolate_preferences(monkeypatch,tmp_path):
    import mutex_imatest.config as module
    monkeypatch.setattr(module,"config_file",lambda:tmp_path/"settings.json")
    # Existing numerical/UI tests use deterministic presentation; production
    # remains system-language/system-theme unless a user chooses otherwise.
    from mutex_imatest.ui.preferences import UiPreferences,save_preferences
    save_preferences(UiPreferences(language='zh_CN',theme='light'))
    import mutex_imatest.templates as templates
    charts=tmp_path/'charts';charts.mkdir()
    monkeypatch.setattr(templates,'library_dir',lambda:charts)
    from mutex_imatest.ui import main_window,template_editor
    monkeypatch.setattr(main_window,'library_dir',lambda:charts)
    monkeypatch.setattr(template_editor,'library_dir',lambda:charts)
@pytest.fixture
def config(tmp_path):
    return AnalysisConfig(transfer="linear",cache_dir=str(tmp_path/"cache"),memory_mb=1024)

