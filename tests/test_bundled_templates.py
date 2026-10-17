import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from mutex_imatest.bundled_templates import BUNDLE_FORMAT, BUNDLE_TOKEN, bundled_charts
from mutex_imatest.chart_package import export_chart_package
from mutex_imatest.models import ChartDefinition,Region


@pytest.fixture
def bundle(tmp_path):
    root=tmp_path/'assets';root.mkdir()
    preview=tmp_path/'input.png'
    Image.fromarray(np.full((96,128,3),160,np.uint8)).save(preview)
    chart=ChartDefinition('bundled-test','Bundled test',[Region('e','edge',(.1,.1,.8,.8))],preview=str(preview),aliases=['old-test'])
    temporary=root/'chart.mxtpl'
    export_chart_package(chart,temporary,BUNDLE_TOKEN)
    asset=temporary.with_suffix('.mxasset');temporary.rename(asset)
    data={'format':BUNDLE_FORMAT,'version':1,'charts':[{'id':chart.id,'file':asset.name,'sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'regions':1}]}
    (root/'manifest.json').write_text(json.dumps(data),encoding='utf-8')
    return root,data


def test_bundle_works_without_source_or_original_library(bundle):
    root,_=bundle
    charts=bundled_charts(root)
    assert len(charts)==1 and charts[0].id=='bundled-test'
    assert charts[0].source_path is None and Path(charts[0].preview).is_file()
    assert charts[0].regions[0].box==(.1,.1,.8,.8)
    assert charts[0].aliases==['old-test']


@pytest.mark.parametrize('change',['hash','regions','escape'])
def test_invalid_bundled_asset_is_not_loaded(bundle,change):
    root,data=bundle
    entry=data['charts'][0]
    if change=='hash':entry['sha256']='0'*64
    elif change=='regions':entry['regions']=99
    else:entry['file']='../chart.mxasset'
    (root/'manifest.json').write_text(json.dumps(data),encoding='utf-8')
    assert bundled_charts(root)==[]


def test_bundle_does_not_duplicate_local_alias(bundle,monkeypatch):
    from mutex_imatest import templates
    root,_=bundle
    local=ChartDefinition('old-test','Local edited',[Region('e','edge',(.2,.2,.6,.6))])
    templates.save_chart(local,templates.library_dir()/'local.json')
    monkeypatch.setattr(templates,'public_charts',lambda:[])
    monkeypatch.setattr('mutex_imatest.bundled_templates.bundled_charts',lambda:bundled_charts(root))
    charts=templates.available_charts()
    assert len([c for c in charts if c.id in {'old-test','bundled-test'}])==1
    assert next(c for c in charts if c.id=='old-test').regions[0].box==(.2,.2,.6,.6)
