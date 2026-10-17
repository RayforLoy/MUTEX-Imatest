"""Public synthetic truth cases: crop registration, binary CTF, no fake scale."""
import cv2
import numpy as np
import pytest
import tifffile
from PIL import Image
from mutex_imatest.analysis.targets import star
from mutex_imatest.analysis.wedge import wedge
from mutex_imatest.analysis.engine import analyze
from mutex_imatest.chart_targets import discover_regions
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.models import ChartDefinition,Region


def test_binary_star_ctf_and_direction_are_distinct_from_mtf():
    yy,xx=np.mgrid[:700,:700];theta=np.arctan2(yy-349.5,xx-349.5)
    pattern=.12+.7*(np.cos(36*theta)>0)
    config=AnalysisConfig(reject_clipping=False)
    good=star(cv2.GaussianBlur(pattern,(0,0),1.1),{'cycles':36,'pattern':'binary'},config)
    soft=star(cv2.GaussianBlur(pattern,(0,0),2.3),{'cycles':36,'pattern':'binary'},config)
    assert 'mtf50' not in good['values'] and good['values']['ctf50']>soft['values']['ctf50']
    assert good['values']['resolution_limit']>soft['values']['resolution_limit']
    assert .9<soft['values']['star_anisotropy']<1.15
    assert len([key for key in good['curves'] if key.startswith('star_sector_')])==8
    wrong=star(pattern,{'cycles':24,'pattern':'binary'},config)
    assert wrong['flags']==['target_mismatch'] and wrong['values']=={}


def test_star_thresholds_do_not_cross_after_its_expected_harmonic_is_lost():
    from mutex_imatest.analysis.sfr import first_crossing
    from scipy.ndimage import median_filter
    yy,xx=np.mgrid[:700,:700];radius=np.hypot(xx-349.5,yy-349.5)
    theta=np.arctan2(yy-349.5,xx-349.5)
    # An outer 36-cycle star turns into a wrong 72-cycle pattern in the
    # center. Its black/white contrast remains substantial after the expected
    # fundamental is lost, so unguarded CTF thresholds produce false results.
    pattern=.12+.7*(np.cos(np.where(radius>160,36,72)*theta)>0)
    output=star(cv2.GaussianBlur(pattern,(0,0),1.5),{'cycles':36,'pattern':'binary'},AnalysisConfig(reject_clipping=False))
    f=np.array(output['curves']['star']['x']);response=np.array(output['curves']['star']['y'])
    coherence=np.array(output['curves']['star_coherence']['y'])
    first_bad=int(np.flatnonzero(coherence<=.2)[0])
    unguarded=first_crossing(f,np.minimum.accumulate(median_filter(response,size=3,mode='nearest')),.5)
    assert unguarded>f[first_bad]  # The test actually exercises the old bug.
    assert all(output['values'][key] is None for key in ['response50','ctf50','ctf20','ctf10'])
    assert output['values']['resolution_limit']<f[first_bad]
    assert output['values']['star_faithful_fraction']==pytest.approx(first_bad/len(f))
    assert 'star_frequency_mismatch' in output['flags']
    assert len(f)==80 and f[-1]>unguarded  # Full diagnostics stay available.


def test_wedge_knows_expected_frequency_and_rejects_later_alias_lobes():
    yy,xx=np.mgrid[:650,:900];t=yy/649;u=xx/899
    pattern=.12+.7*(np.cos(2*np.pi*(6+170*t)*(u-.5))>0)
    params={'direction':'vertical','frequency_samples':[{'t':0,'cycles_across':6},{'t':1,'cycles_across':176}]}
    config=AnalysisConfig(reject_clipping=False,target_frequency=.1)
    good=wedge(cv2.GaussianBlur(pattern,(0,0),1.2),params,config)
    soft=wedge(cv2.GaussianBlur(pattern,(0,0),2.5),params,config)
    assert good['values']['ctf50']>soft['values']['ctf50']
    assert good['values']['resolution_limit']>soft['values']['resolution_limit']
    assert 'mtf50' not in good['values'] and good['values']['contrast_at_frequency']>0
    assert 0<=good['values']['wedge_alias_fraction']<=1


@pytest.mark.parametrize('mirror',[False,True])
def test_partial_reference_registration_measures_visible_rois_only(tmp_path,mirror):
    from scipy.special import erf
    rng=np.random.default_rng(7);canvas=np.full((1000,1400),.83)
    for x,y,r in zip(rng.integers(30,1370,120),rng.integers(30,970,120),rng.integers(3,10,120)):
        cv2.circle(canvas,(int(x),int(y)),int(r),float(rng.uniform(.1,.5)),-1)
    boxes=[(.15,.2,.08,.24),(.58,.2,.08,.24),(.7,.65,.08,.24)]
    for x,y,w,h in boxes:
        x0,y0,xw,yh=int(x*1400),int(y*1000),int(w*1400),int(h*1000)
        yy,xx=np.mgrid[:yh,:xw];d=xx-xw/2-.08*(yy-yh/2)
        canvas[y0:y0+yh,x0:x0+xw]=.12+.7*(.5+.5*erf(d/2))
    image=np.uint8(np.rint(canvas*255));preview=tmp_path/'ref.png';Image.fromarray(image).save(preview)
    # Remove the lower half of the chart, then rotate and optionally mirror.
    crop=np.rot90(image[100:600,100:1300])
    if mirror:crop=np.fliplr(crop)
    sample=tmp_path/'partial.tif';tifffile.imwrite(sample,crop)
    chart=ChartDefinition('partial','Partial reference',[Region(f'e{i}','edge',box) for i,box in enumerate(boxes)],
                          physical_size_mm=(210,297),calibrated=False,preview=str(preview))
    result=analyze(sample,chart,AnalysisConfig(registration='auto_chart',reject_clipping=False,transfer='linear'))
    assert result.registration['method']=='reference_sift_partial_homography'
    assert result.registration['verified'] and result.registration['inliers']>=12
    assert len(result.registration['visible_regions'])==2
    outside=[m for m in result.measurements if m.region_id=='e2']
    assert outside and all(m.flags==['roi_outside'] and not m.values for m in outside)
    assert all(m.metric('mtf50') is not None for m in result.measurements if m.region_id!='e2')
    assert all(m.values.get('mtf50_lp_mm') is None for m in result.measurements)


def test_edge_detection_handles_opencv_line_array_variants():
    # OpenCV 4 returns Nx1x4 while OpenCV 5 returns Nx4.
    image=np.full((500,500,3),230,np.uint8)
    cv2.fillConvexPoly(image,np.array([[150,100],[330,116],[314,296],[134,280]]),[30,30,30])
    regions=discover_regions(image,max_stars=1,max_edges=8)
    assert any(r.kind=='edge' for r in regions)


def test_unknown_single_star_crop_does_not_borrow_printed_template_scale(tmp_path):
    yy,xx=np.mgrid[:600,:600];radius=np.hypot(xx-299.5,yy-299.5)
    a=np.full((600,600),.82);pattern=.12+.7*(np.cos(36*np.arctan2(yy-299.5,xx-299.5))>0)
    a[radius<240]=pattern[radius<240]
    a=np.uint8(np.rint(cv2.GaussianBlur(a,(0,0),1.4)*255))
    sample=tmp_path/'single-star.tif';tifffile.imwrite(sample,a)
    blank=tmp_path/'unrelated.png';Image.fromarray(np.full((200,300),255,np.uint8)).save(blank)
    chart=ChartDefinition('unrelated','Different printed card',[Region('generic','star',(.1,.1,.8,.8),params={'cycles':36,'auto_detect':True})],
                          physical_size_mm=(210,297),calibrated=True,preview=str(blank))
    result=analyze(sample,chart,AnalysisConfig(registration='auto_chart',reject_clipping=False,transfer='linear'))
    assert result.registration['method']=='generic_detected_targets'
    assert not result.template['calibrated'] and result.template['physical_size_mm'] is None
    stars=[m for m in result.measurements if m.kind=='star']
    assert len(stars)==1 and stars[0].metric('ctf50')>0 and stars[0].metric('resolution_limit')>0
    assert stars[0].values.get('ctf50_lp_mm') is None and 'mtf50' not in stars[0].values


def test_reprepare_preserves_authored_wedge_manual_roi_and_calibration(tmp_path,monkeypatch):
    from mutex_imatest.chart_targets import prepare_chart_targets
    image=tmp_path/'preview.png';Image.fromarray(np.full((200,300),255,np.uint8)).save(image)
    manual=Region('edge-001','edge',(.1,.1,.1,.2),'Manual',{'note':'keep'})
    exact=Region('public-star','star',(.5,.5,.2,.2),'Exact',{'auto_detect':True,'target_family':'siemens_star','cycles':36})
    authored=Region('w','wedge',(.3,.1,.2,.2),params={'frequency_samples':[{'t':0,'cycles_across':4},{'t':1,'cycles_across':30}]})
    old_auto=Region('auto-old','edge',(.8,.1,.1,.2),params={'auto_detect':True,'discovery_generated':True})
    chart=ChartDefinition('mixed','Mixed',[manual,exact,authored,old_auto],physical_size_mm=(300,200),calibrated=True,preview=str(image))
    generated=[Region('edge-001','edge',(.12,.12,.08,.16),params={'discovery_generated':True}),
               Region('edge-002','edge',(.75,.5,.05,.2),params={'discovery_generated':True})]
    monkeypatch.setattr('mutex_imatest.chart_targets.discover_regions',lambda *args,**kwargs:generated)
    result=prepare_chart_targets(chart)
    assert len(result.regions)==4 and len({r.id for r in result.regions})==4
    assert next(r for r in result.regions if r.id=='edge-001').params=={'note':'keep'}
    assert next(r for r in result.regions if r.id=='w').params==authored.params
    assert next(r for r in result.regions if r.id=='public-star').params==exact.params
    assert result.calibrated and result.physical_size_mm==(300.,200.)
    assert len(chart.regions)==4 and chart.regions[-1].id=='auto-old'


def test_rotated_wedge_physical_scale_follows_its_measured_cross_section():
    from mutex_imatest.chart_targets import target_physical_scale
    region=Region('w','wedge',(.2,.3,.25,.5),params={'direction':'vertical'})
    chart=ChartDefinition('scale','Scale',[region],physical_size_mm=(200,100),calibrated=True)
    # The ROI is 50 x 50 mm. A quarter turn maps its measured cross section
    # into native Y: 1000 px / 50 mm = 20 px/mm.
    H=np.array([[0,-500,600],[1000,0,100],[0,0,1]],float)
    assert target_physical_scale(chart,region,H)==pytest.approx(20)
    region.params['direction']='horizontal'
    assert target_physical_scale(chart,region,H)==pytest.approx(10)
    chart.calibrated=False
    assert target_physical_scale(chart,region,H) is None
