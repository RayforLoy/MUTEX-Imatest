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


def pillow_font(size):
    """Use an installed CJK font for raster legends on Windows and macOS."""
    from PIL import ImageFont
    for name in ['C:/Windows/Fonts/msyh.ttc', '/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
                 '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']:
        try:return ImageFont.truetype(name,size)
        except OSError:pass
    return ImageFont.load_default(size=size)

