"""Load optional built-in measurement/raster assets, without source artwork.

The public loader token makes shipped assets usable offline without a prompt.
It is not a secrecy/DRM boundary. User .mxtpl exports still use the user's own
password and have no recovery key; this token never opens those exports.
"""
from pathlib import Path
import hashlib
import json
from .chart_package import load_chart_package

BUNDLE_TOKEN = 'MUTEX bundled measurement/raster assets v1'
BUNDLE_FORMAT = 'MUTEX Bundled Templates'


def bundled_charts(root=None):
    if root is None:
        from .templates import public_template_dir
        public = public_template_dir()
        if public is None:
            return []
        root = public/'bundled'
    root = Path(root).resolve()
    manifest = root/'manifest.json'
    if not manifest.is_file():
        return []
    try:
        if manifest.stat().st_size > 128*1024:
            return []
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('format') != BUNDLE_FORMAT or data.get('version') != 1:
            return []
        entries = data['charts']
        if not isinstance(entries,list) or len(entries)>128:
            return []
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return []
    charts = []
    seen = set()
    for entry in entries:
        try:
            path = (root/entry['file']).resolve()
            if not path.is_relative_to(root) or path.suffix != '.mxasset' or path.stat().st_size>65*2**20:
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                continue
            chart = load_chart_package(path,BUNDLE_TOKEN)
            if chart.id!=entry['id'] or chart.id in seen or chart.source_path:
                continue
            if len(chart.regions)!=entry['regions']:
                continue
            charts.append(chart)
            seen.add(chart.id)
        except (ValueError,OSError,KeyError,TypeError):
            continue
    return charts
