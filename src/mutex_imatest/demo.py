from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import tifffile
from scipy.special import erf
from scipy.ndimage import gaussian_filter
from PIL import Image,ImageDraw,ImageFont
from .models import ChartDefinition,Region
from .utils import atomic_json,to_rgb8

DEMO_ID="mutex-synthetic-multitarget-v1"
def demo_definition():
    w,h=1600,1200
    regions=[]
    for iy,ny in enumerate([.16,.5,.84]):
        for ix,nx in enumerate([.1,.5,.9]):
            pw,ph=160,128
            regions.append(Region(f"edge-{iy}-{ix}","edge",((nx*w-pw/2)/w,(ny*h-ph/2)/h,pw/w,ph/h),f"斜边 {iy+1}·{ix+1}"))
    for i,nx in enumerate([.29,.71]):
        size=228
        regions.append(Region(f"star-{i}","star",((nx*w-size/2)/w,(.5*h-size/2)/h,size/w,size/h),f"西门子星 {i+1}",{"cycles":24,"pattern":"binary"}))
    for i,(nx,ny) in enumerate([(.29,.19),(.71,.19),(.29,.81),(.71,.81)]):
        pw,ph=132,96
        regions.append(Region(f"usaf-{i}","usaf",((nx*w-pw/2)/w,(ny*h-ph/2)/h,pw/w,ph/h),f"USAF G1 E{i+1}",{"group":1,"element":i+1,"direction":"vertical"}))
    regions.append(Region("flat-bottom","flat",(.4,.94,.2,.035),"底部均匀块"))
    return ChartDefinition(DEMO_ID,"合成验证卡 · 斜边 / 星图 / USAF",regions,
           physical_size_mm=(160.,120.),reference_size=(w,h),calibrated=True,
           preview="demo-preview.png",asset_license="CC0-1.0; generated test assets",
           notes="本卡是软件生成的合成测试数据，不代表扫描仪或相机实测；物理尺寸为合成真值")

def generate_frame(chart,z=0,seed=7):
    w,h=chart.reference_size
    rgb=np.full((h,w,3),.85,np.float64)
    truth={}
    for region in chart.regions:
        x,y,bw,bh=region.box
        x=int(round(x*w));y=int(round(y*h));bw=int(round(bw*w));bh=int(round(bh*h))
        yy,xx=np.mgrid[:bh,:bw]
        nx=2*(x+bw/2)/w-1;ny=2*(y+bh/2)/h-1
        peak=.18*nx+.1*ny+.30*(nx*nx+ny*ny)
        sigma=np.sqrt(.65**2+(2.0*(z-peak))**2)
        truth[region.id]={"peak":peak,"sigma":float(sigma)}
        if region.kind=="edge":
            distance=(xx-(bw-1)/2-.08749*(yy-(bh-1)/2))/np.sqrt(1+.08749**2)
            for channel,shift in enumerate([.35,0,-.25]):
                rgb[y:y+bh,x:x+bw,channel]=.12+.70*(.5+.5*erf((distance-shift)/(np.sqrt(2)*sigma)))
        elif region.kind=="star":
            theta=np.arctan2(yy-(bh-1)/2,xx-(bw-1)/2)
            target=.12+.7*(np.sin(region.params["cycles"]*theta)>0)
            a=gaussian_filter(target,sigma)
            rgb[y:y+bh,x:x+bw]=a[...,None]
        elif region.kind=="usaf":
            # Physical 3-bar element with 3 bright/dark line pairs and border margins.
            from .analysis.targets import usaf_frequency
            f=usaf_frequency(region.params["group"],region.params["element"])/10
            cx=(bw-1)/2
            target=np.full((bh,bw),.82)
            for bar in [-1,0,1]:
                center=cx+bar/f
                target[(abs(xx-center)<1/(4*f)) & (yy>bh*.16) & (yy<bh*.84)]=.12
            target=gaussian_filter(target,sigma)
            # Tight ROI frequency profile remains a demonstration, printed targets need calibration.
            rgb[y:y+bh,x:x+bw]=target[...,None]
        elif region.kind=="flat":
            rng=np.random.default_rng(seed)
            rgb[y:y+bh,x:x+bw]=np.clip(.5+rng.normal(0,.002,(bh,bw,3)),0,1)
    arr=np.clip(rgb*65535+.5,0,65535).astype(np.uint16)
    return arr,truth

def generate_demo(directory,series=True):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    chart=demo_definition()
    zvalues=np.linspace(-.8,1.2,9) if series else [0.]
    truth={}
    paths=[]
    for z in zvalues:
        arr,t=generate_frame(chart,float(z))
        name=f"synthetic_z{z:+.2f}mm.tiff";path=directory/name
        tifffile.imwrite(path,arr,photometric="rgb",resolution=(254,254),resolutionunit="INCH",metadata=None)
        paths.append(path);truth[name]=t
    chart.preview=str(directory/"chart-preview.png")
    # Thumbnail is a public synthetic chart, not the user's private source.
    image=Image.fromarray(to_rgb8(generate_frame(chart,.2)[0],linear=True))
    draw=ImageDraw.Draw(image)
    from .fonts import pillow_font
    font=pillow_font(16)
    for region in chart.regions:
        x,y,bw,bh=region.box
        draw.text((int(x*1600),max(0,int(y*1200)-26)),region.label,fill=(35,60,72),font=font)
    image.save(chart.preview)
    chart.source_path=None
    atomic_json(directory/"chart.json",chart.to_dict())
    atomic_json(directory/"ground-truth.json",{"format":"MUTEX synthetic truth","unit":"mm","frames":truth,
                                             "note":"Synthetic Gaussian blur; source values are not device measurements"})
    return chart,paths

def build_builtin_assets(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    chart=demo_definition()
    Image.fromarray(to_rgb8(generate_frame(chart,.2)[0],linear=True)).save(directory/"demo-preview.png")
    atomic_json(directory/"demo-chart.json",chart.to_dict())
