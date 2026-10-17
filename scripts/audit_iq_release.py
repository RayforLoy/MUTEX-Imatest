"""Cross-check the actual portable release against its source and test records."""
from pathlib import Path
import datetime
import hashlib
import json
import tomllib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def main():
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    build = read('validation/iq-build/verification.json')
    assert build['returncode'] == 0 and build['stable_sources'] and build['version'] == version
    changed = [name for name, sha in build['source_sha256'].items() if digest(ROOT / name) != sha]
    assert not changed, f'Sources changed since build: {changed}'
    target = ROOT / 'dist/MUTEX Imatest'
    assert digest(target / 'MUTEX Imatest.exe') == build['exe_sha256']
    tests = ET.parse(ROOT / 'validation/iq-v0.7-pytest.xml').getroot().find('testsuite')
    assert tests is not None and int(tests.get('tests', 0)) >= 310
    assert sum(int(tests.get(field, 0)) for field in ['errors', 'failures', 'skipped']) == 0
    desktop = read('validation/packaged-selftest-final/selftest.json')
    assert desktop['passed'] and not desktop['errors']
    assert desktop['environment']['application'] == f'MUTEX Imatest {version}'
    for key in ['encrypted_template', 'iq_workbench', 'measurement_evaluation']:
        assert desktop[key]['passed'], key
    assert desktop['measurement_evaluation']['small_goal_preserved'] == 1e-7
    log = (ROOT / 'validation/iq-final-selftest.log').read_text(encoding='utf-8-sig', errors='replace')
    assert not any(error in log for error in ['Traceback', 'Queue is closed', 'Error calling Python override'])
    packaged = read('validation/iq-packaged/verification.json')
    assert packaged['all_passed'] and len(packaged['checks']) == 11 and packaged['version'] == version
    assert digest(target / 'MUTEX-CLI.exe') == packaged['exe_sha256']
    official = read('validation/imatest-compatibility/verification.json')
    assert len(official['cases']) == 8 and all(case['status'] == 'pass' for case in official['cases'])
    report = {
        'version': version,
        'verified_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'all_passed': True,
        'pytest': {'passed': int(tests.get('tests')), 'seconds': float(tests.get('time'))},
        'stable_source_build': True,
        'portable_gui_sha256': build['exe_sha256'],
        'portable_cli_sha256': packaged['exe_sha256'],
        'packaged_cli_checks': len(packaged['checks']),
        'packaged_gui_selftest': True,
        'official_samples_passed': len(official['cases']),
        'official_sample_revision': official['commit'],
        'ptc_known_gain': packaged['expected_gain_dn_per_e'],
        'ptc_measured_gain': packaged['ptc_gain_dn_per_e'],
        'coverage_regressions': 'Failed USAF units remain in all three direction views for resolution_limit and ctf50.',
        'scope': 'Engineering implementation and sample operability; no claim of full commercial or standards equivalence.',
    }
    (ROOT / 'validation/iq-release-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
