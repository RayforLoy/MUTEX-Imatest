"""Run the ZIP's actual Mac GUI/CLI, all templates, codecs and public RAWs."""
from pathlib import Path
import hashlib
import json
import os
import platform
import plistlib
import subprocess
import sys
import tomllib
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'darwin':
        raise SystemExit('Verify with a native Mac runner')
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    arch = platform.machine()
    package = json.loads((ROOT / 'validation/macos-package.json').read_text())
    archive = ROOT / 'dist' / package['file']
    assert package['sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    qa = ROOT / 'validation/macos-final'
    qa.mkdir(parents=True)
    extract = qa / 'extracted'
    subprocess.run(['ditto', '-x', '-k', str(archive), str(extract)], check=True)
    app = extract / ('MUTEX Imatest macOS ' + arch) / 'MUTEX Imatest.app'
    gui, cli = [app / 'Contents/MacOS' / name for name in ['MUTEX Imatest', 'MUTEX-CLI']]
    assert gui.is_file() and cli.is_file() and os.access(gui, os.X_OK) and os.access(cli, os.X_OK)
    assert arch in subprocess.check_output(['lipo', '-archs', str(gui)], text=True).split()
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    with (app / 'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['CFBundleShortVersionString'] == version and info['LSMinimumSystemVersion'] == '15.0'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1')

    def run(args, name, executable=cli, native_window=False, timeout=600):
        current = env.copy()
        if native_window:
            current['QT_QPA_PLATFORM'] = 'cocoa'
        with (qa / (name + '.log')).open('w') as stream:
            completed = subprocess.run([str(executable), *map(str, args)], cwd=qa, env=current,
                                       stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        assert completed.returncode == 0, (name, completed.returncode)

    runtime = json.loads(subprocess.check_output([str(cli), 'info'], env=env, text=True))
    assert runtime['application'] == 'MUTEX Imatest ' + version and runtime['libraw'] == '0.22.2'
    assert runtime['libvips']
    print('ZIP extracted: native GUI, ten templates and reports.', flush=True)
    run(['selftest', '--out', qa / 'selftest', '--visible'], 'native-gui', gui, native_window=True)
    selftest = json.loads((qa / 'selftest/selftest.json').read_text())
    assert selftest['passed'] and selftest['presentation']['passed'] and selftest['encrypted_template']['passed']
    assert selftest['templates']['total'] == 10
    bundled = {c['name']: c for c in selftest['templates']['bundled']}
    assert bundled['调焦卡_120x1']['regions'] == 4080 and bundled['调焦卡_135x1']['regions'] == 19320
    assert len(bundled) == 3 and all(c['source_absent'] and c['preview_exists'] for c in bundled.values())
    report = qa / 'selftest/report'
    assert (report / 'report.pdf').read_bytes().startswith(b'%PDF-')
    assert (report / 'report.html').stat().st_size > 10000
    print('ZIP extracted: uint16 TIFF compression, planar channels and video.', flush=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/verify_slim_runtime.py'), '--exe', str(cli)],
                   cwd=ROOT, env=env, check=True)
    codecs = json.loads((ROOT / 'validation/slim-runtime/verification.json').read_text())
    raw_checks = []
    fixtures = json.loads((ROOT / 'tests/data/macos-raw-fixtures.json').read_text())
    raw_chart = qa / 'raw-chart.json'
    raw_chart.write_text(json.dumps({'id': 'mac-raw-test', 'name': 'Native RAW ROI', 'regions': [
        {'id': 'patch', 'kind': 'flat', 'box': [.48, .48, .015, .015]}]}))
    config = qa / 'raw-config.json'
    config.write_text(json.dumps({'transfer': 'linear', 'channels': 'G', 'memory_mb': 4096,
                                  'cache_dir': str(qa / 'raw-cache')}))
    import numpy as np
    for fixture in fixtures:
        print('ZIP extracted: public RAW', fixture['device'], flush=True)
        path = qa / fixture['filename']
        urllib.request.urlretrieve(fixture['url'], path)
        assert fixture['license'] == 'CC0-1.0'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == fixture['sha256']
        out = qa / ('raw-' + path.stem)
        run(['analyze', path, '--chart', raw_chart, '--config', config, '--out', out], 'raw-' + path.stem)
        result = json.loads((out / path.stem / 'result.json').read_text())
        assert result['app_version'] == version and result['image']['is_raw'] and result['image']['dtype'] == 'uint16'
        assert result['image']['channels'] == 3 and result['measurements'][0]['values'].get('mean') is not None
        raw_checks.append({'file': path.name, 'device': fixture['device'], 'sha256': fixture['sha256'],
                           'passed': True, 'native_uint16': True, 'license': 'CC0-1.0'})
    cfa_files = list((qa / 'raw-cache').rglob('cfa.npy'))
    assert len(cfa_files) == len(fixtures)
    assert all(np.load(p, mmap_mode='r').dtype == np.uint16 and np.load(p, mmap_mode='r').ndim == 2 for p in cfa_files)
    tests = ET.parse(ROOT / 'validation/pytest.xml').getroot().find('testsuite')
    assert all(tests.get(k) == '0' for k in ['failures', 'errors', 'skipped'])
    audit = {'passed': True, 'version': version, 'architecture': arch,
             'source_commit': json.loads((ROOT / 'release-checks.json').read_text())['source_commit'],
             'archive': package, 'runtime': runtime, 'pytest': int(tests.get('tests')),
             'gui_native_cocoa': True, 'gui_presentation': selftest['presentation'],
             'encrypted_template': True, 'templates': selftest['templates'], 'html_pdf': True,
             'codecs': codecs, 'public_raw_checks': raw_checks,
             'raw_scope': 'Sony A7R IV compressed and Canon 5D IV CC0 files checked on this architecture; other camera modes retain their separate acceptance scope.',
             'native_build': json.loads((ROOT / 'validation/macos-native.json').read_text()),
             'codesign_verified_after_zip': True, 'apple_notarized': False}
    (ROOT / 'dist' / f'macos-{arch}-checks.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Native app ZIP, GUI, CLI, all ten templates, reports and public RAW checks passed.', flush=True)


if __name__ == '__main__':
    main()
