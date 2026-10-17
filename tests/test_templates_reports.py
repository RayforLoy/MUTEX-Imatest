from pathlib import Path
import json,zipfile,hashlib
import numpy as np
import msgpack,pytest,tifffile
from mutex_imatest.models import ChartDefinition,Region,AnalysisResult,ImageMetadata,Measurement
from mutex_imatest.templates import render_source,load_chart,save_chart
from mutex_imatest.reports import export_bundle,export_html
from mutex_imatest.storage import Session

def test_svg_pdf_thumbnail_and_source_not_embedded(tmp_path,qapp):
    svg=tmp_path/"private.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="white"/><path d="M90 0 L110 100 L0 100 L0 0Z" fill="black"/></svg>')
    preview=tmp_path/"thumb.png";image,size,pages=render_source(svg,output=preview)
    assert size==(200,100) and pages==1 and not image.isNull()
    chart=ChartDefinition("private","User template",[Region("r","edge",(.1,.1,.8,.8))],preview=str(preview),source_path=str(svg))
    out=tmp_path/"public.json";save_chart(chart,out,portable=True)
    data=json.loads(out.read_text(encoding="utf-8"))
    assert data["source_path"] is None and Path(tmp_path/data["preview"]).exists()

def test_svg_external_resources_rejected(tmp_path,qapp):
    path=tmp_path/"bad.svg";path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/private.png"/></svg>')
    with pytest.raises(ValueError,match="external"):render_source(path)

def test_coreldraw_standard_doctype_is_inert_and_local_css_works(tmp_path,qapp):
    svg=tmp_path/"corel.svg"
    svg.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><defs><linearGradient id="g"><stop stop-color="black"/></linearGradient></defs><rect width="200" height="100" fill="url('#g')"/></svg>''',encoding="utf-8")
    image,size,_=render_source(svg)
    assert size==(200,100) and not image.isNull()

@pytest.mark.parametrize("payload",[
    '<!DOCTYPE svg [<!ENTITY x "expanded">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    '<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://example.com/style.css)</style></svg>',
])
def test_svg_active_content_stays_rejected(tmp_path,qapp,payload):
    path=tmp_path/"unsafe.svg";path.write_text(payload,encoding="utf-8")
    with pytest.raises(ValueError,match="disabled"):render_source(path)

def test_binary_chart_checksum_reader(tmp_path):
    chart=ChartDefinition("private-pack","Binary chart",[Region("r","edge",(.1,.1,.5,.5))])
    payload=msgpack.packb(chart.to_dict(),use_bin_type=True)
    manifest={"format":"MUTEX Chart Pack","version":1,"definition_sha256":hashlib.sha256(payload).hexdigest()}
    pack=tmp_path/"chart.mchart"
    with zipfile.ZipFile(pack,"w") as z:
        z.writestr("manifest.json",json.dumps(manifest));z.writestr("definition.msgpack",payload)
    assert load_chart(pack).regions[0].id=="r"

def test_session_and_export_pdf(tmp_path,qapp):
    from PIL import Image
    preview=tmp_path/"preview.png";Image.new("RGB",(600,400),"white").save(preview)
    image=ImageMetadata("input.tif",600,400,3,"uint16",16,1440000,"a"*64,decoder="test")
    m=Measurement("r","测试区域","edge","G",(300,200),(250,150,100,100),values={"mtf50":.2},units={"mtf50":"cy/px"})
    result=AnalysisResult(image,"test","测试图卡",[m],{"algorithm_version":"test"},{},warnings=["工程测量验证样本"])
    with_session=Session(tmp_path/"session");with_session.add(result)
    assert with_session.load_results()[0].measurements[0].metric("mtf50")==.2
    with_session.close()
    folder=export_bundle(result,preview,tmp_path/"export")
    for name in ["measurements.csv","result.json","heatmap.png","report.html","report.pdf"]:assert (folder/name).stat().st_size>10
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtCore import QSize
    document=QPdfDocument(None);assert document.load(str(folder/"report.pdf"))==QPdfDocument.Error.None_
    assert document.pageCount()>=3
    assert '结果评价' in '\n'.join(document.getAllText(i).text() for i in range(document.pageCount()))
    page=document.render(0,QSize(800,1100));assert not page.isNull()
    assert render_source(folder/"report.pdf",page=1)[2]==document.pageCount()
    document.close()

def test_html_is_offline_escaped_and_preserves_invalid_measurements(tmp_path):
    from PIL import Image
    from html.parser import HTMLParser
    import base64,io
    preview=tmp_path/"preview.png";Image.new("RGB",(200,100),"white").save(preview)
    image=ImageMetadata("a<script>alert(1)</script>.tif",200,100,3,"uint16",16,120000,"f"*64,decoder="test")
    rows=[Measurement("good","正常 <img src=x onerror=alert(1)>","edge","G",(80,50),(50,20,60,60),values={"mtf50":.2,"mtf50_lp_mm":10},units={"mtf50_lp_mm":"lp/mm"}),
          Measurement("bad","剪切区域","edge","R",(120,50),(90,20,60,60),values={"mtf50":None},flags=["clipped"])]
    result=AnalysisResult(image,"test","图卡 & 测量",rows,{"note":"</pre><script>alert(1)</script>"},{},warnings=["剪切 & 低对比度"])
    path=export_html(result,preview,tmp_path/"report.html",unit="lp/mm")
    class Parse(HTMLParser):
        def __init__(self):super().__init__();self.tags=[];self.text=[]
        def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
        def handle_data(self,data):self.text.append(data)
    doc=Parse();doc.feed(path.read_text(encoding="utf-8"))
    assert sum(tag=="script" for tag,_ in doc.tags)==1
    images=[attrs["src"] for tag,attrs in doc.tags if tag=="img"]
    assert len(images)==1 and images[0].startswith("data:image/png;base64,")
    assert Image.open(io.BytesIO(base64.b64decode(images[0].split(",",1)[1]))).size==(200,100)
    assert not any(tag in {"link","iframe"} for tag,_ in doc.tags)
    assert [attrs["data-valid"] for tag,attrs in doc.tags if tag=="tr" and "data-valid" in attrs]==["1","0"]
    assert "正常 <img src=x onerror=alert(1)>" in doc.text
    assert "mtf50_lp_mm" in "".join(doc.text) and "10" in doc.text
    assert "剪切区域" in "".join(doc.text) and "未测得" in doc.text
    folder=export_bundle(result,preview,tmp_path/"html-only",pdf=False)
    assert (folder/"report.html").exists() and not (folder/"report.pdf").exists()

