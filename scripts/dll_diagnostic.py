from pathlib import Path
import pefile,json
root=Path(__file__).resolve().parents[1]/"dist"/"MUTEX Imatest"/"_internal"
search=[root,root/"PySide6",root/"shiboken6",Path("C:/Windows/System32")]
paths={}
for directory in search:
    for p in directory.glob("*.dll"):paths.setdefault(p.name.lower(),p)
for p in root.rglob("*.dll"):paths.setdefault(p.name.lower(),p)
cache={}
def parse(path):
    k=str(path)
    if k not in cache:
        pe=pefile.PE(k,fast_load=False)
        cache[k]=pe
    return cache[k]
seen=set();missing=[]
def check(path):
    if str(path) in seen:return
    seen.add(str(path));pe=parse(path)
    for entry in getattr(pe,"DIRECTORY_ENTRY_IMPORT",[]):
        name=entry.dll.decode().lower()
        if name.startswith(("api-ms-","ext-ms-")):continue
        dep=paths.get(name)
        if not dep:missing.append({"module":path.name,"dependency":name,"error":"missing DLL"});continue
        other=parse(dep)
        exports={e.name for e in getattr(getattr(other,"DIRECTORY_ENTRY_EXPORT",None),"symbols",[])}
        for imp in entry.imports:
            if imp.name and imp.name not in exports:
                missing.append({"module":path.name,"dependency":str(dep),"symbol":imp.name.decode(errors="replace")})
        if str(dep).startswith(str(root)):check(dep)
check(root/"PySide6"/"QtGui.pyd")
(root.parents[1]/"validation"/"dll-diagnostic.json").write_text(json.dumps(missing,indent=2),encoding="utf-8")
print(json.dumps(missing[:12],indent=2));print("Checked DLLs",len(seen),"missing entries",len(missing))

