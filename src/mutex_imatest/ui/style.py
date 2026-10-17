STYLE = """
QMainWindow, QDialog { background: #f4f6fa; }
QWidget { color: #20394a; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
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
