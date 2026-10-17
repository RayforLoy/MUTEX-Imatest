from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter, label, center_of_mass
from scipy.signal import welch
from .sfr import first_crossing

def flat_field(a,params,config):
    a=np.asarray(a,float); h,w=a.shape
    mean=float(np.mean(a)); std=float(np.std(a,ddof=1)) if a.size>1 else 0
    yy,xx=np.mgrid[:h,:w]
    stride=max(1,int(np.sqrt(a.size/100000)))
    design=np.stack([np.ones(a[::stride,::stride].size),xx[::stride,::stride].ravel()/w,yy[::stride,::stride].ravel()/h],axis=1)
    plane=np.linalg.lstsq(design,a[::stride,::stride].ravel(),rcond=None)[0]
    detrend=a-(plane[0]+plane[1]*xx/w+plane[2]*yy/h)
    noise=float(np.std(detrend,ddof=1))
    axis=0 if config.scan_direction=="y" else 1
    line=np.mean(detrend,axis=1-axis)
    nperseg=min(len(line),256)
    freq,power=welch(line,nperseg=nperseg) if nperseg>=8 else (np.array([0]),np.array([0]))
    values={"mean":mean,"std":std,"spatial_snr_db":float(20*np.log10(mean/noise)) if mean>0 and noise>0 else None,
            "detrended_noise":noise,"uniformity_pct":float(100*(np.percentile(a,95)-np.percentile(a,5))/max(mean,1e-9)),
            "gradient_x_pct":float(plane[1]/max(mean,1e-9)*100),"gradient_y_pct":float(plane[2]/max(mean,1e-9)*100),
            "banding_rms":float(np.std(line))}
    return {"values":values,"flags":["single_frame_spatial_noise"],"confidence":1,
            "curves":{"line":{"x":list(range(len(line))),"y":line.tolist(),"x_unit":"px","y_unit":"linear residual"},
                      "nps_1d":{"x":freq.tolist(),"y":power.tolist(),"x_unit":"cy/px","y_unit":"signal²/(cy/px)"}}}

def color_patch(rgb,params,config):
    mean=np.mean(rgb[...,:3],axis=(0,1))
    values=dict(zip(["mean_R","mean_G","mean_B"],map(float,mean)))
    if "reference_lab" not in params:
        return {"values":values,"flags":["missing_reference"],"confidence":0,"curves":{}}
    if params.get("rgb_space")!="sRGB" or config.transfer=="unknown":
        return {"values":values,"flags":["missing_calibration"],"confidence":0,"curves":{}}
    from .tone_color import color_metrics
    values.update(color_metrics(mean,params['reference_lab'],params.get('reference_illuminant','D65')))
    return {"values":values,"flags":[],"confidence":1,"curves":{}}

def step_patch(a,params,config):
    values={"mean":float(np.mean(a)),"noise":float(np.std(a,ddof=1)),"sample_count":int(a.size)}
    if "reference_density" in params: values["reference_density"]=float(params["reference_density"])
    elif "reference_luminance" in params: values["reference_luminance"]=float(params["reference_luminance"])
    else: return {"values":values,"flags":["missing_reference"],"confidence":0,"curves":{}}
    return {"values":values,"flags":[],"confidence":1,"curves":{}}

def point_spread(a,params,config):
    a=np.asarray(a,float)
    yy,xx=np.mgrid[:a.shape[0],:a.shape[1]]
    baseline=np.median(np.concatenate([a[0],a[-1],a[:,0],a[:,-1]]))
    signal=np.maximum(a-baseline,0)
    total=np.sum(signal)
    if total<=1e-9: return {"values":{},"flags":["low_contrast"],"confidence":0,"curves":{}}
    cy,cx=center_of_mass(signal)
    radius=np.hypot(xx-cx,yy-cy)
    order=np.argsort(radius.ravel()); r=radius.ravel()[order]; enc=np.cumsum(signal.ravel()[order])/total
    radii=np.linspace(0,float(radius.max()),100)
    energy=np.interp(radii,r,enc)
    values={"encircled_r50_px":float(np.interp(.5,enc,r)),"encircled_r80_px":float(np.interp(.8,enc,r)),
            "centroid_x_px":float(cx),"centroid_y_px":float(cy),
            "sigma_x_px":float(np.sqrt(np.sum(signal*(xx-cx)**2)/total)),
            "sigma_y_px":float(np.sqrt(np.sum(signal*(yy-cy)**2)/total))}
    flags=[] if params.get("point_diameter_px",100)<.5 else ["finite_target_size"]
    return {"values":values,"flags":flags,"confidence":.8 if flags else 1,
            "curves":{"encircled":{"x":radii.tolist(),"y":energy.tolist(),"x_unit":"px","y_unit":"encircled energy"}}}

def texture(a,params,config):
    h,w=a.shape
    window=np.outer(np.hanning(h),np.hanning(w))
    spec=np.abs(np.fft.rfft2((a-np.mean(a))*window))**2/max(np.sum(window**2),1)
    fy=np.fft.fftfreq(h)[:,None]; fx=np.fft.rfftfreq(w)[None,:]
    radii=np.hypot(fx,fy); bins=np.minimum((radii*100).astype(int),70)
    counts=np.bincount(bins.ravel(),minlength=71)
    power=np.bincount(bins.ravel(),weights=spec.ravel(),minlength=71)/np.maximum(counts,1)
    return {"values":{"texture_rms":float(np.std(a)),"high_frequency_energy":float(np.sum(spec[radii>.25])/max(np.sum(spec),1e-12))},
            "flags":["not_optical_mtf"],"confidence":1,
            "curves":{"texture_spectrum":{"x":(np.arange(51)/100).tolist(),"y":power[:51].tolist(),"x_unit":"cy/px","y_unit":"power"}}}

def grid_geometry(a,params,config):
    import cv2
    rows,cols=int(params.get("rows",7)),int(params.get("cols",9))
    img=np.clip(a*255,0,255).astype(np.uint8)
    found,points=cv2.findChessboardCornersSB(img,(cols,rows))
    if not found: return {"values":{},"flags":["fit_failed"],"confidence":0,"curves":{}}
    points=points.reshape(-1,2)
    yy,xx=np.mgrid[:rows,:cols]
    ideal=np.column_stack([xx.ravel(),yy.ravel()]).astype(np.float32)
    H,_=cv2.findHomography(ideal,points,0)
    predicted=cv2.perspectiveTransform(ideal[None],H)[0]
    residual=points-predicted; radius=np.linalg.norm(residual,axis=1)
    # Residual from a projective plane includes distortion and target/printing errors.
    return {"values":{"projective_residual_rms_px":float(np.sqrt(np.mean(radius**2))),"projective_residual_max_px":float(np.max(radius))},
            "flags":["target_geometry_affects_result"],"confidence":1,
            "curves":{"grid_residual":{"x":list(range(len(points))),"y":radius.tolist(),"x_unit":"point","y_unit":"px"}},
            "points":points.tolist(),"residual":residual.tolist()}

def temporal_noise(frames):
    """Matched dark/flat frames in already linearized native coordinates."""
    stack=np.asarray(frames,float)
    if stack.ndim<3 or len(stack)<2: raise ValueError("At least two matched frames required")
    mean=np.mean(stack,axis=0)
    temporal=np.var(stack,axis=0,ddof=1)
    temporal_std=float(np.sqrt(np.mean(temporal)))
    fixed_var=max(0,float(np.var(mean))-float(np.mean(temporal))/len(stack))
    return {"temporal_noise":temporal_std,"fixed_pattern_rms":float(np.sqrt(fixed_var)),
            "prnu_pct":float(100*np.sqrt(fixed_var)/np.mean(mean)) if np.mean(mean)>0 else None,
            "frame_count":len(stack)}
