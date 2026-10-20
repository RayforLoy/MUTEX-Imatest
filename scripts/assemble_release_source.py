"""Assemble one current Git snapshot with the draft's unchanged raster assets."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    repo, rid, tag = [os.environ[k] for k in ['GH_REPO', 'RELEASE_ID', 'RELEASE_TAG']]
    expected = os.environ['BASE_SOURCE_SHA256']
    assert rid.isdigit() and re.fullmatch(r'v\d+\.\d+\.\d+', tag)
    assert re.fullmatch(r'[a-f0-9]{64}', expected)

    def api(path, *args):
        return json.loads(subprocess.check_output(['gh', 'api', path, *args]))

    endpoint = f'repos/{repo}/releases/{rid}'
    release = api(endpoint)
    assert release['draft'] and release['tag_name'] == tag
    name = f'MUTEX-Imatest-{tag[1:]}-source.zip'
    old = next(a for a in release['assets'] if a['name'] == name)
    assert old['digest'] == 'sha256:' + expected
    work = ROOT / 'validation/source-assembly'
    work.mkdir(parents=True)
    base = work / 'base.zip'
    with base.open('wb') as stream:
        subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream',
                        f"repos/{repo}/releases/assets/{old['id']}"], stdout=stream, check=True)
    assert hashlib.sha256(base.read_bytes()).hexdigest() == expected
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    files = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
    files = [n for n in files if n and (ROOT / n).is_file()]
    assert not any(p in {'example', 'output', 'private_tools', 'private_assets', 'samples', '.env'}
                   for n in files for p in Path(n).parts)
    target = work / name
    with zipfile.ZipFile(base) as source:
        before = source.read('src/mutex_imatest/imaging.py').decode().replace('\r\n', '\n')
        assert before == (ROOT / 'src/mutex_imatest/imaging.py').read_text().replace('\r\n', '\n')
        audit = json.loads(source.read('release-checks.json'))
        audit['source_commit'] = commit
        audit['source_snapshot']['sha256'] = {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'src').rglob('*.py'))}
        assert audit['version'] == tag[1:]
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for n in sorted(files):
                output.write(ROOT / n, n)
            for n in source.namelist():
                if n.startswith(('template/bundled/', 'third-party-source/')) and not n.endswith('/'):
                    assert '..' not in Path(n).parts
                    output.writestr(n, source.read(n), compress_type=zipfile.ZIP_STORED if n.endswith(('.zip', '.gz')) else zipfile.ZIP_DEFLATED)
            output.writestr('release-checks.json', json.dumps(audit, indent=2))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with zipfile.ZipFile(target) as check:
        assert check.testzip() is None and sum(n.endswith('.mxasset') for n in check.namelist()) == 3
    url = release['upload_url'].split('{')[0]
    assert urllib.parse.urlparse(url).netloc == 'uploads.github.com'
    temporary_name = name + '.next'
    pending = next((a for a in release['assets'] if a['name'] == temporary_name), None)
    if pending:
        subprocess.run(['gh', 'api', '--method', 'DELETE', f"repos/{repo}/releases/assets/{pending['id']}"], check=True)
    request = urllib.request.Request(url + '?name=' + urllib.parse.quote(temporary_name), data=target.read_bytes(), method='POST',
                                    headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Content-Type': 'application/zip'})
    with urllib.request.urlopen(request, timeout=900) as response:
        uploaded = json.load(response)
    assert uploaded['digest'] == 'sha256:' + digest
    current = api(endpoint)
    assert current['draft'] and current['tag_name'] == tag
    assert next(a for a in current['assets'] if a['name'] == name)['id'] == old['id']
    subprocess.run(['gh', 'api', '--method', 'DELETE', f"repos/{repo}/releases/assets/{old['id']}"], check=True)
    payload = work / 'rename.json'
    payload.write_text(json.dumps({'name': name}))
    final = api(f"repos/{repo}/releases/assets/{uploaded['id']}", '--method', 'PATCH', '--input', str(payload))
    assert final['name'] == name and final['digest'] == 'sha256:' + digest
    print(json.dumps({'commit': commit, 'source_sha256': digest, 'source_bytes': target.stat().st_size,
                      'asset_id': final['id'], 'release_id': int(rid), 'tag': tag}, indent=2))


if __name__ == '__main__':
    main()
