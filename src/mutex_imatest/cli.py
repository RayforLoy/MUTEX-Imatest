from __future__ import annotations
from pathlib import Path
import argparse, json,sys,time
from dataclasses import asdict
from . import __version__

def environment_info():
    import rawpy,tifffile,numpy,scipy
    from .imaging import pyvips
    return {"application":f"MUTEX Imatest {__version__}","python":sys.version.split()[0],"rawpy":rawpy.__version__,
            "libraw":".".join(map(str,rawpy.libraw_version)),"rawpy_build_flags":rawpy.flags,"tifffile":tifffile.__version__,
            "numpy":numpy.__version__,"scipy":scipy.__version__,
            "libvips":".".join(str(pyvips.version(i)) for i in range(3)) if pyvips else None,
            "target_devices":{"Sony A7R IV":"14-bit compressed/uncompressed public CC0 ARW fixtures decoded; user chart pending",
              "Nikon Z8":"14-bit lossless public CC0 NEF fixture decoded; HE/HE* excluded; user chart pending",
              "Fujifilm GFX100":"16-bit lossless public CC0 RAF fixture decoded; user chart pending",
              "Epson V850":"uint16 RGB TIFF pipeline tested with synthetic uncompressed/Deflate data; real scanner sample pending",
              "Canon":"Public CC0 Canon 5D IV CR2, R5 CR3 and C-RAW fixtures decoded; user chart pending"}}

def main(argv=None):
    # Jobs are serialized; avoid competing native pools in CLI and Qt workers.
    import cv2
    cv2.setNumThreads(1)
    for stream in [sys.stdout,sys.stderr]:
        if stream is not None and hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8",errors="backslashreplace")
    args=list(sys.argv[1:] if argv is None else argv)
    commands={"gui","analyze","focus","demo","info","watch","temporal","selftest","report","gray-export","charts","chart-prepare","lab","test-db"}
    # Double-click or dropped paths starts GUI.
    if not args or (args[0] not in commands and args[0] not in {"-h","--help","--version"}):
        from .app import run
        demo="--demo" in args
        return run([a for a in args if not a.startswith("--")],demo)
    parser=argparse.ArgumentParser(prog="mutex-imatest",description="Offline focus and optical measurement")
    parser.add_argument("--version",action="version",version=__version__)
    sub=parser.add_subparsers(dest="command",required=True)
    gui=sub.add_parser("gui");gui.add_argument("images",nargs="*");gui.add_argument("--demo",action="store_true")
    info=sub.add_parser("info")
    charts=sub.add_parser('charts',help='List Imatest / standard chart compatibility and prerequisites')
    lab=sub.add_parser('lab',help='Run a saved IQ workbench JSON specification');lab.add_argument('specification');lab.add_argument('--out',required=True)
    database=sub.add_parser('test-db',help='Inspect saved test-plan history');database.add_argument('database');database.add_argument('--limit',type=int,default=100)
    from .official_charts import PROFILES
    prepare=sub.add_parser('chart-prepare',help='Prepare a chart from a local Imatest / standard target photograph')
    prepare.add_argument('image');prepare.add_argument('--out',required=True)
    def profile_arguments(p,required=False):
        p.add_argument('--profile',choices=sorted(PROFILES),required=required)
        p.add_argument('--layout',help='JSON regions for irregular/mixed target layouts')
        p.add_argument('--reference',help='Batch-specific density / Lab / XYZ CSV or CGATS file')
        p.add_argument('--profile-box',nargs=4,type=float,default=[0,0,1,1],metavar=('X','Y','W','H'))
        p.add_argument('--rows',type=int);p.add_argument('--cols',type=int)
        p.add_argument('--transmissive',action='store_true');p.add_argument('--ref-match',choices=['id','order'],default='id')
        p.add_argument('--ref-white',choices=['D50','D65'],default='D50')
    profile_arguments(prepare,True)
    selftest=sub.add_parser("selftest");selftest.add_argument("--out",required=True);selftest.add_argument("--visible",action="store_true")
    demo=sub.add_parser("demo");demo.add_argument("--out",required=True);demo.add_argument("--single",action="store_true");demo.add_argument("--analyze",action="store_true")
    analyze_parser=sub.add_parser("analyze")
    analyze_parser.add_argument("images",nargs="+");analyze_parser.add_argument("--chart")
    analyze_parser.add_argument("--auto",action="store_true");analyze_parser.add_argument("--out",required=True)
    analyze_parser.add_argument("--config");analyze_parser.add_argument("--transfer",choices=["unknown","linear","srgb","gamma"])
    analyze_parser.add_argument("--channels",choices=["R","G","B","Y","RGB","RGBY"])
    from .analysis_catalog import IMAGE_METRICS
    analyze_parser.add_argument('--metrics',nargs='+',choices=sorted(IMAGE_METRICS),help='Generate all selected analyses from one shared measurement pass')
    analyze_parser.add_argument('--whole-card',action='store_true',help='Expand SVG USAF to all frequencies, both directions, RGB plus two gray variants')
    analyze_parser.add_argument("--memory-mb",type=int);analyze_parser.add_argument("--z",type=float)
    analyze_parser.add_argument("--z-unit",choices=["index","mm","um"],default=None);analyze_parser.add_argument("--report",action="store_true",help="Export HTML and PDF reports plus JSON, CSV and PNG")
    analyze_parser.add_argument("--report-format",choices=["both","html","pdf"],default="both",help="Report format used with --report (default: both)")
    profile_arguments(analyze_parser)
    focus=sub.add_parser("focus");focus.add_argument("results",nargs="+");focus.add_argument("--metric",default="mtf50")
    focus.add_argument("--channel",default="G");focus.add_argument("--objective",choices=["balanced","mean","center"],default="balanced");focus.add_argument("--out",required=True)
    focus.add_argument("--height-calibrated",action="store_true",help="Positions are measured axial stage/chart heights, not lens motor units")
    report=sub.add_parser('report');report.add_argument('result');report.add_argument('--preview',required=True);report.add_argument('--out',required=True);report.add_argument('--format',choices=['both','html','pdf'],default='both')
    gray=sub.add_parser('gray-export');gray.add_argument('result');gray.add_argument('--out',required=True)
    watch=sub.add_parser("watch");watch.add_argument("folder");watch.add_argument("--chart",required=True);watch.add_argument("--out",required=True);watch.add_argument("--config");watch.add_argument("--once",action="store_true")
    temporal=sub.add_parser("temporal");temporal.add_argument("images",nargs="+");temporal.add_argument("--roi",nargs=4,type=int,required=True)
    temporal.add_argument("--channel",default="G");temporal.add_argument("--transfer",choices=["linear","srgb","unknown"],default="linear");temporal.add_argument("--out",required=True)
    ns=parser.parse_args(args)
    try:
        if ns.command=="selftest":
            from .selftest import run
            return run(ns.out,not ns.visible)
        if ns.command=="gui":
            from .app import run
            return run(ns.images,ns.demo)
        if ns.command=="info":print(json.dumps(environment_info(),ensure_ascii=False,indent=2));return 0
        if ns.command=='charts':
            print(json.dumps(PROFILES,ensure_ascii=False,indent=2));return 0
        if ns.command=='test-db':
            from .test_manager import TestDatabase
            print(json.dumps(TestDatabase(ns.database).list(ns.limit),ensure_ascii=False,indent=2));return 0
        if ns.command=='lab':
            from .lab import run_workflow
            from .models import plain
            import uuid
            spec=json.loads(Path(ns.specification).read_text(encoding='utf-8-sig'))
            folder=Path(ns.out)
            if (folder/'lab-result.json').exists():folder=folder/('run-'+uuid.uuid4().hex[:12])
            result=run_workflow(spec,folder,progress=lambda value,message:print(f'{value}% {message}'))
            print(json.dumps({'report':str(folder/'report.html'),'workflow':result['workflow'],'artifacts':result['artifacts']},ensure_ascii=False))
            return 2 if result['workflow']=='test_plan' and result['output']['status']!='pass' else 0
        if ns.command=='chart-prepare':
            from .official_charts import prepare_profile
            from .templates import save_chart
            from .imaging import ImageSource
            from .config import AnalysisConfig
            path=Path(ns.out).resolve();path.parent.mkdir(parents=True,exist_ok=True)
            with ImageSource(ns.image,AnalysisConfig()) as source:
                chart=prepare_profile(source,ns.profile,box=ns.profile_box,rows=ns.rows,cols=ns.cols,reference=ns.reference,
                                      layout=ns.layout,match=ns.ref_match,illuminant=ns.ref_white,transmissive=ns.transmissive,
                                      preview_path=path.with_suffix('.preview.png'))
            save_chart(chart,path);print(f'{len(chart.regions)} regions → {path}');return 0
        if ns.command=='gray-export':
            from .models import AnalysisResult
            from .gray_export import export_gray
            print(export_gray(AnalysisResult.load(ns.result),ns.out));return 0
        if ns.command=='report':
            from .models import AnalysisResult
            from .reports import export_bundle
            result=AnalysisResult.load(ns.result)
            export_bundle(result,ns.preview,ns.out,'resolution_limit' if result.optical_summary else result.settings.get('metric','mtf50'),pdf=ns.format!='html',html=ns.format!='pdf')
            print('Reports exported:',ns.out);return 0
        if ns.command=="demo":
            from .demo import generate_demo
            from .config import AnalysisConfig
            chart,paths=generate_demo(ns.out,not ns.single)
            if ns.analyze:
                from .analysis.engine import analyze
                from .focus import analyze_focus
                results=[]
                for path in paths:
                    result=analyze(path,chart,AnalysisConfig(transfer="linear",channels="RGB"))
                    result.save(Path(ns.out)/"results"/(path.stem+".json"));results.append(result)
                if len(results)>=5:analyze_focus(results,height_calibrated=True).save(Path(ns.out)/"focus-series.json")
            print(f"Created {len(paths)} synthetic TIFF samples in {ns.out}");return 0
        if ns.command=="analyze":
            from .templates import load_chart,auto_edge_chart
            from .analysis.engine import analyze
            from .config import AnalysisConfig
            from .imaging import ImageSource
            from .reports import export_bundle
            from PIL import Image
            config=AnalysisConfig.from_dict(json.loads(Path(ns.config).read_text(encoding="utf-8"))) if ns.config else AnalysisConfig()
            if ns.metrics is not None:config.analysis_metrics=ns.metrics
            for k in ["transfer","channels","memory_mb"]:
                if getattr(ns,k) is not None:setattr(config,k,getattr(ns,k))
            config.validate()
            if sum(bool(v) for v in (ns.chart,ns.auto,ns.profile))!=1:raise ValueError("Choose exactly one of --chart, --auto or --profile")
            chart=load_chart(ns.chart) if ns.chart else None
            if ns.whole_card:
                from .analysis.usaf_multifrequency import is_multifrequency
                if not chart:raise ValueError('--whole-card requires an SVG-based chart template')
                if not is_multifrequency(chart):
                    from .vector_usaf import detect_svg_usaf
                    if not chart.source_path:raise ValueError('Template needs SVG source or precomputed multi-frequency ROIs')
                    generated,chart.fiducials,chart.physical_size_mm=detect_svg_usaf(chart.source_path,all_frequencies=True)
                    chart.regions=generated+[r for r in chart.regions if r.kind!='usaf']
                config.channels='RGBY';config.registration='usaf';config.metric='resolution_limit'
            for path in ns.images:
                with ImageSource(path,config) as source:
                    folder=Path(ns.out)/Path(path).stem;folder.mkdir(parents=True,exist_ok=True)
                    if ns.profile:
                        from .official_charts import prepare_profile
                        current=prepare_profile(source,ns.profile,box=ns.profile_box,rows=ns.rows,cols=ns.cols,reference=ns.reference,
                                                layout=ns.layout,match=ns.ref_match,illuminant=ns.ref_white,transmissive=ns.transmissive,
                                                preview_path=folder/'chart-reference.png')
                        from .templates import save_chart
                        save_chart(current,folder/'chart.json')
                    else:current=chart or auto_edge_chart(source)
                    from .analysis.engine import analyze_source
                    result=analyze_source(source,current,config,focus_position=ns.z,focus_unit=ns.z_unit)
                    preview=folder/"preview.png";Image.fromarray(source.preview()).save(preview)
                    if ns.report:export_bundle(result,preview,folder,config.metric,"G",pdf=ns.report_format!="html",html=ns.report_format!="pdf")
                    else:result.save(folder/"result.json")
                    print(f"{Path(path).name}: {sum(m.valid for m in result.measurements)}/{len(result.measurements)} valid, {result.elapsed_seconds:.2f}s → {folder}")
            return 0
        if ns.command=="focus":
            from .focus import analyze_focus
            from .models import AnalysisResult
            paths=[]
            for pattern in ns.results:
                if any(c in pattern for c in "*?[]"):
                    import glob
                    paths.extend(glob.glob(pattern))
                else:paths.append(pattern)
            result=analyze_focus([AnalysisResult.load(p) for p in paths],ns.metric,ns.channel,ns.objective,ns.height_calibrated)
            result.save(ns.out);print(json.dumps({"recommended":result.recommended_position,"unit":result.unit,"field_model":result.field_model},ensure_ascii=False));return 0
        if ns.command=="watch":
            from .templates import load_chart
            from .config import AnalysisConfig
            from .analysis.engine import analyze
            from .watcher import can_read_complete
            config=AnalysisConfig.from_dict(json.loads(Path(ns.config).read_text(encoding="utf-8"))) if ns.config else AnalysisConfig()
            chart=load_chart(ns.chart)
            from .models import IMAGE_EXTENSIONS
            folder=Path(ns.folder).resolve()
            if not folder.is_dir():raise ValueError("Watch folder does not exist")
            seen=set();states={}
            while True:
                now=time.monotonic()
                for path in folder.iterdir():
                    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:continue
                    stat=path.stat();sig=(str(path),stat.st_size,stat.st_mtime_ns)
                    if sig in seen:continue
                    old=states.get(str(path))
                    if old and old[0]==sig and now-old[1]>=3 and can_read_complete(path):
                        try:
                            result=analyze(path,chart,config)
                            result.save(Path(ns.out)/(path.stem+"-"+result.image.fingerprint[:8]+".json"));print("Analyzed",path)
                        except Exception as exc:print("Failed:",path,exc,file=sys.stderr)
                        seen.add(sig)
                    else:
                        if not old or old[0]!=sig:states[str(path)]=(sig,now)
                if ns.once and states and all(s[0] in seen for s in states.values()):return 0
                time.sleep(1)
        if ns.command=="temporal":
            from .analysis.extra import temporal_noise
            from .analysis.preprocess import linearize,channel_image
            from .config import AnalysisConfig
            from .imaging import ImageSource
            from .utils import atomic_json
            import numpy as np
            config=AnalysisConfig(transfer=ns.transfer)
            frames=[];geometry=None
            for path in ns.images:
                with ImageSource(path,config) as source:
                    shape=(source.metadata.width,source.metadata.height)
                    if geometry and geometry!=shape:raise ValueError("Temporal frames must have the same geometry")
                    geometry=shape
                    a=channel_image(linearize(source.read_roi(ns.roi),config,source.metadata.is_linear),ns.channel)
                    if sum(f.nbytes for f in frames)+a.nbytes>config.budget_bytes()/3:raise MemoryError("Temporal stack exceeds budget; reduce ROI")
                    frames.append(a)
            values=temporal_noise(frames);values.update(roi=ns.roi,channel=ns.channel,source_images=ns.images,transfer=ns.transfer)
            atomic_json(ns.out,values);print(json.dumps(values,ensure_ascii=False));return 0
    except KeyboardInterrupt:return 130
    except Exception as exc:
        print(f"Error: {exc}",file=sys.stderr);return 1
    return 0

