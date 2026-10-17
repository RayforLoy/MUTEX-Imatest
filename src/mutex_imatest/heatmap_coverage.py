"""Display footprints, including real USAF unit bounds in historical results.

Older unit summaries store a 4 px marker rather than their measurement extent.
Recover that extent from native element ROIs, or the saved template and local
registration when a metric/focus view no longer contains the element rows.
No measurement, template, registration or source image is changed here.
"""
from __future__ import annotations

from collections import defaultdict
import numpy as np


def _bounds(box):
    try:
        x,y,w,h=map(float,box)
        if np.isfinite([x,y,w,h]).all() and w>0 and h>0:return np.array([x,y,x+w,y+h])
    except (TypeError,ValueError):pass
    return None


def _union(boxes):
    boxes=[box for box in boxes if box is not None]
    if not boxes:return None
    a=np.asarray(boxes)
    return np.r_[a[:,:2].min(axis=0),a[:,2:].max(axis=0)]


def measurement_boxes(result,measurements):
    """Return clipped x/y/w/h display bounds for the selected measurements."""
    template=result.template or {};regions=template.get('regions',[])
    region_units={r['id']:r.get('params',{}).get('unit_id',r['id']) for r in regions if r.get('kind')=='usaf'}
    groups=defaultdict(list)
    for r in regions:
        if r.get('kind')=='usaf' and r.get('enabled',True):groups[region_units[r['id']]].append(r)
    native=defaultdict(lambda:defaultdict(list))
    for m in result.measurements:
        if m.kind=='usaf' and m.region_id in region_units and not {'registration_failed','roi_outside'}.intersection(m.flags):
            native[region_units[m.region_id]][m.channel].append(_bounds(m.box_pixels))
    registration=result.registration or {};cache={}
    iw,ih=result.image.width,result.image.height

    def unit_bounds(unit,channel):
        key=(unit,channel)
        if key in cache:return cache[key]
        # Prefer saved G geometry so raw, metric-only, RGB and focus views use
        # identical extents even when their element rows have been filtered.
        box=None;local=registration.get('unit_transforms',{}).get(unit,{})
        matrix=local.get('homography',registration.get('homography'))
        if matrix is not None:
            try:
                H=np.asarray(matrix,float);projected=[]
                if H.shape!=(3,3) or not np.isfinite(H).all():raise ValueError('Invalid transform')
                for r in groups.get(unit,[]):
                    x,y,w,h=r['box'];corners=np.array([[x,y,1],[x+w,y,1],[x+w,y+h,1],[x,y+h,1]],float)@H.T
                    if np.any(np.abs(corners[:,2])<1e-12):continue
                    xy=corners[:,:2]/corners[:,2,None]
                    if np.isfinite(xy).all():projected.append(np.r_[np.floor(xy.min(axis=0)),np.ceil(xy.max(axis=0))])
                box=_union(projected)
            except (TypeError,ValueError,KeyError):pass
        if box is None:
            rows=native.get(unit,{})
            box=_union(rows.get('G') or rows.get(channel) or next(iter(rows.values()),[]))
        cache[key]=box
        return box

    output=[]
    for m in measurements:
        box=None
        if m.kind in {'usaf_summary','focus'}:
            for suffix in ['-combined-summary','-vertical-summary','-horizontal-summary']:
                if m.region_id.endswith(suffix):
                    box=unit_bounds(m.region_id[:-len(suffix)],m.channel);break
        if box is None:box=_bounds(m.box_pixels)
        if box is None:box=np.array([*m.position,*m.position],float)
        lo=np.maximum(box[:2],0);hi=np.minimum(box[2:],[iw,ih])
        output.append([*lo,*np.maximum(hi-lo,0)])
    return np.asarray(output,float).reshape(-1,4)
