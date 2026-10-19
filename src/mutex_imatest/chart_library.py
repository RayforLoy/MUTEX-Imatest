"""Consolidate generated variants of the same source, with recoverable backups."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import copy,hashlib,json,os,shutil,uuid
from .utils import atomic_json


def family_key(chart):
    if not chart.source_path:return ('id',chart.id)
    path=Path(chart.source_path).resolve()
    base=chart.name.split(' · 整卡多频率')[0].strip()
    # Deliberately named independent templates sharing a source stay distinct.
    return ('source',os.path.normcase(str(path)),chart.source_page,
            tuple(chart.physical_size_mm or ()),base)


def recognizes(chart,identifier):return identifier==chart.id or identifier in chart.aliases


def update_legacy_display_names(charts):
    """Rename the shipped 120 card while preserving custom names and IDs."""
    legacy='42f8e65ab1a94dfb82825b7bd07a2187'
    for chart in charts:
        if legacy in {chart.id,*chart.aliases} and chart.name=='调焦卡_x1':
            chart.name='调焦卡_120x1'
    return charts


def merge_charts(charts):
    if len(charts)==1:return copy.deepcopy(charts[0])
    def score(c):return (sum(bool(r.params.get('multi_frequency')) for r in c.regions),len(c.regions),c.calibrated,len(c.fiducials))
    ordered=sorted(charts,key=score,reverse=True);merged=copy.deepcopy(ordered[0])
    merged.name=ordered[0].name.split(' · 整卡多频率')[0].strip()
    merged.aliases=sorted({a for c in charts for a in [c.id,*c.aliases]}-{merged.id})
    merged.calibrated=any(c.calibrated for c in charts)
    merged.preview=next((c.preview for c in ordered if c.preview),None)
    seen={};ids=set();regions=[]
    def key(r):
        params={k:v for k,v in r.params.items() if k not in {'multi_frequency','frequency_index','profile_band','template_preflight','template_occluded'}}
        return (r.kind,tuple(round(v,8) for v in r.box),r.enabled,json.dumps(params,sort_keys=True,ensure_ascii=False))
    for chart in ordered:
        for r in chart.regions:
            signature=key(r)
            if signature in seen:continue
            r=copy.deepcopy(r)
            if r.id in ids:r.id+='-merged-'+hashlib.sha256(repr(signature).encode()).hexdigest()[:8]
            ids.add(r.id);seen[signature]=r.id;regions.append(r)
    merged.regions=regions
    unique={json.dumps(f,sort_keys=True,ensure_ascii=False):f for c in ordered for f in c.fiducials}
    merged.fiducials=list(unique.values())
    merged.notes='\n'.join(dict.fromkeys(c.notes for c in ordered if c.notes))
    merged.__post_init__();return merged


def consolidate(charts):
    groups=defaultdict(list)
    for c in charts:groups[family_key(c)].append(c)
    return [merge_charts(group) for group in groups.values()]


def consolidate_library(root,entries):
    """entries are (path, decoded chart); no source artwork is modified."""
    # Keep logical AppData paths: Windows packaged hosts can resolve individual
    # files into different physical directories while exposing one library.
    # Membership is checked before any write; no recursive moves are used.
    root=Path(root).absolute();groups=defaultdict(list);output=[]
    for path,chart in entries:
        path=Path(path).absolute()
        if path.parent!=root or path.suffix.lower() not in {'.json','.mchart'}:raise ValueError('Only direct library chart files can be consolidated')
        groups[family_key(chart)].append((path,chart))
    for group in groups.values():
        if len(group)==1:output.append(group[0][1]);continue
        merged=merge_charts([c for _,c in group])
        destination=root/(merged.id+'.json')
        if destination.parent!=root:raise ValueError('Chart identifier cannot contain a directory')
        backup=root/'backups'/('merge-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        if not backup.is_relative_to(root):raise ValueError('Backup must stay inside chart library')
        backup.mkdir(parents=True)
        manifest={'canonical_id':merged.id,'canonical_name':merged.name,'aliases':merged.aliases,'files':[]}
        for path,c in group:
            shutil.copy2(path,backup/path.name)
            manifest['files'].append({'name':path.name,'id':c.id,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        atomic_json(backup/'manifest.json',manifest)
        atomic_json(destination,merged.to_dict())
        for path,c in group:
            if path==destination:continue
            # Originals remain recoverable; only redundant top-level entries
            # leave the dropdown. Do not move any preview or source artwork.
            shutil.move(str(path),str(backup/('retired-'+path.name)))
        output.append(merged)
    return output
