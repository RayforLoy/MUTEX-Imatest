"""Build authorised measurement/raster assets; never distribute source artwork."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import shutil
from mutex_imatest.bundled_templates import BUNDLE_FORMAT, BUNDLE_TOKEN
from mutex_imatest.chart_package import export_chart_package
from mutex_imatest.templates import load_chart


def main():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    parser=argparse.ArgumentParser()
    parser.add_argument('--chart',type=Path,action='append',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    entries=[]
    for path in args.chart:
        chart=copy.deepcopy(load_chart(path))
        # This label preserves the supplied artwork's closed-source status.
        chart.asset_license='User-supplied proprietary chart artwork; original vector excluded; application GPL does not license this artwork.'
        temporary=args.out/(chart.id+'.mxtpl')
        target=temporary.with_suffix('.mxasset')
        if target.exists():raise FileExistsError(target)
        export_chart_package(chart,temporary,BUNDLE_TOKEN)
        temporary.rename(target)
        entries.append({'id':chart.id,'name':chart.name,'file':target.name,
                        'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                        'regions':len(chart.regions),'kinds':sorted({r.kind for r in chart.regions})})
    manifest={'format':BUNDLE_FORMAT,'version':1,'charts':entries,
              'source_artwork':'Original SVG/PDF not included.',
              'loader_token':'Public application token; runtime raster/geometry remain accessible to recipients.',
              'artwork_license':'User-supplied proprietary chart artwork; no open-source artwork licence granted.'}
    (args.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    assets=Path(__file__).resolve().parents[1]/'src/mutex_imatest/assets'
    for name in ['demo-chart.json','demo-preview.png']:
        shutil.copyfile(assets/name,args.out/name)
    (args.out/'README.txt').write_text('Bundled measurement and raster assets. Original private SVG/PDF artwork is not distributed.\nThe public application loader token permits offline use, not DRM or secrecy of raster data.\nPrivate user exports use their own password and are independent of these built-in assets.\n.mxasset artwork rights remain with its owner; the application GPL does not license this artwork.\ndemo-chart.json and demo-preview.png are original synthetic CC0 assets.\n',encoding='utf-8')
    print(json.dumps({'templates':len(entries),'regions':[c['regions'] for c in entries],
                      'bytes':sum(p.stat().st_size for p in args.out.iterdir() if p.is_file())},indent=2))


if __name__=='__main__':main()
