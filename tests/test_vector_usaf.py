from pathlib import Path
import cv2
import numpy as np
import pytest
import tifffile
from PIL import Image
from mutex_imatest.templates import import_source,render_source
from mutex_imatest.vector_usaf import detect_svg_usaf
from mutex_imatest.config import AnalysisConfig
from mutex_imatest.analysis.engine import analyze


def test_transformed_decoration_does_not_disable_untransformed_bars(tmp_path,qapp):
    import copy,xml.etree.ElementTree as ET
    svg=tmp_path/'chart.svg';make_vector(svg)
    expected=detect_svg_usaf(svg,group=1,element=3)
    tree=ET.parse(svg);root=tree.getroot();ns='{http://www.w3.org/2000/svg}'
    branch=ET.SubElement(root,ns+'g',{'transform':'translate(20000 0)'})
    branch.append(copy.deepcopy(next(n for n in root if n.tag==ns+'g')))
    ET.SubElement(root,ns+'rect',{'transform':'rotate(90)','width':'500','height':'100','fill':'black'})
    tree.write(svg,encoding='utf-8')
    regions,fiducials,size=detect_svg_usaf(svg,group=1,element=3)
    assert regions==expected[0] and fiducials==expected[1] and size==expected[2]


def test_reduced_chart_without_group_zero_has_native_registration(tmp_path,qapp):
    svg=tmp_path/'reduced.svg';make_vector(svg)
    svg.write_text(svg.read_text(encoding='utf-8').replace('69mm','17.25mm'),encoding='utf-8')
    chart=import_source(svg)
    chart.regions,chart.fiducials,chart.physical_size_mm=detect_svg_usaf(svg,group=3,element=3)
    assert len(chart.regions)==18 and min(f['k'] for f in chart.fiducials)==12
    chart.calibrated=True
    preview=tmp_path/'reference.png';render_source(svg,1656,output=preview)
    pixels=np.asarray(Image.open(preview).convert('RGB'))
    captured=np.rot90(np.flipud((32+pixels.astype(float)*(193/255)).astype(np.uint8))).copy()
    target=tmp_path/'captured.tif';tifffile.imwrite(target,captured,photometric='rgb',metadata=None)
    config=AnalysisConfig(transfer='linear',channels='G',registration='usaf',reject_clipping=False,cache_dir=str(tmp_path/'cache'))
    result=analyze(target,chart,config)
    assert len(result.registration['unit_transforms'])==9
    assert all(m.valid and m.values['detected_bar_count']==3 for m in result.measurements)
    assert all(m.values['target_lp_mm']==pytest.approx(2**(3+2/6)) for m in result.measurements)


def test_quantized_fine_bar_widths_keep_the_nominal_frequency(tmp_path,qapp):
    # Three 0.21/0.22/0.21-wide bars still have the correct 0.44 period;
    # their 1.10 long sides retain the nominal G7/E6 after SVG rounding.
    body=[]
    for k in range(42,48):
        period=100/2**(k/6)
        for vertical in [True,False]:
            for i in range(3):
                if k==47:
                    minor=[.21,.22,.21][i];major=1.10;along=50+i*.44
                else:minor=period/2;major=2.5*period;along=50+i*period
                cross=50+(k-42)*5+(0 if vertical else 2.5)
                x,y,w,h=(along,cross,minor,major) if vertical else (cross,along,major,minor)
                body.append(f'<rect x="{x:.6f}" y="{y:.6f}" width="{w:.6f}" height="{h:.6f}" fill="black"/>')
    svg=tmp_path/'quantized.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm" viewBox="0 0 1000 1000"><g>'+''.join(body)+'</g></svg>',encoding='utf-8')
    regions,_,_=detect_svg_usaf(svg,all_frequencies=True)
    assert len(regions)==12 and {r.params['frequency_index'] for r in regions}==set(range(42,48))


def make_vector(path):
    body=[]
    for row in range(3):
        for col in range(3):
            bars=[]
            for k in range(18):
                period=100/2**(k/6)
                for direction in [0,1]:
                    cx=col*2200+(k%3)*700+125+direction*350
                    cy=row*2200+(k//3)*350+125
                    for i in [-1,0,1]:
                        if direction==0:x,y,w,h=cx+i*period-period/4,cy-1.25*period,.5*period,2.5*period
                        else:x,y,w,h=cx-1.25*period,cy+i*period-period/4,2.5*period,.5*period
                        bars.append(f'<polygon class="bar" points="{x:.3f},{y:.3f} {x+w:.3f},{y:.3f} {x+w:.3f},{y+h:.3f} {x:.3f},{y+h:.3f}"/>')
            body.append('<g>'+''.join(bars)+'</g>')
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="69mm" height="69mm" viewBox="0 0 6900 6900"><defs><style>.bar {fill:black}</style></defs>'+''.join(body)+'</svg>',encoding='utf-8')


@pytest.mark.parametrize("mirror",[False,True])
@pytest.mark.parametrize("turns",[0,1,2,3])
def test_native_vector_registration_handles_mirror_and_shear(tmp_path,qapp,mirror,turns):
    svg=tmp_path/'chart.svg';make_vector(svg)
    chart=import_source(svg)
    chart.regions,chart.fiducials,chart.physical_size_mm=detect_svg_usaf(svg,group=1,element=3)
    chart.calibrated=True
    assert len(chart.regions)==18 and len(chart.fiducials)==324
    reference=tmp_path/'reference.png';render_source(svg,max_side=1656,output=reference)
    pixels=np.asarray(Image.open(reference).convert('RGB'))
    pixels=(32+pixels.astype(float)*(193/255)).astype(np.uint8)
    h,w=pixels.shape[:2]
    M=np.array([[1,.007,8],[0,-1 if mirror else 1,h-1 if mirror else 0],[0,0,1]],float)
    scanned=cv2.warpPerspective(pixels,M,(w+25,h),borderValue=(225,225,225))
    sh,sw=scanned.shape[:2]
    rotations=[np.eye(3),np.array([[0,1,0],[-1,0,sw-1],[0,0,1]]),
               np.array([[-1,0,sw-1],[0,-1,sh-1],[0,0,1]]),
               np.array([[0,-1,sh-1],[1,0,0],[0,0,1]])]
    scanned=np.rot90(scanned,turns).copy()
    M=rotations[turns]@M
    target=tmp_path/'scan.tif';tifffile.imwrite(target,scanned,photometric='rgb',metadata=None)
    before=target.read_bytes()
    config=AnalysisConfig(transfer='linear',channels='RGB',registration='usaf',reject_clipping=False,cache_dir=str(tmp_path/'cache'))
    result=analyze(target,chart,config)
    assert result.registration['method']=='vector_usaf_native_refinement'
    assert len(result.registration['unit_transforms'])==9
    assert all(m.valid and m.values['detected_bar_count']==3 for m in result.measurements)
    expected=M@np.diag([w,h,1])
    for region in chart.regions:
        x,y,bw,bh=region.box
        center=cv2.perspectiveTransform(np.array([[[x+bw/2,y+bh/2]]],float),expected)[0,0]
        measured=next(m for m in result.measurements if m.region_id==region.id)
        assert np.linalg.norm(np.array(measured.position)-center)<1.5
        assert measured.values['target_lp_mm']==pytest.approx(2**(1+2/6))
        assert measured.values['registration_rms_px']<1.2
    assert target.read_bytes()==before
