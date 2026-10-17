"""The whole-card desktop shortcut also accepts a PDF mixed-target card."""
from PIL import Image
from mutex_imatest.models import ChartDefinition,Region
from mutex_imatest.analysis_catalog import SEQUENCE_METRICS


def test_whole_card_shortcut_uses_mixed_pdf_rois_without_svg_expansion(qtbot,tmp_path,monkeypatch):
    from mutex_imatest.ui.main_window import MainWindow
    preview=tmp_path/'reference.png';Image.new('RGB',(300,200),'white').save(preview)
    chart=ChartDefinition('mixed-pdf','Mixed PDF',[
        Region('s','star',(.1,.1,.2,.3),params={'cycles':36,'pattern':'binary','auto_detect':True}),
        Region('e','edge',(.4,.1,.1,.3)),
        Region('w','wedge',(.6,.1,.2,.3),params={'frequency_samples':[{'t':0,'cycles_across':6},{'t':1,'cycles_across':36}]})],
        preview=str(preview),source_path=str(tmp_path/'private.pdf'))
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False
    window.charts.append(chart);window.chart_combo.addItem(chart.name,chart.id);window.chart_combo.setCurrentIndex(len(window.charts)-1)
    window.clipping_policy.setCurrentIndex(window.clipping_policy.findData(True))
    seen=[];errors=[]
    monkeypatch.setattr(window,'analyze_selected',lambda:seen.append(window.snapshot_config().to_dict()))
    monkeypatch.setattr(window,'message_error',lambda value:errors.append(str(value)))
    def no_svg(*args,**kwargs):raise AssertionError('PDF must use its existing mixed ROIs')
    monkeypatch.setattr('mutex_imatest.vector_usaf.detect_svg_usaf',no_svg)
    window.analyze_whole_card()
    assert not errors and len(seen)==1
    config=seen[0];selected=set(config['analysis_metrics'])
    assert config['channels']=='RGBY' and config['registration']=='auto_chart'
    assert config['reject_clipping'] and config['transfer']=='unknown'
    assert {'mtf50','ctf50','resolution_limit','star_anisotropy','wedge_alias_fraction','ca_r_g_px','ca_b_g_px'}<=selected
    assert not selected&SEQUENCE_METRICS and 'alignment_gain_pct' not in selected
    assert window.metric_selector.currentData()=='resolution_limit'
    assert len(chart.regions)==3 and chart.source_path.endswith('.pdf')
    window.close()
