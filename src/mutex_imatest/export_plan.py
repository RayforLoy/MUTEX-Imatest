"""Desktop export options, with one isolated folder for each export.

The legacy ``reports.export_bundle`` API keeps its original filenames and
defaults. The desktop uses this layer to choose names, formats and attachments
without silently replacing a previous report.
"""
from __future__ import annotations

from dataclasses import dataclass,replace
from pathlib import Path
import re
import shutil


_ILLEGAL=re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED={'CON','PRN','AUX','NUL','CONIN$','CONOUT$',
           *(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10)),
           'COM¹','COM²','COM³','LPT¹','LPT²','LPT³'}


def report_basename(value):
    """Accept a filename stem, never a path (Windows rules on every host)."""
    value=str(value)
    if not value or value!=value.strip() or value.endswith('.'):
        raise ValueError('文件名不能为空，不能以空格开头或结尾，也不能以句点结尾')
    if _ILLEGAL.search(value) or value in {'.','..'}:
        raise ValueError('文件名不能包含路径或 Windows 不允许的字符：<>:"/\\|?*')
    if value.lower().endswith(('.html','.htm','.pdf')):
        value=value.rsplit('.',1)[0]
    if not value or value.endswith((' ','.')) or value.split('.',1)[0].rstrip(' .').upper() in _RESERVED:
        raise ValueError('请使用普通文件名，不能使用 Windows 保留名称（例如 CON、NUL、COM1）')
    if len(value)>100:
        raise ValueError('报告文件名最多 100 个字符')
    return value


def default_basename(image_path):
    value=_ILLEGAL.sub('_',Path(image_path).stem).strip(' .')[:100] or '分析报告'
    try:return report_basename(value)
    except ValueError:return '分析报告'


@dataclass(frozen=True)
class ExportOptions:
    directory: str|Path
    basename: str
    format: str='both'
    title: str=''
    include_data: bool=True
    include_images: bool=False
    include_detail: bool=True

    def validate(self):
        name=report_basename(self.basename)
        directory=str(self.directory).strip()
        if not directory:raise ValueError('请选择导出目录')
        path=Path(directory).expanduser().resolve()
        if path.exists() and not path.is_dir():raise ValueError('导出目录指向一个文件，请选择文件夹')
        if self.format not in {'html','pdf','both'}:raise ValueError('报告格式必须为 HTML、PDF 或两者')
        title=self.title.strip()
        if len(title)>80 or any(ord(c)<32 for c in title):
            raise ValueError('报告标题最多 80 个字符，且不能包含换行或控制字符')
        return replace(self,directory=path,basename=name,title=title)

    @property
    def html(self):return self.format in {'html','both'}

    @property
    def pdf(self):return self.format in {'pdf','both'}


def next_available_folder(directory,basename):
    """Read-only destination preview. Export rechecks this when creating it."""
    directory=Path(directory);candidate=directory/basename;index=2
    while candidate.exists():candidate=directory/f'{basename} ({index})';index+=1
    return candidate


def export_report(result,preview,options,metric='mtf50',channel='G',unit='cy/px',*,focus_data=None):
    """Export exactly the selected formats/attachments into a new child folder.

    A cancelled dialog never calls this function. Existing files are never
    overwritten. Validation happens before any directory is created, and an
    unsuccessful export removes only the new folder allocated by this call.
    """
    from .reports import export_bundle
    from .utils import atomic_json
    options=options.validate();options.directory.mkdir(parents=True,exist_ok=True)
    while True:
        folder=next_available_folder(options.directory,options.basename)
        try:folder.mkdir();break
        except FileExistsError:continue
    try:
        export_bundle(result,preview,folder,metric,channel,unit,pdf=options.pdf,html=options.html,
                      include_data=options.include_data,include_images=options.include_images,
                      include_detail=options.include_detail,basename=options.basename,title=options.title)
        if options.include_data:
            if focus_data:atomic_json(folder/'focus-series.json',focus_data)
            atomic_json(folder/'export-manifest.json',{
                'format':'MUTEX report export','version':1,'source_sha256':result.image.fingerprint,
                'report_name':options.basename,'title':options.title,'formats':
                    [fmt for fmt,selected in [('html',options.html),('pdf',options.pdf)] if selected],
                'include_data':options.include_data,'include_images':options.include_images,
                'include_detail':options.include_detail,
                'files':sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file())})
    except Exception:
        # The folder was allocated by this call. Check its final absolute target
        # again before recursively removing a failed export on Windows.
        if folder.resolve().parent==options.directory and not folder.is_symlink():
            shutil.rmtree(folder)
        raise
    return folder
