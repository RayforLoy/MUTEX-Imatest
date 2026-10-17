from __future__ import annotations

import json
import numpy as np
import pytest
import tifffile
from mutex_imatest.models import Region, ChartDefinition, AnalysisResult
from mutex_imatest.analysis.engine import analyze
from mutex_imatest.official_charts import prepare_profile, PROFILES, patch_grid
from mutex_imatest.imaging import ImageSource
from mutex_imatest.lab import run_workflow


def test_profile_references_engine_and_oecf_export(tmp_path,config):
    rng=np.random.default_rng(2)
    density=np.linspace(.05,2.05,12)
    values=(10**-density*.8)**(1/2.2)
    image=np.repeat(np.repeat(values,60)[None],100,axis=0)
    image=np.clip(image+rng.normal(0,.001,image.shape),0,1)
    path=tmp_path/'gray.tif';tifffile.imwrite(path,(image*65535).round().astype(np.uint16))
    ref=tmp_path/'density.csv';ref.write_text('id,density\n'+'\n'.join(f'{i+1},{d}' for i,d in enumerate(density)),encoding='utf-8')
    with ImageSource(path,config) as source:
        chart=prepare_profile(source,'linear_step',rows=1,cols=12,reference=ref,transmissive=True,preview_path=tmp_path/'preview.png')
    result=analyze(path,chart,config)
    summary=next(m for m in result.measurements if m.kind=='tone_summary')
    assert summary.values['oecf_gamma']==pytest.approx(1/2.2,abs=.004)
    assert result.template['fiducials'][0]['reference_sha256']
    result.save(tmp_path/'result.json')
    report=run_workflow({'workflow':'oecf','files':[str(tmp_path/'result.json')]},tmp_path/'out',config)
    assert (tmp_path/'out/oecf.json').is_file()
    assert '<!doctype html>' in (tmp_path/'out/report.html').read_text(encoding='utf-8')
    assert report['sources'][0]['sha256']
    loaded=AnalysisResult.load(tmp_path/'result.json')
    assert loaded.measurements[-1].curves['oecf']


def test_missing_reference_remains_invalid(tmp_path,config):
    path=tmp_path/'color.tif';tifffile.imwrite(path,np.full((200,300,3),30000,np.uint16))
    with ImageSource(path,config) as source:
        chart=prepare_profile(source,'colorchecker24')
    assert len(chart.regions)==24
    result=analyze(path,chart,config)
    assert not any(m.valid for m in result.measurements)
    assert all('missing_reference' in m.flags for m in result.measurements)
    assert not any(m.values.get('delta_e_2000') is not None for m in result.measurements)


def test_irregular_profile_requires_actual_layout(tmp_path,config):
    path=tmp_path/'mixed.tif';tifffile.imwrite(path,np.full((80,120),30000,np.uint16))
    with ImageSource(path,config) as source:
        with pytest.raises(ValueError,match='布局'):prepare_profile(source,'colorgray44')
        layout=tmp_path/'layout.json';layout.write_text(json.dumps({'regions':[{'id':'1','kind':'flat','box':[0,0,.5,1]}]}))
        chart=prepare_profile(source,'colorgray44',layout=layout)
    assert chart.regions[0].kind=='flat'
    assert len(PROFILES)>=30
    with ImageSource(path,config) as source:
        with pytest.raises(ValueError):prepare_profile(source,'general_gray',box=(-.01,0,1,1))
        with pytest.raises(ValueError):prepare_profile(source,'general_gray',rows=0)


def test_compare_simulation_and_reproducible_sources(tmp_path,config):
    source=np.linspace(.1,.9,96*96).reshape(96,96)
    path=tmp_path/'source.tif';tifffile.imwrite(path,(source*65535).astype(np.uint16))
    report=run_workflow({'workflow':'compare','files':[str(path)]*2,'parameters':{'roi':[0,0,96,96]}},tmp_path/'compare',config)
    assert report['output']['ssim']==pytest.approx(1)
    assert len(report['sources'])==2
    spec={'workflow':'simulate','files':[str(path)],'parameters':{'roi':[0,0,96,96],'seed':4}}
    first=run_workflow(spec,tmp_path/'sim1',config)
    second=run_workflow(spec,tmp_path/'sim2',config)
    assert np.array_equal(tifffile.imread(first['artifacts'][0]),tifffile.imread(second['artifacts'][0]))


def test_video_file_and_capture_without_camera(tmp_path,config):
    import cv2
    path=tmp_path/'video.avi'
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10.,(96,64))
    if not writer.isOpened():pytest.skip('MJPG encoder unavailable')
    for i in range(30):
        level=int(min(100,30+i*7));frame=np.full((64,96,3),level,np.uint8)
        frame[15:40,20+i//4:40+i//4]=200
        writer.write(frame)
    writer.release()
    report=run_workflow({'workflow':'video','files':[str(path)],'parameters':{'every':1,'max_frames':30}},tmp_path/'video-report',config)
    assert report['output']['summary']['frame_count']==30
    assert (tmp_path/'video-report/frames.csv').exists()
    captured=run_workflow({'workflow':'capture','parameters':{'source':str(path),'count':3}},tmp_path/'capture',config)
    assert captured['output']['captured']==3
    assert len(list((tmp_path/'capture').glob('capture-*.tif')))==3


def test_new_ui_entry_points_and_parameters(qtbot,config,monkeypatch,tmp_path):
    from mutex_imatest.ui.iq_workbench import ProfileDialog,WorkbenchDialog
    from mutex_imatest.ui.main_window import MainWindow
    import mutex_imatest.ui.iq_workbench as module
    monkeypatch.setattr(module,'library_dir',lambda:tmp_path/'charts')
    profile=ProfileDialog(config);qtbot.addWidget(profile)
    assert profile.profile.count()==len(PROFILES)
    profile.profile.setCurrentIndex(profile.profile.findData('colorchecker_sg'))
    assert (profile.rows.value(),profile.cols.value())==(10,14)
    lab=WorkbenchDialog(config);qtbot.addWidget(lab)
    lab.workflow.setCurrentIndex(lab.workflow.findData('ptc'))
    assert lab.specification()['parameters']['dark_count']==2
    main=MainWindow();main.persist_preferences=False;qtbot.addWidget(main)
    assert main.official_chart_action.text().startswith('Imatest')
    assert main.workbench_action.isEnabled()
    main.close();profile.reject();lab.reject()


def test_cfa_site_uses_sensor_samples_not_demosaiced_pixels(tmp_path,config,monkeypatch):
    from types import SimpleNamespace
    from mutex_imatest.lab import read_pixels
    import mutex_imatest.imaging as imaging
    pixels=np.arange(64*64,dtype=np.uint16).reshape(64,64)
    cfa=tmp_path/'cfa.npy';np.save(cfa,pixels)
    class Sensor:
        def __init__(self,*args,**kwargs):
            self.metadata=SimpleNamespace(width=64,height=64,channels=3,is_raw=True,fingerprint='known',bits_per_sample=12,dtype='uint16')
            self.path=tmp_path/'photo.nef';self.raw_cfa_path=str(cfa)
            self.raw_info={'raw_pattern':[[0,1],[3,2]],'white_level':4095}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def verify_unchanged(self):pass
        def read_roi(self,*args):raise AssertionError('PTC must not read demosaiced RGB')
    monkeypatch.setattr(imaging,'ImageSource',Sensor)
    actual,source=read_pixels(tmp_path/'photo.nef',config,[1,1,40,40],'G',native_dn=True,cfa_site=[0,1])
    assert np.array_equal(actual,pixels[2:41:2,1:41:2])
    assert source['sensor_white_level']==4095
    with pytest.raises(ValueError):read_pixels(tmp_path/'photo.nef',config,[0,0,40,40],'G',native_dn=True)


def test_worker_completion_may_close_its_dialog(qapp):
    from mutex_imatest.workers import WorkerManager
    class Output:
        closed=False
        def get_nowait(self):
            if self.closed:raise ValueError('closed queue')
            return {'type':'done','lab_result':'result.json'}
        def close(self):self.closed=True
    class Process:
        def is_alive(self):return False
        def join(self,timeout=None):pass
    manager=WorkerManager();output=Output();events=[]
    manager.current={'id':'test','queue':output,'process':Process(),'cancel':type('Cancel',(),{'set':lambda self:None})(),'finished':False}
    def completed(uid,event):
        events.append(event)
        manager.close()
    manager.event.connect(completed)
    manager._poll();manager.timer.stop()
    assert len(events)==1 and output.closed and manager.current is None
