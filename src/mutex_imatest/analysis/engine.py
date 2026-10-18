from __future__ import annotations
import time, json
from dataclasses import asdict
from pathlib import Path
import numpy as np
from ..models import Measurement, AnalysisResult, ChartDefinition
from ..config import AnalysisConfig
from ..imaging import ImageSource
from ..detection import register_chart,transform_box,local_scale,usaf_native_axes
from ..utils import check_cancel,focus_from_name
from .preprocess import linearize,channel_image,clipping_fraction
from .sfr import slanted_edge
from .targets import usaf,star
from .extra import flat_field,step_patch,color_patch,point_spread,texture,grid_geometry

ALGORITHM_VERSION="mutex-native-2026.10.18"
def analyze(path,chart,config=None,cancel=None,progress=None,focus_position=None,focus_unit=None):
    config=(config or AnalysisConfig()).validate()
    progress=progress or (lambda *a:None)
    start=time.perf_counter()
    with ImageSource(path,config,cancel,progress) as source:
        return analyze_source(source,chart,config,cancel,progress,focus_position,focus_unit,start)

def analyze_source(source,chart,config,cancel=None,progress=None,focus_position=None,focus_unit=None,start=None):
    if config.backend!="native":raise ValueError("本版 MTF Mapper 是独立复核入口，尚未作为数值后端对齐；请选择 native")
    include_source_time=start is None
    start=start or time.perf_counter();progress=progress or (lambda *a:None)
    if isinstance(chart,dict): chart=ChartDefinition.from_dict(chart)
    from ..analysis_catalog import required_channels,RGB_METRICS
    if config.analysis_metrics is not None:
        if not config.analysis_metrics:raise ValueError('请先勾选至少一个分析项目')
        if source.metadata.channels<3 and set(config.analysis_metrics)&RGB_METRICS:raise ValueError('RGB 位移和对齐分析需要源图像包含三个颜色通道')
        config=AnalysisConfig.from_dict(dict(config.to_dict(),channels=required_channels(config.channels,config.analysis_metrics)))
    H,registration=register_chart(chart,source,config)
    if registration.get('detected_regions') is not None:
        # Unmatched generic targets live in current image coordinates. The
        # printable reference's dimensions must never become a false scale.
        from copy import deepcopy
        chart=deepcopy(chart)
        from ..models import Region
        chart.regions=[Region(**r) for r in registration['detected_regions']]
        chart.calibrated=False;chart.physical_size_mm=None
    measurements=[]
    regions=[r for r in chart.regions if r.enabled]
    if not regions: raise ValueError("模板没有测量区域，请先在模板编辑器添加 ROI")
    channels=['R','G','B','Y'] if config.channels=='RGBY' else ["R","G","B"] if config.channels=="RGB" else [config.channels]
    warnings=list(source.metadata.warnings)
    from ..official_charts import profile_metadata
    profile=profile_metadata(chart)
    if profile.get('warning'):warnings.append(profile['warning'])
    matrix=None
    if config.color_matrix_path:
        matrix=json.loads(Path(config.color_matrix_path).read_text(encoding='utf-8-sig'))
    if registration.get("warning"):warnings.append(registration["warning"])
    if config.transfer=="unknown" and not source.metadata.is_linear: warnings.append("传递曲线未知：报告为输入信号响应，不能等同线性光学 MTF")
    warnings.append("独立工程测量；未声称通过 Imatest 数值等效验收或 ISO/FADGI 标准认证")
    from .usaf_multifrequency import is_multifrequency,analyze_whole_chart
    full=is_multifrequency(chart)
    optical_summary={}
    if full:
        measurements,optical_summary=analyze_whole_chart(source,chart,config,H,registration,cancel,progress)
        warnings.extend(["整卡分辨率由设定阈值和三线分离共同判读；图卡范围外不外推，等效 DPI 与采样 DPI 不同。",
                         "对齐后灰度经过双线性重采样，仅为软件对齐结果；单张图像不提供 RGB 最佳焦位。"])
    additional=[r for r in regions if r.kind!='usaf'] if full else regions
    unit_centers={}
    if full and additional and config.registration=='usaf':
        from collections import defaultdict
        centers=defaultdict(list)
        for r in regions:
            if r.kind=='usaf':centers[r.params.get('unit_id',r.id)].append([r.box[0]+r.box[2]/2,r.box[1]+r.box[3]/2])
        unit_centers={key:np.mean(points,axis=0) for key,points in centers.items()}
    for index,region in enumerate(additional):
        check_cancel(cancel)
        progress(95+int(4*index/max(1,len(additional))) if full else 18+int(78*index/len(regions)),f"测量 {region.label or region.id}")
        region_H=H
        nearby_registration=False
        if config.registration=="usaf":
            anchor=region.params.get('unit_id')
            if full and not anchor and unit_centers:
                center=np.array([region.box[0]+region.box[2]/2,region.box[1]+region.box[3]/2])
                anchor=min(unit_centers,key=lambda key:np.linalg.norm((unit_centers[key]-center)*np.asarray(chart.physical_size_mm or (1,1))))
                nearby_registration=True
            local=registration.get("unit_transforms",{}).get(anchor)
            if local is None:
                box,_=transform_box(region.box,H,source.metadata.width,source.metadata.height)
                x,y,w,h=box
                for channel in channels:
                    measurements.append(Measurement(region.id,region.label,region.kind,channel,(x+w/2,y+h/2),box,flags=["registration_failed"],confidence=0))
                continue
            region_H=np.asarray(local["homography"])
        box,outside=transform_box(region.box,region_H,source.metadata.width,source.metadata.height)
        x,y,w,h=box;position=(x+w/2,y+h/2)
        if min(w,h)<4 or outside:
            for channel in channels:
                measurements.append(Measurement(region.id,region.label,region.kind,channel,position,box,flags=["roi_outside"],confidence=0))
            continue
        estimated_roi_peak=w*h*(8*source.metadata.channels+96)
        if estimated_roi_peak>config.budget_bytes()*.7:
            raise MemoryError("此 ROI 的分析缓冲估计超过内存预算，请在模板编辑器缩小区域")
        raw=source.read_roi(box)
        data=linearize(raw,config,source.metadata.is_linear)
        reference_data=noise_data=None
        if region.kind=='texture' and region.params.get('reference_image'):
            for name in ('reference_image','noise_image'):
                if not region.params.get(name):continue
                with ImageSource(region.params[name],config,cancel) as ref_source:
                    ref_box=region.params.get('reference_box' if name=='reference_image' else 'noise_box',[0,0,w,h])
                    sampled=linearize(ref_source.read_roi(ref_box),config,ref_source.metadata.is_linear)
                    if sampled.shape[:2]!=data.shape[:2]:raise ValueError('纹理参考 ROI 必须与原图 ROI 同尺寸，不能隐式缩放')
                    if name=='reference_image':reference_data=sampled
                    else:noise_data=sampled
        edge_outputs={}
        for channel in channels:
            channel_data=channel_image(data,channel)
            # Source clipping inspected per channel; black level has already been subtracted by LibRaw.
            raw_channel=channel_image(raw,channel) if channel!="Y" else raw[...,:3] if raw.ndim==3 else raw
            clip=clipping_fraction(raw_channel)
            try:
                normal=np.array([1.,0.])
                if region.kind=="edge":
                    result=slanted_edge(channel_data,config);edge_outputs[channel]=result
                    normal=np.asarray(result.get("normal",normal))
                    from .quality import edge_information
                    edge_information(result,channel_data,region.params)
                elif region.kind=="usaf":
                    direction=region.params.get("direction","vertical")
                    native_direction,_=usaf_native_axes(region_H,position,direction)
                    normal=np.array([1.,0.]) if native_direction=="vertical" else np.array([0.,1.])
                    scale=local_scale(chart,region_H,position,normal)
                    result=usaf(channel_data,dict(region.params,direction=native_direction),config,scale)
                    result["direction_deg"]=0 if direction=="vertical" else 90
                elif region.kind in {"star","wedge"}:
                    rx,ry,rw,rh=region.box
                    target_params=dict(region.params)
                    target_params['_native_homography']=(np.array([[1,0,-x],[0,1,-y],[0,0,1]],float)@region_H@np.array([[rw,0,rx],[0,rh,ry],[0,0,1]],float)).tolist()
                    if region.kind=='star':result=star(channel_data,target_params,config)
                    else:
                        from .wedge import wedge
                        result=wedge(channel_data,target_params,config)
                elif region.kind=="flat":
                    result=flat_field(channel_data,region.params,config)
                    from .quality import uniformity
                    extended=uniformity(channel_data,region.params,config)
                    result['values'].update(extended['values']);result['curves'].update(extended['curves']);result['flags'].extend(extended['flags'])
                    result['diagnostics']={k:extended[k] for k in ('blemishes','grid')}
                    if data.ndim==3 and data.shape[2]>=3:
                        green=data[...,1];usable=green>max(float(np.mean(green))*.1,1e-9)
                        if usable.any():
                            for i,name in [(0,'r_g'),(2,'b_g')]:
                                ratios=data[...,i][usable]/green[usable]
                                result['values'][f'color_shading_{name}_pct']=float(100*np.std(ratios)/max(np.mean(ratios),1e-9))
                elif region.kind=="step":
                    result=step_patch(channel_data,region.params,config)
                    encoded=raw_channel.astype(float)/np.iinfo(raw.dtype).max if raw.dtype.kind in 'ui' else raw_channel
                    if channel=='Y' and raw.ndim==3:encoded=channel_image(encoded,'Y')
                    result['values'].update(encoded_mean=float(np.mean(encoded)),white_clip_fraction=float(np.mean(encoded>=1)),black_clip_fraction=float(np.mean(encoded<=0)))
                elif region.kind=="color":
                    if matrix is not None:
                        from .tone_color import apply_color_matrix
                        from copy import copy
                        color_config=copy(config);color_config.transfer='linear'
                        result=color_patch(apply_color_matrix(data,matrix),dict(region.params,rgb_space='sRGB'),color_config)
                        result['flags'].append('calibrated_source_rgb')
                    elif source.metadata.is_raw:
                        result={"values":dict(zip(["mean_R","mean_G","mean_B"],map(float,np.mean(data[...,:3],axis=(0,1))))),"flags":["missing_calibration"],"confidence":0,"curves":{}}
                    else:result=color_patch(data,region.params,config)
                elif region.kind=="grid":
                    result=grid_geometry(channel_data,region.params,config)
                    if result.get('points'):
                        from .geometry import fit_radial_distortion
                        yy,xx=np.mgrid[:int(region.params.get('rows',7)),:int(region.params.get('cols',9))]
                        try:
                            radial=fit_radial_distortion(np.column_stack([xx.ravel(),yy.ravel()]),result['points'],(w,h),region.params.get('center_px'))
                            result['values'].update(radial['values']);result['curves'].update(radial['curves']);result['flags'].extend(radial['flags'])
                            result['diagnostics']={k:v for k,v in radial.items() if k not in {'values','curves','flags','confidence'}}
                        except ValueError as exc:result.setdefault('diagnostics',{})['radial_model_unavailable']=str(exc)
                elif region.kind=='dot':
                    from .geometry import dot_geometry,dot_chromatic_aberration
                    result=dot_geometry(channel_data,region.params,config)
                    result['values'].update(dot_chromatic_aberration(data,result['points']))
                    result['diagnostics']={k:v for k,v in result.items() if k not in {'values','curves','flags','confidence','diagnostics'}}
                elif region.kind=='logf':
                    from .quality import log_frequency
                    result=log_frequency(channel_data,region.params,config)
                elif region.kind=='flare':
                    from .quality import flare
                    result=flare(channel_data,region.params,config)
                elif region.kind=='rings':
                    from .geometry import concentric_rings
                    result=concentric_rings(channel_data,region.params,config)
                elif region.kind=="point": result=point_spread(channel_data,region.params,config)
                else:
                    result=texture(channel_data,region.params,config)
                    if reference_data is not None:
                        from .quality import texture_transfer
                        transfer=texture_transfer(channel_data,channel_image(reference_data,channel),channel_image(noise_data,channel) if noise_data is not None else None)
                        result['values'].update(transfer['values']);result['curves'].update(transfer['curves']);result['flags'].extend(transfer['flags'])
                if region.kind in {'wedge','logf','star'} and data.ndim==3:
                    from .quality import color_moire
                    result['values'].update(color_moire(data))
                values=result.get("values",{})
                scale=local_scale(chart,region_H,position,normal)
                if region.kind in {'star','wedge'}:
                    from ..chart_targets import target_physical_scale
                    scale=target_physical_scale(chart,region,target_params['_native_homography'])
                from ..resolution import frequency_values,FREQUENCY_METRICS
                for key in FREQUENCY_METRICS:
                    if values.get(key) is not None:values.update(frequency_values(key,values[key],scale,config.picture_height_px or source.metadata.height))
                if scale:
                    for key in ["mtf50","mtf50p","mtf20","mtf10","ctf50","response50"]:
                        if values.get(key) is not None: values[key+"_lp_mm"]=values[key]*scale
                for key in ["mtf50","mtf50p","mtf20","mtf10"]:
                    if values.get(key) is not None:
                        values[key+"_lw_ph"]=values[key]*2*(config.picture_height_px or source.metadata.height)
                        if config.sensor_pixel_um>0: values[key+"_lp_sensor_mm"]=values[key]*1000/config.sensor_pixel_um
                values["clipping_fraction"]=clip
                if registration.get('rms_px') is not None:values['registration_rms_px']=registration['rms_px']
                if config.registration=="usaf":
                    values["registration_rms_px"]=local["rms_px"]
                    values["registration_matches"]=local["matches"]
                flags=list(result.get("flags",[]))
                if nearby_registration:flags.append('nearby_unit_registration')
                if clip>config.maximum_clip_fraction:
                    flags.append("clipped" if config.reject_clipping else "clipping_advisory")
                if not source.metadata.is_linear and config.transfer=="unknown": flags.append("transfer_unknown")
                units={k:('DPI' if k.endswith('_dpi') else 'LP/PH' if k.endswith('_lp_ph') else "lp/mm" if k.endswith("_lp_mm") or k.endswith("_lp_sensor_mm") or k=="target_lp_mm" else "LW/PH" if k.endswith("_lw_ph") else "cy/px" if k in FREQUENCY_METRICS|{'target_frequency'} else "px" if k.endswith("_px") else "%" if k.endswith("_pct") else "ratio") for k in values}
                units.update({k:"dB" for k in values if k.endswith("_db")})
                units.update({k:"deg" for k in values if k.endswith("_deg")})
                if "delta_e_2000" in values:units["delta_e_2000"]="ΔE2000"
                if "detected_bar_count" in values:units["detected_bar_count"]="count"
                if "registration_matches" in values:units["registration_matches"]="count"
                if "resolved" in values:units["resolved"]="boolean"
                if 'information_capacity_1d' in values:units['information_capacity_1d']='bits/px (1D model)'
                for key in values:
                    if key.endswith('_count'):units[key]='count'
                    if key.endswith('_ev'):units[key]='EV'
                measurements.append(Measurement(region.id,region.label or region.id,region.kind,channel,position,box,values,units,result.get("curves",{}),flags,float(result.get("confidence",1)),f"{ALGORITHM_VERSION}/{region.kind}",
                                               result.get("direction_deg"),scale,result.get('diagnostics',{})))
            except (ValueError,np.linalg.LinAlgError,FloatingPointError) as exc:
                measurements.append(Measurement(region.id,region.label or region.id,region.kind,channel,position,box,
                                    flags=["fit_failed"],confidence=0,values={},method=f"{ALGORITHM_VERSION}: {exc}"))
        if region.kind=="edge" and all(c in edge_outputs for c in ["R","G","B"]):
            ref=edge_outputs["G"]
            if "edge_center" in ref:
                normal=np.asarray(ref["normal"]);gc=np.asarray(ref["edge_center"])
                for c in ["R","B"]:
                    if "edge_center" in edge_outputs[c]:
                        shift=float(np.dot(np.asarray(edge_outputs[c]["edge_center"])-gc,normal))
                        for m in measurements:
                            if m.region_id==region.id:
                                m.values[f"ca_{c.lower()}_g_px"]=shift;m.units[f"ca_{c.lower()}_g_px"]="px (edge-normal projection)"
                                m.values["ca_projection_angle_deg"]=ref["direction_deg"]
                                m.units["ca_projection_angle_deg"]="deg"
    from .tone_color import summarize_tone
    measurements.extend(summarize_tone(measurements,chart,(source.metadata.width,source.metadata.height)))
    auto_z,auto_unit=focus_from_name(source.path)
    if hasattr(source,"verify_unchanged"):source.verify_unchanged()
    settings=config.to_dict();settings["algorithm_version"]=ALGORITHM_VERSION
    settings["measurement_pipeline"]="linear-camera-rgb" if source.metadata.is_raw else "native-pixels/"+config.transfer
    if config.transfer=="oecf":
        from ..utils import file_fingerprint
        settings["oecf_sha256"]=file_fingerprint(config.oecf_path)
    if config.color_matrix_path:
        from ..utils import file_fingerprint
        settings['ccm_sha256']=file_fingerprint(config.color_matrix_path)
    result=AnalysisResult(source.metadata,chart.id,chart.name,measurements,settings,chart.to_dict(),registration,
                        focus_position if focus_position is not None else auto_z,
                        focus_unit or (auto_unit if auto_z is not None else config.focus_unit),
                        time.perf_counter()-start+(getattr(source,"open_elapsed_seconds",0) if include_source_time else 0),warnings,optical_summary=optical_summary)
    if config.analysis_metrics is not None:
        from ..analysis_plan import summarize_selected
        result.analysis_summary=summarize_selected(result)
    from ..evaluation import evaluate_result
    result.evaluation_summary=evaluate_result(result,config.analysis_metrics)
    progress(100,"分析完成")
    return result
