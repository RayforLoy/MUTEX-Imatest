"""Presentation commands preserve measurement identities and source files."""
from pathlib import Path
import copy
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from mutex_imatest.ui.main_window import MainWindow
from mutex_imatest.ui.preferences import UiPreferences,load_preferences


def test_header_menus_language_theme_and_keys_stay_in_sync(qtbot):
    window=MainWindow();qtbot.addWidget(window);window.show()
    before=copy.deepcopy(window.snapshot_config().to_dict())
    keys=[window.metric_selector.itemData(i) for i in range(window.metric_selector.count())]
    window.language_choice.setCurrentIndex(window.language_choice.findData('en'))
    qtbot.waitUntil(lambda:window.edit_menu.title()=='Edit')
    assert window.language_actions['en'].isChecked() and load_preferences().language=='en'
    window.on_zoom(27.5);assert window.zoom_label.text()=='Preview zoom: 27.5%'
    assert [window.metric_selector.itemData(i) for i in range(window.metric_selector.count())]==keys
    assert window.snapshot_config().to_dict()==before
    window.theme_actions['dark'].trigger();qtbot.wait(30)
    assert window.theme_actions['dark'].isChecked() and load_preferences().theme=='dark'
    assert window.palette().color(window.palette().ColorRole.Window).lightness()<80
    assert window.snapshot_config().to_dict()==before
    window.language_actions['zh_CN'].trigger();qtbot.waitUntil(lambda:window.edit_menu.title()=='编辑')
    assert window.language_choice.currentData()=='zh_CN'
    window.persist_preferences=False;window.close()


def test_remove_from_queue_cannot_delete_source_or_retarget_running_job(qtbot,tmp_path):
    path=tmp_path/'用户自定义文件.png';Image.new('RGB',(80,80),'white').save(path);original=path.read_bytes()
    window=MainWindow();window.persist_preferences=False;qtbot.addWidget(window);window.show()
    window.import_paths([str(path)])
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']) and window.worker.current is None,timeout=30000)
    window.images.selectAll();window.worker.pending.append(('reserved',{}))
    window.remove_selected_images();assert len(window.entries)==1 and path.read_bytes()==original
    window.worker.pending.clear();window.remove_selected_images()
    assert not window.entries and window.current_index==-1 and window.viewer.metadata is None
    assert not window.viewer.scene().items() and path.read_bytes()==original
    window.import_paths([str(path)])
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']) and window.worker.current is None,timeout=30000)
    assert window.viewer.metadata is not None and path.read_bytes()==original
    window.close()


def test_settings_import_reset_preserve_host_resources_and_old_results(qtbot,tmp_path):
    window=MainWindow();window.persist_preferences=False;qtbot.addWidget(window)
    window.config.cache_dir=str(tmp_path/'host-cache');window.config.memory_mb=1024
    window.gamma.setValue(1.8);window.config=window.snapshot_config()
    original=copy.deepcopy(window.config.to_dict())
    window.show_analysis_settings()
    assert window.mode.currentIndex()==1 and window.advanced.isVisibleTo(window)
    window.reset_analysis_config()
    assert window.gamma.value()==2.2 and window.config.cache_dir==original['cache_dir'] and window.config.memory_mb==1024
    window.overlay_action.setChecked(False);assert not window.overlay.isChecked()
    window.overlay.setChecked(True);assert window.overlay_action.isChecked()
    window.close()
