"""Regression for a light-QSS window launched under a dark Windows palette."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QPalette
from mutex_imatest.ui.style import apply_light_theme
from mutex_imatest.ui.main_window import MainWindow


@pytest.mark.parametrize("system_dark",[False,True])
def test_system_palette_cannot_leave_dark_panels_or_unreadable_menus(qapp,qtbot,tmp_path,system_dark):
    original=QPalette(qapp.palette())
    original_scheme=qapp.styleHints().colorScheme()
    palette=QPalette()
    background="#202020" if system_dark else "#f0f0f0"
    foreground="#eeeeee" if system_dark else "#202020"
    for role in (QPalette.ColorRole.Window,QPalette.ColorRole.Base,QPalette.ColorRole.Button):
        palette.setColor(role,QColor(background))
    for role in (QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText):
        palette.setColor(role,QColor(foreground))
    palette.setColor(QPalette.ColorRole.Highlight,QColor("#ff00ff"))
    qapp.styleHints().setColorScheme(Qt.ColorScheme.Dark if system_dark else Qt.ColorScheme.Light)
    qapp.setPalette(palette)
    window=None
    try:
        apply_light_theme(qapp)
        window=MainWindow();window.persist_preferences=False
        qtbot.addWidget(window);window.mode.setCurrentIndex(1);window.show()
        qapp.processEvents()
        for group in (QPalette.ColorGroup.Active,QPalette.ColorGroup.Inactive):
            current=window.palette()
            assert current.color(group,QPalette.ColorRole.Window).name()=="#f4f6fa"
            assert current.color(group,QPalette.ColorRole.Text).name()=="#20394a"
            assert current.color(group,QPalette.ColorRole.Highlight).name()=="#137b80"
        assert window.advanced.palette().color(QPalette.ColorRole.Window).lightness()>230
        menu=window.menuBar().grab().toImage()
        assert menu.pixelColor(menu.width()-4,2).lightness()>230
        assert window.grab().save(str(tmp_path/f"theme-{'dark' if system_dark else 'light'}.png"))
    finally:
        if window is not None:window.close()
        qapp.styleHints().setColorScheme(original_scheme)
        qapp.setPalette(original)
