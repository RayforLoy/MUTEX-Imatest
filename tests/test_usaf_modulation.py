"""Finite three-bar optical truth, independent of the peak detector."""
import numpy as np
import pytest
from scipy.optimize import minimize_scalar
from scipy.special import erf
from mutex_imatest.analysis.usaf_multifrequency import measure_bars,summarize_curve
from mutex_imatest.models import Measurement


def blurred_bars(frequency,sigma,phase=0,noise=0,missing=None):
    period=1/frequency
    width=int(np.ceil(3.2*period));height=max(6,int(1.6*period))
    center=(width-1)/2+phase
    def signal(x):
        ink=np.zeros_like(np.asarray(x,dtype=float))
        for k in (-1,0,1):
            if k==missing:continue
            lo=center+(k-.25)*period;hi=lo+.5*period
            ink+=.5*(erf((x-lo)/(np.sqrt(2)*sigma))-erf((x-hi)/(np.sqrt(2)*sigma)))
        return .9-.8*ink
    image=np.tile(signal(np.arange(width)),(height,1))
    if noise:image+=np.random.default_rng(829).normal(0,noise,image.shape)
    # Continuous extrema of an analytic finite target, not sampled image data.
    dark=[minimize_scalar(signal,bounds=(center+(k-.4)*period,center+(k+.4)*period),method='bounded').fun for k in (-1,0,1)]
    white=[-minimize_scalar(lambda x:-signal(x),bounds=(center+(k+.1)*period,center+(k+.9)*period),method='bounded').fun for k in (-1,0)]
    bright=np.mean(white);black=(dark[0]+2*dark[1]+dark[2])/4
    return image,float((bright-black)/(bright+black))


@pytest.mark.parametrize('frequency',[.01,.04,.08,.14,.2])
@pytest.mark.parametrize('phase',[-.45,0,.45])
def test_internal_ctf_matches_continuous_finite_bar_truth(frequency,phase):
    image,truth=blurred_bars(frequency,.25/frequency,phase)
    values,flags,confidence,curve=measure_bars(image,frequency)
    assert values['detected_bar_count']==3 and not flags
    assert values['ctf']==pytest.approx(truth,abs=.025)
    assert confidence>0


def test_white_margins_cannot_keep_fading_internal_modulation_high():
    # A weak periodic pattern in a dark finite strip with bright outer margins.
    # Its white surroundings are not part of its internal Michelson contrast.
    f=.1;x=np.arange(33);z=x-16
    profile=np.where(np.abs(z)<=12.5,.5-.08*np.cos(2*np.pi*f*z),.95)
    image=np.tile(profile,(18,1));truth=.16
    values,flags,confidence,curve=measure_bars(image,f)
    assert not flags and truth<.22
    assert values['roi_contrast']>values['ctf']+.2
    assert values['ctf']==pytest.approx(truth,abs=.015)


@pytest.mark.parametrize('missing',[-1,0,1])
def test_a_missing_bar_cannot_be_fitted_into_a_ctf_sample(missing):
    image,truth=blurred_bars(.1,1,missing=missing)
    values,flags,confidence,curve=measure_bars(image,.1)
    assert 'bars_not_separated' in flags
    assert values['ctf'] is None


@pytest.mark.parametrize('kind',['flat','gradient','blob','noise'])
def test_non_targets_supply_no_valid_ctf(kind):
    image=np.full((80,160),.5)
    if kind=='gradient':image+=np.linspace(-.3,.3,160)
    if kind=='blob':image-=.3*np.exp(-((np.arange(160)-80)/30)**2)
    if kind=='noise':image+=np.random.default_rng(72).normal(0,.08,image.shape)
    values,flags,confidence,curve=measure_bars(image,.02)
    assert {'bars_not_separated','bar_geometry_mismatch','low_contrast','ctf_noise_limited'}.intersection(flags)


def test_two_low_modulation_gaps_remain_measurable_with_sensor_noise():
    image,truth=blurred_bars(.1,2.6,.35,noise=.015)
    values,flags,confidence,curve=measure_bars(image,.1)
    assert not flags and values['ctf']==pytest.approx(truth,abs=.02)


def test_three_minima_with_the_wrong_period_fail_geometry_check():
    image,_=blurred_bars(.1,1)
    values,flags,confidence,curve=measure_bars(image,.16)
    assert values['detected_bar_count']==3 and 'bar_geometry_mismatch' in flags
    assert confidence==0


def test_noise_trials_do_not_become_three_bar_ctf_samples():
    rng=np.random.default_rng(8089)
    for _ in range(100):
        image=.5+rng.normal(0,.08,(80,160))
        values,flags,confidence,curve=measure_bars(image,.02)
        assert {'bars_not_separated','bar_geometry_mismatch','low_contrast','ctf_noise_limited'}.intersection(flags)


def synthetic_curve():
    rows=[];truth_rows=[]
    for i in range(25):
        f=.025*2**(i/6)
        image,truth=blurred_bars(f,2.2,.3)
        values,flags,confidence,curve=measure_bars(image,f)
        rows.append(Measurement(str(i),'','usaf','G',(0,0),(0,0,*image.shape[::-1]),values=values,flags=flags))
        truth_rows.append(Measurement(str(i),'','usaf','G',(0,0),(0,0,*image.shape[::-1]),values={'ctf':truth,'detected_bar_count':3,'target_frequency':f}))
    return rows,truth_rows


def test_blurred_chart_yields_bounded_ctf50_and_ctf20_without_extrapolation():
    rows,truth_rows=synthetic_curve()
    values,curve,flags,confidence=summarize_curve(rows)
    expected,_,_,_=summarize_curve(truth_rows)
    for key in ['ctf50','ctf20']:
        assert values[key] is not None
        assert values[key]==pytest.approx(expected[key],rel=.04)
        assert min(curve['frequency'])<values[key]<max(curve['frequency'])


def test_excluded_clipping_does_not_discard_a_later_measured_bracket():
    rows,truth_rows=synthetic_curve()
    expected,_,_,_=summarize_curve(rows)
    rows[4].flags.append('clipped')
    rows[6].flags.append('clipped')
    values,curve,flags,confidence=summarize_curve(rows)
    assert values['resolution_limit']==rows[3].values['target_frequency']
    for key in ['ctf50','ctf20']:
        assert values[key]==expected[key]
        support=curve['crossing_support'][key]
        lo,hi=map(int,[support['lower_element'],support['upper_element']])
        assert hi==lo+1 and not rows[lo].flags and not rows[hi].flags
        assert support['after_excluded_clipping']
    assert 'ctf_segment_after_clipping' in flags
    assert all(v is None for i,v in enumerate(curve['ctf_envelope']) if i in [4,6])


def test_no_ctf_interpolation_across_a_clipped_threshold_bracket():
    rows,truth_rows=synthetic_curve()
    expected,original_curve,_,_=summarize_curve(rows)
    index=int(original_curve['crossing_support']['ctf50']['upper_element'])
    rows[index].flags.append('clipped')
    values,curve,flags,confidence=summarize_curve(rows)
    assert values['ctf50'] is None
    assert values['ctf20']==expected['ctf20']


@pytest.mark.parametrize('failure',['bars_not_separated','bar_geometry_mismatch','ctf_noise_limited','low_contrast'])
def test_clipped_points_cannot_hide_a_real_target_failure(failure):
    rows,truth_rows=synthetic_curve()
    rows[4].flags+=['clipped',failure]
    if failure=='bars_not_separated':rows[4].values['detected_bar_count']=2
    values,curve,flags,confidence=summarize_curve(rows)
    assert values['ctf50'] is None and values['ctf20'] is None


def test_clipped_low_frequency_reference_cannot_be_replaced_with_later_targets():
    rows,truth_rows=synthetic_curve()
    rows[0].flags.append('clipped');rows[1].flags.append('clipped')
    values,curve,flags,confidence=summarize_curve(rows)
    assert not values and flags==['invalid_ctf_reference']


def test_report_curve_breaks_at_clipping_without_drawing_a_fake_zero():
    from xml.etree import ElementTree as ET
    from mutex_imatest.reports_usaf import ctf_svg
    curve={'frequency':[.01,.02,.03,.04,.05,.06],
           'ctf':[.9,.8,None,.6,.3,.1],'response':[1,.9,None,.7,.35,.12],
           'envelope':[1,.9,0,0,0,0],'sequence_valid':[True,True,False,False,False,False],
           'ctf_envelope':[1,.9,None,.7,.35,.12],'ctf_support':[True,True,False,True,True,True]}
    rec={'unit_id':'truth','directions':{'vertical':{'R':{'curve':curve}}}}
    svg=ET.fromstring(ctf_svg(rec,calibrated=False))
    envelope=next(p for p in svg if p.attrib.get('opacity')=='0.25')
    assert envelope.attrib['d'].count('M')==2


@pytest.mark.parametrize('failure',['missing','gap','bad_geometry','noise'])
def test_bad_frequency_support_never_interpolates_an_artificial_zero(failure):
    rows=[Measurement(str(i),'','usaf','G',(0,0),(0,0,20,10),
                      values={'ctf':c,'detected_bar_count':3,'target_frequency':.03*2**(i/6)})
          for i,c in enumerate([.9,.9,.9,.8,.7,.6,.1,.05])]
    if failure=='missing':rows[5].values['ctf']=None
    elif failure=='gap':rows=rows[:4]+rows[7:]
    elif failure=='bad_geometry':rows[5].flags.append('bar_geometry_mismatch')
    else:rows[5].flags.append('ctf_noise_limited')
    values,curve,flags,confidence=summarize_curve(rows)
    assert values['ctf20'] is None and values['ctf50'] is None
    assert values['resolution_upper_bound'] is not None


def test_exact_threshold_sample_is_a_measurement_not_a_missing_crossing():
    rows=[Measurement(str(i),'','usaf','G',(0,0),(0,0,20,10),
                      values={'ctf':c,'detected_bar_count':3,'target_frequency':.03*2**(i/6)})
          for i,c in enumerate([1.,1.,1.,.8,.5,.2])]
    values,curve,flags,confidence=summarize_curve(rows)
    assert values['ctf50']==rows[4].values['target_frequency']
    assert values['ctf20']==rows[5].values['target_frequency']
    assert curve['crossing_support']['ctf20']['exact_sample']
