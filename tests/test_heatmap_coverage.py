import copy
import numpy as np
import pytest
from PIL import Image
from mutex_imatest.models import AnalysisResult,ImageMetadata,Measurement,ChartDefinition,Region
from mutex_imatest.heatmap import heatmap_data,heatmap_rgba
from mutex_imatest.resolution import view_result


def result(rows,width=100,height=100):
    return AnalysisResult(ImageMetadata('synthetic',width,height,3,'uint8',8,1,'test'),'test','test',rows,{}, {})


def sample(key,position,box,value,**extra):
    return Measurement(key,key,'edge','G',position,box,values={'mtf50':value},**extra)


def test_center_plane_unchanged_and_boundary_extends_to_real_roi_edges():
    r=result([sample('tl',(30,30),(20,20,20,20),.1),sample('tr',(70,30),(60,20,20,20),.3),
              sample('bl',(30,70),(20,60,20,20),.3),sample('br',(70,70),(60,60,20,20),.5)])
    before=copy.deepcopy(r.to_dict());data=heatmap_rgba(r,'mtf50',width=101,height=101)
    f=data['field']
    assert f[20,20]==pytest.approx(.1) and f[20,80]==pytest.approx(.3)
    assert f[80,20]==pytest.approx(.3) and f[80,80]==pytest.approx(.5)
    assert f[20,50]==pytest.approx(.2) and f[50,80]==pytest.approx(.4)
    assert f[40,50]==pytest.approx(.25) and f[50,50]==pytest.approx(.3)
    assert np.isfinite(f[20:81,20:81]).all()
    assert np.isnan(f[19,:]).all() and np.isnan(f[:,81]).all()
    assert data['rgba'][20,20,3]>0 and data['rgba'][19,20,3]==0
    assert np.nanmin(f)>=.1 and np.nanmax(f)<=.5
    assert r.to_dict()==before


def test_existing_nonplanar_center_mesh_and_its_diagonals_are_preserved():
    from scipy.spatial import Delaunay
    from scipy.interpolate import LinearNDInterpolator
    rng=np.random.default_rng(352)
    points=np.array([(x,y) for y in [20,40,60,80] for x in [20,40,60,80]])
    points=points[rng.permutation(len(points))];values=rng.uniform(.1,.5,len(points))
    r=result([sample(str(i),p,(p[0]-5,p[1]-5,10,10),v) for i,(p,v) in enumerate(zip(points,values))])
    data=heatmap_data(r,'mtf50',width=101,height=101)
    yy,xx=np.mgrid[20:81,20:81];query=np.column_stack([xx.ravel(),yy.ravel()])/100
    old=LinearNDInterpolator(Delaunay(points/100),values)(query).reshape(xx.shape)
    np.testing.assert_allclose(data['field'][20:81,20:81],old,atol=1e-13)


@pytest.mark.parametrize('layout',['single','row','column'])
def test_single_and_collinear_regions_have_full_width_coverage(layout):
    points={'single':[(50,50)],'row':[(25,50),(50,50),(75,50)],'column':[(50,25),(50,50),(50,75)]}[layout]
    r=result([sample(str(i),p,(p[0]-10,p[1]-10,20,20),.1+i*.1) for i,p in enumerate(points)])
    f=heatmap_data(r,'mtf50',width=101,height=101)['field']
    x,y=points[0];assert f[y-10,x-10]==pytest.approx(.1)
    x,y=points[-1];assert f[y+10,x+10]==pytest.approx(.1+(len(points)-1)*.1)
    assert np.isnan(f[0,0])
    if layout=='row':assert np.isfinite(f[40:61,15:86]).all() and np.isnan(f[39,50])
    if layout=='column':assert np.isfinite(f[15:86,40:61]).all() and np.isnan(f[50,39])


def test_invalid_missing_and_low_confidence_regions_do_not_expand_support():
    r=result([sample('good',(20,20),(10,10,20,20),.2),
              sample('failed',(80,20),(60,10,30,30),.8,flags=['registration_failed']),
              sample('weak',(20,80),(10,60,30,30),.8,confidence=.01),
              Measurement('absent','absent','star','G',(80,80),(60,60,30,30),values={'ctf50':.1})])
    d=heatmap_data(r,'mtf50',width=101,height=101)
    assert d['ids']==['good'] and np.isfinite(d['field'][10:31,10:31]).all()
    assert np.isnan(d['field'][20,80]) and np.isnan(d['field'][80,20]) and np.isnan(d['field'][80,80])


def test_disconnected_clusters_keep_large_unmeasured_gap_transparent():
    points=[(x,y) for x in [20,40,160,180] for y in [20,40]]
    r=result([sample(str(i),p,(p[0]-5,p[1]-5,10,10),.1+i*.05) for i,p in enumerate(points)],200,100)
    f=heatmap_data(r,'mtf50',width=201,height=101)['field']
    assert np.isfinite(f[15:46,15:46]).all() and np.isfinite(f[15:46,155:186]).all()
    assert np.isnan(f[:,60:141]).all()


def test_disabled_interpolation_colors_only_each_roi_not_the_gap():
    r=result([sample('a',(25,50),(15,40,20,20),.1),sample('b',(75,50),(65,40,20,20),.3)])
    f=heatmap_data(r,'mtf50',width=101,height=101,interpolate=False)['field']
    assert np.all(f[40:61,15:36]==.1) and np.all(f[40:61,65:86]==.3)
    assert np.isnan(f[50,50])


def test_coincident_centers_are_stable_and_raw_values_are_preserved():
    r=result([sample('a',(50,50),(40,40,20,20),.1),sample('b',(50,50),(40,40,20,20),.3)])
    d=heatmap_data(r,'mtf50',width=101,height=101)
    assert d['values'].tolist()==[.1,.3] and d['field'][40,40]==pytest.approx(.2)


def whole_result():
    # The marker deliberately differs from the real chart footprint. The
    # saved matrix also covers a reflected/local registration, not full-frame.
    chart=ChartDefinition('whole','whole',[Region('u-bars','usaf',(.1,.2,.3,.4),params={'unit_id':'u'})])
    rows=[Measurement('u-bars','bars','usaf','G',(55,55),(40,35,30,40),values={'ctf':.2}),
          Measurement('u-combined-summary','u','usaf_summary','G',(55,55),(53,53,4,4),values={'resolution_limit':.2})]
    unit={'unit_id':'u','position':[55,55],'located':True,'rgb_shifts':{'R':{'valid':True,'magnitude_px':1.,'correlation':.99}}}
    r=result(rows);r.template=chart.to_dict();r.optical_summary={'units':[unit]}
    r.registration={'unit_transforms':{'u':{'homography':[[-100,0,80],[0,100,15],[0,0,1]]}}}
    return r


@pytest.mark.parametrize('metric',['resolution_limit','ca_r_g_px','best_focus'])
def test_usaf_unit_rgb_and_focus_maps_recover_native_or_registered_extent(metric):
    r=whole_result();before=copy.deepcopy(r.to_dict())
    if metric=='best_focus':
        m=copy.deepcopy(r.measurements[-1]);m.kind='focus';m.values={'best_focus':.12};r.measurements=[m];r.optical_summary={}
        before=copy.deepcopy(r.to_dict())
    elif metric=='ca_r_g_px':
        # This is also what the GUI passes to the viewer: a metric view whose
        # original element rows are gone. Saved local geometry must suffice.
        r=view_result(r,metric);before=copy.deepcopy(r.to_dict())
    d=heatmap_data(r,metric,width=101,height=101)
    np.testing.assert_array_equal(d['boxes'][0],[40,35,30,40])
    assert np.isfinite(d['field'][35:76,40:71]).all()
    assert np.isnan(d['field'][34,55]) and np.isnan(d['field'][55,71])
    assert r.to_dict()==before


def test_export_overlay_uses_same_region_boundary_as_view(tmp_path):
    from mutex_imatest.reports import export_overlay
    r=result([sample('a',(50,50),(20,30,60,40),.25)])
    preview=tmp_path/'preview.png';Image.new('RGB',(101,101),'white').save(preview)
    data=export_overlay(r,preview,tmp_path/'heatmap.png')
    expected=heatmap_rgba(r,'mtf50',width=101,height=101)
    np.testing.assert_allclose(data['field'],expected['field'],equal_nan=True)
    # Below the report's label band, the physical ROI edge is colored and
    # outside remains the source preview. This tests the actual PNG output.
    pixels=np.asarray(Image.open(tmp_path/'heatmap.png'))
    assert not np.all(pixels[60,20]==255) and np.all(pixels[60,19]==255)


def test_export_respects_disabled_interpolation_setting(tmp_path):
    from mutex_imatest.reports import export_overlay
    r=result([sample('a',(25,50),(15,40,20,20),.1),sample('b',(75,50),(65,40,20,20),.3)])
    r.settings['interpolate']=False
    preview=tmp_path/'preview.png';Image.new('RGB',(101,101),'white').save(preview)
    data=export_overlay(r,preview,tmp_path/'heatmap.png')
    assert np.isfinite(data['field'][50,15]) and np.isnan(data['field'][50,50])


def test_raw_and_filtered_whole_card_views_have_identical_boundaries():
    r=whole_result()
    # Pixel sampling of a shifted channel is separate from the G-coordinate
    # unit envelope saved by registration. Every view must use that envelope.
    r.measurements[0].box_pixels=(41,36,28,38)
    raw=heatmap_data(r,'resolution_limit',width=101,height=101)
    filtered=heatmap_data(view_result(r,'resolution_limit'),'resolution_limit',width=101,height=101)
    np.testing.assert_array_equal(raw['boxes'],filtered['boxes'])
    np.testing.assert_allclose(raw['field'],filtered['field'],equal_nan=True)
