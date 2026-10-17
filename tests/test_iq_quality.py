from __future__ import annotations

import json
import numpy as np
import pytest
from scipy.ndimage import gaussian_filter
from mutex_imatest.analysis.quality import compare_images, uniformity, log_frequency, texture_transfer, flare
from mutex_imatest.analysis.sensor import photon_transfer, dark_flat_calibration
from mutex_imatest.analysis.geometry import fit_radial_distortion, calibrate_camera
from mutex_imatest.analysis.tone_color import fit_color_matrix, apply_color_matrix, summarize_tone, export_oecf
from mutex_imatest.analysis.temporal import settling_time
from mutex_imatest.models import Region, ChartDefinition, Measurement, AnalysisResult, ImageMetadata
from mutex_imatest.test_manager import evaluate_limits, TestDatabase
from mutex_imatest.reference_io import read_reference, attach_references


def test_ssim_identity_and_noise():
    rng = np.random.default_rng(10)
    a = rng.uniform(.1, .9, (96, 96))
    perfect = compare_images(a, a)
    assert perfect['ssim'] == pytest.approx(1)
    assert perfect['identical'] and perfect['psnr_db'] is None
    noisy = compare_images(a, a+rng.normal(0, .02, a.shape))
    assert .95 < noisy['ssim'] < 1
    assert noisy['psnr_db'] == pytest.approx(34, abs=.3)
    assert compare_images(a, gaussian_filter(a, 2))['ssim'] < noisy['ssim']
    with pytest.raises(ValueError):compare_images(a, a[:20])


def test_flat_defects_and_illumination(config):
    a = np.full((256, 256), .5)
    a[80, 90] = .99; a[100, 120] = .01
    yy, xx = np.mgrid[:256, :256]
    a -= .12*np.exp(-((xx-180)**2+(yy-170)**2)/(2*6**2))
    result = uniformity(a, {}, config)
    assert result['values']['hot_pixel_count'] >= 1
    assert result['values']['dead_pixel_count'] >= 1
    assert result['values']['blemish_count'] >= 1
    assert any(abs(b['x_px']-180) < 10 and abs(b['y_px']-170) < 10 for b in result['blemishes'])
    assert len(result['curves']['radial_nps']['x']) == 64


def test_log_sine_gaussian_truth(config):
    width = 1536; sigma = 1.35
    x = np.arange(width); rate = np.log(.4/.015)/(width-1)
    phase = 2*np.pi*.015*np.expm1(rate*x)/rate
    source = np.repeat((.5+.2*np.sin(phase))[None], 80, axis=0)
    blurred = gaussian_filter(source, sigma)
    result = log_frequency(blurred, {'f_start':.015,'f_end':.4,'reference_modulation':.4}, config)
    truth = np.sqrt(np.log(2))/(np.sqrt(2)*np.pi*sigma)
    assert result['values']['log_mtf50'] == pytest.approx(truth, abs=.012)
    assert 'missing_reference' in log_frequency(source, {}, config)['flags']


def test_texture_reference_gaussian_truth():
    rng = np.random.default_rng(8)
    source = .5+rng.normal(0, .08, (512, 512))
    sigma = 1.3
    result = texture_transfer(gaussian_filter(source, sigma), source)
    truth = np.sqrt(np.log(2))/(np.sqrt(2)*np.pi*sigma)
    assert result['values']['texture_mtf50'] == pytest.approx(truth, abs=.014)
    with pytest.raises(ValueError):texture_transfer(source, np.ones_like(source))


def test_trap_flare_ratio(config):
    a = np.full((100, 100), .801)
    a[40:60, 40:60] = .003
    result = flare(a, {'dark_box':[.4,.4,.2,.2], 'bright_box':[.1,.1,.2,.2], 'black_level':.001}, config)
    assert result['values']['veiling_glare_pct'] == pytest.approx(.25)
    with pytest.raises(ValueError):flare(a, {}, config)


def test_photon_transfer_known_gain():
    rng = np.random.default_rng(7)
    shape = (112, 112); gain = .8; black = 120; read = 3.
    fixed_dark = rng.normal(0, 1.5, shape)
    dark = black+fixed_dark+rng.normal(0, read, (8, *shape))
    pattern = rng.normal(1, .005, shape)
    groups = []
    for signal in [200, 500, 900, 1400, 2000, 2600]:
        groups.append(black+fixed_dark+gain*rng.poisson(signal/gain*pattern, (8, *shape))+rng.normal(0, read, (8, *shape)))
    result = photon_transfer(dark, groups, 4095)
    assert result['gain_dn_per_e'] == pytest.approx(gain, rel=.04)
    assert result['read_noise_dn'] == pytest.approx(read, rel=.03)
    assert result['dsnu_dn'] == pytest.approx(1.5, rel=.07)
    assert result['prnu_pct'] == pytest.approx(.5, abs=.1)
    assert result['ptc_r_squared'] > .99
    with pytest.raises(ValueError):photon_transfer(dark, groups[:2], 4095)


def test_dark_flat_correction():
    yy, xx = np.mgrid[:48, :64]
    offset = .02+.001*xx/64
    gain = .8+.2*xx/64
    dark = np.stack([offset]*3); flat = np.stack([offset+.5*gain]*4)
    black, multiplier, mask = dark_flat_calibration(dark, flat)
    corrected = (.3*gain+offset-black)*multiplier
    assert mask.all()
    assert np.std(corrected) < 1e-12


def test_radial_distortion_known_coefficients():
    yy, xx = np.mgrid[:8, :10]
    ideal = np.column_stack([xx.ravel(), yy.ravel()])
    plane = ideal*np.array([84, 80])+[120, 110]
    center = np.array([500, 400]); scale = np.hypot(1000, 800)/2
    r2 = np.sum(((plane-center)/scale)**2, axis=1)
    observed = center+(plane-center)*(1-.13*r2+.035*r2**2)[:,None]
    result = fit_radial_distortion(ideal, observed, (1000, 800))
    assert result['values']['radial_k1'] == pytest.approx(-.13, abs=1e-5)
    assert result['values']['radial_k2'] == pytest.approx(.035, abs=1e-5)
    assert result['values']['radial_fit_rms_px'] < .001


def test_multiview_camera_calibration_known_truth():
    import cv2
    yy, xx = np.mgrid[:7, :9]
    obj = np.column_stack([xx.ravel()*10., yy.ravel()*10., np.zeros(xx.size)]).astype(np.float32)
    matrix = np.array([[900,0,640],[0,910,480],[0,0,1.]], float)
    distortion = np.array([-.12,.025,.001,-.002,0.])
    images = []
    for i in range(8):
        rv = np.array([-.25+i*.06, .12-i*.05, -.1+i*.025])
        tv = np.array([-40+i*3., -30+i*2., 250+i*13.])
        images.append(cv2.projectPoints(obj, rv, tv, matrix, distortion)[0])
    result = calibrate_camera([obj]*len(images), images, (1280,960))
    assert result['rms_px'] < .001
    assert np.array(result['camera_matrix'])[0,0] == pytest.approx(900, rel=.001)
    assert result['distortion'][0] == pytest.approx(-.12, abs=.002)
    with pytest.raises(ValueError):calibrate_camera([obj]*5, [images[0]]*5, (1280,960))


def test_ccm_known_matrix_and_d50_adaptation():
    import colour
    rng = np.random.default_rng(3)
    source = rng.uniform(.05,.65,(36,3))
    truth = np.array([[1.1,-.04,.02],[.03,.9,.04],[-.02,.02,1.03]])
    target = source@truth
    lab = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(target, apply_cctf_decoding=False))
    result = fit_color_matrix(source, lab, 'D65', optimize_lab=False)
    corrected = apply_color_matrix(source, result)
    assert corrected == pytest.approx(target, abs=.0002)
    assert result['mean_delta_e_after'] < .03
    assert result['mean_delta_e_before'] > 1
    from mutex_imatest.analysis.tone_color import reference_xyz
    xyz = reference_xyz([[100,0,0]], 'D50')
    assert xyz[0] == pytest.approx(colour.xy_to_XYZ([.3127,.329]), abs=.001)


def make_tone_result():
    regions, measurements = [], []
    for i, density in enumerate(np.linspace(0, 3.0, 21)):
        x = 10**-density; encoded = (.85*x)**(1/2.2)
        regions.append(Region(str(i),'step',(i/21,0,1/21,1),params={'reference_density':float(density),'transmissive':True}))
        measurements.append(Measurement(str(i),str(i),'step','G',(10,10),(0,0,20,20),
                            {'mean':x*.85,'noise':.003,'encoded_mean':encoded,'white_clip_fraction':0.,'black_clip_fraction':0.}))
    chart = ChartDefinition('tone','tone',regions)
    measurements.extend(summarize_tone(measurements,chart,(420,20)))
    image = ImageMetadata('test.tif',420,20,1,'uint16',16,200,'123')
    return AnalysisResult(image,chart.id,chart.name,measurements,{},chart.to_dict())


def test_oecf_and_measured_dynamic_range():
    result = make_tone_result()
    summary = result.measurements[-1]
    assert summary.values['oecf_gamma'] == pytest.approx(1/2.2)
    expected = np.log2(.85/.003)
    assert summary.values['dynamic_range_snr1_stops'] == pytest.approx(expected, abs=.12)
    assert summary.values['dynamic_range_snr1_lower_bound'] == 0
    assert summary.values['dynamic_range_snr20_stops'] < summary.values['dynamic_range_snr1_stops']
    oecf = export_oecf(result)
    assert len(oecf['encoded']) == 21
    assert np.all(np.diff(oecf['linear']) > 0)
    # Reflective cards cannot establish a sensor dynamic range.
    chart = ChartDefinition.from_dict(result.template)
    for region in chart.regions:region.params['transmissive']=False
    summary = summarize_tone(result.measurements[:21],chart,(420,20))[0]
    assert 'dynamic_range_snr1_stops' not in summary.values


def test_csv_cgats_reference_matching(tmp_path):
    csv = tmp_path/'reference.csv';csv.write_text('id,Lab_L,Lab_a,Lab_b\nA1,50,2,-3\nA2,70,1,2\n',encoding='utf-8')
    reference = read_reference(csv)
    regions = [Region('A1','color',(0,0,.5,1)),Region('A2','color',(.5,0,.5,1))]
    attached = attach_references(regions,reference)
    assert attached[0].params['reference_lab'] == [50,2,-3]
    assert attached[0].params['reference_illuminant'] == 'D50'
    regions[0].id='other'
    with pytest.raises(ValueError):attach_references(regions,reference)
    cgats = tmp_path/'reference.txt';cgats.write_text('CGATS.17\nBEGIN_DATA_FORMAT\nSAMPLE_ID D_VIS\nEND_DATA_FORMAT\nBEGIN_DATA\n1 0.1\n2 6.2\nEND_DATA\n',encoding='utf-8')
    ref = read_reference(cgats)
    assert ref['records'][1]['reference_density']==6.2


def test_pass_fail_missing_invalid_and_database(tmp_path):
    result = make_tone_result()
    rule = {'metric':'oecf_gamma','channel':'G','min':.4,'max':.5}
    assert evaluate_limits(result,[rule])['status']=='pass'
    assert evaluate_limits(result,[dict(rule,region_ids=['not-here'])])['status']=='fail'
    result.measurements[-1].flags.append('clipped')
    assert evaluate_limits(result,[rule])['status']=='fail'
    result.measurements[-1].values.pop('oecf_gamma')
    assert evaluate_limits(result,[rule])['status']=='fail'
    db = TestDatabase(tmp_path/'runs.sqlite')
    run = db.add({'name':'example'},{'status':'fail'})
    assert db.list()[0]['id']==run


def test_settling_requires_sustained_target():
    t = np.arange(30)/10
    values = np.r_[np.linspace(.2,.5,10),np.repeat(.5,20)]
    assert settling_time(t,values,.5,stable_duration=.5)['settling_seconds']==pytest.approx(.9)
    values[-1]=.7
    assert settling_time(t,values,.5)['settling_seconds'] is None
    with pytest.raises(ValueError):settling_time([0,float('nan'),2],[1,1,1])


def test_testplan_never_uses_lower_bound_to_prove_an_upper_limit():
    result=make_tone_result();measurement=result.measurements[-1]
    measurement.values.update(dynamic_range_snr1_stops=10.,dynamic_range_snr1_lower_bound=1)
    rule={'metric':'dynamic_range_snr1_stops','channel':'G','min':9.}
    assert evaluate_limits(result,[rule])['status']=='pass'
    upper=evaluate_limits(result,[dict(rule,max=12.)])
    assert upper['status']=='fail' and upper['rules'][0]['lower_bound_count']==1
    assert '下界' in upper['rules'][0]['reason']
    for invalid in [dict(rule,min=None,max=None),dict(rule,minimum_confidence=-1),dict(rule,minimum_count=1.5)]:
        with pytest.raises(ValueError):evaluate_limits(result,[invalid])
