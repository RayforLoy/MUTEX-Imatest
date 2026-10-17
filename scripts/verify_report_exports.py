"""Verify current product HTML/PDF exports and their input/data provenance.

Historical sample-specific research outputs retain their original algorithm
hashes and are not evidence for the current executable.
"""
from __future__ import annotations
import base64
import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReportParser(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.images, self.downloads, self.external_resources = [], [], []
        self.rows = 0
        self.curves = 0
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img":
            self.images.append(attrs.get("src", ""))
        if tag == "a" and "download" in attrs:
            self.downloads.append(attrs.get("href", ""))
        if tag in {"img", "script", "iframe", "link"}:
            src = attrs.get("src", attrs.get("href", ""))
            if src and not src.startswith("data:"):
                self.external_resources.append(src)
        if tag == "tr" and "data-valid" in attrs:
            self.rows += 1
        if tag == 'svg' and attrs.get('data-curve'):
            self.curves += 1


def main():
    folder = ROOT/"validation"/"report-export"
    folder.mkdir(parents=True, exist_ok=True)
    native_folder = ROOT/"validation"/"packaged-selftest-final"/"report"
    result = json.loads((native_folder/"result.json").read_text(encoding="utf-8"))
    exe = ROOT/"dist"/"MUTEX Imatest"/"MUTEX-CLI.exe"
    chart = folder/"chart.json"
    chart.write_text(json.dumps(result["template"], ensure_ascii=False), encoding="utf-8")
    checks = {}
    for format in ["html", "pdf"]:
        out = folder/("cli-"+format)
        command = [str(exe), "analyze", result["image"]["path"], "--chart", str(chart),
                   "--out", str(out), "--transfer", "linear", "--channels", "RGB",
                   "--report", "--report-format", format]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                   timeout=120, check=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        exported = out/Path(result["image"]["path"]).stem
        assert (exported/f"report.{format}").is_file()
        other = "pdf" if format == "html" else "html"
        assert not (exported/f"report.{other}").exists()
        assert all((exported/name).is_file() for name in ["result.json", "heatmap.png", "measurements.csv"])
        checks["cli_"+format] = {"passed": True, "stdout": completed.stdout.strip()}
    native = ReportParser((native_folder/("detail-report.html" if result.get('analysis_summary') else "report.html")).read_text(encoding="utf-8"))
    assert len(native.images) == 1 and not native.external_resources
    assert base64.b64decode(native.images[0].split(",", 1)[1]) == (native_folder/"heatmap.png").read_bytes()
    assert native.rows == len(result["measurements"])
    checks["packaged_both"] = {"passed": (native_folder/"report.pdf").is_file(),
                                "html_measurement_rows": native.rows, "external_resources": native.external_resources}
    assert native.curves > 0
    assert hashlib.sha256(Path(result['image']['path']).read_bytes()).hexdigest()==result['image']['fingerprint']
    with (native_folder/'measurements.csv').open(encoding='utf-8-sig',newline='') as file:
        exported_rows=list(csv.DictReader(file))
    assert len(exported_rows)==sum(len(m['values']) for m in result['measurements'])
    expected={(m['region_id'],m['channel'],key) for m in result['measurements'] for key in m['values']}
    assert {(row['region'],row['channel'],row['metric']) for row in exported_rows}=={
        (m['label'],m['channel'],key) for m in result['measurements'] for key in m['values']}
    assert len(expected)>0
    desktop=json.loads((native_folder.parent/'selftest.json').read_text(encoding='utf-8'))
    assert desktop['passed'] and desktop['environment']['application']=='MUTEX Imatest '+result['app_version']
    checks['current_product_data']={'passed':True,'app_version':result['app_version'],
        'input_fingerprint_verified':True,'csv_metric_rows':len(exported_rows),
        'native_inline_curve_plots':native.curves,'csv_keys_match_result':True,
        'historical_sample_research':'Archived separately; not used to validate this executable'}
    record = {"passed": all(v["passed"] for v in checks.values()), "generated_at": datetime.now().astimezone().isoformat(),
              "portable_cli_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "checks": checks}
    (folder/"verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
