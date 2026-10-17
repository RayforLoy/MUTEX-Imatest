from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter
from scipy.signal import find_peaks
from mutex_imatest import templates
from mutex_imatest.models import ChartDefinition, Region

ROOT=Path(__file__).resolve().parents[1]/"template"

def rgb(image):
    from PySide6.QtGui import QImage
    image=image.convertToFormat(QImage.Format.Format_RGB888)
    return np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()

def test_public_library_has_reviewed_licenses_and_complete_hashes():
    manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
    charts=templates.public_charts(ROOT)
    assert len(charts)==len(manifest["charts"])>=6
    assert {c.id for c in charts}=={entry["id"] for entry in manifest["charts"]}
    assert len({c.id for c in charts})==len(charts)
    assert {c.asset_license.split(";")[0] for c in charts}=={"CC0-1.0","CC-BY-SA-3.0"}
    assert all(not c.calibrated and c.physical_size_mm and Path(c.preview).is_file() and Path(c.source_path).is_file() for c in charts)
    for entry in manifest["files"]:
        file=(ROOT/entry["path"]).resolve()
        assert file.is_relative_to(ROOT.resolve()) and file.stat().st_size==entry["bytes"]
        assert hashlib.sha256(file.read_bytes()).hexdigest()==entry["sha256"]
    assert set(x["path"] for x in manifest["files"])=={p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and p.name!="manifest.json" and 'bundled' not in p.relative_to(ROOT).parts}
    upstream=json.loads((ROOT/"upstream-sources.json").read_text(encoding="utf-8"))
    assert len(upstream)==2
    for entry in upstream:
        assert entry["url"].startswith("https://upload.wikimedia.org/") and entry["source_page"].startswith("https://commons.wikimedia.org/wiki/File:")
        assert entry["license"]=="CC-BY-SA-3.0"
        assert hashlib.sha256((ROOT/entry["path"]).read_bytes()).hexdigest()==entry["sha256"]
    names={r.kind for c in charts for r in c.regions}
    assert {"star","edge","wedge","usaf","grid"}<=names
    assert all("example" not in p.parts and "private_assets" not in p.parts for p in ROOT.rglob("*"))

def test_public_loader_rejects_path_escape_bad_license_and_missing_preview(tmp_path):
    preview=tmp_path/"preview.png";preview.write_bytes(b"test")
    chart=ChartDefinition("allowed","Allowed",[Region("e","edge",(.1,.1,.2,.2))],preview="preview.png")
    templates.save_chart(chart,tmp_path/"card.json")
    outside=tmp_path.parent/"outside-card.json";templates.save_chart(chart,outside)
    entries=[{"id":"allowed","definition":"card.json","license":"CC0-1.0"}]
    def listing(records):
        (tmp_path/"manifest.json").write_text(json.dumps({"format":"MUTEX Public Template Library","version":1,"charts":records}),encoding="utf-8")
        return templates.public_charts(tmp_path)
    assert len(listing(entries))==1
    assert not listing([dict(entries[0],definition="../outside-card.json")])
    assert not listing([dict(entries[0],license="All rights reserved")])
    assert not listing([dict(entries[0],id="wrong-id")])
    preview.unlink()
    assert not listing(entries)
    (tmp_path/"manifest.json").write_text("[]",encoding="utf-8")
    assert not templates.public_charts(tmp_path)

def test_printable_pdf_and_svg_keep_star_cycles_and_binary_duty_cycle(qapp):
    # A PDF print renderer once inflated SVG arc outlines. Check the actual
    # PDF and SVG angular samples so printing cannot silently change a target.
    for chart in templates.public_charts(ROOT):
        star=next((r for r in chart.regions if r.kind=="star"),None)
        if not star:continue
        for source in [Path(chart.source_path),Path(chart.source_path).with_suffix(".pdf")]:
            image,_,_=templates.render_source(source,max_side=2200)
            data=rgb(image).mean(axis=2)/255
            x,y,w,h=star.box;cx=(x+w/2)*data.shape[1];cy=(y+h/2)*data.shape[0]
            radius=min(w*data.shape[1],h*data.shape[0])*.32
            theta=np.arange(4096)*2*np.pi/4096
            signal=map_coordinates(data,[cy+radius*np.sin(theta),cx+radius*np.cos(theta)],order=1)
            spectrum=np.abs(np.fft.rfft(signal-signal.mean()))
            assert int(np.argmax(spectrum))==star.params["cycles"]
            assert .40<float(np.mean(signal<.5))<.60

def test_known_public_wedges_have_the_declared_cross_section_frequencies(qapp):
    chart=next(c for c in templates.public_charts(ROOT) if "generic-iso12233" in c.id)
    image,_,_=templates.render_source(chart.source_path,max_side=3200)
    data=rgb(image).mean(axis=2)/255
    for wedge in [r for r in chart.regions if r.kind=="wedge"]:
        assert wedge.params["frequency_samples"]==[{"t":0,"cycles_across":6},{"t":1,"cycles_across":36}]
        x,y,w,h=wedge.box;vertical=wedge.params["direction"]=="vertical"
        u=np.linspace(.001,.999,4096)
        for t in [.2,.8]:
            xs=(x+w*u)*data.shape[1] if vertical else np.full_like(u,(x+w*t)*data.shape[1])
            ys=np.full_like(u,(y+h*t)*data.shape[0]) if vertical else (y+h*u)*data.shape[0]
            signal=map_coordinates(data,[ys,xs],order=1)
            peaks,_=find_peaks(-signal,prominence=.3,distance=50)
            assert abs(len(peaks)-(6+30*t))<=1

def test_native_engine_measures_public_star_and_slanted_rois_once(tmp_path,qapp):
    from mutex_imatest.analysis.engine import analyze
    from mutex_imatest.config import AnalysisConfig
    chart=next(c for c in templates.public_charts(ROOT) if "generic-siemens-slanted" in c.id)
    image,_,_=templates.render_source(chart.source_path,max_side=2400)
    data=gaussian_filter(rgb(image).astype(float),(1,1,0))
    data=np.rint(32+data*(192/255)).astype(np.uint8)
    target=tmp_path/"open-chart-regression.png";Image.fromarray(data).save(target)
    config=AnalysisConfig(channels="G",transfer="linear",registration="none",reject_clipping=False,cache_dir=str(tmp_path/"cache"),
                          analysis_metrics=["mtf50","ctf50","resolution_limit"])
    result=analyze(target,chart,config)
    assert len(result.measurements)==27
    assert sum(m.kind=="edge" and m.valid and m.metric("mtf50") is not None for m in result.measurements)==18
    assert sum(m.kind=="star" and m.valid and m.metric("ctf50") is not None for m in result.measurements)==9
    assert len(result.analysis_summary["items"])==3 and all(item["status"]=="complete" for item in result.analysis_summary["items"])
    assert all(m.object_scale_px_per_mm is None for m in result.measurements)
