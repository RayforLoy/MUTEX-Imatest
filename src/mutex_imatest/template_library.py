"""Recoverable user-library changes; public artwork is never edited in place."""
from __future__ import annotations
import copy,hashlib,json,shutil,uuid
from datetime import datetime
from pathlib import Path
from .templates import available_charts,library_dir,load_chart,save_chart


def _signature(chart):
    data=chart.to_dict()
    for key in ['id','aliases','preview','source_path','notes']:data.pop(key,None)
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def user_chart_path(chart):
    root=library_dir().resolve()
    for path in root.iterdir():
        if path.suffix.lower() not in {'.json','.mchart'} or not path.is_file() or path.is_symlink():continue
        try:
            if load_chart(path).id==chart.id:return path
        except (ValueError,OSError,KeyError,TypeError):continue
    return None


def install_chart(chart):
    """Import once, without replacing an existing template or its source."""
    signature=_signature(chart)
    for existing in available_charts():
        if _signature(existing)==signature:return existing
    imported=copy.deepcopy(chart);imported.id='user-'+uuid.uuid4().hex;imported.aliases=[]
    save_chart(imported,library_dir()/(imported.id+'.json'))
    return imported


def copy_chart(chart,name=None):
    duplicate=copy.deepcopy(chart);duplicate.id='user-'+uuid.uuid4().hex;duplicate.aliases=[]
    duplicate.name=name or chart.name+' · 副本'
    save_chart(duplicate,library_dir()/(duplicate.id+'.json'))
    return duplicate


def rename_chart(chart,name):
    name=name.strip()
    if not name:raise ValueError('模板名称不能为空')
    path=user_chart_path(chart)
    if path is None:raise ValueError('内置 / 公开模板请先复制到用户库后再重命名')
    renamed=copy.deepcopy(chart);renamed.name=name;save_chart(renamed,path)
    return renamed


def archive_chart(chart):
    """Move only the user definition to a recoverable local archive."""
    root=library_dir().resolve();path=user_chart_path(chart)
    if path is None:raise ValueError('内置 / 公开模板不能归档；用户副本可以归档')
    path=path.resolve()
    if path.parent!=root:raise ValueError('模板定义必须位于本机图卡库内')
    folder=root/'backups'/('archive-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    if not folder.resolve().is_relative_to(root):raise ValueError('归档位置不合法')
    folder.mkdir(parents=True);destination=folder/path.name
    shutil.move(str(path),str(destination))
    return destination
