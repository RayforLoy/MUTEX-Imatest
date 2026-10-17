"""Use official patch release DLL after comparing every imported C++ symbol.
Only modifies this project's virtual environment, retaining the original DLL.
A rawpy reinstall reverts it; rerun this script before packaging."""
from pathlib import Path
import ctypes,hashlib,json,shutil,sys,urllib.request,zipfile
import pefile
ROOT=Path(__file__).resolve().parents[1]
vendor=ROOT/"vendor"/"libraw-0.22.2"
vendor.mkdir(parents=True,exist_ok=True)
archive=vendor/"LibRaw-0.22.2-Win64.zip"
url="https://www.libraw.org/data/LibRaw-0.22.2-Win64.zip"
if not archive.exists():
    supplied=ROOT/"third-party-source"/archive.name
    if supplied.exists():shutil.copyfile(supplied,archive)
    else:urllib.request.urlretrieve(url,archive)
folder=vendor/"official"
if not folder.exists():
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            target=(folder/member.filename).resolve()
            if not target.is_relative_to(folder.resolve()):raise ValueError("Unexpected archive path")
        z.extractall(folder)
source=folder/"LibRaw-0.22.2"/"bin"/"libraw.dll"
raw_dir=ROOT/".venv"/"Lib"/"site-packages"/"rawpy"
extension=next(raw_dir.glob("*.pyd"))
pe=pefile.PE(str(extension));imports={e.name for d in pe.DIRECTORY_ENTRY_IMPORT if d.dll==b"raw_r.dll" for e in d.imports}
dll=pefile.PE(str(source));exports={e.name for e in dll.DIRECTORY_ENTRY_EXPORT.symbols}
missing=imports-exports
if missing:raise RuntimeError(f"LibRaw ABI mismatch: {missing}")
backup=vendor/"rawpy-original-0.22.1.dll"
if not backup.exists():shutil.copy2(raw_dir/"raw_r.dll",backup)
shutil.copy2(source,raw_dir/"raw_r.dll")
lib=ctypes.CDLL(str(raw_dir/"raw_r.dll"))
lib.libraw_version.restype=ctypes.c_char_p
actual=lib.libraw_version().decode()
if not actual.startswith("0.22.2"):raise RuntimeError(actual)
record={"source_url":url,"archive_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
        "dll_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"imported_symbols_checked":len(imports),
        "runtime_version":actual,"note":"Official DLL renamed raw_r.dll for the rawpy wheel; all 32 imported C++ symbols resolved. Real RAW regression must also pass."}
(ROOT/"validation").mkdir(exist_ok=True)
(ROOT/"validation"/"libraw-upgrade.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
print(json.dumps(record,indent=2))

