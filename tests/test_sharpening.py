import numpy as np
import pytest
from scipy.ndimage import gaussian_filter1d,gaussian_filter
from scipy.special import erf
from mutex_imatest.analysis.sharpening import bar_halos
from mutex_imatest.analysis.usaf_multifrequency import measure_bars
from mutex_imatest.analysis.sfr import slanted_edge
from mutex_imatest.analysis.sfr import first_crossing
from mutex_imatest.config import AnalysisConfig


def bars(amount=0,phase=0,period=80):
    x=np.arange(int(3.2*period));c=(len(x)-1)/2+phase
    ink=sum(.5*(erf((x-(c+(k-.25)*period))/1.7)-erf((x-(c+(k+.25)*period))/1.7)) for k in [-1,0,1])
    p=.8-.6*ink
    return p+amount*(p-gaussian_filter1d(p,2.2))


@pytest.mark.parametrize('phase',[-1.4,0,1.4])
def test_coarse_bars_detect_increasing_unsharp_mask_halos(phase):
    values=[bar_halos(bars(a,phase),80) for a in [0,.5,1.]]
    assert values[0]['sharpening_halo_pct']<.01
    assert 2<values[1]['sharpening_halo_pct']<values[2]['sharpening_halo_pct']
    assert all(v['halo_edge_count']==4 for v in values)


def test_noise_gradient_and_single_pixel_do_not_become_halos():
    p=bars()+np.linspace(-.01,.01,256)
    assert bar_halos(p,80,noise=.003)['sharpening_halo_pct']<2
    p=bars();p[72]+=.1
    assert bar_halos(p,80)['sharpening_halo_pct']<2


def test_clipping_can_hide_sharpening_and_does_not_prove_unprocessed():
    p=np.clip(bars(1),.2,.8)
    assert bar_halos(p,80)['sharpening_halo_pct']<.01


def test_fine_bars_and_noisy_evidence_provide_no_estimate():
    assert not bar_halos(bars(period=20),20)
    assert not bar_halos(bars(),80,noise=.1)


def test_native_bar_measurement_includes_halos_without_resampling():
    a=np.tile(bars(.8),(50,1));before=a.copy()
    values,flags,confidence,curve=measure_bars(a,1/80)
    assert values['sharpening_halo_pct']>2
    np.testing.assert_array_equal(a,before)


def test_slanted_edge_detects_halos_with_an_independent_spatial_measure():
    y,x=np.mgrid[:192,:192];image=.2+.6*.5*(1+erf((x-96-.075*(y-96))/1.7))
    original=slanted_edge(image,AnalysisConfig(transfer='linear'))
    sharp=slanted_edge(image+(image-gaussian_filter(image,2)),AnalysisConfig(transfer='linear'))
    assert original['values']['sharpening_halo_pct']<.1
    assert sharp['values']['sharpening_halo_pct']>2
    assert 'sharpening_or_ringing' in sharp['flags']


def test_exact_sfr_threshold_at_last_sample_is_not_lost():
    assert first_crossing([0,.1,.2],[1,.8,.5],.5)==.2
