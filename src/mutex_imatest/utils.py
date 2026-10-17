from __future__ import annotations
from pathlib import Path
import hashlib, json, math, os, re, shutil, time
import numpy as np
from .models import plain

class Cancelled(Exception): pass
def check_cancel(event):
    if event is not None and event.is_set(): raise Cancelled("Cancelled")
def file_fingerprint(path, cancel=None):
    h = hashlib.sha256()
    with open(path,"rb") as f:
        while block := f.read(8*2**20):
            check_cancel(cancel); h.update(block)
    return h.hexdigest()
def atomic_json(path, data):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix+".partial")
    temp.write_text(json.dumps(plain(data), ensure_ascii=False, indent=2, allow_nan=False),encoding="utf-8")
    os.replace(temp,p)
def focus_from_name(path):
    m = re.search(r"(?:^|[_\s-])z([+-]?\d+(?:\.\d+)?)(mm|um|µm|idx)?(?:[_\s.-]|$)", Path(path).stem)
    if not m: return None, "index"
    return float(m[1]), {"mm":"mm","um":"um","µm":"um"}.get(m[2],"index")
def to_rgb8(array, linear=False, white_balance=False, exposure=0):
    a = np.asarray(array)
    a = a.astype(np.float32)/np.iinfo(a.dtype).max if a.dtype.kind in "ui" else a.astype(np.float32)
    if a.ndim==2: a=np.repeat(a[...,None],3,axis=2)
    if a.shape[2]==1: a=np.repeat(a,3,axis=2)
    a=a[...,:3]
    if white_balance:
        means=np.percentile(a.reshape(-1,3),90,axis=0)
        gains=means[1]/np.maximum(means,1e-6); a=a*gains
    a=np.nan_to_num(np.maximum(a*2**exposure,0))
    if linear: a=np.where(a<=.0031308,12.92*a,1.055*np.maximum(a,0)**(1/2.4)-.055)
    return np.ascontiguousarray(np.clip(a*255+.5,0,255).astype(np.uint8))
def cache_trim(root, limit_bytes, preserve=()):
    root=Path(root).resolve()
    entries=[]
    for p in root.iterdir():
        if p.is_dir() and not p.is_symlink() and re.fullmatch(r"[a-f0-9]{64}",p.name) and (p/"MUTEX_CACHE").is_file():
            size=sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            entries.append((p.stat().st_mtime,size,p))
    total=sum(e[1] for e in entries)
    for _,size,p in sorted(entries):
        if total<=limit_bytes: break
        if p.name in preserve: continue
        if p.resolve().parent != root: continue
        try: shutil.rmtree(p); total-=size
        except OSError: pass
    return total
