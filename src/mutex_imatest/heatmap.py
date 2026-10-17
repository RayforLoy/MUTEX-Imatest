from __future__ import annotations
import numpy as np
from collections import Counter
from scipy.spatial import Delaunay,ConvexHull,QhullError,cKDTree
from scipy.interpolate import LinearNDInterpolator

STOPS=np.array([[0,36,69,142],[.25,32,149,191],[.5,77,195,146],[.75,245,208,71],[1,237,91,65]],float)

def colorize(values,low,high,alpha=.48):
    v=np.clip((values-low)/max(high-low,1e-12),0,1)
    rgba=np.zeros(v.shape+(4,),np.uint8)
    for c in range(3):rgba[...,c]=np.interp(np.nan_to_num(v),STOPS[:,0],STOPS[:,c+1]).astype(np.uint8)
    rgba[...,3]=np.where(np.isfinite(values),int(alpha*255),0).astype(np.uint8)
    return rgba

def _corners(box):
    x,y,w,h=box
    return np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],float)


def _paint_coverage(mask,vertices,xs,ys):
    """Rasterize a convex support polygon at the actual display sample sites."""
    vertices=np.unique(vertices,axis=0)
    if len(vertices)<3:return
    try:polygon=vertices[ConvexHull(vertices).vertices]
    except QhullError:return
    lo=polygon.min(axis=0);hi=polygon.max(axis=0)
    x0=np.searchsorted(xs,lo[0]);x1=np.searchsorted(xs,hi[0],side='right')
    y0=np.searchsorted(ys,lo[1]);y1=np.searchsorted(ys,hi[1],side='right')
    if x0==x1 or y0==y1:return
    xx=xs[x0:x1][None,:];yy=ys[y0:y1,None];inside=np.ones((y1-y0,x1-x0),bool)
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        inside&=(b[0]-a[0])*(yy-a[1])-(b[1]-a[1])*(xx-a[0])>=-1e-8
    mask[y0:y1,x0:x1]|=inside


def _field_to_region_edges(points,values,boxes,iw,ih,width,height,interpolate):
    """Keep center interpolation; extend its boundary values to ROI envelopes.

    Valid short center triangles/edges determine which regions may be joined.
    Expanding those local supports to their ROI corners avoids a global hull
    bridging missing areas. Outside the center mesh, the closest mesh boundary
    value is continued without inventing higher/lower measured extrema.
    """
    field=np.full((height,width),np.nan)
    if not len(points):return field
    xs=np.linspace(0,iw,width);ys=np.linspace(0,ih,height)
    coverage=np.zeros((height,width),bool)
    for box in boxes:_paint_coverage(coverage,_corners(box),xs,ys)
    # Coincident points must not make neighbor spacing zero or give Qhull an
    # arbitrary direction's value. Raw values/IDs remain unchanged in the view.
    unique,first,inverse=np.unique(points,axis=0,return_index=True,return_inverse=True)
    order=np.argsort(first);sites=unique[order]
    samples=(np.bincount(inverse,weights=values)/np.bincount(inverse))[order]
    # Preserve the original site order (including Qhull's diagonal choices on
    # regular grids), so this boundary change does not reshape the center field.
    remap=np.empty(len(order),int);remap[order]=np.arange(len(order));inverse=remap[inverse]
    owner_boxes=[]
    for i in range(len(sites)):
        b=boxes[inverse==i];lo=b[:,:2].min(axis=0);hi=(b[:,:2]+b[:,2:]).max(axis=0)
        owner_boxes.append(np.r_[lo,hi-lo])
    owner_corners=[_corners(b) for b in owner_boxes]
    if len(sites)==1:
        field[coverage]=samples[0];return field
    span=max(iw,ih);normalized=sites/span;tree=cKDTree(normalized)
    neighbors=tree.query(normalized,k=2)[0][:,1]
    limit=max(.12,float(np.median(neighbors))*3)
    tri=None;accepted=np.empty((0,3),int);short_edges=set()
    if interpolate:
        try:
            tri=Delaunay(normalized)
            triangles=tri.simplices
            lengths=np.max(np.linalg.norm(normalized[triangles][:,:,None,:]-normalized[triangles][:,None,:,:],axis=3),axis=(1,2))
            accepted=triangles[lengths<=limit]
            all_edges={tuple(sorted((int(a),int(b)))) for row in triangles for a,b in zip(row,np.roll(row,-1))}
            short_edges={edge for edge in all_edges if np.linalg.norm(normalized[edge[0]]-normalized[edge[1]])<=limit}
        except QhullError:
            # One row/column or two ROIs: join only consecutive nearby sites.
            axis=int(np.argmax(np.ptp(sites,axis=0)));order=np.argsort(sites[:,axis],kind='stable')
            short_edges={tuple(sorted((int(a),int(b)))) for a,b in zip(order[:-1],order[1:]) if np.linalg.norm(normalized[a]-normalized[b])<=limit}
        counts=Counter(tuple(sorted((int(a),int(b)))) for row in accepted for a,b in zip(row,np.roll(row,-1)))
        for row in accepted:
            _paint_coverage(coverage,np.vstack([sites[row],*(owner_corners[i] for i in row)]),xs,ys)
        dangling=short_edges-set(counts)
        for a,b in dangling:
            _paint_coverage(coverage,np.vstack([sites[[a,b]],owner_corners[a],owner_corners[b]]),xs,ys)
        boundary=[edge for edge,count in counts.items() if count==1]+sorted(dangling)
    else:boundary=[]
    iy,ix=np.nonzero(coverage)
    if not len(ix):return field
    query=np.column_stack([xs[ix],ys[iy]])/span
    output=np.full(len(query),np.nan)
    if tri is not None and len(accepted):
        simplex=tri.find_simplex(query);valid=simplex>=0
        allowed=np.zeros(len(tri.simplices),bool)
        allowed[np.flatnonzero(lengths<=limit)]=True
        valid[valid]&=allowed[simplex[valid]]
        output[valid]=LinearNDInterpolator(tri,samples,fill_value=np.nan)(query[valid])
    missing=np.flatnonzero(~np.isfinite(output))
    if len(missing):
        q=query[missing];distance,index=tree.query(q);best=distance**2;extended=samples[index].copy()
        for a,b in boundary:
            start=normalized[a];edge=normalized[b]-start;length=float(edge@edge)
            if length<=0:continue
            dx=q[:,0]-start[0];dy=q[:,1]-start[1]
            t=np.clip((dx*edge[0]+dy*edge[1])/length,0,1)
            dist=(dx-t*edge[0])**2+(dy-t*edge[1])**2;take=dist<best
            extended[take]=(1-t[take])*samples[a]+t[take]*samples[b];best[take]=dist[take]
        output[missing]=extended
    field[iy,ix]=output
    return field


def heatmap_data(result,metric,channel="G",width=800,height=None,unit="cy/px",interpolate=True):
    from .resolution import metric_key,view_result,PAIRED_SHIFT_METRICS
    if metric in PAIRED_SHIFT_METRICS:channel=PAIRED_SHIFT_METRICS[metric];unit='px'
    source=result
    result=view_result(result,metric,result.settings.get('report_usaf_direction','both'),result.settings.get('report_frequency_index'))
    iw,ih=result.image.width,result.image.height
    height=height or max(1,int(width*ih/iw))
    points=[];values=[];ids=[];rows=[]
    actual=metric_key(metric,unit)
    for m in result.measurements:
        v=m.metric(actual)
        if m.channel==channel and m.valid and v is not None and m.confidence>.05 and np.isfinite(m.position).all():
            points.append(m.position);values.append(v);ids.append(m.region_id);rows.append(m)
    points=np.asarray(points,float).reshape(-1,2);values=np.asarray(values,float)
    from .heatmap_coverage import measurement_boxes
    boxes=measurement_boxes(source,rows)
    field=_field_to_region_edges(points,values,boxes,iw,ih,width,height,interpolate)
    low=float(values.min()) if len(values) else 0
    high=float(values.max()) if len(values) else 1
    return {"field":field,"points":points,"values":values,"ids":ids,"boxes":boxes,"low":low,"high":high,"metric":actual,"unit":unit}

def heatmap_rgba(result,metric,channel="G",width=800,height=None,unit="cy/px",alpha=.48,interpolate=True,limits=None):
    data=heatmap_data(result,metric,channel,width,height,unit,interpolate)
    low,high=limits or (data["low"],data["high"])
    data["rgba"]=colorize(data["field"],low,high,alpha)
    data["limits"]=(low,high)
    return data
