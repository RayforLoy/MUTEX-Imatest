"""Build both Mac architectures against the same hash-pinned LibRaw source."""
from pathlib import Path
import hashlib
import json
import os
import platform
import importlib.metadata as metadata
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'LibRaw-0.22.2.tar.gz': ('https://www.libraw.org/data/LibRaw-0.22.2.tar.gz',
                           'de86b035655accff8d4010f1a221fdf50d353cb7b1422ba26f14a0db92612cfa'),
    'rawpy-0.27.1.tar.gz': ('https://files.pythonhosted.org/packages/f3/ae/c1c7816ed3f3cbf7ca284a37371243500f4eb39b6a32f7368b585c4ef5c4/rawpy-0.27.1.tar.gz',
                          '3194d64ff690ac945e1a43237edae8a18f1f493751924de1ae2bcef473c0fb79'),
}


def main():
    if sys.platform != 'darwin':
        raise SystemExit('This script requires a native macOS build host')
    cache = ROOT / '.cache/macos-build'
    cache.mkdir(parents=True, exist_ok=True)
    supplied = ROOT / 'third-party-source'
    supplied.mkdir(exist_ok=True)
    for name, (url, digest) in SOURCES.items():
        archive = supplied / name
        if not archive.exists():
            urllib.request.urlretrieve(url, archive)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest, name
    libraw = cache / 'LibRaw-0.22.2'
    if not libraw.exists():
        with tarfile.open(supplied / 'LibRaw-0.22.2.tar.gz') as archive:
            archive.extractall(cache, filter='data')
    subprocess.run(['brew', 'install', 'jpeg-turbo', 'little-cms2', 'pkgconf', 'openssl@3'], check=True)
    prefixes = [Path(subprocess.check_output(['brew', '--prefix', package], text=True).strip())
                for package in ['jpeg-turbo', 'little-cms2']]
    native = (cache / 'native').resolve()
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='15.0', RAWPY_USE_SYSTEM_LIBRAW='1')
    env['OPENSSL_DIR'] = subprocess.check_output(['brew', '--prefix', 'openssl@3'], text=True).strip()
    env['OPENSSL_STATIC'] = '1'
    env['PKG_CONFIG_PATH'] = os.pathsep.join(str(p / 'lib/pkgconfig') for p in [native, *prefixes])
    env['CPPFLAGS'] = ' '.join('-I' + str(p / 'include') for p in [native, *prefixes])
    env['LDFLAGS'] = ' '.join('-L' + str(p / 'lib') for p in [native, *prefixes])
    env['CFLAGS'] = env['CXXFLAGS'] = '-O2 -mmacosx-version-min=15.0'
    subprocess.run(['./configure', '--prefix=' + str(native), '--disable-examples',
                    '--disable-openmp', '--disable-static', '--enable-shared'], cwd=libraw, env=env, check=True)
    subprocess.run(['make', '-j3'], cwd=libraw, env=env, check=True)
    subprocess.run(['make', 'install'], cwd=libraw, env=env, check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements-macos-build.txt'],
                   cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-build-isolation', '--no-deps',
                    str(supplied / 'rawpy-0.27.1.tar.gz')], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install',
                    '-r', 'requirements-macos.txt'], cwd=ROOT, env=env, check=True)
    import rawpy
    assert tuple(rawpy.libraw_version) == (0, 22, 2), rawpy.libraw_version
    # Native wheels/source builds have platform-specific notices. Keep them
    # without changing the common dependency lock or the existing inventory.
    notices = ROOT / 'licenses/macos-runtime'
    notices.mkdir(parents=True, exist_ok=True)
    inventory = []
    for dist in metadata.distributions():
        name = dist.metadata.get('Name', 'unknown')
        copied = []
        for entry in dist.files or []:
            if Path(entry).name.lower().startswith(('license', 'copying', 'copyright', 'notice')):
                source = Path(dist.locate_file(entry))
                if source.is_file() and source.stat().st_size < 2 * 2**20:
                    target = notices / name / str(entry).replace('/', '_')
                    target.parent.mkdir(exist_ok=True)
                    shutil.copyfile(source, target)
                    copied.append(str(target.relative_to(ROOT)))
        inventory.append({'name': name, 'version': dist.version, 'license_files': copied})
    for prefix in [*prefixes, Path(env['OPENSSL_DIR'])]:
        for source in prefix.rglob('*'):
            if source.is_file() and source.name.lower().startswith(('license', 'copying', 'copyright', 'notice')) and source.stat().st_size < 2 * 2**20:
                target = notices / 'native' / (prefix.name + '_' + str(source.relative_to(prefix)).replace('/', '_'))
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, target)
    (notices / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    record = {'architecture': platform.machine(), 'libraw': list(rawpy.libraw_version),
              'rawpy': rawpy.__version__, 'rawpy_flags': rawpy.flags,
              'sources': {n: {'url': u, 'sha256': h} for n, (u, h) in SOURCES.items()},
              'deployment_target': '15.0', 'rawpy_built_from_source': True}
    target = ROOT / 'validation/macos-native.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
