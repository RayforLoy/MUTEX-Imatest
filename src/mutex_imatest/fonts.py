from pathlib import Path
def configure_fonts():
    """The Qt offscreen plugin on Windows has no system font enumeration."""
    from PySide6.QtGui import QFontDatabase,QFont,QGuiApplication
    app=QGuiApplication.instance()
    if not app:return
    families=QFontDatabase.families()
    if not families:
        for name in ["msyh.ttc","msyhbd.ttc","segoeui.ttf","segoeuib.ttf","consola.ttf"]:
            path=Path("C:/Windows/Fonts")/name
            if path.exists():QFontDatabase.addApplicationFont(str(path))
    if "Microsoft YaHei UI" in QFontDatabase.families():app.setFont(QFont("Microsoft YaHei UI",9))

