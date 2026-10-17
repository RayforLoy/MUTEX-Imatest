"""Encrypted transport, bounded untrusted input, and native-analysis truth."""
import base64
import copy
import io
import json
from pathlib import Path
import struct
import warnings
import zipfile
import zlib

import cv2
import msgpack
import numpy as np
from PIL import Image, PngImagePlugin
import pytest
import tifffile
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mutex_imatest import chart_package as package
from mutex_imatest.analysis.engine import analyze
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.models import ChartDefinition, Region
from mutex_imatest.templates import builtin_chart, import_source, render_source


PASSWORD = "chart-test-口令-2026"


@pytest.fixture
def chart(tmp_path):
    a=np.full((400,600,3),220,np.uint8)
    cv2.fillConvexPoly(a,np.array([[80,80],[190,90],[180,280],[70,270]]),[30,30,30])
    preview=tmp_path/"private-reference.png"
    # Text/ICC/source filenames on a supplied image must not hitchhike into
    # the encrypted raster payload, even after the recipient decrypts it.
    metadata=PngImagePlugin.PngInfo()
    metadata.add_text("private_source",r"D:\private\artwork.svg")
    Image.fromarray(a).save(preview,pnginfo=metadata)
    return ChartDefinition("portable-test","Portable 测试卡",[
        Region("edge","edge",(.1,.2,.1,.45),"斜边",{"keep":[1,2,.2]}),
        Region("star","star",(.5,.2,.2,.3),"星图",{"cycles":36,"pattern":"binary"})],
        physical_size_mm=(200.,140.),reference_size=(600,400),calibrated=True,
        fiducials=[{"position":[.2,.3],"kind":"point"}],preview=str(preview),
        asset_license="CC0-1.0; test fixture",notes="普通说明；许可及标定应保持",aliases=["兼容别名"])


def _parts(path):
    with zipfile.ZipFile(path) as archive:
        return {n:archive.read(n) for n in archive.namelist()}


def _write(path, parts):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",UserWarning)
        with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
            for name,data in parts:
                archive.writestr(name,data)


def _payload(path):
    parts=_parts(path)
    manifest,salt,nonce=package._manifest(parts["manifest.json"])
    plain=AESGCM(package._derive(PASSWORD.encode(),salt)).decrypt(nonce,parts["encrypted.bin"],parts["manifest.json"])
    return msgpack.unpackb(plain,raw=False),parts,manifest,salt,nonce


def _write_payload(path,data,parts,manifest,salt,nonce):
    plain=msgpack.packb(data,use_bin_type=True)
    manifest=copy.deepcopy(manifest);manifest["payload_bytes"]=len(plain)+16
    public=package._json_bytes(manifest)
    cipher=AESGCM(package._derive(PASSWORD.encode(),salt)).encrypt(nonce,plain,public)
    _write(path,[("manifest.json",public),("encrypted.bin",cipher)])


def test_roundtrip_keeps_measurement_geometry_and_no_source_artwork(chart,tmp_path,qapp):
    chart.source_path=str(tmp_path/"original-private.svg")
    chart.regions[0].params["local_path"]=str(tmp_path/"secret.svg")
    chart.regions[0].params["frequency_geometry_source"]="reference_raster_estimated"
    chart.notes+="\n原稿：D:\\private\\very secret.svg"
    before=copy.deepcopy(chart.to_dict());preview_before=Path(chart.preview).read_bytes()
    target=package.export_chart_package(chart,tmp_path/"test.mxtpl",PASSWORD)
    loaded=package.load_chart_package(target,PASSWORD,tmp_path/"cache")
    assert loaded.id==chart.id and loaded.name==chart.name
    assert loaded.source_path is None and loaded.source_page==0
    assert loaded.calibrated and loaded.physical_size_mm==chart.physical_size_mm
    assert loaded.fiducials==chart.fiducials and loaded.aliases==chart.aliases
    assert loaded.asset_license==chart.asset_license
    assert loaded.regions[0].params=={"keep":[1,2,.2],"frequency_geometry_source":"reference_raster_estimated"}
    assert "D:" not in loaded.notes and "普通说明" in loaded.notes
    assert Path(loaded.preview).is_file() and Path(loaded.preview).parent.joinpath("thumbnail.png").is_file()
    assert package.load_chart_package(target,PASSWORD,tmp_path/"cache").preview==loaded.preview
    assert chart.to_dict()==before and Path(chart.preview).read_bytes()==preview_before
    payload,parts,manifest,_,_=_payload(target)
    assert set(parts)=={"manifest.json","encrypted.bin"}
    assert manifest["cipher"]=="AES-256-GCM" and manifest["kdf"]["n"]==32768
    assert not any(b"<svg" in value or b"%PDF-" in value for value in parts.values())
    assert b"Portable" not in parts["manifest.json"] and b"Portable" not in parts["encrypted.bin"]
    definition_bytes=msgpack.packb(payload["chart"],use_bin_type=True)
    assert str(tmp_path).encode() not in definition_bytes and b"D:\\private" not in definition_bytes
    for key in ["reference_png","thumbnail_png"]:
        with Image.open(io.BytesIO(payload[key])) as image:
            assert not image.info and max(image.size)<=(4096 if key=="reference_png" else 512)
    with zipfile.ZipFile(target) as archive:
        assert all(e.compress_type==zipfile.ZIP_DEFLATED for e in archive.infolist())


def test_each_export_has_fresh_randomness_and_never_overwrites(chart,tmp_path,qapp):
    a=package.export_chart_package(chart,tmp_path/"a.mxtpl",PASSWORD)
    b=package.export_chart_package(chart,tmp_path/"b.mxtpl",PASSWORD)
    aa,bb=_parts(a),_parts(b)
    assert aa["encrypted.bin"]!=bb["encrypted.bin"] and aa["manifest.json"]!=bb["manifest.json"]
    before=a.read_bytes()
    with pytest.raises(FileExistsError):package.export_chart_package(chart,a,PASSWORD)
    assert a.read_bytes()==before


def test_path_redaction_preserves_license_urls_and_normal_text(chart,tmp_path,qapp):
    license_text="CC-BY-SA-3.0; https://creativecommons.org/licenses/by-sa/3.0/; http://example.com/attribution"
    chart.asset_license=license_text
    chart.notes="普通介绍和校准说明； https://example.com/chart/method\n本地原稿 /Users/name/private.svg; 许可保持"
    chart.aliases=["旧图卡名称","Original name"]
    target=package.export_chart_package(chart,tmp_path/"license.mxtpl",PASSWORD)
    loaded=package.load_chart_package(target,PASSWORD,tmp_path/"cache")
    assert loaded.asset_license==license_text and loaded.aliases==chart.aliases
    assert "https://example.com/chart/method" in loaded.notes
    assert "private.svg" not in loaded.notes and "许可保持" in loaded.notes


def test_password_and_authentication_fail_before_any_cache_output(chart,tmp_path,qapp):
    target=package.export_chart_package(chart,tmp_path/"test.mxtpl",PASSWORD)
    cache=tmp_path/"cache"
    with pytest.raises(package.ChartPackagePasswordError):package.load_chart_package(target,"wrong-password",cache)
    assert not cache.exists()
    parts=_parts(target);cipher=bytearray(parts["encrypted.bin"]);cipher[-1]^=128
    damaged=tmp_path/"damaged.mxtpl";_write(damaged,[("manifest.json",parts["manifest.json"]),("encrypted.bin",cipher)])
    with pytest.raises(package.ChartPackagePasswordError):package.load_chart_package(damaged,PASSWORD,cache)
    assert not cache.exists()
    # Reformatting a valid manifest changes the authenticated associated data.
    altered=tmp_path/"altered.mxtpl"
    public=json.dumps(json.loads(parts["manifest.json"]),indent=2).encode()
    _write(altered,[("manifest.json",public),("encrypted.bin",parts["encrypted.bin"])])
    with pytest.raises(package.ChartPackagePasswordError):package.load_chart_package(altered,PASSWORD,cache)
    assert not cache.exists()


@pytest.mark.parametrize("attack",["traversal","duplicate","third-file","zip-bomb","high-kdf","bad-entry-count"])
def test_zip_and_kdf_attacks_are_bounded_and_create_no_files(chart,tmp_path,qapp,attack):
    target=package.export_chart_package(chart,tmp_path/"valid.mxtpl",PASSWORD)
    parts=_parts(target);entries=list(parts.items());cache=tmp_path/"cache"
    if attack=="traversal":entries[1]=( "../encrypted.bin",entries[1][1])
    if attack=="duplicate":entries[1]=("manifest.json",entries[1][1])
    if attack=="third-file":entries.append(("original.svg",b"<svg>private</svg>"))
    if attack=="zip-bomb":entries[0]=("manifest.json",b"x"*100000)
    if attack=="high-kdf":
        m=json.loads(parts["manifest.json"]);m["kdf"]["n"]=2**28;entries[0]=("manifest.json",json.dumps(m).encode())
    bad=tmp_path/"attack.mxtpl";_write(bad,entries)
    if attack=="bad-entry-count":
        data=bytearray(bad.read_bytes());p=data.rfind(b"PK\x05\x06");struct.pack_into("<H",data,p+10,65534);bad.write_bytes(data)
    with pytest.raises(package.ChartPackageError):package.load_chart_package(bad,PASSWORD,cache)
    assert not cache.exists() and not (tmp_path.parent/"encrypted.bin").exists()


@pytest.mark.parametrize("attack",["schema","nonfinite","path","vector","png-bomb","png-metadata","png-tail"])
def test_authenticated_but_invalid_payloads_are_rejected(chart,tmp_path,qapp,attack):
    target=package.export_chart_package(chart,tmp_path/"valid.mxtpl",PASSWORD)
    data,parts,manifest,salt,nonce=_payload(target)
    if attack=="schema":data["chart"]["schema_version"]=999
    if attack=="nonfinite":data["chart"]["physical_size_mm"][0]=float("nan")
    if attack=="path":data["chart"]["regions"][0]["params"]["local_path"]=r"C:\secret\x.svg"
    if attack=="vector":data["chart"]["notes"]="<svg><path d='M0 0'/></svg>"
    if attack=="png-bomb":
        png=bytearray(data["reference_png"]);struct.pack_into(">I",png,16,200000)
        struct.pack_into(">I",png,29,zlib.crc32(png[12:29])&0xffffffff);data["reference_png"]=bytes(png)
    if attack=="png-metadata":
        image=Image.new("RGB",(10,10));out=io.BytesIO();info=PngImagePlugin.PngInfo();info.add_text("source","<svg/>image")
        image.save(out,format="PNG",pnginfo=info);data["reference_png"]=out.getvalue()
    if attack=="png-tail":data["reference_png"]+=b"%PDF-1.4"
    bad=tmp_path/"authenticated-bad.mxtpl";_write_payload(bad,data,parts,manifest,salt,nonce)
    cache=tmp_path/"cache"
    with pytest.raises(package.ChartPackageError):package.load_chart_package(bad,PASSWORD,cache)
    assert not cache.exists()


def test_password_length_embedded_vector_and_failed_write_leave_no_output(chart,tmp_path,qapp,monkeypatch):
    destination=tmp_path/"new.mxtpl"
    with pytest.raises(package.ChartPackagePasswordError):package.export_chart_package(chart,destination,"short")
    assert not destination.exists()
    chart.regions[0].params["embedded_svg"]="<svg/>"
    # Artwork keys are dropped, and arbitrary binary values are rejected.
    chart.regions[0].params["unknown_binary"]=b"original-private-vector"
    with pytest.raises(package.ChartPackageError):package.export_chart_package(chart,destination,PASSWORD)
    assert not destination.exists()
    chart.regions[0].params.pop("unknown_binary")
    def failed(*args,**kwargs):raise OSError("simulated destination failure")
    monkeypatch.setattr(zipfile.ZipFile,"writestr",failed)
    with pytest.raises(OSError):package.export_chart_package(chart,destination,PASSWORD)
    assert not destination.exists()


def test_source_svg_is_rasterized_and_builtin_without_preview_has_reference(tmp_path,qapp):
    svg=tmp_path/"private.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="white"/><circle cx="70" cy="50" r="30" fill="black"/></svg>')
    chart=import_source(svg)
    target=package.export_chart_package(chart,tmp_path/"svg.mxtpl",PASSWORD)
    data,*_=_payload(target)
    assert data["reference_png"].startswith(b"\x89PNG") and svg.read_bytes() not in target.read_bytes()
    chart=builtin_chart();chart.preview=None;chart.source_path=None
    target=package.export_chart_package(chart,tmp_path/"builtin.mxtpl",PASSWORD)
    loaded=package.load_chart_package(target,PASSWORD,tmp_path/"cache")
    with Image.open(loaded.preview) as image:
        assert image.size==(1600,1200) and np.std(np.asarray(image))>10


def test_failed_cache_publish_cleans_only_new_temporary_files(chart,tmp_path,qapp,monkeypatch):
    target=package.export_chart_package(chart,tmp_path/"new.mxtpl",PASSWORD)
    cache=tmp_path/"cache";cache.mkdir()
    old=cache/"unrelated.png";old.write_bytes(b"keep existing local content")
    def failure(*args,**kwargs):raise OSError("simulated cache publish failure")
    monkeypatch.setattr(Path,"rename",failure)
    with pytest.raises(OSError):package.load_chart_package(target,PASSWORD,cache)
    assert list(cache.iterdir())==[old] and old.read_bytes()==b"keep existing local content"


def test_existing_corrupt_cache_is_reported_without_overwriting(chart,tmp_path,qapp):
    target=package.export_chart_package(chart,tmp_path/"new.mxtpl",PASSWORD)
    cache=tmp_path/"cache";loaded=package.load_chart_package(target,PASSWORD,cache)
    Path(loaded.preview).write_bytes(b"corrupt existing reference")
    with pytest.raises(package.ChartPackageError):package.load_chart_package(target,PASSWORD,cache)
    assert Path(loaded.preview).read_bytes()==b"corrupt existing reference"


def test_vector_usaf_product_engine_is_unchanged_after_source_free_roundtrip(tmp_path,qapp):
    from test_vector_usaf import make_vector
    from mutex_imatest.vector_usaf import detect_svg_usaf
    cv2.setNumThreads(1)
    svg=tmp_path/"usaf-source.svg";make_vector(svg)
    chart=import_source(svg)
    chart.regions,chart.fiducials,chart.physical_size_mm=detect_svg_usaf(svg,group=1,element=3)
    chart.calibrated=True
    reference=tmp_path/"reference.png";render_source(svg,max_side=1656,output=reference)
    pixels=np.asarray(Image.open(reference).convert("RGB"))
    pixels=(32+pixels.astype(float)*(193/255)).astype(np.uint8)
    h,w=pixels.shape[:2]
    M=np.array([[1,.007,8],[0,-1,h-1],[0,0,1]],float)
    scanned=cv2.warpPerspective(pixels,M,(w+25,h),borderValue=(225,225,225))
    sample=tmp_path/"scan.tif";tifffile.imwrite(sample,scanned,photometric="rgb",metadata=None)
    config=AnalysisConfig(transfer="linear",channels="RGB",registration="usaf",reject_clipping=False,cache_dir=str(tmp_path/"engine"))
    before=analyze(sample,chart,config)
    pack=package.export_chart_package(chart,tmp_path/"chart.mxtpl",PASSWORD)
    loaded=package.load_chart_package(pack,PASSWORD,tmp_path/"imported")
    # Prove this is independent from original SVG and original thumbnail.
    svg.unlink();Path(chart.preview).unlink()
    after=analyze(sample,loaded,config)
    assert after.registration["method"]==before.registration["method"]=="vector_usaf_native_refinement"
    assert after.registration["homography"]==pytest.approx(np.asarray(before.registration["homography"]))
    assert len(after.measurements)==len(before.measurements)==54
    for a,b in zip(before.measurements,after.measurements):
        assert a.region_id==b.region_id and a.channel==b.channel and a.flags==b.flags
        assert a.position==pytest.approx(b.position,abs=1e-7)
        assert a.values==pytest.approx(b.values,nan_ok=True)
        assert a.valid and b.valid


def test_partial_auto_chart_product_analysis_is_unchanged_after_roundtrip(tmp_path,qapp):
    from scipy.special import erf
    cv2.setNumThreads(1)
    rng=np.random.default_rng(7);canvas=np.full((1000,1400),.83)
    for x,y,r in zip(rng.integers(30,1370,120),rng.integers(30,970,120),rng.integers(3,10,120)):
        cv2.circle(canvas,(int(x),int(y)),int(r),float(rng.uniform(.1,.5)),-1)
    boxes=[(.15,.2,.08,.24),(.58,.2,.08,.24),(.7,.65,.08,.24)]
    for x,y,w,h in boxes:
        x0,y0,xw,yh=int(x*1400),int(y*1000),int(w*1400),int(h*1000)
        yy,xx=np.mgrid[:yh,:xw];d=xx-xw/2-.08*(yy-yh/2)
        canvas[y0:y0+yh,x0:x0+xw]=.12+.7*(.5+.5*erf(d/2))
    pixels=np.uint8(np.rint(canvas*255));preview=tmp_path/"ref.png";Image.fromarray(pixels).save(preview)
    sample=tmp_path/"crop.tif";tifffile.imwrite(sample,np.fliplr(np.rot90(pixels[100:600,100:1300])))
    chart=ChartDefinition("partial","Partial reference",[Region(f"e{i}","edge",box) for i,box in enumerate(boxes)],
        physical_size_mm=(210,297),calibrated=False,preview=str(preview))
    config=AnalysisConfig(registration="auto_chart",reject_clipping=False,transfer="linear",cache_dir=str(tmp_path/"engine"))
    before=analyze(sample,chart,config)
    pack=package.export_chart_package(chart,tmp_path/"partial.mxtpl",PASSWORD)
    loaded=package.load_chart_package(pack,PASSWORD,tmp_path/"imported");preview.unlink()
    after=analyze(sample,loaded,config)
    assert after.registration["method"]==before.registration["method"]=="reference_sift_partial_homography"
    assert after.registration["visible_regions"]==before.registration["visible_regions"]==["e0","e1"]
    assert after.registration["reference_mirrored"]
    assert np.asarray(after.registration["homography"])==pytest.approx(np.asarray(before.registration["homography"]),abs=1e-7)
    for a,b in zip(before.measurements,after.measurements):
        assert a.flags==b.flags and a.values==pytest.approx(b.values,nan_ok=True)
