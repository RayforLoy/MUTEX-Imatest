# Native macOS build. GUI and CLI share one signed app bundle.
from pathlib import Path
import importlib.metadata as metadata
import platform
import sys
import tomllib
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

if sys.platform != 'darwin':
    raise RuntimeError('Build this specification on a Mac of the target architecture')
ROOT = Path(SPECPATH)
VERSION = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
datas = collect_data_files('mutex_imatest')
for directory in ['template', 'docs', 'licenses']:
    datas.append((str(ROOT / directory), directory))
bundled = ROOT / 'private_assets/bundled_templates'
if bundled.is_dir():
    datas.append((str(bundled), 'template/bundled'))
for name in ['README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
    datas.append((str(ROOT / name), '.'))
binaries = collect_dynamic_libs('rawpy') + collect_dynamic_libs('numpy')
vips = metadata.distribution('pyvips-binary')
for entry in vips.files or []:
    source = Path(vips.locate_file(entry))
    if source.suffix.lower() in {'.so', '.dylib'} and '..' not in entry.parts:
        binaries.append((str(source), str(entry.parent)))
a = Analysis([str(ROOT / 'scripts/entry.py')], pathex=[str(ROOT / 'src')],
             datas=datas, binaries=binaries,
             hiddenimports=['_libvips', 'tifffile', 'imagecodecs', 'rawpy', 'cv2', 'colour',
                            'cryptography.hazmat.bindings._rust', 'PySide6.QtSvg', 'PySide6.QtPdf',
                            'scipy.spatial._qhull', 'scipy.special._ufuncs'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
                       'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.Qt3DCore', 'PySide6.Qt3DRender',
                       'PySide6.QtTest', 'IPython', 'jupyter', 'tkinter', 'matplotlib', 'pytest',
                       'pytestqt', 'setuptools'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MUTEX Imatest', console=False,
          target_arch=platform.machine(), codesign_identity=None, argv_emulation=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MUTEX-CLI', console=True,
          target_arch=platform.machine(), codesign_identity=None)
coll = COLLECT(gui, cli, a.binaries, a.datas, name='MUTEX Imatest', strip=False, upx=False)
app = BUNDLE(coll, name='MUTEX Imatest.app', icon=str(ROOT / 'src/mutex_imatest/assets/app.icns'),
             bundle_identifier='org.mutex.imatest', version=VERSION, codesign_identity=None,
             info_plist={'CFBundleShortVersionString': VERSION, 'CFBundleVersion': VERSION,
                         'LSMinimumSystemVersion': '15.0', 'NSHighResolutionCapable': True,
                         'NSRequiresAquaSystemAppearance': False})
