"""Exercise the frozen CLI's new workflows, including a deliberate limit failure."""
from pathlib import Path
import json
import subprocess
import sys
import hashlib
import tomllib
import uuid
import numpy as np
import tifffile


def main():
    root=Path(__file__).resolve().parents[1]
    exe=root/'dist/MUTEX Imatest/MUTEX-CLI.exe'
    base=root/'validation/iq-packaged';base.mkdir(parents=True,exist_ok=True)
    out=base/('run-'+uuid.uuid4().hex[:12]);out.mkdir()
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    def invoke(name,args,expected=0):
        completed=subprocess.run([str(exe),*map(str,args)],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300)
        (out/(name+'.log')).write_text(completed.stdout+'\n'+completed.stderr,encoding='utf-8')
        if completed.returncode!=expected:raise RuntimeError(f'{name}: exit {completed.returncode}, expected {expected}; see log')
        if name=='version' and completed.stdout.strip()!=version:raise ValueError('Frozen version differs from source')
        if name=='charts' and len(json.loads(completed.stdout))!=35:raise ValueError('Expected 35 chart compatibility profiles')
        return {'name':name,'returncode':completed.returncode,'expected':expected,'passed':True}
    checks=[invoke('version',['--version']),invoke('charts',['charts'])]
    sample=root/'samples/private/imatest-examples/SFRplus/SFRplus_iPhone_4.JPG'
    config={'transfer':'srgb','reject_clipping':False};(out/'config.json').write_text(json.dumps(config),encoding='utf-8')
    checks.append(invoke('official-sfrplus',['analyze',sample,'--profile','sfrplus','--out',out/'official','--transfer','srgb','--channels','G','--report','--report-format','html','--config',out/'config.json']))
    checks.append(invoke('chart-prepare',['chart-prepare',sample,'--profile','sfrplus','--out',out/'sfrplus-chart.json']))
    specifications={
        'compare':{'workflow':'compare','files':[str(sample)]*2,'config':{'transfer':'srgb'},'parameters':{'roi':[0,0,128,128]}},
        'simulate':{'workflow':'simulate','files':[str(sample)],'config':{'transfer':'srgb'},'parameters':{'roi':[0,0,128,128],'seed':55}},
    }
    fixtures=out/'sensor';fixtures.mkdir(exist_ok=True)
    rng=np.random.default_rng(13);shape=(80,80);black=120;gain=.8;read_noise=3.
    dark=rng.normal(0,1.5,shape);pattern=rng.normal(1,.005,shape)
    sensor_paths=[]
    for index in range(4):
        a=black+dark+rng.normal(0,read_noise,shape)
        path=fixtures/f'dark-{index}.tif';tifffile.imwrite(path,np.rint(a).astype(np.uint16));sensor_paths.append(str(path))
    for level,signal in enumerate([200,500,900,1400,2000,2600]):
        for frame in range(4):
            a=black+dark+gain*rng.poisson(signal/gain*pattern)+rng.normal(0,read_noise,shape)
            path=fixtures/f'flat-{level}-{frame}.tif';tifffile.imwrite(path,np.rint(a).astype(np.uint16));sensor_paths.append(str(path))
    specifications['ptc']={'workflow':'ptc','files':sensor_paths,'config':{'transfer':'linear'},'parameters':{'roi':[0,0,80,80],'dark_count':4,'group_size':4,'saturation_dn':4095}}
    import colour
    source=rng.uniform(.05,.65,(24,3));matrix=np.array([[1.1,-.04,.02],[.03,.9,.04],[-.02,.02,1.03]])
    lab=colour.XYZ_to_Lab(colour.sRGB_to_XYZ(source@matrix,apply_cctf_decoding=False))
    specifications['ccm']={'workflow':'ccm','files':[],'parameters':{'measured_rgb':source.tolist(),'reference_lab':lab.tolist(),'illuminant':'D65'}}
    for name,spec in specifications.items():
        path=out/(name+'-task.json');path.write_text(json.dumps(spec),encoding='utf-8')
        checks.append(invoke(name,['lab',path,'--out',out/name]))
    ptc=json.loads((out/'ptc/lab-result.json').read_text(encoding='utf-8'))['output']
    if abs(ptc['gain_dn_per_e']/gain-1)>.08:raise ValueError('Frozen PTC disagrees with known gain')
    result=out/'official'/sample.stem/'result.json'
    measured=json.loads(result.read_text(encoding='utf-8'))
    selected=[m['region_id'] for m in measured['measurements'] if m['values'].get('mtf50') is not None and not set(m['flags'])&{'clipped','fit_failed','invalid_edge'}][:8]
    if len(selected)<5:raise ValueError('Insufficient valid official sample ROIs')
    for name,minimum,maximum,expected in [('pass',.001,1.,0),('fail',0.,.0001,2)]:
        plan={'version':1,'name':'Frozen '+name,'tests':[{'result':str(result),'limits':[{'metric':'mtf50','channel':'G','region_ids':selected,'min':minimum,'max':maximum,'minimum_count':5}]}]}
        plan_path=out/(name+'-plan.json');plan_path.write_text(json.dumps(plan),encoding='utf-8')
        spec={'workflow':'test_plan','parameters':{'plan':str(plan_path)}}
        path=out/(name+'-task.json');path.write_text(json.dumps(spec),encoding='utf-8')
        checks.append(invoke(name+'-plan',['lab',path,'--out',out/(name+'-plan')],expected))
    checks.append(invoke('test-db',['test-db',out/'pass-plan/test-history.sqlite']))
    report={'executable':str(exe),'version':version,'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
            'run_folder':str(out),'checks':checks,'ptc_gain_dn_per_e':ptc['gain_dn_per_e'],'expected_gain_dn_per_e':gain,'all_passed':all(c['passed'] for c in checks)}
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (base/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
