from pathlib import Path
import numpy as np
import tifffile
import pytest
from mutex_imatest.imaging import ImageSource
from mutex_imatest.models import ChartDefinition,Region,AnalysisResult
from mutex_imatest.analysis.engine import analyze
from mutex_imatest.heatmap import heatmap_data
from mutex_imatest.analysis.preprocess import linearize
from mutex_imatest.demo import demo_definition,generate_frame
from mutex_imatest.utils import focus_from_name,cache_trim

@pytest.mark.parametrize("compression",[None,"deflate","lzw"])
@pytest.mark.parametrize("planar",[False,True])
def test_48bit_tiff_exact_roi_and_readonly(tmp_path,compression,planar,config):
    ramp=(np.arange(90*100*3,dtype=np.uint32).reshape(90,100,3)*13%65536).astype(np.uint16)
    array=np.moveaxis(ramp,-1,0) if planar else ramp
    path=tmp_path/"ramp.tif"
    tifffile.imwrite(path,array,photometric="rgb",planarconfig="separate" if planar else "contig",compression=compression,metadata=None)
    before=path.read_bytes()
    with ImageSource(path,config) as source:
        roi=source.read_roi((13,17,31,29))
        assert roi.dtype==np.uint16
        np.testing.assert_array_equal(roi,ramp[17:46,13:44])
        assert source.metadata.bits_per_sample==16
        assert source.preview(50).shape[-1]==3
    assert path.read_bytes()==before

def test_oecf_monotonic_and_gamma(config):
    values=np.array([[0,16384,32768,65535]],np.uint16)
    config.transfer="gamma";config.gamma=2
    np.testing.assert_allclose(linearize(values,config),(values/65535)**2)
    # RAW native-linear overrides display transfer configuration.
    np.testing.assert_allclose(linearize(values,config,True),values/65535)

def test_synthetic_engine_ca_scale_roundtrip(tmp_path,config):
    chart=demo_definition();a,_=generate_frame(chart,.2)
    path=tmp_path/"sample_z+0.20mm.tif";tifffile.imwrite(path,a,photometric="rgb",metadata=None)
    config.channels="RGB"
    result=analyze(path,chart,config)
    m=next(m for m in result.measurements if m.kind=="edge" and m.channel=="G")
    assert m.valid and m.values["ca_r_g_px"]==pytest.approx(.35,abs=.1)
    assert m.values["ca_b_g_px"]==pytest.approx(-.25,abs=.1)
    assert m.values["mtf50_lp_mm"]==pytest.approx(m.values["mtf50"]*10,rel=.001)
    assert result.focus_position==pytest.approx(.2) and result.focus_unit=="mm"
    out=tmp_path/"result.json";result.save(out)
    assert AnalysisResult.load(out).image.fingerprint==result.image.fingerprint

def test_heatmap_no_extrapolation(tmp_path,config):
    from mutex_imatest.models import ImageMetadata,Measurement,AnalysisResult
    image=ImageMetadata("fake",100,100,3,"uint16",16,1,"abc")
    measurements=[Measurement(str(i),"","edge","G",p,(p[0]-5,p[1]-5,10,10),values={"mtf50":v}) for i,(p,v) in enumerate([
        ((25,25),.1),((75,25),.2),((50,75),.3)])]
    result=AnalysisResult(image,"test","test",measurements,{}, {})
    field=heatmap_data(result,"mtf50",width=100,height=100)["field"]
    assert np.isnan(field[0,0]) and np.isnan(field[-1,-1])
    assert np.isfinite(field[40,50])


def test_tall_heatmap_preserves_square_sampling_grid():
    from mutex_imatest.models import ImageMetadata,Measurement,AnalysisResult
    image=ImageMetadata("tall",100,400,3,"uint16",16,1,"abc")
    points=[(x+offset,y) for y in range(20,381,30) for x in (20,50,80) for offset in (-2,2)]
    measurements=[Measurement(str(i),"","usaf","G",p,(p[0]-2,p[1]-5,4,10),values={"contrast_at_frequency":p[1]/400})
                  for i,p in enumerate(points)]
    result=AnalysisResult(image,"test","test",measurements,{}, {})
    field=heatmap_data(result,"contrast_at_frequency",width=100,height=400)["field"]
    assert np.isfinite(field[200,35]) and np.isfinite(field[200,65])
    assert field[200,35]==pytest.approx(200/399,abs=.001)
    assert np.isnan(field[0,0]) and np.isnan(field[200,95])

def test_focus_file_name():
    assert focus_from_name("scan_z-0.25mm.tiff")==(-.25,"mm")
    assert focus_from_name("scan_z12um.tif")==(12,"um")
    assert focus_from_name("photo.tif")==(None,"index")

def test_cache_eviction_does_not_delete_foreign_directory(tmp_path):
    foreign=tmp_path/"keep";foreign.mkdir();(foreign/"important.txt").write_text("data")
    owned=tmp_path/("a"*64);owned.mkdir();(owned/"MUTEX_CACHE").touch();(owned/"pixels").write_bytes(b"x"*200)
    cache_trim(tmp_path,1)
    assert foreign.exists() and not owned.exists()

def test_roi_budget_guard(tmp_path,config):
    path=tmp_path/"large.tif"
    tifffile.imwrite(path,shape=(2000,2000,3),dtype=np.uint16,photometric="rgb",metadata=None)
    config.memory_mb=32
    with ImageSource(path,config) as source:
        with pytest.raises(MemoryError):source.read_roi((0,0,2000,2000))

@pytest.mark.parametrize("compression",[None,"deflate"])
def test_miniswhite_decoder_semantics_agree(tmp_path,config,compression):
    a=np.arange(200*300,dtype=np.uint16).reshape(200,300)
    path=tmp_path/"white-zero.tif"
    tifffile.imwrite(path,a,photometric="miniswhite",compression=compression,metadata=None)
    with ImageSource(path,config) as source:
        np.testing.assert_array_equal(source.read_roi((10,10,20,20)),65535-a[10:30,10:30])

