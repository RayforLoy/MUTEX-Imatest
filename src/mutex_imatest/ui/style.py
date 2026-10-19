def apply_light_theme(app):
    """Use one complete palette instead of mixing QSS with the Windows theme."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setStyle("Fusion")
    palette=QPalette()
    colors={
        "Window":"#f4f6fa", "WindowText":"#20394a", "Base":"#ffffff",
        "AlternateBase":"#f3f7fa", "Text":"#20394a", "Button":"#ffffff",
        "ButtonText":"#20394a", "BrightText":"#ffffff",
        "ToolTipBase":"#173d4b", "ToolTipText":"#ffffff",
        "Highlight":"#137b80", "HighlightedText":"#ffffff",
        "Link":"#126b74", "LinkVisited":"#596c9b", "PlaceholderText":"#738795",
        "Light":"#ffffff", "Midlight":"#e7edf2", "Mid":"#ccd9e1",
        "Dark":"#738795", "Shadow":"#28485a", "Accent":"#137b80",
    }
    for name,color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole,name),QColor(color))
    for name in ("WindowText","Text","ButtonText","PlaceholderText"):
        palette.setColor(QPalette.ColorGroup.Disabled,getattr(QPalette.ColorRole,name),QColor("#83939f"))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Highlight,QColor("#deedf1"))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.HighlightedText,QColor("#617684"))
    app.setPalette(palette)
    app.setProperty('mutexTheme', 'light')


STYLE = """
QMainWindow, QDialog { background: #f4f6fa; }
QWidget { color: #20394a; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
QMenuBar, QMenu { background: #f4f6fa; color: #20394a; }
QMenuBar::item:selected, QMenu::item:selected { background: #deedf1; color: #126b74; }
QMenu::item:disabled { color: #83939f; }
QComboBox QAbstractItemView { background: white; color: #20394a; selection-background-color: #deedf1; selection-color: #126b74; }
QTableCornerButton::section { background: #f3f7fa; border: none; }
QLabel#brand { font-size: 22px; font-weight: 700; color: #123c4a; }
QLabel#subtitle { color: #738795; font-size: 11px; }
QLabel#section { font-size: 13px; font-weight: 700; color: #28485a; }
QLabel#bigValue { font-size: 28px; font-weight: 600; color: #137b80; }
QLabel#pill { background: #e2f2ee; color: #22776b; border-radius: 10px; padding: 5px 12px; }
QFrame#card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; }
QFrame#sidebar { background: #f9fbfd; border-right: 1px solid #e0e7ee; }
QPushButton { background: white; border: 1px solid #d8e2ea; border-radius: 6px; padding: 7px 12px; min-height: 18px; }
QPushButton:hover { background: #edf5f7; border-color: #96b7bf; }
QPushButton:pressed { background: #ddecef; }
QPushButton:disabled { color: #a1afb7; background: #f1f4f7; }
QPushButton#primary { background: #137b80; color: white; border: 1px solid #137b80; font-weight: 600; }
QPushButton#primary:hover { background: #10686c; }
QPushButton#primary:disabled { background: #a8c8c9; border-color: #a8c8c9; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: white; border: 1px solid #dce4ec; border-radius: 5px; padding: 5px; min-height: 18px; }
QComboBox::drop-down { border: none; width: 20px; }
QTextEdit, QPlainTextEdit { background: white; border: 1px solid #dce4ec; border-radius: 5px; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 9px 6px; border-radius: 6px; margin: 2px 0; }
QListWidget::item:selected { background: #deedf1; color: #126b74; }
QListWidget::item:hover { background: #eaf2f5; }
QTabWidget::pane { background: white; border: 1px solid #e1e8ef; border-radius: 8px; }
QTabBar::tab { background: transparent; padding: 9px 17px; color: #738694; }
QTabBar::tab:selected { color: #147980; border-bottom: 2px solid #147980; font-weight: 600; }
QTableWidget { background: white; border: none; gridline-color: #edf1f5; selection-background-color: #e2f0f2; selection-color: #20394a; }
QHeaderView::section { background: #f3f7fa; border: none; border-bottom: 1px solid #e1e8ef; padding: 7px; font-weight: 600; color: #617684; }
QProgressBar { background: #e7eef2; border: none; border-radius: 3px; max-height: 6px; }
QProgressBar::chunk { background: #148489; border-radius: 3px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #ccd9e1; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #e7edf2; }
QGroupBox { border: 1px solid #dde6ee; border-radius: 7px; margin-top: 10px; padding-top: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #4a6577; }
QToolTip { background: #173d4b; color: white; border: 0; padding: 5px; }
"""

# One palette and matching stylesheet are applied together, including popup
# menus. Source previews and image pixels are never recolored.
DARK_REPLACEMENTS = {
    '#f4f6fa':'#171f2b', '#20394a':'#dce6ee', '#deedf1':'#244a50',
    '#126b74':'#78d5d8', '#83939f':'#8b98a7', '#f3f7fa':'#242f3e',
    '#123c4a':'#d7eef4', '#738795':'#a9b8c7', '#28485a':'#c2d4e1',
    '#137b80':'#31a4a9', '#e2f2ee':'#173f3d', '#22776b':'#86ded0',
    '#e2e8f0':'#344558', '#f9fbfd':'#1d2735', '#e0e7ee':'#344558',
    '#d8e2ea':'#405167', '#edf5f7':'#304351', '#96b7bf':'#5d9da8',
    '#ddecef':'#284a52', '#a1afb7':'#778697', '#f1f4f7':'#232d3a',
    '#a8c8c9':'#355759', '#dce4ec':'#3b4d63', '#eaf2f5':'#2b3e4e',
    '#e1e8ef':'#344558', '#738694':'#b4c1cd', '#147980':'#76d1d7',
    '#edf1f5':'#344354', '#e2f0f2':'#2b4b55', '#617684':'#b2c2d1',
    '#e7eef2':'#303e50', '#148489':'#4ec6c9', '#ccd9e1':'#536276',
    '#e7edf2':'#334254', '#dde6ee':'#405167', '#4a6577':'#bacdda',
    '#e9eef3':'#202b3a', '#e5ebf0':'#202b3a',
    '#147565':'#8ad9c6', '#986200':'#f1c26c', '#b33c35':'#ffaaa0', '#936500':'#eac777',
    '#285875':'#9bcbea', '#5a6c7a':'#b5c5d2', '#798793':'#b5c5d2',
    '#fff6e4':'#433821', '#77500f':'#f5d28f', '#c99b3b':'#d8aa51',
}


def themed_stylesheet(source, theme):
    if theme != 'dark':
        return source
    import re
    text = re.sub(r'#[0-9a-fA-F]{6}', lambda m: DARK_REPLACEMENTS.get(m.group().lower(),m.group()), source)
    # QSS named white backgrounds are only chrome; image pixmaps are untouched.
    text = re.sub(r'(background(?:-color)?\s*:\s*)white\b', r'\1#202c3b', text)
    # Primary buttons keep bright text on teal, even after global recoloring.
    return text


DARK_STYLE = themed_stylesheet(STYLE, 'dark')+"""
QPushButton#primary { background: #176e75; border-color: #33848b; color: white; }
QPushButton#primary:hover { background: #1e7d84; }
QPushButton#primary:disabled { background: #355759; color: #aab8c7; }
"""


def apply_dark_theme(app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPalette
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    app.setStyle('Fusion')
    palette = QPalette()
    colors = {
        'Window':'#171f2b', 'WindowText':'#dce6ee', 'Base':'#202c3b',
        'AlternateBase':'#242f3e', 'Text':'#dce6ee', 'Button':'#202c3b',
        'ButtonText':'#dce6ee', 'BrightText':'#ffffff',
        'ToolTipBase':'#294957', 'ToolTipText':'#ffffff',
        'Highlight':'#2a6971', 'HighlightedText':'#ffffff',
        'Link':'#78d5d8', 'LinkVisited':'#c0a7e6', 'PlaceholderText':'#a9b8c7',
        'Light':'#4b5e73', 'Midlight':'#3e4e62', 'Mid':'#344558',
        'Dark':'#111820', 'Shadow':'#080e15', 'Accent':'#4ec6c9',
    }
    for name,color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole,name),QColor(color))
    for name in ('WindowText','Text','ButtonText','PlaceholderText'):
        palette.setColor(QPalette.ColorGroup.Disabled,getattr(QPalette.ColorRole,name),QColor('#7c899b'))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Base,QColor('#242d3a'))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Button,QColor('#242d3a'))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.Highlight,QColor('#394352'))
    palette.setColor(QPalette.ColorGroup.Disabled,QPalette.ColorRole.HighlightedText,QColor('#96a4b5'))
    app.setPalette(palette)
    app.setProperty('mutexTheme','dark')


def is_dark():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return bool(app and app.property('mutexTheme') == 'dark')


def chrome_colors():
    if is_dark():
        return {'enabled':'#9be3e3','disabled':'#8894a6','base':'#202c3b',
                'disabled_base':'#29313e','selected':'#2a4e54','secondary':'#b2c1cf',
                'canvas':'#202b3a','axis':'#aabacb'}
    return {'enabled':'#075f66','disabled':'#858b94','base':'#ffffff',
            'disabled_base':'#eef0f3','selected':'#d5efec','secondary':'#617986',
            'canvas':'#e9eef3','axis':'#657986'}


def apply_widget_theme(window, theme):
    """Adapt local chrome and plots without changing source images or data."""
    from PySide6.QtWidgets import QWidget,QGraphicsView,QApplication
    from PySide6.QtGui import QColor,QPalette
    window.setStyleSheet(DARK_STYLE if theme == 'dark' else STYLE)
    # Widgets created under a previous QSS can retain a resolved light palette
    # until their first polish. Apply the matching palette immediately too.
    window.setPalette(QApplication.palette())
    colors = chrome_colors()
    for widget in [window,*window.findChildren(QWidget)]:
        if widget is not window:
            current = widget.styleSheet()
            record = getattr(widget,'_mutex_style_source',None)
            if record is None or current != record[1]:
                record = (current,current)
            source = record[0]
            transformed = themed_stylesheet(source,theme)
            if current != transformed: widget.setStyleSheet(transformed)
            widget._mutex_style_source = (source,transformed)
        if isinstance(widget,QGraphicsView):
            if hasattr(widget,'setBackground') and hasattr(widget,'getPlotItem'):
                widget.setBackground(colors['base'])
                for axis in ('bottom','left','top','right'):
                    item = widget.getAxis(axis)
                    item.setPen(QColor(colors['axis']));item.setTextPen(QColor(colors['axis']))
            elif widget.__class__.__name__ in {'ImageViewer','RoiCanvas'}:
                widget.setBackgroundBrush(QColor(colors['canvas']))
        if widget.__class__.__name__ == 'MetricChecklist':
            widget.viewport().update()
        if widget.__class__.__name__ == 'TemplateComboBox':
            widget.view().viewport().update()
    window.update()
