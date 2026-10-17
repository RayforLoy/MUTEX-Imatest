"""Exercise codecs and video using the actual portable CLI, not source imports.

RAW fixtures are optional local inputs and are never copied into a release.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import uuid
import numpy as np
import tifffile
import cv2

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, default=ROOT/'dist/MUTEX Imatest/MUTEX-CLI.exe')
    parser.add_argument('--raw-folder', type=Path)
    args = parser.parse_args()
    base = ROOT/'validation/slim-runtime'
    folder = base/uuid.uuid4().hex[:12]
    folder.mkdir(parents=True)
    checks = []

    def invoke(name, command):
        run = subprocess.run([str(args.exe), *map(str, command)], capture_output=True,
                             encoding='utf-8', errors='replace', timeout=300, cwd=ROOT)
        (folder/(name+'.log')).write_text(run.stdout+'\n'+run.stderr, encoding='utf-8')
        if run.returncode:
            raise RuntimeError(f'{name}: exit {run.returncode}; see {folder/name}.log')

    config = folder/'config.json'
    config.write_text(json.dumps({'transfer':'linear','channels':'RGB','memory_mb':1024,
                                  'cache_dir':str(folder/'cache')}), encoding='utf-8')
    chart = folder/'chart.json'
    chart.write_text(json.dumps({'id':'codec-test','name':'Synthetic codec edge',
                                 'regions':[{'id':'edge','kind':'edge','box':[.05,.05,.9,.9]}]}), encoding='utf-8')
    y, x = np.mgrid[:256,:384]
    edge = (7000+48000/(1+np.exp(-np.clip((x-192-.08*(y-128))/1.2,-50,50)))).astype(np.uint16)
    rgb = np.repeat(edge[...,None],3,axis=2)
    for name, compression, planar in [('uint16-deflate','deflate',False),
                                       ('uint16-lzw','lzw',False),
                                       ('uint16-planar','deflate',True)]:
        file = folder/(name+'.tif')
        tifffile.imwrite(file, np.moveaxis(rgb,-1,0) if planar else rgb, photometric='rgb',
                         compression=compression, planarconfig='separate' if planar else 'contig')
        out = folder/name
        invoke(name, ['analyze',file,'--chart',chart,'--config',config,'--out',out])
        data = json.loads((out/name/'result.json').read_text(encoding='utf-8'))
        assert data['image']['dtype']=='uint16' and data['image']['channels']==3
        assert len(data['measurements'])==3
        checks.append({'name':name,'passed':True,'dtype':'uint16','channels':3})

    video = folder/'frames.avi'
    writer = cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),10.,(128,96))
    assert writer.isOpened()
    for index in range(15):
        a = np.full((96,128,3),90+index,dtype=np.uint8)
        cv2.rectangle(a,(30+index,20),(65+index,65),(180,180,180),-1)
        writer.write(a)
    writer.release()
    spec = folder/'video.json'
    spec.write_text(json.dumps({'workflow':'video','files':[str(video)],
                                'parameters':{'every':1,'max_frames':15,'roi':[0,0,128,96]}}), encoding='utf-8')
    invoke('video',['lab',spec,'--out',folder/'video-result'])
    checks.append({'name':'video-mjpeg','passed':True})

    if args.raw_folder:
        raw_chart=folder/'raw-chart.json'
        raw_chart.write_text(json.dumps({'id':'raw-codec-test','name':'Native RAW ROI',
                                         'regions':[{'id':'patch','kind':'flat','box':[.48,.48,.015,.015]}]}),encoding='utf-8')
        for file in sorted(args.raw_folder.iterdir()):
            if file.suffix.lower() not in {'.arw','.nef','.raf','.cr2','.cr3'}:
                continue
            out = folder/('raw-'+file.stem)
            invoke('raw-'+file.stem,['analyze',file,'--chart',raw_chart,'--config',config,
                                     '--channels','G','--memory-mb','4096','--out',out])
            data = json.loads((out/file.stem/'result.json').read_text(encoding='utf-8'))
            assert data['image']['is_raw'] and data['image']['dtype']=='uint16'
            checks.append({'name':file.name,'passed':True,'dtype':'uint16','raw':True})

    record = {'passed':True,'exe_sha256':hashlib.sha256(args.exe.read_bytes()).hexdigest(),
              'checks':checks}
    (base/'verification.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    main()
