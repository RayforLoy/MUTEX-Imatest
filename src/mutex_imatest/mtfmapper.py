from __future__ import annotations
from pathlib import Path
import os,subprocess,json
from .utils import atomic_json

def run_mapper(executable,image,output,extra_args=None):
    """Launch an installed MTF Mapper separately; never silently replace native data."""
    exe=Path(executable)
    image=Path(image).resolve();out=Path(output).resolve()
    if not exe.is_file():raise ValueError("请先安装 MTF Mapper，并在资源设置填写可执行文件路径")
    if not image.is_file():raise FileNotFoundError(image)
    if image.suffix.lower() not in {".tif",".tiff",".png",".pgm",".ppm",".jpg",".jpeg"}:
        raise ValueError("MTF Mapper 复核请使用无锐化 16-bit TIFF；RAW 解码流程需要另行对齐")
    out.mkdir(parents=True,exist_ok=True)
    # MTF Mapper public CLI: options then input image and working directory.
    args=[str(exe),"-q",*(extra_args or []),str(image),str(out)]
    atomic_json(out/"mutex-reference-run.json",{"command":args,"tool":"MTF Mapper","native_results_overwritten":False,"validated_parser":False})
    logfile=open(out/"mtf-mapper.log","ab")
    try:
        process=subprocess.Popen(args,stdout=logfile,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    finally:logfile.close()
    return process.pid

