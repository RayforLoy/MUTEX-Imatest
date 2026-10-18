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


def _field_to_region_edges(points,values,boxes,iw,ih,width,height,interpolate,context_points=None):
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
    # Missing values are holes in the test layout, not permission to connect
    # the few surviving samples across the whole card. Triangulate the full
    # layout, then retain only simplices whose vertices have measured values.
    mesh=sites
    if context_points is not None:
        seen={tuple(p) for p in sites};extra=[]
        for p in context_points:
            key=tuple(p)
            if np.isfinite(p).all() and key not in seen:extra.append(p);seen.add(key)
        if extra:mesh=np.vstack([sites,extra])
    mesh_normalized=mesh/span
    neighbors=cKDTree(mesh_normalized).query(mesh_normalized,k=2)[0][:,1]
    footprint=float(np.median(np.linalg.norm(np.asarray(owner_boxes)[:,2:],axis=1)))/span
    spacing=float(np.median(neighbors))*3
    # Two isolated small ROIs cannot establish a card-wide interpolation
    # baseline. A known mesh of three or more sites retains its usual scale.
    if len(mesh)==2:spacing=min(spacing,footprint*3)
    limit=max(.12,spacing)
    tri=None;accepted=np.empty((0,3),int);short_edges=set()
    if interpolate:
        try:
            tri=Delaunay(mesh_normalized)
            triangles=tri.simplices
            lengths=np.max(np.linalg.norm(mesh_normalized[triangles][:,:,None,:]-mesh_normalized[triangles][:,None,:,:],axis=3),axis=(1,2))
            allowed=(lengths<=limit)&np.all(triangles<len(sites),axis=1)
            accepted=triangles[allowed]
            all_edges={tuple(sorted((int(a),int(b)))) for row in triangles for a,b in zip(row,np.roll(row,-1))}
            short_edges={edge for edge in all_edges if edge[1]<len(sites) and np.linalg.norm(normalized[edge[0]]-normalized[edge[1]])<=limit}
        except QhullError:
            # One row/column or two ROIs: join only consecutive nearby sites.
            axis=int(np.argmax(np.ptp(mesh,axis=0)));order=np.argsort(mesh[:,axis],kind='stable')
            short_edges={tuple(sorted((int(a),int(b)))) for a,b in zip(order[:-1],order[1:]) if a<len(sites) and b<len(sites) and np.linalg.norm(normalized[a]-normalized[b])<=limit}
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
        valid[valid]&=allowed[simplex[valid]]
        mesh_samples=np.r_[samples,np.full(len(mesh)-len(sites),np.nan)]
        output[valid]=LinearNDInterpolator(tri,mesh_samples,fill_value=np.nan)(query[valid])
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
    from .resolution import metric_key,view_result,PAIRED_SHIFT_METRICS,RAW_METRIC_KINDS,MULTI_METRICS
    if metric in PAIRED_SHIFT_METRICS:channel=PAIRED_SHIFT_METRICS[metric];unit='px'
    source=result
    result=view_result(result,metric,result.settings.get('report_usaf_direction','both'),result.settings.get('report_frequency_index'))
    iw,ih=result.image.width,result.image.height
    height=height or max(1,int(width*ih/iw))
    points=[];values=[];ids=[];rows=[]
    actual=metric_key(metric,unit)
    candidates=[m for m in result.measurements if m.channel==channel and
                (actual in m.values or metric in m.values or m.kind in RAW_METRIC_KINDS.get(metric,set()) or
                 m.kind=='usaf_summary' and metric in MULTI_METRICS or m.kind=='focus' and metric in {'best_focus','focus_offset'})]
    from .heatmap_coverage import measurement_boxes
    context_boxes=measurement_boxes(source,candidates)
    regions=[]
    for m,box in zip(candidates,context_boxes):
        v=m.metric(actual)
        usable=m.valid and v is not None and m.confidence>.05 and np.isfinite(m.position).all()
        if usable:
            points.append(m.position);values.append(v);ids.append(m.region_id);rows.append(m)
        reason='' if usable else '质量检查未通过' if not m.valid else '置信度过低' if m.confidence<=.05 else (
            f'未测得可靠的 {metric.upper()} 阈值交点；有效曲线可能未跨阈值，或三条纹已不可分辨'
            if metric in {'ctf50','ctf20','ctf10'} else '缺少物理标定，无法换算当前单位' if m.metric(metric) is not None else '当前指标未测得有效数值')
        regions.append({'id':m.region_id,'label':m.label,'position':m.position,'box':box,'value':v,
                        'usable':usable,'valid':m.valid,'reason':reason,'flags':m.flags})
    points=np.asarray(points,float).reshape(-1,2);values=np.asarray(values,float)
    boxes=measurement_boxes(source,rows)
    context_points=np.asarray([m.position for m in candidates],float).reshape(-1,2)
    field=_field_to_region_edges(points,values,boxes,iw,ih,width,height,interpolate,context_points)
    low=float(values.min()) if len(values) else 0
    high=float(values.max()) if len(values) else 1
    missing=[r for r in regions if not r['usable']]
    notice=(f'当前指标 {len(values)}/{len(regions)} 个区域有有效数值；灰色斜线为未测得区域，不跨缺失测点插值。' if missing else '')
    if missing and metric in {'ctf50','ctf20','ctf10'}:
        notice+=f' {metric.upper()} 需要可靠的阈值交点；整卡调焦可查看“已确认分辨率”或“整卡多频率调焦评分”。'
    return {"field":field,"points":points,"values":values,"ids":ids,"boxes":boxes,"low":low,"high":high,"metric":actual,"unit":unit,
            'regions':regions,'missing_count':len(missing),'notice':notice}

def heatmap_rgba(result,metric,channel="G",width=800,height=None,unit="cy/px",alpha=.48,interpolate=True,limits=None):
    data=heatmap_data(result,metric,channel,width,height,unit,interpolate)
    low,high=limits or (data["low"],data["high"])
    data["rgba"]=colorize(data["field"],low,high,alpha)
    # No-data hatching is deliberately achromatic and carries no scalar value.
    # The numerical field stays NaN, including in exports and saved results.
    if data['missing_count']:
        ih,iw=data['field'].shape;missing=np.zeros((ih,iw),bool)
        xs=np.linspace(0,result.image.width,iw);ys=np.linspace(0,result.image.height,ih)
        for r in data['regions']:
            if not r['usable']:_paint_coverage(missing,_corners(r['box']),xs,ys)
        missing&=~np.isfinite(data['field'])
        yy,xx=np.indices((ih,iw));lines=(xx+yy)%12<2
        data['rgba'][missing,:3]=[118,129,137]
        data['rgba'][missing,3]=np.where(lines[missing],min(110,int(alpha*200)),min(32,int(alpha*55)))
    data["limits"]=(low,high)
    return data
