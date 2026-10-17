import copy,hashlib
from pathlib import Path
import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt,QPointF
from mutex_imatest.preview_orientation import PreviewOrientation,orientation_from_homography,match_preview_orientation
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.models import AnalysisResult,ImageMetadata,Measurement,ChartDefinition


def rich_reference():
    a=np.full((600,800),240,np.uint8)
    cv2.putText(a,'TOP / 12',(45,70),cv2.FONT_HERSHEY_SIMPLEX,1.6,20,4)
    cv2.putText(a,'LEFT A',(40,545),cv2.FONT_HERSHEY_SIMPLEX,1.2,45,3)
    cv2.circle(a,(630,120),57,25,5);cv2.rectangle(a,(520,400),(750,560),40,5)
    rng=np.random.default_rng(41)
    for i in range(110):
        x,y=map(int,rng.integers([35,110],[750,480]));w,h=map(int,rng.integers(5,30,2))
        cv2.rectangle(a,(x,y),(x+w,y+h),int(rng.integers(20,180)),int(rng.choice([-1,2])))
    return a


def write_image(path,a):
    from PIL import Image
    Image.fromarray(a).save(path)


def test_discrete_orientation_recovers_all_reflections_and_quarter_turns():
    for q in range(4):
        for mirrored in [False,True]:
            forward=PreviewOrientation(q,mirrored).matrix()
            H=np.eye(3);H[:2,:2]=forward@np.array([[3000,15],[12,5100.]])
            recovered=orientation_from_homography(H)
            assert np.array_equal(recovered.matrix()@forward,np.eye(2))
            for step in [-1,1]:assert np.array_equal(recovered.rotated(step).matrix(),PreviewOrientation(step%4).matrix()@recovered.matrix())
            assert np.array_equal(recovered.mirrored('horizontal').matrix(),np.diag([-1,1])@recovered.matrix())
            assert np.array_equal(recovered.mirrored('vertical').matrix(),np.diag([1,-1])@recovered.matrix())
    assert orientation_from_homography(np.diag([400,-900,1]))==PreviewOrientation(0,False,True)
    with pytest.raises(ValueError):PreviewOrientation(45)
    with pytest.raises(ValueError):orientation_from_homography(np.zeros((3,3)))
    with pytest.raises(ValueError):orientation_from_homography([[1,-1,0],[1,1,0],[0,0,1]])


def test_thumbnail_orientation_recovers_reflection_rotation_and_refuses_blank(tmp_path):
    ref=rich_reference();path=tmp_path/'模板.png';write_image(path,ref)
    chart=ChartDefinition('test','test',[],preview=str(path))
    for q in range(4):
        for mirror in [False,True]:
            image=np.rot90(ref,-q)
            if mirror:image=image[:,::-1]
            image=cv2.GaussianBlur(image,(3,3),.4)
            target=tmp_path/'预览.png';write_image(target,image)
            result=match_preview_orientation(target,chart)
            actual=PreviewOrientation(q,mirror).matrix()
            assert np.array_equal(PreviewOrientation.from_dict(result['orientation']).matrix()@actual,np.eye(2))
            assert result['inliers']>=12 and result['correlation']>.3
    write_image(target,np.full((600,800),200,np.uint8))
    with pytest.raises(ValueError,match='特征不足'):match_preview_orientation(target,chart)


def test_rotated_view_keeps_native_tiles_picking_anchors_and_compare_state(qtbot,tmp_path,monkeypatch):
    from mutex_imatest.ui.viewer import ImageViewer
    a=np.zeros((256,384,3),np.uint8);a[:128,:,0]=180;a[:,192:,1]=150
    source=tmp_path/'source.png';preview=tmp_path/'preview.png';write_image(source,a);write_image(preview,cv2.resize(a,(96,64)))
    metadata=ImageMetadata(str(source),384,256,3,'uint8',8,source.stat().st_size,hashlib.sha256(source.read_bytes()).hexdigest())
    before=source.read_bytes();config=AnalysisConfig(cache_dir=str(tmp_path/'cache'))
    viewer=ImageViewer();qtbot.addWidget(viewer);viewer.resize(650,500);viewer.show()
    other=ImageViewer();qtbot.addWidget(other);other.resize(650,500);other.show()
    try:
        viewer.load(preview,metadata,config);other.load(preview,metadata,config)
        assert viewer.orientation==PreviewOrientation()
        m=Measurement('mark','mark','edge','G',(180,100),(168,88,24,24),{'mtf50':.2},{'mtf50':'cy/px'})
        result=AnalysisResult(metadata,'test','test',[m],{},{});snapshot=result.to_dict();viewer.set_result(result)
        viewer.rotate_preview(1);viewer.mirror_preview('vertical')
        assert viewer.zoom_scale()>0
        viewer.native_zoom();assert viewer.zoom_scale()==pytest.approx(1.)
        requests=[];monkeypatch.setattr(viewer.reader,'request',lambda *args:requests.append(args))
        viewer.pending.clear();viewer._request_tiles();assert requests and requests[0][-1]==0
        with qtbot.waitSignal(viewer.region_selected,timeout=1000) as selected:
            qtbot.mouseClick(viewer.viewport(),Qt.MouseButton.LeftButton,pos=viewer.mapFromScene(QPointF(*m.position)))
        assert selected.args==['mark']
        viewer.fit_image();viewer.begin_anchors();points=[[30,30],[350,30],[350,225],[30,225]]
        with qtbot.waitSignal(viewer.anchors_done,timeout=2000) as anchored:
            for point in points:qtbot.mouseClick(viewer.viewport(),Qt.MouseButton.LeftButton,pos=viewer.mapFromScene(QPointF(*point)))
        assert np.max(np.abs(np.array(anchored.args[0])-points))<1.5
        states=[];viewer.view_changed.connect(states.append);viewer.native_zoom();other.apply_view_state(states[-1])
        assert other.orientation==viewer.orientation and other.zoom_scale()==pytest.approx(1.)
        assert source.read_bytes()==before and result.to_dict()==snapshot
        viewer.load(preview,metadata,config);assert viewer.orientation==PreviewOrientation()
    finally:viewer.close_reader();other.close_reader()


def test_preview_buttons_fast_existing_registration_and_thumbnail_worker(qtbot,tmp_path,monkeypatch):
    from mutex_imatest.ui.main_window import MainWindow
    from PySide6.QtWidgets import QListWidgetItem
    reference=tmp_path/'template.png';source=tmp_path/'scan.png';write_image(reference,rich_reference());write_image(source,np.flip(rich_reference(),axis=0))
    before=source.read_bytes();metadata=ImageMetadata(str(source),800,600,1,'uint8',8,len(before),hashlib.sha256(before).hexdigest())
    window=MainWindow();qtbot.addWidget(window);window.persist_preferences=False;window.show()
    window.config=AnalysisConfig(cache_dir=str(tmp_path/'cache'));chart=copy.deepcopy(window.current_chart());chart.preview=str(reference)
    window.charts[window.chart_combo.currentIndex()]=chart
    measurement=Measurement('point','point','edge','G',(300,200),(280,180,40,40),{'mtf50':.2},{'mtf50':'cy/px'})
    result=AnalysisResult(metadata,chart.id,chart.name,[measurement],{},chart.to_dict(),{'method':'four_corner_homography','homography':[[800,0,0],[0,-600,600],[0,0,1]]})
    snapshot=result.to_dict()
    entry={'path':str(source),'preview':str(source),'metadata':metadata,'result':result,'result_path':None,'status':'已分析','config':window.config.to_dict()}
    window.entries=[entry];window.images.addItem(QListWidgetItem('scan'));window.images.setCurrentRow(0)
    assert window.viewer.orientation==PreviewOrientation()
    qtbot.mouseClick(window.rotate_right,Qt.MouseButton.LeftButton);assert window.viewer.orientation.quarter_turns==1
    qtbot.mouseClick(window.reset_orientation_button,Qt.MouseButton.LeftButton);assert window.viewer.orientation==PreviewOrientation()
    qtbot.mouseClick(window.quick_orientation,Qt.MouseButton.LeftButton)
    assert window.viewer.orientation==PreviewOrientation(0,False,True) and window.worker.current is None
    assert result.to_dict()==snapshot and 'preview_orientation' not in window.snapshot_config().to_dict()
    window.entries.append(dict(entry,result=None,preview_orientation=PreviewOrientation().to_dict()));window.images.addItem(QListWidgetItem('second'))
    window.images.setCurrentRow(1);assert window.viewer.orientation==PreviewOrientation()
    window.images.setCurrentRow(0);assert window.viewer.orientation==PreviewOrientation(0,False,True)
    window.entries[1]['result']=result;window.refresh_compare();window.compare.setCurrentIndex(window.compare.findData(1))
    assert window.viewer.orientation==PreviewOrientation(0,False,True) and window.reference_viewer.orientation==window.viewer.orientation
    window.compare.setCurrentIndex(0)
    entry['result']=None;window.viewer.reset_orientation();window.display_entry(0)
    submitted=[];original=window.worker.submit
    def capture(payload):submitted.append(payload);return original(payload)
    monkeypatch.setattr(window.worker,'submit',capture)
    qtbot.mouseClick(window.quick_orientation,Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda:window.worker.current is None,timeout=30000)
    assert len(submitted)==1 and submitted[0]['action']=='preview_orientation' and 'path' not in submitted[0]
    assert window.viewer.orientation==PreviewOrientation(0,False,True) and entry['result'] is None
    window.jobs['stale']={'index':0,'action':'preview_orientation','chart':chart.to_dict(),'fingerprint':metadata.fingerprint,'view_revision':entry.get('preview_view_revision',0)}
    window.viewer.rotate_preview(1);current=window.viewer.orientation
    window.job_event('stale',{'type':'done','preview_orientation':{'orientation':PreviewOrientation().to_dict(),'correlation':1.}})
    assert window.viewer.orientation==current
    assert source.read_bytes()==before
    window.close()
