from pathlib import Path
import argparse,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from mutex_imatest.demo import generate_demo,build_builtin_assets
p=argparse.ArgumentParser()
p.add_argument("--out",default=str(ROOT/"samples"/"demo"))
p.add_argument("--assets",action="store_true")
p.add_argument("--single",action="store_true")
ns=p.parse_args()
if ns.assets:build_builtin_assets(ROOT/"src"/"mutex_imatest"/"assets")
chart,paths=generate_demo(ns.out,not ns.single)
print(f"Generated {len(paths)} 48-bit TIFF files in {ns.out}")
