"""User-visible template browsing, recoverable edits and encrypted exchange."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import cv2
import pytest
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication,QCheckBox,QDialog,QDialogButtonBox,
                              QPushButton)

from mutex_imatest import templates,template_library
from mutex_imatest.models import ImageMetadata
from mutex_imatest.ui import template_manager as manager_ui
from mutex_imatest.ui.template_editor import TemplateEditor
from mutex_imatest.ui.main_window import MainWindow
from mutex_imatest.ui.template_widgets import TemplateComboBox,TemplatePreview


PASSWORD='ui-chart-pass-2026'


@pytest.fixture(autouse=True)
def isolated_library(monkeypatch):
    cv2.setNumThreads(1)
    root=templates.library_dir()
    monkeypatch.setattr(template_library,'library_dir',lambda:root)
    monkeypatch.setattr(manager_ui,'library_dir',lambda:root)
    return root


@pytest.fixture
def public_chart():
    return next(c for c in templates.public_charts() if c.id=='public-generic-checkerboard-v1')


def button(widget,text):
    return next(b for b in widget.findChildren(QPushButton) if b.text()==text)


def fingerprint(paths):
    return {str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}


def source_files(chart):
    root=templates.public_template_dir()
    return [Path(chart.source_path),Path(chart.preview),root/'definitions'/'generic-checkerboard.json']


def modal_interaction(qtbot,expected,callback):
    """Drive the real modal dialog once its nested Qt loop becomes active."""
    seen=[]
    def interact():
        dialog=QApplication.activeModalWidget()
        try:
            assert isinstance(dialog,expected)
            qtbot.addWidget(dialog);seen.append(dialog);callback(dialog)
        finally:
            # An assertion should fail the test, never leave exec() blocked.
            if dialog is not None and dialog.isVisible():dialog.reject()
    QTimer.singleShot(0,interact)
    return seen


def enter_password(qtbot,*,password=PASSWORD,confirm=PASSWORD):
    def interact(dialog):
        qtbot.keyClicks(dialog.secret,password)
        if dialog.exporting:qtbot.keyClicks(dialog.confirm,confirm)
        controls=dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(controls.button(QDialogButtonBox.StandardButton.Ok),Qt.MouseButton.LeftButton)
    return modal_interaction(qtbot,manager_ui.TemplatePasswordDialog,interact)


def test_main_template_selection_loads_actual_preview_and_labels_zoom(qtbot,public_chart,tmp_path):
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    window.config.cache_dir=str(tmp_path/'cache');window.resize(1450,980);window.show()
    try:
        assert isinstance(window.chart_combo,TemplateComboBox)
        assert isinstance(window.template_preview,TemplatePreview)
        index=window.chart_combo.findData(public_chart.id)
        assert index>=0 and not window.chart_combo.itemIcon(index).isNull()
        window.chart_combo.setCurrentIndex(index)
        qtbot.waitUntil(lambda:window.current_chart().id==public_chart.id)
        assert window.template_preview.original.toImage()==QPixmap(public_chart.preview).toImage()
        assert not window.template_preview.image.pixmap().isNull()
        assert '棋盘格' in window.template_preview.info.text()
        assert '未确认' in window.template_preview.info.text()
        assert window.registration.currentData()=='auto_chart'
        assert window.metric_selector.currentData()=='projective_residual_rms_px'
        assert window.zoom_label.text().startswith('预览缩放：')
        assert '不是分析完成进度' in window.zoom_label.toolTip()
        from PIL import Image
        source=Path(public_chart.preview);w,h=Image.open(source).size
        before=source.read_bytes()
        metadata=ImageMetadata(str(source),w,h,3,'uint8',8,len(before),hashlib.sha256(before).hexdigest())
        window.viewer.load(source,metadata,window.config)
        qtbot.mouseClick(button(window,'100%'),Qt.MouseButton.LeftButton)
        assert window.zoom_label.text()=='预览缩放：100.0%'
        assert source.read_bytes()==before
        assert window.progress.value()==0
    finally:window.close()


def test_template_toolbar_menu_opens_real_manager_for_selected_chart(qtbot,public_chart):
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    try:
        window.chart_combo.setCurrentIndex(window.chart_combo.findData(public_chart.id))
        assert window.template_menu.title()=='图卡模板'
        assert window.templates_button.menu() is window.template_menu
        actions={a.text():a for a in window.template_menu.actions()}
        assert {'模板管理…','新建 / 导入 SVG、PDF…','编辑当前模板…','导入模板包…','导出当前模板（加密）…'}<=set(actions)
        def inspect(dialog):
            assert dialog.current_chart().id==public_chart.id
            assert dialog.preview.original.toImage()==QPixmap(public_chart.preview).toImage()
            index=next(i for i,c in enumerate(dialog.charts) if c.id=='public-generic-siemens-slanted-v1')
            dialog.list.setCurrentRow(index)
            qtbot.mouseClick(dialog.use_button,Qt.MouseButton.LeftButton)
        seen=modal_interaction(qtbot,manager_ui.TemplateManager,inspect)
        actions['模板管理…'].trigger()
        assert len(seen)==1
        assert window.current_chart().id=='public-generic-siemens-slanted-v1'
        assert window.template_preview.original.toImage()==QPixmap(window.current_chart().preview).toImage()
    finally:window.close()


@pytest.mark.parametrize('source',['public','builtin'])
def test_template_manager_protects_read_only_originals_and_searches(qtbot,public_chart,source):
    chart=public_chart if source=='public' else templates.builtin_chart()
    manager=manager_ui.TemplateManager(chart);qtbot.addWidget(manager);manager.show()
    assert manager.current_chart().id==chart.id
    assert not manager.rename_button.isEnabled() and not manager.archive_button.isEnabled()
    assert manager.edit_button.isEnabled() and button(manager,'复制到用户库').isEnabled()
    if source=='public':
        assert '只读' in manager.origin.text()
        assert not manager.list.currentItem().icon().isNull()
        qtbot.keyClicks(manager.search,'9')
        assert not manager.list.currentItem().isHidden()
        manager.search.setText('no-such-template-012345')
        assert all(manager.list.item(i).isHidden() for i in range(manager.list.count()))
        manager.search.clear()
        assert not manager.list.currentItem().isHidden()
    manager.reject()


def test_manager_copy_rename_archive_and_restore_preserve_source(qtbot,public_chart,isolated_library,monkeypatch):
    before=fingerprint(source_files(public_chart))
    manager=manager_ui.TemplateManager(public_chart);qtbot.addWidget(manager);manager.show()
    with qtbot.waitSignal(manager.library_changed,timeout=2000):
        qtbot.mouseClick(button(manager,'复制到用户库'),Qt.MouseButton.LeftButton)
    copied=manager.current_chart();definition=template_library.user_chart_path(copied)
    assert copied.id!=public_chart.id and copied.name.endswith(' · 副本')
    assert definition is not None and definition.parent==isolated_library.resolve()
    assert [r.__dict__ for r in copied.regions]==[r.__dict__ for r in public_chart.regions]
    assert copied.physical_size_mm==public_chart.physical_size_mm
    assert manager.rename_button.isEnabled() and manager.archive_button.isEnabled()
    monkeypatch.setattr(manager_ui.QInputDialog,'getText',lambda *a,**k:('My calibrated checkerboard',True))
    qtbot.mouseClick(manager.rename_button,Qt.MouseButton.LeftButton)
    renamed=manager.current_chart();saved=definition.read_bytes()
    assert renamed.id==copied.id and templates.load_chart(definition).name=='My calibrated checkerboard'
    qtbot.mouseClick(manager.archive_button,Qt.MouseButton.LeftButton)
    assert not definition.exists() and '可恢复' in manager.status.text()
    archived=list((isolated_library/'backups').glob('archive-*/*.json'))
    assert len(archived)==1 and archived[0].read_bytes()==saved
    assert not any(c.id==copied.id for c in templates.available_charts())
    assert fingerprint(source_files(public_chart))==before
    # The archive is a complete, recoverable definition; preview/source were
    # deliberately left where they were, so restoring requires no artwork copy.
    shutil.copyfile(archived[0],definition)
    manager.refresh(copied.id)
    assert manager.current_chart().id==copied.id
    assert manager.current_chart().name=='My calibrated checkerboard'
    assert manager.preview.original.toImage()==QPixmap(public_chart.preview).toImage()
    assert fingerprint(source_files(public_chart))==before
    manager.reject()


def test_editing_public_template_saves_user_copy_through_editor(qtbot,public_chart,isolated_library):
    before=fingerprint(source_files(public_chart))
    manager=manager_ui.TemplateManager(public_chart);qtbot.addWidget(manager);manager.show()
    def save_copy(editor):
        assert editor.chart.id!=public_chart.id
        assert editor.chart.regions[0].params==public_chart.regions[0].params
        editor.name.setText('Edited checkerboard copy')
        editor.width.setValue(296.5);editor.calibrated.setChecked(True)
        qtbot.mouseClick(editor.save_button,Qt.MouseButton.LeftButton)
    seen=modal_interaction(qtbot,TemplateEditor,save_copy)
    qtbot.mouseClick(manager.edit_button,Qt.MouseButton.LeftButton)
    assert len(seen)==1
    saved=manager.current_chart()
    assert saved.id!=public_chart.id and saved.name=='Edited checkerboard copy'
    assert saved.calibrated and saved.physical_size_mm==(296.5,210.)
    assert len(list(isolated_library.glob('*.json')))==1
    loaded=templates.load_chart(isolated_library/(saved.id+'.json'))
    assert loaded.to_dict()==saved.to_dict()
    assert public_chart.physical_size_mm==(297.,210.) and not public_chart.calibrated
    assert fingerprint(source_files(public_chart))==before
    manager.reject()


@pytest.mark.parametrize('password,confirm,expected',[('short','short','至少'),(PASSWORD,'different-password','不一致')])
def test_export_password_validation_then_cancel_leaves_no_output(qtbot,public_chart,tmp_path,monkeypatch,password,confirm,expected):
    destination=tmp_path/'cancelled-export.mxtpl'
    monkeypatch.setattr(manager_ui.QFileDialog,'getSaveFileName',lambda *a,**k:(str(destination),'MUTEX 加密模板'))
    before=public_chart.to_dict();source_before=fingerprint(source_files(public_chart))
    def reject_invalid(dialog):
        qtbot.keyClicks(dialog.secret,password);qtbot.keyClicks(dialog.confirm,confirm)
        controls=dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(controls.button(QDialogButtonBox.StandardButton.Ok),Qt.MouseButton.LeftButton)
        assert dialog.isVisible() and dialog.result()!=QDialog.DialogCode.Accepted
        assert expected in dialog.error.text()
        qtbot.mouseClick(controls.button(QDialogButtonBox.StandardButton.Cancel),Qt.MouseButton.LeftButton)
    seen=modal_interaction(qtbot,manager_ui.TemplatePasswordDialog,reject_invalid)
    assert manager_ui.export_template_dialog(public_chart) is None
    assert len(seen)==1 and seen[0].password is None
    assert not seen[0].secret.text() and not seen[0].confirm.text()
    assert not destination.exists() and not list(tmp_path.glob('*.mxtpl'))
    assert public_chart.to_dict()==before and fingerprint(source_files(public_chart))==source_before


def test_file_dialog_cancel_and_password_visibility_are_explicit(qtbot,public_chart,tmp_path,monkeypatch):
    monkeypatch.setattr(manager_ui.QFileDialog,'getSaveFileName',lambda *a,**k:('',''))
    assert manager_ui.export_template_dialog(public_chart) is None
    dialog=manager_ui.TemplatePasswordDialog(export=True);qtbot.addWidget(dialog);dialog.show()
    qtbot.keyClicks(dialog.secret,PASSWORD);qtbot.keyClicks(dialog.confirm,PASSWORD)
    assert dialog.secret.echoMode()==dialog.secret.EchoMode.Password
    visible=dialog.findChild(QCheckBox);visible.setFocus()
    qtbot.keyClick(visible,Qt.Key.Key_Space)
    assert dialog.secret.echoMode()==dialog.secret.EchoMode.Normal
    assert dialog.confirm.echoMode()==dialog.confirm.EchoMode.Normal
    dialog.reject()
    assert dialog.password is None and not dialog.secret.text() and not dialog.confirm.text()
    assert not list(tmp_path.glob('*.mxtpl'))


def test_ui_helpers_roundtrip_real_aes_and_install_once(qtbot,public_chart,isolated_library,tmp_path,monkeypatch):
    chart=copy.deepcopy(public_chart);chart.id='ui-roundtrip-checkerboard';chart.name='UI roundtrip checkerboard'
    chart.calibrated=True;chart.aliases=['old-ui-template'];chart.notes='保留标定和测量参数'
    chart.fiducials=[{'kind':'point','position':[.15,.25]}]
    before=copy.deepcopy(chart.to_dict());source_before=fingerprint(source_files(public_chart))
    base=tmp_path/'portable-checkerboard'
    monkeypatch.setattr(manager_ui.QFileDialog,'getSaveFileName',lambda *a,**k:(str(base),'MUTEX 加密模板'))
    exported_dialogs=enter_password(qtbot)
    destination=manager_ui.export_template_dialog(chart)
    assert destination==base.with_suffix('.mxtpl') and destination.is_file()
    assert exported_dialogs[0].password is None and not exported_dialogs[0].secret.text()
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist())=={'manifest.json','encrypted.bin'}
        metadata=json.loads(archive.read('manifest.json'))
        assert metadata['cipher']=='AES-256-GCM'
        assert all(item.compress_type==zipfile.ZIP_DEFLATED for item in archive.infolist())
    imported_dialogs=enter_password(qtbot)
    decoded=manager_ui.load_chart_dialog(destination)
    expected=copy.deepcopy(before);expected['source_path']=None;expected['preview']=decoded.preview
    assert decoded.to_dict()==expected
    assert imported_dialogs[0].password is None and Path(decoded.preview).is_file()
    assert chart.to_dict()==before and fingerprint(source_files(public_chart))==source_before
    monkeypatch.setattr(manager_ui.QFileDialog,'getOpenFileName',lambda *a,**k:(str(destination),'MUTEX 加密模板'))
    enter_password(qtbot);installed=manager_ui.import_template_dialog()
    enter_password(qtbot);again=manager_ui.import_template_dialog()
    assert installed.id==again.id and installed.id!=chart.id
    definitions=list(isolated_library.glob('*.json'))
    assert len(definitions)==1
    assert templates.load_chart(definitions[0]).to_dict()==installed.to_dict()
    assert installed.regions[0].params==chart.regions[0].params
    assert installed.calibrated and installed.fiducials==chart.fiducials
    assert installed.asset_license==chart.asset_license
    assert len([c for c in templates.available_charts() if c.name==chart.name])==1


def test_ui_wrong_password_does_not_create_import_cache(qtbot,public_chart,isolated_library,tmp_path,monkeypatch):
    destination=tmp_path/'encrypted.mxtpl'
    monkeypatch.setattr(manager_ui.QFileDialog,'getSaveFileName',lambda *a,**k:(str(destination),'MUTEX 加密模板'))
    enter_password(qtbot);manager_ui.export_template_dialog(public_chart)
    before={p.relative_to(isolated_library) for p in isolated_library.rglob('*')}
    dialogs=enter_password(qtbot,password='wrong-ui-password')
    from mutex_imatest.chart_package import ChartPackagePasswordError
    with pytest.raises(ChartPackagePasswordError):manager_ui.load_chart_dialog(destination)
    assert dialogs[0].password is None and not dialogs[0].secret.text()
    assert {p.relative_to(isolated_library) for p in isolated_library.rglob('*')}==before
