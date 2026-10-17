from __future__ import annotations
import json
from pathlib import Path
import numpy as np

def linearize(raw,config,source_linear=False):
    raw=np.asarray(raw)
    a=raw.astype(np.float64)/np.iinfo(raw.dtype).max if raw.dtype.kind in "ui" else raw.astype(np.float64)
    if source_linear or config.transfer in {"linear","unknown"}: return a
    if config.transfer=="srgb": return np.where(a<=.04045,a/12.92,np.maximum((a+.055)/1.055,0)**2.4)
    if config.transfer=="gamma": return np.maximum(a,0)**config.gamma
    data=json.loads(Path(config.oecf_path).read_text(encoding="utf-8"))
    x=np.asarray(data["encoded"],float); y=np.asarray(data["linear"],float)
    if len(x)<3 or len(x)!=len(y) or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)) or not np.all(np.diff(x)>0) or not np.all(np.diff(y)>=0) or min(x[0],y[0])<0 or max(x[-1],y[-1])>1:
        raise ValueError("OECF must contain equal monotonic encoded/linear arrays in [0,1]")
    return np.interp(a,x,y)

def channel_image(a,channel):
    if a.ndim==2: return a
    if a.shape[-1]==1: return a[...,0]
    if channel=="Y": return np.einsum("ijk,k->ij",a[...,:3],[.2126,.7152,.0722])
    return a[...,{"R":0,"G":1,"B":2}[channel]]

def clipping_fraction(raw):
    a=np.asarray(raw)
    if a.dtype.kind in "ui": return float(np.mean((a<=0)|(a>=np.iinfo(a.dtype).max)))
    return float(np.mean(~np.isfinite(a)|(a<=0)|(a>=1)))
