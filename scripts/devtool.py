from __future__ import annotations
import argparse, json, pathlib, subprocess, sys, compileall
ROOT = pathlib.Path(__file__).resolve().parents[1]
def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['write','test','compile','run','build','demo','benchmark','licenses'])
    p.add_argument('args', nargs='*')
    ns = p.parse_args()
    if ns.action == 'write':
        sys.stdin.reconfigure(encoding='utf-8')
        payload = json.load(sys.stdin)
        for relative, content in payload.items():
            target = (ROOT / relative).resolve()
            if not target.is_relative_to(ROOT):
                raise ValueError('File outside project: ' + relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8', newline='\n')
        print('Wrote', len(payload), 'project files')
        return 0
    if ns.action == 'compile':
        return 0 if compileall.compile_dir(str(ROOT/'src'), quiet=1) else 1
    if ns.action == 'test':
        return subprocess.call([sys.executable,'-m','pytest',*ns.args], cwd=ROOT)
    if ns.action == 'build':
        return subprocess.call([sys.executable,'-m','PyInstaller','--noconfirm','MUTEX.spec'], cwd=ROOT)
    if ns.action in ['demo','benchmark','licenses']:
        return subprocess.call([sys.executable,str(ROOT/'scripts'/('make_demo.py' if ns.action=='demo' else ns.action+'.py')),*ns.args], cwd=ROOT)
    if ns.action == 'run':
        return subprocess.call([sys.executable,'-m','mutex_imatest',*ns.args], cwd=ROOT)
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
