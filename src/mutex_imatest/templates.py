from __future__ import annotations
from pathlib import Path
import base64, hashlib, json, re, sys, uuid, zipfile, zlib
import xml.etree.ElementTree as ET
import msgpack
import platformdirs
from .models import ChartDefinition, Region
from .utils import atomic_json

def library_dir():
    p=Path(platformdirs.user_data_dir("MUTEX Imatest","MUTEX"))/"charts"
    p.mkdir(parents=True,exist_ok=True); return p

def builtin_chart():
    p=Path(__file__).parent/"assets"/"demo-chart.json"
    return load_chart(p)

def load_chart(path,password=None):
    path=Path(path).resolve()
    if path.suffix.lower()=='.mxtpl':
        from .chart_package import load_chart_package
        return load_chart_package(path,password)
    if path.suffix.lower()==".mchart":
        with zipfile.ZipFile(path) as z:
            if any(i.file_size>16*2**20 for i in z.infolist()) or sum(i.file_size for i in z.infolist())>32*2**20:
                raise ValueError("Chart pack exceeds safety limits")
            manifest=json.loads(z.read("manifest.json"))
            if manifest.get("format")!="MUTEX Chart Pack" or manifest.get("version")!=1: raise ValueError("Unsupported chart pack")
            payload=z.read("definition.msgpack")
            if hashlib.sha256(payload).hexdigest()!=manifest["definition_sha256"]: raise ValueError("Chart definition checksum mismatch")
            data=msgpack.unpackb(payload,raw=False)
            if "preview.png" in z.namelist():
                png=z.read("preview.png")
                if hashlib.sha256(png).hexdigest()!=manifest.get("preview_sha256"): raise ValueError("Chart preview checksum mismatch")
                cache=library_dir()/"previews"; cache.mkdir(exist_ok=True)
                target=cache/(hashlib.sha256(png).hexdigest()+".png")
                if not target.exists(): target.write_bytes(png)
                data["preview"]=str(target)
            data["source_path"]=None
    else:
        data=json.loads(path.read_text(encoding="utf-8"))
        for key in ["preview","source_path"]:
            if data.get(key) and not Path(data[key]).is_absolute(): data[key]=str((path.parent/data[key]).resolve())
    return ChartDefinition.from_dict(data)

def read_pack_reference(path):
    """Internal reference bytes. Binary packaging is not an access-control mechanism."""
    with zipfile.ZipFile(path) as z:
        manifest=json.loads(z.read("manifest.json"))
        entry=z.getinfo("reference.bin")
        if entry.file_size>16*2**20:raise ValueError("Reference block too large")
        payload=z.read(entry)
        if hashlib.sha256(payload).hexdigest()!=manifest.get("reference_sha256"):raise ValueError("Reference checksum mismatch")
        decoder=zlib.decompressobj();decoded=decoder.decompress(payload,32*2**20)
        if decoder.unconsumed_tail or not decoder.eof:raise ValueError("Reference exceeds decompression limit")
        reference=msgpack.unpackb(decoded,raw=False)
        if reference["media_type"] not in {"image/svg+xml","application/pdf"}:raise ValueError("Unsupported reference type")
        if hashlib.sha256(reference["source_bytes"]).hexdigest()!=reference["source_sha256"]:raise ValueError("Source checksum mismatch")
        return reference

def save_chart(chart,path,portable=False):
    data=chart.to_dict()
    path=Path(path)
    if portable:
        data["source_path"]=None
        if chart.preview and Path(chart.preview).is_file():
            import shutil
            target=path.with_suffix(".preview.png")
            if Path(chart.preview).resolve()!=target.resolve():shutil.copyfile(chart.preview,target)
            data["preview"]=target.name
    atomic_json(path,data)

def available_charts():
    entries=[]
    for path in sorted(library_dir().glob("*")):
        if path.suffix.lower() in {".json",".mchart"}:
            try: entries.append((path,load_chart(path)))
            except (ValueError,OSError,KeyError): pass
    from .chart_library import consolidate_library
    charts=[builtin_chart()]+consolidate_library(library_dir(),entries)
    # Public definitions live beside the portable app, independently of the
    # user's private source artwork and recoverable private-library merges.
    from .bundled_templates import bundled_charts
    existing={identifier for c in charts for identifier in [c.id,*c.aliases]}
    for c in bundled_charts()+public_charts():
        identifiers={c.id,*c.aliases}
        if not identifiers&existing:
            charts.append(c);existing.update(identifiers)
    return charts

def public_template_dir():
    """Source checkout or portable root; _internal is a packaging fallback."""
    candidates=[]
    if getattr(sys,"frozen",False):
        candidates.append(Path(sys.executable).resolve().parent/"template")
        if getattr(sys,"_MEIPASS",None):candidates.append(Path(sys._MEIPASS)/"template")
    else:candidates.append(Path(__file__).resolve().parents[2]/"template")
    return next((p for p in candidates if (p/"manifest.json").is_file()),None)

def public_charts(root=None):
    """Load only allowlisted, local public definitions and their references.

    No upstream download is performed at startup. A broken optional entry
    cannot hide the user's private cards. Paths must stay within template/.
    The manifest records reviewed licenses and hashes for redistribution.
    """
    root=Path(root) if root is not None else public_template_dir()
    if root is None:return []
    root=root.resolve();manifest=root/"manifest.json"
    try:
        if manifest.stat().st_size>2*2**20:return []
        data=json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data,dict):return []
        if data.get("format")!="MUTEX Public Template Library" or data.get("version")!=1:return []
    except (OSError,ValueError):return []
    charts=[];seen=set()
    for entry in data.get("charts",[]):
        try:
            path=(root/entry["definition"]).resolve()
            if not path.is_relative_to(root) or path.suffix.lower()!=".json" or path.stat().st_size>2*2**20:continue
            chart=load_chart(path)
            if chart.id!=entry["id"] or chart.id in seen:continue
            if entry.get("license") not in {"CC0-1.0","CC-BY-SA-3.0"}:continue
            if any(value and not Path(value).resolve().is_relative_to(root) for value in [chart.preview,chart.source_path]):continue
            if not chart.preview or not Path(chart.preview).is_file():continue
            seen.add(chart.id);charts.append(chart)
        except (ValueError,OSError,KeyError,TypeError):continue
    return charts

_qapp=None
def ensure_qt():
    global _qapp
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None: _qapp=QGuiApplication([])
    from .fonts import configure_fonts
    configure_fonts()
    return QGuiApplication.instance()

def render_source(path,max_side=1600,page=0,output=None):
    """Thumbnail only. Never rasterize a design to use it as measured image data."""
    path=Path(path).resolve()
    if not path.is_file(): raise FileNotFoundError(path)
    ensure_qt()
    from PySide6.QtCore import QByteArray, QRectF, QSize
    from PySide6.QtGui import QImage, QPainter, QColor
    ext=path.suffix.lower()
    if ext==".svg":
        from .svg_source import read_svg
        text,tree=read_svg(path)
        from PySide6.QtSvg import QSvgRenderer
        renderer=QSvgRenderer(QByteArray(text.encode()))
        if not renderer.isValid(): raise ValueError("Invalid SVG")
        size=renderer.defaultSize()
        if size.isEmpty(): size=QSize(1000,1000)
        scale=max_side/max(size.width(),size.height())
        image=QImage(max(1,int(size.width()*scale)),max(1,int(size.height()*scale)),QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        painter=QPainter(image); renderer.render(painter,QRectF(image.rect())); painter.end()
        dimensions=(size.width(),size.height()); pages=1
    elif ext==".pdf":
        from PySide6.QtPdf import QPdfDocument
        document=QPdfDocument(None)
        if document.load(str(path))!=QPdfDocument.Error.None_: raise ValueError("PDF could not be opened (password/encryption unsupported)")
        pages=document.pageCount()
        if not 0<=page<pages: raise ValueError("Invalid PDF page")
        size=document.pagePointSize(page); scale=max_side/max(size.width(),size.height())
        image=document.render(page,QSize(max(1,int(size.width()*scale)),max(1,int(size.height()*scale))))
        dimensions=(float(size.width()),float(size.height()))
        document.close()
    else:
        image=QImage(str(path))
        if image.isNull(): raise ValueError("Unsupported preview image")
        dimensions=(image.width(),image.height());pages=1
        if max(image.width(),image.height())>max_side:
            image=image.scaled(QSize(max_side,max_side),__import__("PySide6.QtCore",fromlist=["Qt"]).Qt.AspectRatioMode.KeepAspectRatio)
    if output:
        Path(output).parent.mkdir(parents=True,exist_ok=True)
        if not image.save(str(output),"PNG"): raise OSError("Could not write chart thumbnail")
    return image,dimensions,pages

def import_source(path,name=None,physical_size=None,page=0):
    uid=uuid.uuid4().hex
    preview=library_dir()/f"{uid}.png"
    _,size,_=render_source(path,page=page,output=preview)
    if Path(path).suffix.lower()==".svg" and physical_size is None:
        from .svg_source import read_svg,svg_dimensions
        try:physical_size=svg_dimensions(read_svg(path)[1])[1]
        except ValueError:pass
    chart=ChartDefinition(uid,name or Path(path).stem,[],physical_size_mm=physical_size,
                          reference_size=tuple(map(int,size)),calibrated=False,preview=str(preview),
                          source_path=str(Path(path).resolve()),source_page=page)
    return chart

def auto_edge_chart(source):
    """Candidate ROIs only; they are explicitly approximate until reviewed."""
    from .detection import suggest_edges
    boxes=suggest_edges(source.preview(1600))
    regions=[Region(f"edge-{i+1}","edge",box,f"候选斜边 {i+1}") for i,box in enumerate(boxes)]
    return ChartDefinition(uuid.uuid4().hex,"自动斜边候选",regions,notes="自动检测的候选斜边，请检查 ROI 是否只包含一条斜边；无物理标定")
