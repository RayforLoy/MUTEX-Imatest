# PyInstaller portable, dynamic Qt/LibRaw/vips; GUI and console share _internal.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files,collect_dynamic_libs
import importlib.metadata as metadata
import PySide6
ROOT=Path(SPECPATH)
datas=collect_data_files("mutex_imatest")
# Documentation, licences and printable charts are copied once beside the EXE.
binaries=collect_dynamic_libs("rawpy")
binaries += collect_dynamic_libs("numpy")
# pyvips-binary keeps its vendored extension and DLL at site-packages root.
for file in metadata.distribution("pyvips-binary").files or []:
    source=Path(metadata.distribution("pyvips-binary").locate_file(file))
    if source.suffix.lower() in {".pyd",".dll"}:binaries.append((str(source),"."))
    if source.name.startswith(".load-order-"):datas.append((str(source),"."))
hiddenimports=["_libvips","tifffile","imagecodecs","rawpy","cv2","colour","cryptography.hazmat.bindings._rust",
               "PySide6.QtSvg","PySide6.QtPdf","scipy.spatial._qhull","scipy.special._ufuncs"]
a=Analysis([str(ROOT/"scripts"/"entry.py")],pathex=[str(ROOT/"src")],
           binaries=binaries,datas=datas,hiddenimports=hiddenimports,
           excludes=["PySide6.QtWebEngineCore","PySide6.QtWebEngineWidgets","PySide6.QtWebEngineQuick",
                     "PySide6.QtQml","PySide6.QtQuick","PySide6.Qt3DCore","PySide6.Qt3DRender",
                     "PySide6.QtTest",
                     "IPython","jupyter","tkinter","matplotlib","pytest","pytestqt","setuptools"],
           noarchive=False)
# Qt 6.12 uses the Windows system ICU with unsuffixed exports. Do not collect
# incompatible Poppler ICU DLLs from the developer host's unrelated PATH.
a.binaries=[entry for entry in a.binaries if not Path(entry[0]).name.lower().startswith(("icuuc", "icuin", "icudt"))]
# The application and pyqtgraph use the raster QWidget renderer. Default Qt
# hooks also collect a virtual keyboard and its QML/Quick tree; neither is used.
# pyqtgraph imports QtOpenGL bindings even for raster plots, so retain those.
# Keep Windows/offscreen platforms, SVG/PDF/image codecs and scientific/RAW DLLs.
def unused_qt_binary(entry):
    path=Path(entry[0])
    return (path.name.lower().startswith(("qt6qml", "qt6quick", "qt6virtualkeyboard"))
            or path.name.lower()=="opengl32sw.dll"
            or "platforminputcontexts" in path.parts)
a.binaries=[entry for entry in a.binaries if not unused_qt_binary(entry)]
# Prefer one current MSVC runtime in the shared root, matching the Qt wheel.
runtime_names={"vcruntime140.dll","vcruntime140_1.dll","msvcp140.dll","msvcp140_1.dll","msvcp140_2.dll"}
a.binaries=[entry for entry in a.binaries if Path(entry[0]).name.lower() not in runtime_names]
for name in runtime_names:
    source=Path(PySide6.__file__).resolve().parent/name
    if source.exists():a.binaries.append((name,str(source),"BINARY"))
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name="MUTEX Imatest",console=False,
        icon=str(ROOT/"src"/"mutex_imatest"/"assets"/"app.ico"),uac_admin=False)
cli=EXE(pyz,a.scripts,[],exclude_binaries=True,name="MUTEX-CLI",console=True,
        icon=str(ROOT/"src"/"mutex_imatest"/"assets"/"app.ico"),uac_admin=False)
coll=COLLECT(gui,cli,a.binaries,a.datas,name="MUTEX Imatest",strip=False,upx=False)
# Keep redistributable resources visible, once, beside the executable.
import shutil
target=Path(DISTPATH)/'MUTEX Imatest'
for directory in ['template','docs','licenses']:
    shutil.copytree(ROOT/directory,target/directory,dirs_exist_ok=True)
bundled=ROOT/'private_assets'/'bundled_templates'
if bundled.is_dir():
    shutil.copytree(bundled,target/'template'/'bundled',dirs_exist_ok=True)
for filename in ['LICENSE','README.md','THIRD_PARTY_NOTICES.md']:
    shutil.copyfile(ROOT/filename,target/filename)

