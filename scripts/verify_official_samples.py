"""Download opt-in, pinned GPL Imatest examples and record compatibility checks.

Official photographs stay in ignored samples/private, never in template assets
or portable binaries. This checks operability, not numerical Imatest equivalence.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import urllib.request
import urllib.parse

CASES = [
    ('sfrplus', 'SFRplus/SFRplus_iPhone_4.JPG'),
    ('esfr_iso', 'ISO 12233 2017 E-SFR Resolution/eSFR-ISO_LX7_fromRAW.jpg'),
    ('esfr_iso_2024', 'ISO 12233 2023 E-SFR Resolution/eSFR-ISO-23_001.jpg'),
    ('iso12233_2000', 'ISO 12233 2000 E-SFR Resolution/SFR_ISO12233-2000_EOS10D.jpg'),
    ('flatfield', 'Flatfield/Flatfield_Blemish_1spot.jpg'),
    ('flatfield', 'Flatfield/Flatfield_HotDead_1.jpg'),
    ('dot_pattern', 'DotPattern/DotPattern_1.PNG'),
    ('spilled_coins', 'SpilledCoins/SpilledCoins_cross.jpg'),
]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');parser.add_argument('--out',default='validation/imatest-compatibility')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];private=root/'samples/private/imatest-examples';private.mkdir(parents=True,exist_ok=True)
    revision_file=private/'revision.json'
    if args.download and not revision_file.exists():
        request=urllib.request.Request('https://api.github.com/repos/imatest/examples/commits/main',headers={'User-Agent':'MUTEX-compatibility-validation'})
        revision=json.load(urllib.request.urlopen(request,timeout=30))['sha']
        revision_file.write_text(json.dumps({'repository':'https://github.com/imatest/examples','commit':revision}),encoding='utf-8')
    revision=json.loads(revision_file.read_text(encoding='utf-8'))['commit']
    if args.download:
        for relative in ['LICENSE']+[path for _,path in CASES]:
            target=private/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():
                url=f'https://raw.githubusercontent.com/imatest/examples/{revision}/'+urllib.parse.quote(relative,safe='/')
                target.write_bytes(urllib.request.urlopen(url,timeout=60).read())
    license_text=(private/'LICENSE').read_text(encoding='utf-8')
    if 'GNU GENERAL PUBLIC LICENSE' not in license_text or 'Version 3' not in license_text:raise ValueError('Unexpected example license')
    from mutex_imatest.imaging import ImageSource
    from mutex_imatest.config import AnalysisConfig
    from mutex_imatest.official_charts import prepare_profile
    from mutex_imatest.analysis.engine import analyze_source
    from mutex_imatest.utils import atomic_json
    import cv2
    cv2.setNumThreads(1)
    out=(root/args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'repository':'https://github.com/imatest/examples','commit':revision,'license':'GPL-3.0','cases':[],
            'scope':'Official sample operability; not comparison against commercial Imatest numerical outputs.'}
    for index,(profile,relative) in enumerate(CASES):
        path=private/relative;entry={'profile':profile,'sample':relative,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        config=AnalysisConfig(transfer='srgb',channels='G',reject_clipping=False,registration='template')
        try:
            with ImageSource(path,config) as source:
                options={}
                if profile=='dot_pattern':
                    # Record a guided grid, not a guessed match; actual dimensions are
                    # supplied after inspecting this fixture (see verification notes).
                    options={'rows':15,'cols':20}
                chart=prepare_profile(source,profile,preview_path=out/f'case-{index}-preview.png',**options)
                result=analyze_source(source,chart,config)
                result.save(out/f'case-{index}-result.json')
                metrics={key:[m.values[key] for m in result.measurements if m.valid and key in m.values] for key in ['mtf50','blemish_count','hot_pixel_count','dead_pixel_count','radial_fit_rms_px','high_frequency_energy']}
                entry.update(regions=len(chart.regions),valid=sum(m.valid for m in result.measurements),measurements=len(result.measurements),metrics=metrics,
                             flags=list({f for m in result.measurements for f in m.flags}))
                entry['status']='pass' if entry['valid'] else 'fail'
        except Exception as exc:entry.update(status='error',error=str(exc))
        report['cases'].append(entry);print(profile,entry['status'],entry.get('valid',entry.get('error')),flush=True)
    atomic_json(out/'verification.json',report)
    return int(any(case['status']!='pass' for case in report['cases']))


if __name__=='__main__':raise SystemExit(main())
