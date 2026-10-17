import numpy as np
import pytest
from scipy.special import erf
from mutex_imatest.analysis.sfr import slanted_edge
from mutex_imatest.analysis.targets import usaf_frequency
from mutex_imatest.analysis.extra import temporal_noise
from mutex_imatest.focus import fit_peak,analyze_focus
from mutex_imatest.models import Measurement,ImageMetadata,AnalysisResult,ChartDefinition,Region

@pytest.mark.parametrize("sigma",[.8,1.,1.5,2.,3.])
@pytest.mark.parametrize("axis",[0,1])
def test_gaussian_sfr_matches_analytic(sigma,axis,config):
    yy,xx=np.mgrid[:200,:160]
    distance=(xx-79.5-.08749*(yy-99.5))/np.sqrt(1+.08749**2)
    a=.12+.72*(.5+.5*erf(distance/(np.sqrt(2)*sigma)))
    if axis:a=a.T
    out=slanted_edge(a,config)
    expected=np.sqrt(2*np.log(2))/(2*np.pi*sigma)
    assert abs(out["values"]["mtf50"]/expected-1)<.05
    assert "invalid_edge" not in out["flags"]

def test_rgb_subpixel_shift(config):
    yy,xx=np.mgrid[:180,:128]
    d=(xx-63.5-.08*(yy-89.5))/np.sqrt(1+.08**2)
    outputs=[slanted_edge(.1+.75*(.5+.5*erf((d-s)/(np.sqrt(2)*1.2))),config) for s in [0,.37,-.29]]
    normal=np.asarray(outputs[0]["normal"]);base=np.asarray(outputs[0]["edge_center"])
    for out,expected in zip(outputs[1:],[.37,-.29]):
        measured=np.dot(np.asarray(out["edge_center"])-base,normal)
        assert abs(measured-expected)<.1

def test_invalid_parallel_edge(config):
    a=np.zeros((80,80))+.1;a[:,40:]=.8
    assert "invalid_edge" in slanted_edge(a,config)["flags"]

def test_usaf_frequency():
    assert usaf_frequency(0,1)==1
    assert usaf_frequency(2,1)==4
    assert usaf_frequency(-1,6)==pytest.approx(.5*2**(5/6))
    with pytest.raises(ValueError):usaf_frequency(0,7)

def test_anisotropic_physical_frequency_uses_covector_transform():
    from mutex_imatest.detection import local_scale
    chart=ChartDefinition("scale","scale",[],physical_size_mm=(100,100),calibrated=True)
    H=np.diag([1000.,2000.,1.])
    n=np.array([1,1])/np.sqrt(2)
    assert local_scale(chart,H,(500,1000),n)==pytest.approx(np.sqrt(250))

def test_usaf_contrast_not_diluted_by_roi_blank_margins(config):
    from mutex_imatest.analysis.targets import usaf
    yy,xx=np.mgrid[:80,:220];a=np.full((80,220),.82)
    for center in [97.5,110,122.5]:a[abs(xx-center)<3.125]=.12
    out=usaf(a,{"frequency_cy_px":.08,"direction":"vertical"},config)
    assert out["values"]["ctf"]==pytest.approx((.82-.12)/(.82+.12),rel=.01)
    assert out["values"]["resolved"]==1

def test_peak_bracketing_and_flatness():
    z=np.linspace(-1,1,9)
    scores=1-.4*(z-.15)**2
    p,u,c,flags,_=fit_peak(z,scores)
    assert p==pytest.approx(.15,abs=1e-8)
    assert not flags and c>.99
    assert fit_peak(z,np.ones(9))[3]==["flat_focus_response"]
    assert "peak_not_bracketed" in fit_peak(z,np.arange(9))[3]

def focus_truth_results():
    regions=[Region(f"r-{i}-{j}","edge",(.12+i*.32,.12+j*.32,.1,.1)) for j in range(3) for i in range(3)]
    chart=ChartDefinition("test","Test",regions,physical_size_mm=(100,100),calibrated=True)
    results=[]
    for z in np.linspace(-1,1.5,11):
        ms=[]
        for r in regions:
            x,y,w,h=r.box;px=(x+w/2)*1000;py=(y+h/2)*1000
            nx=(px/1000-.5)*100;ny=(py/1000-.5)*100
            peak=.1+.002*nx-.001*ny+.0001*(nx*nx+ny*ny)
            score=1-.25*(z-peak)**2
            ms.append(Measurement(r.id,r.id,"edge","G",(px,py),(0,0,64,64),values={"mtf50":score},method="fixed"))
        results.append(AnalysisResult(ImageMetadata("test",1000,1000,3,"uint16",16,1,str(z),decoder="test"),
          chart.id,chart.name,ms,{"channels":"G"},chart.to_dict(),{"homography":np.diag([1000,1000,1]).tolist()},float(z),"mm"))
    return results

def test_focus_field_recovers_plane_curvature():
    result=analyze_focus(focus_truth_results(),height_calibrated=True)
    assert result.field_model["coefficients"]==pytest.approx([.1,.002,-.001,.0001],abs=1e-8)
    assert result.field_model["physical_calibration"]
    assert result.recommended_position is not None
    assert len(result.peaks)==9

def test_focus_motor_mm_not_claimed_as_physical_tilt():
    result=analyze_focus(focus_truth_results())
    assert not result.field_model["physical_calibration"]
    assert "apparent_tilt_deg" not in result.field_model

def test_focus_rejects_incompatible_pipeline():
    results=focus_truth_results();results[0].settings["transfer"]="srgb"
    with pytest.raises(ValueError,match="相同"):analyze_focus(results)

def test_temporal_noise_separates_fixed_pattern():
    rng=np.random.default_rng(5)
    fixed=rng.normal(0,.02,(128,128))
    stack=.5+fixed+rng.normal(0,.01,(20,128,128))
    values=temporal_noise(stack)
    assert values["temporal_noise"]==pytest.approx(.01,rel=.02)
    assert values["fixed_pattern_rms"]==pytest.approx(.02,rel=.03)

