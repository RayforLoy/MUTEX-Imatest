"""Re-download the two unmodified, redistributable upstream SVG artworks.

This is a maintainer utility, not part of the program's startup. Each expected
hash is pinned by template/manifest.json once the reviewed library is generated.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ("commons-siemens", "Siemens_star.svg", "https://commons.wikimedia.org/wiki/File:Siemens_star.svg", "Leonhard Wimmer", "2006-09-05"),
    ("commons-usaf", "USAF-1951.svg", "https://commons.wikimedia.org/wiki/File:USAF-1951.svg", "Setreset; 2022 typography edit by Mikhail Ryazanov", "2022-07-23"),
]

def fetch(url):
    req = Request(url, headers={"User-Agent": "MUTEX-Imatest-public-template-maintainer/0.4 (offline open chart library)"})
    with urlopen(req, timeout=45) as response:
        return response.read()

def main():
    manifest_path = ROOT / "template" / "manifest.json"
    expected = {}
    if manifest_path.exists():
        expected = {a["path"]: a["sha256"] for a in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]}
    records = []
    for chart_id, filename, page, author, revision in SOURCES:
        digest = hashlib.md5(filename.encode()).hexdigest()
        url = f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{filename}"
        data = fetch(url)
        relative = f"upstream/{chart_id}/{filename}"
        actual = hashlib.sha256(data).hexdigest()
        if relative in expected and actual != expected[relative]:
            raise ValueError(f"Upstream changed: {url}; review new content/license before updating the library")
        target = ROOT / "template" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append({"id": chart_id, "path": relative, "url": url, "source_page": page,
                        "author": author, "file_revision": revision, "license": "CC-BY-SA-3.0", "sha256": actual})
    for name, url in [("CC-BY-SA-3.0.txt", "https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt"),
                      ("CC0-1.0.txt", "https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt")]:
        data = fetch(url)
        relative = "licenses/" + name
        if relative in expected and hashlib.sha256(data).hexdigest() != expected[relative]:
            raise ValueError(f"License text changed: {url}; review before replacing")
        target = ROOT / "template" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    destination = ROOT / "template" / "upstream-sources.json"
    destination.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(records, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
