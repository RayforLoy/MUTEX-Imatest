from pathlib import Path
import argparse,hashlib,json,shutil,zipfile,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
import tomllib
VERSION=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']

def main():
    p=argparse.ArgumentParser();p.add_argument("--zip",action="store_true");p.add_argument('--portable-dir',type=Path)
    p.add_argument('--compresslevel',type=int,choices=range(1,10),default=9)
    p.add_argument('--require-bundled',action='store_true');ns=p.parse_args()
    target=ns.portable_dir.resolve() if ns.portable_dir else ROOT/"dist"/"MUTEX Imatest"
    if not (target/"MUTEX Imatest.exe").exists():raise ValueError("Build portable app first")
    test=ET.parse(ROOT/"validation"/"pytest.xml").find("testsuite")
    if test is None or int(test.get("tests","0"))<1 or int(test.get("errors","0"))+int(test.get("failures","0")):
        raise ValueError("Automated validation has not passed")
    if not json.loads((ROOT/"validation"/"packaged-selftest-final"/"selftest.json").read_text(encoding="utf-8"))["passed"]:
        raise ValueError("Final portable selftest has not passed")
    if not json.loads((ROOT/"validation"/"packaged-selftest-final"/"selftest.json").read_text(encoding="utf-8")).get('encrypted_template',{}).get('passed'):
        raise ValueError("Frozen encrypted template export/import has not passed")
    if (ROOT/"validation"/"packaged-selftest-final"/"selftest.json").stat().st_mtime<(target/"MUTEX Imatest.exe").stat().st_mtime:
        raise ValueError("Repeat selftest for the current executable before release")
    for filename in ["README.md","LICENSE","THIRD_PARTY_NOTICES.md","requirements-lock.txt","启动 MUTEX Imatest.cmd"]:
        shutil.copyfile(ROOT/filename,target/filename)
    # Add the matching official LibRaw source release, not any private chart source.
    source=ROOT/"vendor"/"libraw-0.22.2"/"LibRaw-0.22.2-Win64.zip"
    (target/"third-party-source").mkdir(exist_ok=True)
    if not source.exists():raise ValueError('Run scripts/upgrade_libraw.py to obtain matching LibRaw source before release')
    shutil.copyfile(source,target/"third-party-source"/source.name)
    shutil.copytree(ROOT/"docs",target/"docs",dirs_exist_ok=True)
    shutil.copytree(ROOT/'template',target/'template',dirs_exist_ok=True)
    bundled=ROOT/'private_assets'/'bundled_templates'
    if not bundled.is_dir():bundled=ROOT/'template'/'bundled'
    if ns.require_bundled and not (bundled/'manifest.json').is_file():raise ValueError('Bundled templates are required for this release')
    if bundled.is_dir():shutil.copytree(bundled,target/'template'/'bundled',dirs_exist_ok=True)
    # Sync notices after optional report tooling is installed; source originals
    # and example scan/report outputs remain outside both distribution archives.
    shutil.copytree(ROOT/"licenses",target/"licenses",dirs_exist_ok=True)
    # Historical QA screenshots and local paths do not belong in the runtime.
    # Publish the small current-release audit separately from local test data.
    audit=ROOT/'validation'/'release-checks.json'
    if audit.exists():shutil.copyfile(audit,target/'release-checks.json')
    # No .venv, samples, private_tools/private_assets, decode caches or personal originals.
    files=[]
    for directory in ["src","tests","docs","scripts","licenses","template"]:
        for file in (ROOT/directory).rglob("*"):
            if file.is_file() and file.name not in {"validate_asset_pack.py","analyze_999_scan.py"} and not any(x in file.parts for x in ["__pycache__",".pytest_cache","mutex_imatest.egg-info"]):files.append(file)
    files.extend(ROOT/name for name in ["README.md","LICENSE","THIRD_PARTY_NOTICES.md","pyproject.toml","requirements-lock.txt","MUTEX.spec",".gitignore",".gitattributes","启动 MUTEX Imatest.cmd"])
    with zipfile.ZipFile(ROOT/"dist"/f"MUTEX-Imatest-{VERSION}-source.zip","w",zipfile.ZIP_DEFLATED,compresslevel=ns.compresslevel) as z:
        for file in sorted(files):z.write(file,file.relative_to(ROOT))
        z.write(source,Path("third-party-source")/source.name,compress_type=zipfile.ZIP_STORED)
        if audit.exists():z.write(audit,'release-checks.json')
        if bundled.is_dir() and not bundled.is_relative_to(ROOT/'template'):
            for file in sorted(bundled.rglob('*')):
                if file.is_file():z.write(file,Path('template/bundled')/file.relative_to(bundled))
    with zipfile.ZipFile(ROOT/'dist'/f'MUTEX-Imatest-{VERSION}-templates.zip','w',zipfile.ZIP_DEFLATED,compresslevel=ns.compresslevel) as z:
        for file in sorted((target/'template').rglob('*')):
            if file.is_file():z.write(file,Path('template')/file.relative_to(target/'template'))
    if ns.zip:
        with zipfile.ZipFile(ROOT/"dist"/f"MUTEX-Imatest-{VERSION}-windows-x64.zip","w",zipfile.ZIP_DEFLATED,compresslevel=ns.compresslevel) as z:
            for file in sorted(target.rglob("*")):
                if file.is_file():z.write(file,Path("MUTEX Imatest")/file.relative_to(target),compress_type=zipfile.ZIP_STORED if file.suffix.lower()=='.zip' else zipfile.ZIP_DEFLATED)
    records={}
    for file in (ROOT/"dist").glob(f"MUTEX-Imatest-{VERSION}-*.zip"):records[file.name]={"bytes":file.stat().st_size,"sha256":hashlib.sha256(file.read_bytes()).hexdigest()}
    records["portable"]={"file_count":sum(p.is_file() for p in target.rglob("*")),"bytes":sum(p.stat().st_size for p in target.rglob("*") if p.is_file()),
                         "exe_sha256":hashlib.sha256((target/"MUTEX Imatest.exe").read_bytes()).hexdigest()}
    (ROOT/"dist"/"release-manifest.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
    (ROOT/'dist'/'SHA256SUMS.txt').write_text(''.join(f"{value['sha256']}  {name}\n" for name,value in records.items() if name!='portable'),encoding='utf-8')
    print(json.dumps(records,indent=2))
if __name__=="__main__":main()

