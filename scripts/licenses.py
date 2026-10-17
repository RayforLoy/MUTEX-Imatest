from pathlib import Path
import importlib.metadata as metadata
import json,shutil,subprocess,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/"licenses";out.mkdir(exist_ok=True)
license_path=ROOT/"LICENSE"
if not license_path.exists():
    urllib.request.urlretrieve("https://www.gnu.org/licenses/gpl-3.0.txt",license_path)
entries=[]
for dist in sorted(metadata.distributions(),key=lambda d:d.metadata.get("Name","").lower()):
    name=dist.metadata.get("Name","unknown");folder=out/name;folder.mkdir(exist_ok=True)
    copied=[]
    for file in dist.files or []:
        lower=str(file).lower();base=Path(file).name.lower()
        if base.startswith(("license","copying","notice","copyright","authors")) and (".dist-info" in lower or "pyside6" in lower):
            source=Path(dist.locate_file(file))
            if source.is_file():
                target=folder/str(file).replace("/","_").replace("\\","_")
                shutil.copyfile(source,target);copied.append(str(target.relative_to(ROOT)))
    expression=dist.metadata.get("License-Expression") or dist.metadata.get("License") or "See bundled license files and upstream"
    entries.append({"name":name,"version":dist.version,"license":expression,
                    "project_urls":dist.metadata.get_all("Project-URL") or [],
                    "license_files":copied})
vendor=ROOT/"vendor"/"libraw-0.22.2"/"official"/"LibRaw-0.22.2"
rawout=out/"LibRaw-0.22.2";rawout.mkdir(exist_ok=True)
for name in ["LICENSE.LGPL","LICENSE.CDDL","COPYRIGHT","Changelog.txt"]:
    if (vendor/name).exists():shutil.copyfile(vendor/name,rawout/name)
(out/"inventory.json").write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding="utf-8")
freeze=subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True)
(ROOT/"requirements-lock.txt").write_text("\n".join('-e .' if l.startswith('-e ') else l for l in freeze.splitlines() if "mutex-imatest" not in l)+"\n",encoding="utf-8")
print("Collected notices for",len(entries),"installed distributions")

