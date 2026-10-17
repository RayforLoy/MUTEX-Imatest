"""Bounded-memory native-size gray exports using the measured RGB shift field."""
from pathlib import Path
import zlib
import numpy as np
import cv2
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import Delaunay,QhullError
from .analysis.preprocess import linearize
from .utils import atomic_json,check_cancel


class AlignmentField:
    def __init__(self,summary):
        units=[u for u in summary['units'] if u['located'] and all(u['rgb_shifts'].get(c,{}).get('valid') for c in ['R','B'])]
        if len(units)<3:raise ValueError('至少需要 3 个位置分布充分的有效 RGB 位移测点')
        self.points=np.array([u['position'] for u in units]);self.values=np.array([[u['rgb_shifts'][c][k] for c in ['R','B'] for k in ['dx_px','dy_px']] for u in units])
        try:self.tri=Delaunay(self.points);self.interpolate=LinearNDInterpolator(self.tri,self.values,fill_value=np.nan)
        except QhullError as exc:raise ValueError('RGB 测点共线，无法建立二维位移场') from exc
    def sample(self,x,y):
        shape=np.broadcast_shapes(np.shape(x),np.shape(y));x,y=np.broadcast_arrays(x,y)
        return self.interpolate(np.column_stack([x.ravel(),y.ravel()])).reshape(shape+(4,))


def export_gray(result,directory,cancel=None,progress=None):
    from .imaging import ImageSource
    from .config import AnalysisConfig
    from tifffile import TiffWriter
    progress=progress or (lambda *args:None)
    if not result.optical_summary:raise ValueError('需要整卡 RGB 多频率分析结果')
    field=AlignmentField(result.optical_summary);config=AnalysisConfig.from_dict(result.settings).validate()
    target=Path(directory);target.mkdir(parents=True,exist_ok=True)
    weights=np.array(result.optical_summary['gray_weights']);width,height=result.image.width,result.image.height
    band=128;pad=int(np.ceil(config.rgb_max_shift_px))+3
    files=[];counts={}
    with ImageSource(result.image.path,config,cancel,progress) as source:
        if source.metadata.fingerprint!=result.image.fingerprint:raise ValueError('源文件已改变，请重新分析')
        for mode in ['Y','Y_align','alignment_valid_mask']:
            path=target/(mode+'.tif');partial=path.with_suffix('.partial.tif');valid_count=0
            def strips():
                nonlocal valid_count
                for y in range(0,height,band):
                    check_cancel(cancel);h=min(band,height-y);start=max(0,y-pad);end=min(height,y+h+pad)
                    raw=source.read_roi((0,start,width,end-start));data=linearize(raw,config,source.metadata.is_linear)
                    if data.ndim==2:data=np.repeat(data[...,None],3,axis=2)
                    if mode=='Y':gray=data[y-start:y-start+h,...,:3]@weights;mask=np.ones((h,width),bool)
                    else:
                        xx,yy=np.meshgrid(np.arange(width,dtype=np.float32),np.arange(y,y+h,dtype=np.float32));shift=field.sample(xx,yy)
                        mask=np.isfinite(shift).all(axis=2);gray=data[y-start:y-start+h,...,1]*weights[1]
                        for ci,si in [(0,0),(2,2)]:
                            mx=xx+shift[...,si];my=yy+shift[...,si+1]-start
                            mask&=(mx>=0)&(mx<=width-1)&(my>=0)&(my<=len(data)-1)
                            sampled=cv2.remap(data[...,ci].astype(np.float32),np.nan_to_num(mx,nan=-1).astype(np.float32),np.nan_to_num(my,nan=-1).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
                            gray+=sampled*weights[ci]
                    valid_count+=int(mask.sum())
                    progress(int(5+90*(len(files)+y/height)/3),f'导出 {mode}: {y+h}/{height}')
                    pixels=mask.astype(np.uint8)*255 if mode=='alignment_valid_mask' else np.rint(np.clip(np.where(mask,gray,0),0,1)*65535).astype('<u2')
                    # Tifffile's ndarray iterator represents full pages. A byte
                    # iterator with declared compression represents encoded
                    # strips and keeps memory bounded without a page buffer.
                    yield zlib.compress(pixels.tobytes(),6)
            try:
                with TiffWriter(partial,bigtiff=width*height*2>3.5*2**30) as writer:
                    writer.write(strips(),shape=(height,width),dtype=np.uint8 if mode=='alignment_valid_mask' else np.uint16,
                                 photometric='minisblack',rowsperstrip=band,compression='deflate',metadata=None,
                                 description='MUTEX derived gray; see gray-export.json. Invalid aligned pixels are zero and identified by alignment_valid_mask.tif.')
                partial.replace(path)
            except BaseException:
                partial.unlink(missing_ok=True);raise
            files.append(path.name);counts[mode]=valid_count
    info={'source_sha256':result.image.fingerprint,'source':result.image.path,'files':files,'valid_pixels':counts,
          'weights':weights.tolist(),'transfer':config.transfer,'gamma':config.gamma,'dtype':'uint16 derived gray (not additional measured precision)',
          'alignment':'G reference; piecewise linear R/B shift field inside measured convex hull, bilinear intensity sampling; no extrapolation',
          'invalid_pixels':'Y_align zero outside supported shift field or image boundary; use alignment_valid_mask.tif',
          'resolution_measurements':'Original analysis uses each local unit shift; full-frame exported field interpolates those shifts and is a separate derived product.'}
    atomic_json(target/'gray-export.json',info);return target
