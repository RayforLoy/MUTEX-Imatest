from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image
import pytest

from mutex_imatest.analysis.engine import analyze
from mutex_imatest.config import AnalysisConfig
from mutex_imatest import templates

ROOT=Path(__file__).resolve().parents[1]


def checkerboard():
    return next(c for c in templates.public_charts() if c.id=='public-generic-checkerboard-v1')


def reference_image(chart,max_side=2200,source_path=None):
    # This is synthetic input with a declared geometric truth. The test
    # measurement itself always calls the product engine on a saved image.
    image,_,_=templates.render_source(source_path or chart.source_path,max_side=max_side)
    from PySide6.QtGui import QImage
    image=image.convertToFormat(QImage.Format.Format_Grayscale8)
    data=np.frombuffer(image.constBits(),np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()].copy()
    data=cv2.GaussianBlur(data,(0,0),.7)
    return np.uint8(np.rint(32+data*(192/255)))


def sample_image(image,case):
    h,w=image.shape
    if case=='perspective':
        M=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),
                                     np.float32([[120,80],[w-90,135],[w-35,h-80],[190,h-65]]))
        return cv2.warpPerspective(image,M,(w,h),flags=cv2.INTER_LINEAR,borderValue=235)
    if case=='quarter_turn':return np.rot90(image).copy()
    if case=='paper_crop':return image[int(h*.09):int(h*.91),int(w*.025):int(w*.975)].copy()
    if case=='board_crop':return image[int(h*.28):int(h*.92),int(w*.01):int(w*.99)].copy()
    if case=='radial_deformation':
        yy,xx=np.mgrid[:h,:w].astype(np.float32);cx,cy=(w-1)/2,(h-1)/2
        r2=((xx-cx)**2+(yy-cy)**2)/(min(w,h)/2)**2
        return cv2.remap(image,cx+(xx-cx)*(1+.065*r2),cy+(yy-cy)*(1+.065*r2),
                         cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=224)
    return image.copy()


def expected_homography(image,case):
    """Known normalized artwork -> native image transform, before detection."""
    h,w=image.shape;H=np.diag([float(w),float(h),1.])
    if case=='perspective':
        M=cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),
                                     np.float32([[120,80],[w-90,135],[w-35,h-80],[190,h-65]]))
        return M@H
    if case=='quarter_turn':return np.array([[0,1,0],[-1,0,w-1],[0,0,1.]])@H
    if case in {'paper_crop','board_crop'}:
        left,top=(int(w*.025),int(h*.09)) if case=='paper_crop' else (int(w*.01),int(h*.28))
        return np.array([[1,0,-left],[0,1,-top],[0,0,1.]])@H
    return None if case=='radial_deformation' else H


def product_result(folder,case,registration='auto_chart'):
    cv2.setNumThreads(1)
    chart=checkerboard()
    folder.mkdir(parents=True,exist_ok=True)
    sample=folder/(case+'.png')
    source=Path(chart.source_path).with_suffix('.pdf') if case=='printed_pdf' else None
    Image.fromarray(sample_image(reference_image(chart,source_path=source),case)).save(sample)
    result=analyze(sample,chart,AnalysisConfig(channels='G',transfer='linear',registration=registration,
                     reject_clipping=False,cache_dir=str(folder/'cache'),analysis_metrics=['projective_residual_rms_px']))
    return chart,sample,result


def test_checkerboard_design_has_exact_unclipped_geometry_and_no_text_in_roi():
    chart=checkerboard();grid=chart.regions[0]
    assert len(chart.regions)==1 and grid.kind=='grid'
    assert grid.params['cols']==9 and grid.params['rows']==7
    assert grid.params['board_square_counts']==[10,8]
    assert grid.params['square_size_mm']==16 and grid.params['board_rotation_deg']==5
    assert not chart.calibrated and not grid.params.get('auto_detect')
    assert chart.physical_size_mm==(297.,210.) and chart.asset_license.startswith('CC0-1.0;')
    x,y,w,h=np.array(grid.box)*np.array([297,210,297,210])
    angle=math.radians(5);c,s=math.cos(angle),math.sin(angle)
    board=np.array([[-80,-64],[80,-64],[80,64],[-80,64]])@np.array([[c,s],[-s,c]])+np.array([148.5,105])
    assert np.all(board.min(axis=0)-[x,y]>=7.9999)
    assert np.all([x+w,y+h]-board.max(axis=0)>=7.9999)
    tree=ET.parse(chart.source_path)
    ns={'svg':'http://www.w3.org/2000/svg'}
    squares=tree.findall('.//svg:g/svg:rect',ns)
    assert len(squares)==40 and all(float(a.get('width'))==16 and float(a.get('height'))==16 for a in squares)
    for node in tree.findall('.//svg:text',ns):
        tx,ty=float(node.get('x')),float(node.get('y'))
        assert not (x<=tx<=x+w and y<=ty<=y+h)


@pytest.mark.parametrize('case',['original','printed_pdf','perspective','quarter_turn','paper_crop'])
def test_checkerboard_native_corner_measurement_handles_complete_board(tmp_path,qapp,case):
    chart,sample,result=product_result(tmp_path,case)
    assert result.registration['method']=='reference_sift_partial_homography'
    assert result.registration['verified'] and result.registration['inliers']>=12
    assert result.registration['visible_regions']==['GRID-9x7']
    assert not result.registration['outside_regions']
    source=Path(chart.source_path).with_suffix('.pdf') if case=='printed_pdf' else None
    truth=expected_homography(reference_image(chart,source_path=source),case)
    loci=np.array([[[.25,.25],[.75,.25],[.75,.75],[.25,.75],[.5,.5]]],float)
    expected=cv2.perspectiveTransform(loci,truth)
    actual=cv2.perspectiveTransform(loci,np.array(result.registration['homography']))
    assert np.max(np.linalg.norm(expected-actual,axis=2))<2.5
    assert result.image.width==Image.open(sample).width
    assert len(result.measurements)==1
    measurement=result.measurements[0]
    assert measurement.valid and measurement.metric('projective_residual_rms_px')<.25
    assert measurement.metric('projective_residual_max_px')<.6
    curve=measurement.curves['grid_residual']
    assert len(curve['x'])==len(curve['y'])==63 and curve['y_unit']=='px'
    assert 'target_geometry_affects_result' in measurement.flags
    assert measurement.object_scale_px_per_mm is None
    assert 'distortion_pct' not in measurement.values
    assert result.analysis_summary['items'][0]['status']=='complete'


def test_checkerboard_cut_board_never_invents_corner_residual(tmp_path,qapp):
    _,_,result=product_result(tmp_path,'board_crop')
    assert result.registration['method']=='reference_sift_partial_homography'
    assert result.registration['outside_regions']==['GRID-9x7']
    measurement=result.measurements[0]
    assert not measurement.valid and measurement.flags==['roi_outside']
    assert not measurement.values and not measurement.curves
    assert result.analysis_summary['items'][0]['status']=='no_valid_data'


def test_checkerboard_residual_responds_to_nonprojective_deformation(tmp_path,qapp):
    _,_,ordinary=product_result(tmp_path/'ordinary','original','none')
    _,_,deformed=product_result(tmp_path/'deformed','radial_deformation','none')
    low=ordinary.measurements[0];high=deformed.measurements[0]
    assert low.valid and high.valid
    assert low.metric('projective_residual_rms_px')<.25
    assert high.metric('projective_residual_rms_px')>1
    assert high.metric('projective_residual_rms_px')>low.metric('projective_residual_rms_px')*10
    assert high.units['projective_residual_rms_px']=='px'
    assert 'target_geometry_affects_result' in high.flags


if __name__=='__main__':
    # Reproduce a reviewable, public-only product regression without pytest.
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,default=ROOT/'validation'/'checkerboard')
    args=parser.parse_args();args.out=args.out.resolve();templates.ensure_qt();cv2.setNumThreads(1)
    records=[]
    for case in ['original','printed_pdf','perspective','quarter_turn','paper_crop','board_crop','radial_deformation']:
        chart,sample,result=product_result(args.out/'samples',case,'none' if case=='radial_deformation' else 'auto_chart')
        result.save(args.out/(case+'-result.json'))
        records.append({'case':case,'input':sample.relative_to(ROOT).as_posix(),
                        'input_sha256':hashlib.sha256(sample.read_bytes()).hexdigest(),
                        'result':(args.out/(case+'-result.json')).relative_to(ROOT).as_posix(),
                        'known_homography':None if case=='radial_deformation' else expected_homography(reference_image(chart,source_path=Path(chart.source_path).with_suffix('.pdf') if case=='printed_pdf' else None),case).tolist(),
                        'registration':result.registration,
                        'measurements':[{'valid':m.valid,'values':m.values,'flags':m.flags,
                                         'corner_residual_count':len(m.curves.get('grid_residual',{}).get('x',[]))} for m in result.measurements]})
    report={'kind':'public synthetic regression through mutex_imatest.analysis.engine.analyze',
            'chart_id':chart.id,'source_svg_sha256':hashlib.sha256(Path(chart.source_path).read_bytes()).hexdigest(),
            'source_pdf_sha256':hashlib.sha256(Path(chart.source_path).with_suffix('.pdf').read_bytes()).hexdigest(),
            'public_manifest_sha256':hashlib.sha256((ROOT/'template'/'manifest.json').read_bytes()).hexdigest(),
            'complete_board_inner_corners':[9,7],'nominal_square_mm':16,'calibrated':False,
            'pdf_visual_review':{'renderer':'Poppler pdftoppm','dpi':145,'reviewed':'2026-10-17',
                                 'image':'validation/checkerboard/render/generic-checkerboard.png',
                                 'result':'pass; full board, white border, labels and unique registration marks do not overlap'},
            'limitations':['No recovery of missing checkerboard corners','Residual combines target, print, optical and detection errors',
                           'No lens distortion percentage or camera calibration from one photo'],
            'cases':records}
    previous=args.out/'previous-manifest.json'
    if previous.is_file():
        old=json.loads(previous.read_text(encoding='utf-8'))
        kept=[x for x in old['files'] if x['path'].startswith(('originals/','previews/','definitions/','upstream/'))]
        report['previous_geometry_assets_unchanged']=all(hashlib.sha256((ROOT/'template'/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in kept)
    (args.out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{'case':r['case'],'measurements':r['measurements']} for r in records],ensure_ascii=False,indent=2))
