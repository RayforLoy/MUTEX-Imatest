"""Real native mixed-target curves survive offline HTML/PDF export unchanged."""
import copy
import json
from collections import Counter
from html.parser import HTMLParser
import numpy as np
import pytest
from PIL import Image
from mutex_imatest.models import ChartDefinition,Region,Measurement
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.reports import export_html,export_pdf
from mutex_imatest.reports_curves import collect_regions,curve_svg,curve_name


def native_mixed_result(tmp_path):
    import cv2,tifffile
    from scipy.special import erf
    from mutex_imatest.analysis.engine import analyze
    width,height=1700,700;rgb=np.full((height,width,3),.83,np.float32)
    regions=[]
    def add(key,kind,x,y,w,h,params):
        regions.append(Region(key,kind,(x/width,y/height,w/width,h/height),key,params))
        return np.mgrid[:h,:w]
    yy,xx=add('native-edge','edge',15,35,180,600,{})
    for ch,(shift,sigma) in enumerate([(.3,.8),(0,1.0),(-.2,1.2)]):
        rgb[35:635,15:195,ch]=.12+.7*(.5+.5*erf((xx-90-.085*(yy-300)-shift)/(np.sqrt(2)*sigma)))
    yy,xx=add('native-star','star',240,35,600,600,{'cycles':36,'pattern':'binary'})
    target=.12+.7*(np.cos(36*np.arctan2(yy-299.5,xx-299.5))>0)
    for ch,sigma in enumerate([1.1,1.3,1.5]):rgb[35:635,240:840,ch]=cv2.GaussianBlur(target,(0,0),sigma)
    yy,xx=add('native-wedge','wedge',900,35,760,600,{'direction':'vertical','frequency_samples':[{'t':0,'cycles_across':6},{'t':1,'cycles_across':136}]})
    target=.12+.7*(np.cos(2*np.pi*(6+130*yy/599)*(xx/759-.5))>0)
    for ch,sigma in enumerate([1.0,1.2,1.4]):rgb[35:635,900:1660,ch]=cv2.GaussianBlur(target,(0,0),sigma)
    image=np.uint16(np.rint(rgb*65535));path=tmp_path/'synthetic-mixed.tif'
    tifffile.imwrite(path,image,photometric='rgb',metadata=None)
    preview=tmp_path/'preview.png';Image.fromarray(np.uint8(np.rint(rgb*255))).save(preview)
    chart=ChartDefinition('public-native-mixed','公开合成斜边 / 星图 / 楔形',regions,reference_size=(width,height))
    result=analyze(path,chart,AnalysisConfig(channels='RGBY',transfer='linear',reject_clipping=False,
                                          registration='none',cache_dir=str(tmp_path/'cache')))
    assert not result.optical_summary
    return result,preview


class ParsedReport(HTMLParser):
    def __init__(self):super().__init__();self.tags=[];self.text=[]
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
    def handle_data(self,text):self.text.append(text)


def test_native_mixed_curves_are_merged_by_region_and_embedded_offline(tmp_path,qapp):
    result,preview=native_mixed_result(tmp_path)
    before=json.dumps(result.to_dict(),ensure_ascii=False)
    path=export_html(result,preview,tmp_path/'mixed.html')
    doc=ParsedReport();doc.feed(path.read_text(encoding='utf-8'))
    plots=[attrs for tag,attrs in doc.tags if tag=='svg']
    keys=Counter(attrs['data-curve'] for attrs in plots)
    expected=['sfr','esf','lsf','edge_nps','star','star_contrast','star_coherence',*[f'star_sector_{i}' for i in range(8)],
              'wedge','wedge_contrast','wedge_coherence','wedge_separation','wedge_bar_count','wedge_expected_bars']
    assert set(keys)==set(expected) and all(count==1 for count in keys.values())
    assert len([1 for tag,attrs in doc.tags if tag=='section' and attrs.get('class')=='curve-region'])==3
    assert all(attrs['data-series-count']=='4' for attrs in plots)
    assert {attrs['data-channel'] for tag,attrs in doc.tags if tag=='path' and 'data-channel' in attrs}=={'R','G','B','Y'}
    assert any(attrs['data-x-unit']=='px' and attrs['data-y-unit']=='signal/px' for attrs in plots)
    assert not any(tag in {'link','iframe','object'} for tag,_ in doc.tags)
    assert not any((attrs.get('src') and not attrs['src'].startswith('data:image/')) or attrs.get('href') for tag,attrs in doc.tags)
    text=''.join(doc.text)
    assert 'relative_response' in text and 'CTF 是条纹对比度响应' in text and '缺失样本不补零' in text
    assert json.dumps(result.to_dict(),ensure_ascii=False)==before


def test_pdf_renders_all_native_curve_types_and_does_not_allocate_empty_roi_pages(tmp_path,qapp):
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtCore import QSize
    result,preview=native_mixed_result(tmp_path)
    before=json.dumps(result.to_dict(),ensure_ascii=False)
    target=export_pdf(result,preview,tmp_path/'mixed.pdf')
    document=QPdfDocument(None);assert document.load(str(target))==QPdfDocument.Error.None_
    base_pages=document.pageCount()
    text='\n'.join(document.getAllText(page).text() for page in range(base_pages))
    for key in ['sfr','esf','lsf','star','star_contrast','star_coherence','wedge','wedge_contrast','wedge_coherence','wedge_separation','wedge_bar_count','wedge_expected_bars',*[f'star_sector_{i}' for i in range(8)]]:
        assert curve_name(key) in text
    assert 'cy/px' in text and 'signal/px' in text and 'R' in text and 'Y' in text
    assert 'relative_response' in text and base_pages>=5
    curve_page=next(page for page in range(base_pages) if '斜边 SFR' in document.getAllText(page).text())
    rendered=document.render(curve_page,QSize(850,1200))
    pixels=np.frombuffer(rendered.bits(),dtype=np.uint8).reshape(rendered.height(),rendered.bytesPerLine()//4,4)[...,:3].astype(int)
    # Qt PDF rendering uses BGRA. Hundreds of colored pixels beyond the small
    # legend prove that the response lines themselves reached the PDF.
    for channel_index in range(3):
        others=[i for i in range(3) if i!=channel_index]
        dominant=(pixels[...,channel_index]>pixels[...,others[0]]+25)&(pixels[...,channel_index]>pixels[...,others[1]]+25)
        assert dominant.sum()>120
    document.close()
    cropped=copy.deepcopy(result)
    for i in range(192):
        for channel in ['R','G','B','Y']:
            cropped.measurements.append(Measurement(f'outside-{i:03d}',f'星图不可见 {i:03d}','star',channel,(0,0),(0,0,0,0),flags=['roi_outside'],confidence=0))
    crop_target=export_pdf(cropped,preview,tmp_path/'cropped.pdf')
    assert document.load(str(crop_target))==QPdfDocument.Error.None_
    crop_pages=document.pageCount()
    crop_text='\n'.join(document.getAllText(page).text() for page in range(crop_pages))
    assert '星图不可见 191' in crop_text and 'roi_outside' in crop_text
    assert crop_pages<base_pages+16
    assert crop_text.count('原生曲线 ·')==text.count('原生曲线 ·')
    document.close()
    assert json.dumps(result.to_dict(),ensure_ascii=False)==before


def test_curve_gaps_units_invalid_diagnostics_and_markup_are_preserved(tmp_path,qapp):
    result,preview=native_mixed_result(tmp_path)
    measurement=result.measurements[0]
    measurement.label='长标签与质量说明 '*25+'<img src="https://example.invalid/tracker">'
    measurement.flags=['clipped','long_diagnostic_flag_'*35]
    measurement.curves={'sfr':{'x':[0,1,2,3,4],'y':[.6,.5,None,.3,.2],'x_unit':'native x','y_unit':'<script>native & y</script>'}}
    # Same key with different units must not be silently overlaid on one axis.
    other=result.measurements[1];other.curves={'sfr':{'x':[0,1],'y':[1,.5],'x_unit':'other','y_unit':'response'}}
    region=collect_regions(result)[0]
    assert len([plot for plot in region.plots if plot.key=='sfr'])==3
    diagnostic=next(plot for plot in region.plots if plot.x_unit=='native x')
    svg=curve_svg(diagnostic)
    assert svg.count('data-channel="R"')==2 and 'stroke-dasharray="5 3"' in svg
    assert '<script>' not in svg and '&lt;script&gt;' in svg and 'None' not in svg
    report=export_html(result,preview,tmp_path/'escaped.html')
    doc=ParsedReport();doc.feed(report.read_text(encoding='utf-8'))
    assert not any(attrs.get('src')=='https://example.invalid/tracker' for _,attrs in doc.tags)
    assert '<img src="https://example.invalid/tracker">' in ''.join(doc.text)
    export_pdf(result,preview,tmp_path/'long-label.pdf')
    from PySide6.QtPdf import QPdfDocument
    document=QPdfDocument(None);assert document.load(str(tmp_path/'long-label.pdf'))==QPdfDocument.Error.None_
    text='\n'.join(document.getAllText(page).text() for page in range(document.pageCount()))
    assert 'long_diagnostic_flag_' in text and 'native x' in text
    document.close()
