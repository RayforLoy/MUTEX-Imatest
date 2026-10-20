"""Create a Mac ZIP preserving app signatures, frameworks and executable bits."""
from pathlib import Path
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Package on the target Mac architecture')
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    arch = platform.machine()
    assert arch in {'arm64', 'x86_64'}
    app = ROOT / 'dist/MUTEX Imatest.app'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    stage = ROOT / 'dist' / ('MUTEX Imatest macOS ' + arch)
    stage.mkdir()
    shutil.copytree(app, stage / app.name, symlinks=True)
    for directory in ['template', 'docs', 'licenses']:
        shutil.copytree(ROOT / directory, stage / directory, symlinks=True)
    (stage / 'third-party-source').mkdir()
    for name in ['LibRaw-0.22.2.tar.gz', 'rawpy-0.27.1.tar.gz']:
        shutil.copyfile(ROOT / 'third-party-source' / name, stage / 'third-party-source' / name)
    bundled = ROOT / 'private_assets/bundled_templates'
    if bundled.is_dir():
        shutil.copytree(bundled, stage / 'template/bundled', dirs_exist_ok=True)
    for name in ['README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md']:
        shutil.copyfile(ROOT / name, stage / name)
    archive = ROOT / 'dist' / f'MUTEX-Imatest-{version}-macos-{arch}.zip'
    assert not archive.exists()
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(stage), str(archive)], check=True)
    metadata = {'version': version, 'architecture': arch, 'file': archive.name,
                'bytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'signing': 'ad-hoc', 'apple_notarized': False, 'minimum_macos': '15.0'}
    (ROOT / 'validation/macos-package.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    main()
