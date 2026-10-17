"""End-to-end truth cases for the whole-card native engine and exports."""
import copy,json
import cv2
import numpy as np
import pytest
import tifffile
from PIL import Image
from mutex_imatest.analysis.engine import analyze
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.templates import import_source,render_source
from mutex_imatest.vector_usaf import detect_svg_usaf
from mutex_imatest.resolution import view_result


@pytest.fixture(scope='module')
def whole_truth(tmp_path_factory,qapp):
    from test_vector_usaf import make_vector
    root=tmp_path_factory.mktemp('whole-native');svg=root/'truth.svg';make_vector(svg)
    # A design label bridges two bars in the middle of G0/E6. The source
    # preflight must select its clean upper band; the captured image is also
    # reflected in Y, so native sampling must reflect that band correctly.
    period=100/2**(5/6);cx,cy=1525,475
    source=svg.read_text(encoding='utf-8').replace('</svg>',f'<rect x="{cx+.25*period}" y="{cy-.15*period}" width="{.5*period}" height="{1.5*period}" fill="black"/></svg>')
    svg.write_text(source,encoding='utf-8')
    chart=import_source(svg);chart.regions,chart.fiducials,chart.physical_size_mm=detect_svg_usaf(svg,all_frequencies=True);chart.calibrated=True
    preview=root/'reference.png';render_source(svg,max_side=1656,output=preview)
    a=.12+np.asarray(Image.open(preview).convert('RGB'))[...,0].astype(np.float32)/255*.73
    g=cv2.GaussianBlur(a,(0,0),.8)
    r=cv2.warpAffine(cv2.GaussianBlur(a,(0,0),1.1),np.array([[1,0,.4],[0,1,-.55]],np.float32),(len(a),len(a)),borderMode=cv2.BORDER_REFLECT)
    b=cv2.warpAffine(cv2.GaussianBlur(a,(0,0),1.4),np.array([[1,0,-.6],[0,1,.35]],np.float32),(len(a),len(a)),borderMode=cv2.BORDER_REFLECT)
    rgb=np.flip(np.rint(np.stack([r,g,b],axis=2)*65535).astype(np.uint16),axis=0).copy();path=root/'truth_scan.tif';tifffile.imwrite(path,rgb,photometric='rgb',metadata=None)
    config=AnalysisConfig(channels='RGBY',transfer='linear',registration='usaf',reject_clipping=False,cache_dir=str(root/'cache'),metric='resolution_limit')
    result=analyze(path,chart,config)
    return root,result,rgb,preview


def test_native_whole_chart_recovers_channels_shifts_and_units(whole_truth):
    root,result,rgb,preview=whole_truth
    assert set(result.optical_summary['channels'])=={'R','G','B','Y','Y_align'}
    assert len(result.optical_summary['units'])==9
    combined=view_result(result,'resolution_limit').measurements
    assert len(combined)==45 and all(m.metric('resolution_limit') is not None for m in combined)
    for unit in result.optical_summary['units']:
        for ch,dx,dy in [('R',.4,.55),('B',-.6,-.35)]:
            shift=unit['rgb_shifts'][ch]
            assert shift['valid'] and shift['dx_px']==pytest.approx(dx,abs=.1) and shift['dy_px']==pytest.approx(dy,abs=.1)
    for m in combined:
        assert m.values['resolution_limit_dpi']==pytest.approx(m.values['resolution_limit_lp_mm']*50.8)
    occluded=next(r for r in result.template['regions'] if r['id']=='svg-usaf-001-vertical-g0e6')
    assert occluded['params']['profile_band'][1]<.5
    assert all(m.values['detected_bar_count']==3 for m in result.measurements if m.region_id==occluded['id'])
    assert np.array_equal(tifffile.imread(result.image.path),rgb)


def test_whole_reports_are_compact_and_preserve_complete_curves(whole_truth,tmp_path):
    from mutex_imatest.reports_usaf import export_html,export_pdf,export_tables
    from PySide6.QtPdf import QPdfDocument
    root,result,rgb,preview=whole_truth
    export_html(result,preview,tmp_path/'report.html');export_pdf(result,preview,tmp_path/'report.pdf');export_tables(result,tmp_path)
    text=(tmp_path/'report.html').read_text(encoding='utf-8')
    assert text.count('<details class="unit">')==9 and 'Y_align' in text and 'data:image/png;base64,' in text
    assert '<script src=' not in text and str(result.image.fingerprint) in text
    assert (tmp_path/'ctf_curves.csv').stat().st_size>1000
    doc=QPdfDocument(None);assert doc.load(str(tmp_path/'report.pdf'))==QPdfDocument.Error.None_
    assert doc.pageCount()>=4
    pdf_text='\n'.join(doc.getAllText(i).text() for i in range(doc.pageCount()))
    assert '结果评价' in pdf_text and '参考值' in pdf_text and '评价标准' in pdf_text
    doc.close()


def test_native_gray_tiff_has_truth_weights_and_validity_mask(whole_truth,tmp_path):
    from mutex_imatest.gray_export import export_gray
    root,result,rgb,preview=whole_truth
    export_gray(result,tmp_path)
    before=tifffile.imread(tmp_path/'Y.tif');after=tifffile.imread(tmp_path/'Y_align.tif');mask=tifffile.imread(tmp_path/'alignment_valid_mask.tif')
    assert before.shape==rgb.shape[:2] and before.dtype==np.uint16 and after.dtype==np.uint16
    expected=rgb.astype(float)@np.array(result.optical_summary['gray_weights'])
    assert np.max(np.abs(before.astype(float)-expected))<=.51
    assert mask.max()==255 and mask.min()==0 and np.all(after[mask==0]==0)
    info=json.loads((tmp_path/'gray-export.json').read_text(encoding='utf-8'))
    assert info['source_sha256']==result.image.fingerprint and info['valid_pixels']['Y_align']==np.sum(mask>0)


def test_five_channel_focus_recovers_axial_offsets():
    from test_science import focus_truth_results
    from mutex_imatest.focus import analyze_focus
    results=focus_truth_results();offsets={'R':.12,'G':0,'B':-.08,'Y':.02,'Y_align':.01}
    for result in results:
        rows=[]
        for m in result.measurements:
            for ch,offset in offsets.items():
                n=copy.deepcopy(m);n.channel=ch
                x,y=np.array(m.position)/1000*100-50;peak=.1+.002*x-.001*y+.0001*(x*x+y*y)+offset
                n.values={'usaf_focus_score':1-.25*(result.focus_position-peak)**2};n.kind='usaf_summary';n.direction_deg=None
                rows.append(n)
        result.measurements=rows;result.settings['channels']='RGBY';result.optical_summary={'channels':list(offsets)}
    fit=analyze_focus(results,'usaf_focus_score','ALL',height_calibrated=True)
    assert set(fit.channel_results)==set(offsets)
    assert fit.rgb_focus_offsets['R-G']['median']==pytest.approx(.12,abs=1e-8)
    assert fit.rgb_focus_offsets['B-G']['median']==pytest.approx(-.08,abs=1e-8)
    assert fit.rgb_focus_offsets['R-G']['count']==9
    results[0].settings['gray_weights']=[.3,.6,.1]
    with pytest.raises(ValueError,match='相同'):analyze_focus(results,'usaf_focus_score','G')


def test_full_result_ui_channel_switch_ctf_and_focus_views(whole_truth,qtbot):
    from mutex_imatest.ui.main_window import MainWindow
    root,result,rgb,preview=whole_truth
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    window.entries=[{'path':result.image.path,'result':result,'metadata':result.image,'preview':str(preview),'config':result.settings}]
    window.current_index=0;window.metric_selector.setCurrentIndex(window.metric_selector.findData('resolution_limit'))
    window.display_entry(0)
    requested=window.metric_selector.checked_keys()
    window.metric_selector.setCurrentIndex(window.metric_selector.findData('ctf20'))
    assert window.metric_selector.checked_keys()==requested
    window.metric_selector.setCurrentIndex(window.metric_selector.findData('resolution_limit'))
    for ch in ['R','G','B','Y','Y_align']:
        window.channel.setCurrentText(ch);window.update_visuals()
        assert window.table.rowCount()==9 and window.channel.currentText()==ch
        assert '有效单元 9' in window.summary_label.text()
        assert len(window.curve.listDataItems())==10
    window.unit.setCurrentText('DPI');window.update_visuals()
    assert window.unit.currentText()=='DPI'
    assert '等效分辨 DPI' in window.optical_detail.toPlainText()
    window.close()


def test_imported_result_preserves_host_cache_and_preview_pipeline(whole_truth,qtbot,tmp_path):
    from mutex_imatest.ui.main_window import MainWindow
    root,original,rgb,preview=whole_truth
    result=copy.deepcopy(original)
    blocked=tmp_path/'foreign-cache';blocked.write_text('A file cannot be used as a cache directory')
    result.settings['cache_dir']=str(blocked)
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    window.config.cache_dir=str(tmp_path/'host-cache')
    window.add_result(result)
    qtbot.waitUntil(lambda:bool(window.entries[0]['preview']),timeout=90000)
    assert window.config.cache_dir==str(tmp_path/'host-cache')
    assert window.entries[0]['config']['cache_dir']==str(tmp_path/'host-cache')
    assert window.entries[0]['result'].settings['cache_dir']==str(blocked)
    assert window.entries[0]['config']['transfer']==result.settings['transfer']
    window.close()


def test_old_desktop_relative_cache_preferences_migrate_to_user_default(tmp_path):
    from mutex_imatest.config import save_config,load_config
    config=AnalysisConfig(cache_dir='foreign/relative/cache',transfer='gamma',gamma=2.1)
    save_config(config)
    migrated=load_config()
    assert migrated.cache_dir=='' and migrated.transfer=='gamma' and migrated.gamma==2.1


def test_fixed_rgb_pair_list_selects_correct_channel_and_disabled_items_stay_disabled(whole_truth,qtbot):
    from mutex_imatest.ui.main_window import MainWindow
    from mutex_imatest.ui.availability import ENABLED_TEXT,DISABLED_TEXT
    from PySide6.QtCore import Qt
    root,result,rgb,preview=whole_truth
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    window.entries=[{'path':result.image.path,'result':result,'metadata':result.image,'preview':str(preview),'config':result.settings}];window.current_index=0
    window.display_entry(0)
    for key,ch in [('ca_r_g_px','R'),('ca_b_g_px','B')]:
        idx=window.metric_selector.findData(key);item=window.metric_selector.model().item(idx)
        assert item.isEnabled() and item.foreground().color().name()==ENABLED_TEXT
        window.metric_selector.setCurrentIndex(idx)
        assert window.metric_selector.currentData()==key and window.channel.currentText()==ch
        assert not window.channel.isEnabled() and window.table.rowCount()==9
        assert len(window.viewer.refresh_overlay()['values'])==9
    idx=window.metric_selector.findData('mtf50');item=window.metric_selector.model().item(idx)
    assert not item.isEnabled() and item.foreground().color().name()==DISABLED_TEXT and '不可用' in item.text()
    assert item.toolTip()
    view=window.metric_selector;index=view.model().index(idx,0);view.scrollTo(index)
    qtbot.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=view.visualRect(index).center())
    assert window.metric_selector.currentData()=='ca_b_g_px'
    window.close()


def test_whole_chart_preserves_and_measures_other_pattern_rois(whole_truth,tmp_path):
    from mutex_imatest.models import ChartDefinition,Region
    root,original,rgb,preview=whole_truth
    chart=ChartDefinition.from_dict(original.template);chart.regions.append(Region('manual-flat','flat',(.95,.95,.025,.025),'附加均匀块'))
    config=AnalysisConfig.from_dict(original.settings);config.cache_dir=str(tmp_path/'cache')
    result=analyze(original.image.path,chart,config)
    extra=[m for m in result.measurements if m.region_id=='manual-flat']
    assert len(extra)==4 and all(m.valid and m.values.get('mean') is not None for m in extra)
    assert all('nearby_unit_registration' in m.flags for m in extra)
    assert len(view_result(result,'mean').measurements)==4
    assert result.optical_summary['statistics']['G']['resolution_limit']==original.optical_summary['statistics']['G']['resolution_limit']
