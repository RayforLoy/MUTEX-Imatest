import numpy as np
import pytest
import cv2
from mutex_imatest.analysis.rgb_registration import estimate_translation,align_gray
from mutex_imatest.analysis.usaf_multifrequency import summarize_curve
from mutex_imatest.models import Measurement
from mutex_imatest.resolution import frequency_values,view_result


def test_rgb_translation_sign_and_subpixel_truth():
    rng=np.random.default_rng(841)
    reference=cv2.GaussianBlur(rng.random((180,220)).astype(np.float32),(0,0),1.3)
    for dx,dy in [(.375,-.625),(-2.25,1.5)]:
        moving=cv2.warpAffine(reference,np.array([[1,0,dx],[0,1,dy]],np.float32),(220,180),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REFLECT)
        result=estimate_translation(reference,moving,max_shift=6)
        assert result['dx_px']==pytest.approx(dx,abs=.08)
        assert result['dy_px']==pytest.approx(dy,abs=.08)
        rgb=np.stack([moving,reference,reference],axis=2)
        aligned,valid=align_gray(rgb,{'R':result,'G':{'valid':True,'dx_px':0,'dy_px':0},'B':{'valid':True,'dx_px':0,'dy_px':0}},weights=(1,0,0))
        valid[:8]=False;valid[-8:]=False;valid[:,:8]=False;valid[:,-8:]=False
        assert np.mean((aligned[valid]-reference[valid])**2)<np.mean((moving[valid]-reference[valid])**2)


def _rows(contrasts):
    return [Measurement(str(i),'','usaf','G',(1,1),(0,0,32,32),
             values={'ctf':c,'target_frequency':.03*2**(i/6),'detected_bar_count':3}) for i,c in enumerate(contrasts)]


def test_resolution_revival_is_not_a_new_highest_pass():
    rows=_rows([.9,.85,.8,.7,.5,.3,.1,.8,.9])
    values,curve,flags,confidence=summarize_curve(rows,threshold=.2,mode='absolute',scale=100,height=1000)
    assert values['resolution_limit']==rows[5].values['target_frequency']
    assert values['resolution_upper_bound']==rows[6].values['target_frequency']
    assert rows[5].values['target_frequency']<values['ctf20']<rows[6].values['target_frequency']
    assert curve['pass'][-2:]==[False,False]
    assert values['resolution_limit_dpi']==pytest.approx(values['resolution_limit']*100*50.8)


def test_chart_limited_resolution_is_a_lower_bound():
    rows=_rows([.9]*12)
    values,curve,flags,confidence=summarize_curve(rows,scale=None,height=500)
    assert 'target_limited' in flags and values['ctf20'] is None
    assert values['resolution_limit']==rows[-1].values['target_frequency']
    assert values['resolution_limit_lp_mm'] is None and values['resolution_limit_dpi'] is None
    assert values['resolution_limit_lw_ph']==pytest.approx(values['resolution_limit']*1000)


def test_failed_separation_does_not_fabricate_a_ctf_crossing():
    rows=_rows([.9,.8,.75,.7,.6,.5])
    rows[-1].values['detected_bar_count']=2
    values,curve,flags,confidence=summarize_curve(rows,mode='absolute')
    assert values['resolution_limit']==rows[-2].values['target_frequency']
    assert values['ctf20'] is None


def test_frequency_units_distinguish_equivalent_dpi_from_sampling():
    v=frequency_values('resolution_limit',.2,100,1000)
    assert v['resolution_limit_lp_mm']==20
    assert v['resolution_limit_dpi']==1016
    assert v['resolution_limit_lw_ph']==400 and v['resolution_limit_lp_ph']==200
