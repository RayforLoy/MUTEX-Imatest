"""Build while recording the exact source revision in an uncommitted workspace.

A build that overlaps source edits exits with code 2 and must be repeated.
It never terminates another chat, an editor, or a running application.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[1]


def checksums():
    files=list((ROOT/'src').rglob('*.py'))+list((ROOT/'docs').rglob('*.md'))
    files += [ROOT/name for name in ['README.md','pyproject.toml','MUTEX.spec','scripts/entry.py']]
    return {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files) if path.is_file()}


def main():
    folder=ROOT/'validation/iq-build';folder.mkdir(parents=True,exist_ok=True)
    before=checksums()
    print('Building portable application; full output: validation/iq-build/pyinstaller.log',flush=True)
    with (folder/'pyinstaller.log').open('w',encoding='utf-8') as log:
        completed=subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','MUTEX.spec'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    after=checksums()
    changes=sorted(key for key in before.keys()|after.keys() if before.get(key)!=after.get(key))
    exe=ROOT/'dist/MUTEX Imatest/MUTEX Imatest.exe'
    report={'version':tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
            'returncode':completed.returncode,'stable_sources':not changes,'changed_during_build':changes,
            'source_sha256':after,'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest() if exe.exists() else None}
    (folder/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},indent=2))
    return completed.returncode or (2 if changes else 0)


if __name__=='__main__':raise SystemExit(main())
