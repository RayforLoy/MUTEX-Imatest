from __future__ import annotations
from pathlib import Path
import argparse,json,math,subprocess,sys,time
import psutil,numpy as np,tifffile
from scipy.special import erf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"src"))
def fixture(size_mb,directory):
    from mutex_imatest.models import ChartDefinition,Region
    bytes_target=int(size_mb*2**20);width=int(math.sqrt(bytes_target/6/.75)//256)*256
    height=int(bytes_target/6/width//256)*256
    path=directory/f"uint16-{size_mb}MiB.tif"
    chart_path=path.with_suffix(".chart.json")
    regions=[]
    for iy in range(3):
        for ix in range(3):
            cx=int(width*(.1+.4*ix));cy=int(height*(.1+.4*iy))
            regions.append(Region(f"edge-{iy}-{ix}","edge",((cx-64)/width,(cy-100)/height,128/width,200/height),f"Edge {iy+1}-{ix+1}"))
    chart=ChartDefinition(f"benchmark-{size_mb}","Large TIFF benchmark",regions)
    if not path.exists():
        out=tifffile.memmap(path,shape=(height,width,3),dtype=np.uint16,photometric="rgb",metadata=None)
        for y in range(0,height,128):out[y:y+128]=np.uint16(32768)
        yy,xx=np.mgrid[:200,:128]
        d=(xx-63.5-.08749*(yy-99.5))/np.sqrt(1+.08749**2)
        edge=np.clip((.12+.7*(.5+.5*erf(d/(np.sqrt(2)*1.5))))*65535+.5,0,65535).astype(np.uint16)
        for r in regions:
            x,y,w,h=r.box;x=int(round(x*width));y=int(round(y*height));out[y:y+200,x:x+128]=edge[...,None]
        out.flush();del out
    from mutex_imatest.utils import atomic_json
    atomic_json(chart_path,chart.to_dict())
    return path,chart_path

def case(path,chart_path,out):
    from mutex_imatest.imaging import ImageSource
    from mutex_imatest.analysis.engine import analyze_source
    from mutex_imatest.templates import load_chart
    from mutex_imatest.config import AnalysisConfig
    from PIL import Image
    start=time.perf_counter();config=AnalysisConfig(transfer="linear",memory_mb=1024,cache_dir=str(ROOT/"validation"/"bench-cache"))
    with ImageSource(path,config) as source:
        decoded=source.metadata.width*source.metadata.height*source.metadata.channels*2
        t=time.perf_counter();preview=source.preview();preview_time=time.perf_counter()-t
        t=time.perf_counter();result=analyze_source(source,load_chart(chart_path),config);analysis_time=time.perf_counter()-t
        Image.fromarray(preview).save(Path(out).with_suffix(".preview.png"))
        result.save(Path(out).with_suffix(".result.json"))
        data={"file":str(path),"file_bytes":Path(path).stat().st_size,"decoded_bytes":decoded,
              "width":source.metadata.width,"height":source.metadata.height,"dtype":source.metadata.dtype,
              "decoder":source.metadata.decoder,"preview_seconds":preview_time,"analysis_seconds":analysis_time,
              "total_seconds":time.perf_counter()-start,"valid_regions":sum(m.valid for m in result.measurements),
              "mtf50_values":[m.metric("mtf50") for m in result.measurements],"memory_budget_mb":1024}
    Path(out).write_text(json.dumps(data,indent=2),encoding="utf-8")

def main():
    p=argparse.ArgumentParser();p.add_argument("--sizes",nargs="+",type=int,default=[100,300,800]);p.add_argument("--compressed",action="store_true")
    p.add_argument("--case");p.add_argument("--chart");p.add_argument("--out");ns=p.parse_args()
    if ns.case:case(ns.case,ns.chart,ns.out);return 0
    folder=ROOT/"samples"/"benchmarks";folder.mkdir(parents=True,exist_ok=True)
    validation=ROOT/"validation";validation.mkdir(exist_ok=True)
    fixtures=[fixture(size,folder) for size in ns.sizes]
    if ns.compressed:
        path,chart=fixtures[-1];compressed=path.with_name(path.stem+"-deflate.tif")
        if not compressed.exists():
            a=tifffile.memmap(path,mode="r")
            tifffile.imwrite(compressed,a,photometric="rgb",metadata=None,compression="deflate",tile=(256,256),maxworkers=2)
            del a
        fixtures.append((compressed,chart))
    results=[]
    for path,chart in fixtures:
        out=validation/(path.stem+".benchmark.json");log=out.with_suffix(".log")
        with open(log,"w",encoding="utf-8") as handle:
            proc=subprocess.Popen([sys.executable,__file__,"--case",str(path),"--chart",str(chart),"--out",str(out)],stdout=handle,stderr=subprocess.STDOUT,cwd=ROOT)
            monitor=psutil.Process(proc.pid);peak=0;private_peak=0
            while proc.poll() is None:
                try:
                    infos=[p.memory_info() for p in [monitor,*monitor.children(recursive=True)]]
                    peak=max(peak,sum(i.rss for i in infos))
                    private_peak=max(private_peak,sum(getattr(i,"private",i.vms) for i in infos))
                except psutil.Error:pass
                time.sleep(.05)
            code=proc.wait()
        data=json.loads(out.read_text(encoding="utf-8")) if code==0 else {"file":str(path),"error":log.read_text(encoding="utf-8")}
        data.update(peak_rss_bytes=peak,peak_private_bytes=private_peak,exit_code=code,memory_scope="venv launcher plus all child processes");results.append(data)
        print(path.name,"peak",round(peak/2**20),"MiB",data.get("total_seconds"),"seconds",flush=True)
    (validation/"large-image-benchmarks.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    return 0 if all(r["exit_code"]==0 for r in results) else 1
if __name__=="__main__":raise SystemExit(main())

