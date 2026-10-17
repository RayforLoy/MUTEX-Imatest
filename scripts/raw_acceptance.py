"""Download selected CC0 RAW regression files and validate decoding/precision.
Network is used only by this developer script, never by the desktop application."""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,os,re,subprocess,sys,time,urllib.request,uuid
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
TARGETS=[(3480,"Sony A7R IV", ".ARW"),(3481,"Sony A7R IV uncompressed",".ARW"),
         (6617,"Nikon Z8 lossless",".NEF"),(3773,"Fujifilm GFX100 16-bit lossless",".RAF"),
         (983,"Canon 5D Mark IV",".CR2"),(4694,"Canon R5",".CR3"),(4698,"Canon R5 C-RAW",".CR3")]
def download(row,directory):
    html=row[7];url=re.search(r"href='([^']+)'",html)[1]
    file_id=int(re.search(r"getfile.php/(\d+)/",url)[1])
    target=next((t for t in TARGETS if t[0]==file_id),None)
    if not target:return None
    if "publicdomain/zero" not in row[5]:raise ValueError("Selected fixture is not CC0")
    expected=re.search(r"Checksum'>([a-f0-9]{64})",html)[1]
    path=directory/(str(file_id)+target[2])
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        encoded=quote(url,safe=":/")
        temp=path.with_suffix(path.suffix+".partial")
        with urllib.request.urlopen(encoded,timeout=90) as response,open(temp,"wb") as out:
            while block:=response.read(4*2**20):out.write(block)
        if hashlib.sha256(temp.read_bytes()).hexdigest()!=expected:raise ValueError(f"Checksum mismatch {file_id}")
        os.replace(temp,path)
    record={"id":file_id,"device":target[1],"path":str(path),"mode":row[2],"remark":row[4],
            "source":url,"sha256":expected,"license":"CC0-1.0","file_bytes":path.stat().st_size}
    print("Fixture downloaded:",target[1],flush=True);return record
def case(path,out,cache=None):
    from mutex_imatest.imaging import ImageSource
    from mutex_imatest.config import AnalysisConfig
    import numpy as np
    from PIL import Image
    start=time.perf_counter()
    config=AnalysisConfig(transfer="linear",memory_mb=8192,cache_dir=cache or str(ROOT/"validation"/"raw-cache"))
    with ImageSource(path,config,progress=lambda n,s:print(n,s,flush=True)) as source:
        m=source.metadata
        preview=source.preview(1600);Image.fromarray(preview).save(Path(out).with_suffix(".png"))
        roi=source.read_roi((m.width//2-128,m.height//2-128,256,256))
        assert roi.dtype==np.uint16 and roi.shape==(256,256,3)
        assert source.raw_cfa_path and Path(source.raw_cfa_path).is_file()
        cfa=np.load(source.raw_cfa_path,mmap_mode="r")
        assert cfa.dtype==np.uint16 and cfa.ndim==2
        from dataclasses import asdict
        data={"status":"passed","metadata":asdict(m),"cfa_shape":list(cfa.shape),"roi_dtype":str(roi.dtype),
              "elapsed_seconds":time.perf_counter()-start,"raw_info":source.raw_info,
              "scope":"File decoding, native uint16 ROI and CFA retention; does not validate chart measurement on this camera"}
        Path(out).write_text(json.dumps(data,indent=2),encoding="utf-8")
def main():
    p=argparse.ArgumentParser();p.add_argument("--case");p.add_argument("--out");p.add_argument("--limit",type=int,default=0);p.add_argument("--cache");p.add_argument("--cold",action="store_true");ns=p.parse_args()
    if ns.case:case(ns.case,ns.out,ns.cache);return 0
    cache=ROOT/"validation"/("raw-cold-"+uuid.uuid4().hex if ns.cold else "raw-cache")
    folder=ROOT/"samples"/"private"/"raw-regression";folder.mkdir(parents=True,exist_ok=True)
    catalog=ROOT/"validation"/"raw-catalogue.json"
    if not catalog.exists():
        catalog.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve("https://raw.pixls.us/json/getrepository.php?set=all",catalog)
    rows=json.loads(catalog.read_text(encoding="utf-8"))["data"]
    ids={t[0] for t in TARGETS[:ns.limit or None]}
    selected=[row for row in rows if any(f"getfile.php/{i}/" in row[7] for i in ids)]
    with ThreadPoolExecutor(max_workers=3) as pool:records=list(pool.map(lambda row:download(row,folder),selected))
    records=[r for r in records if r]
    import psutil
    results=[]
    for record in records:
        out=ROOT/"validation"/f"raw-{record['id']}.json"
        log=out.with_suffix(".log")
        with open(log,"w",encoding="utf-8") as log_file:
            proc=subprocess.Popen([sys.executable,__file__,"--case",record["path"],"--out",str(out),"--cache",str(cache)],stdout=log_file,stderr=subprocess.STDOUT,cwd=ROOT)
            monitored=psutil.Process(proc.pid);peak=0;private_peak=0
            start=time.monotonic()
            while proc.poll() is None:
                try:
                    infos=[p.memory_info() for p in [monitored,*monitored.children(recursive=True)]]
                    peak=max(peak,sum(i.rss for i in infos))
                    private_peak=max(private_peak,sum(getattr(i,"private",i.vms) for i in infos))
                except psutil.Error:pass
                if time.monotonic()-start>600:proc.terminate();break
                time.sleep(.1)
            code=proc.wait()
        data=json.loads(out.read_text(encoding="utf-8")) if code==0 and out.exists() else {"status":"failed","log":str(log)}
        data.update(fixture=record,peak_rss_bytes=peak,peak_private_bytes=private_peak,exit_code=code,cache_mode="cold" if ns.cold else "warm");results.append(data)
        print(record["device"],data["status"],f"peak {peak/2**20:.0f} MiB",flush=True)
    target=ROOT/"validation"/("raw-acceptance-cold.json" if ns.cold else "raw-acceptance.json")
    target.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if all(r["status"]=="passed" for r in results) else 1
if __name__=="__main__":raise SystemExit(main())

