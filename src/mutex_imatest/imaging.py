from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
import hashlib, json, math, os, time
import numpy as np
import tifffile
from PIL import Image
from .config import AnalysisConfig
from .models import ImageMetadata, RAW_EXTENSIONS
from .utils import file_fingerprint, check_cancel, atomic_json, to_rgb8, cache_trim

try:
    import pyvips
    pyvips.cache_set_max_mem(64*2**20)
    pyvips.cache_set_max(64)
except (ImportError, OSError):
    pyvips=None
VIPS_DTYPES={"uchar":"uint8","char":"int8","ushort":"uint16","short":"int16","uint":"uint32","int":"int32","float":"float32","double":"float64"}

class ImageSource:
    """Native sensor/image coordinates. Measurement always reads original precision."""
    def __init__(self, path, config=None, cancel=None, progress=None):
        opened_at=time.perf_counter()
        self.path=Path(path).resolve()
        self.config=config or AnalysisConfig()
        self.cancel=cancel
        self.progress=progress or (lambda *a: None)
        self.array=None; self.vips=None; self.raw_cfa_path=None; self.raw_info={}
        if not self.path.is_file(): raise FileNotFoundError(self.path)
        before=self.path.stat()
        self.progress(2,"计算文件指纹")
        self.fingerprint=file_fingerprint(self.path,cancel)
        check_cancel(cancel)
        ext=self.path.suffix.lower()
        if ext in RAW_EXTENSIONS: self._raw()
        elif ext in {".tif",".tiff"}: self._tiff()
        else: self._generic()
        after=self.path.stat()
        if before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns:
            self.close(); raise ValueError("File changed during import; wait until capture is complete")
        self.open_elapsed_seconds=time.perf_counter()-opened_at
        self.source_stat=(after.st_size,after.st_mtime_ns)
    def _base(self,w,h,c,dtype,**kwargs):
        dtype=np.dtype(dtype)
        self.metadata=ImageMetadata(str(self.path),int(w),int(h),int(c),str(dtype),dtype.itemsize*8,self.path.stat().st_size,self.fingerprint,**kwargs)
    def _tiff(self):
        with tifffile.TiffFile(self.path) as tf:
            p=tf.pages[0]; w,h,c=int(p.imagewidth),int(p.imagelength),int(p.samplesperpixel)
            dtype=p.dtype; tags=p.tags
            orientation=int(tags["Orientation"].value) if "Orientation" in tags else 1
            dpi=None
            def rational(value):
                return float(value[0])/value[1] if isinstance(value,tuple) else float(value)
            if "XResolution" in tags and "YResolution" in tags:
                factor=2.54 if int(tags.get("ResolutionUnit").value if tags.get("ResolutionUnit") else 1)==3 else 1
                if int(tags.get("ResolutionUnit").value if tags.get("ResolutionUnit") else 1) in (2,3):
                    dpi=(rational(tags["XResolution"].value)*factor,rational(tags["YResolution"].value)*factor)
            warnings=[]
            if len(tf.pages)>1: warnings.append("多页 TIFF：本次测量第一页")
            if orientation!=1: warnings.append("显示和 ROI 使用文件原生坐标，未根据 Orientation 重采样")
            if "InterColorProfile" in tags: warnings.append("ICC 仅作元数据记录；分析未自动转换色彩")
            planar=int(p.planarconfig or 1)
            photometric=int(p.photometric)
            if photometric not in {0,1,2}: raise ValueError("Measurement TIFF must be grayscale or RGB (not palette/CMYK)")
        self._base(w,h,c,dtype,is_linear=self.config.transfer=="linear",orientation=orientation,dpi=dpi,decoder=f"tifffile {tifffile.__version__}",warnings=warnings)
        try:
            self.array=tifffile.memmap(self.path,page=0,mode="r")
            if planar==2 and self.array.ndim==3: self.array=np.moveaxis(self.array,0,-1)
            self.array.flags.writeable=False
        except (ValueError, OSError):
            if pyvips is not None:
                self.vips=pyvips.Image.new_from_file(str(self.path),access="random",fail_on="error")
                if self.vips.width!=w or self.vips.height!=h: raise ValueError("TIFF decoder geometry mismatch")
                if self.vips.format not in VIPS_DTYPES or np.dtype(VIPS_DTYPES[self.vips.format])!=np.dtype(dtype):
                    raise ValueError("TIFF decoder precision mismatch")
                self.metadata.decoder+=f" / libvips {pyvips.version(0)}.{pyvips.version(1)}.{pyvips.version(2)}"
            else:
                if w*h*c*np.dtype(dtype).itemsize>self.config.budget_bytes()/3: raise MemoryError("Compressed TIFF needs libvips or a larger memory budget")
                self.array=tifffile.imread(self.path,key=0)
                if planar==2 and self.array.ndim==3: self.array=np.moveaxis(self.array,0,-1)
                self.array.flags.writeable=False
        # libvips applies MINISWHITE inversion; tifffile exposes stored values.
        self._invert = photometric==0 and self.vips is None
    def _raw(self):
        import rawpy
        decoder=f"rawpy {rawpy.__version__} / LibRaw {'.'.join(map(str,rawpy.libraw_version))}"
        key=hashlib.sha256((self.fingerprint+decoder+self.config.demosaic+"linear-camera-rgb-unity-v3").encode()).hexdigest()
        folder=self.config.cache_path()/key
        folder.mkdir(parents=True,exist_ok=True); (folder/"MUTEX_CACHE").touch()
        manifest=folder/"metadata.json"
        if manifest.is_file() and (folder/"pixels.npy").is_file() and (folder/"cfa.npy").is_file():
            data=json.loads(manifest.read_text(encoding="utf-8"))
            self.metadata=ImageMetadata(**data["metadata"]); self.metadata.path=str(self.path)
            self.array=np.load(folder/"pixels.npy",mmap_mode="r")
            if self.array.shape!=(self.metadata.height,self.metadata.width,3) or self.array.dtype!=np.uint16: raise ValueError("Invalid RAW cache")
            self.raw_cfa_path=str(folder/"cfa.npy"); self.raw_info=data["raw_info"]
            if "decoder_flags" in self.raw_info:self.raw_info["rawpy_build_flags"]=self.raw_info.pop("decoder_flags")
            os.utime(folder,None); self.progress(16,"使用线性 RAW 缓存"); return
        raw=rawpy.RawPy()
        try:
            raw.open_file(str(self.path))
            size=raw.sizes
            estimate=max(size.raw_width*size.raw_height,size.width*size.height)*32
            if estimate>self.config.budget_bytes():
                raise MemoryError(f"RAW 解码估计需要 {estimate/2**30:.2f} GiB；预算 {self.config.budget_bytes()/2**30:.2f} GiB。提高预算或外部转换为 16-bit TIFF。")
            self.progress(8,"解包 RAW，保留 CFA")
            check_cancel(self.cancel); raw.unpack(); check_cancel(self.cancel)
            self.raw_info={"black_level_per_channel":list(raw.black_level_per_channel),"white_level":raw.white_level,
                           "color_desc":raw.color_desc.decode(errors="replace"),
                           "raw_pattern":raw.raw_pattern.tolist() if raw.raw_pattern is not None else None,
                           "rawpy_build_flags":rawpy.flags}
            cfa=raw.raw_image_visible
            self._save_array(folder/"cfa.npy",cfa)
            self.raw_cfa_path=str(folder/"cfa.npy")
            self.progress(12,"线性相机 RGB 解码（不锐化）")
            algo=rawpy.DemosaicAlgorithm.AHD if cfa.ndim==2 and raw.raw_pattern is not None and raw.raw_pattern.shape==(2,2) and self.config.demosaic=="AHD" else rawpy.DemosaicAlgorithm.VNG
            rgb=raw.postprocess(gamma=(1,1),no_auto_bright=True,use_camera_wb=False,use_auto_wb=False,
                user_wb=[1,1,1,1],output_color=rawpy.ColorSpace.raw,output_bps=16,user_flip=0,
                demosaic_algorithm=algo,fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
                median_filter_passes=0,chromatic_aberration=(1,1))
            check_cancel(self.cancel)
            self._save_array(folder/"pixels.npy",rgb)
            self._base(rgb.shape[1],rgb.shape[0],3,rgb.dtype,is_raw=True,is_linear=True,decoder=decoder,
                warnings=["RAW 测量为线性相机 RGB；去马赛克结果依赖算法，原始 CFA 已保留",
                          "相机内置处理无法由本软件逆转；文件兼容性需按相机和压缩模式验收"])
            del rgb
            atomic_json(manifest,{"metadata":asdict(self.metadata),"raw_info":self.raw_info,"estimated_peak_bytes":estimate})
        except rawpy.LibRawFileUnsupportedError as exc:
            raise ValueError("LibRaw 不支持此 RAW/压缩模式。Nikon Z8 HE/HE★ 首版不支持；请使用无损 NEF 或外部转成线性 16-bit TIFF/DNG。") from exc
        finally: raw.close()
        self.array=np.load(folder/"pixels.npy",mmap_mode="r")
        cache_trim(self.config.cache_path(),int(self.config.cache_gb*2**30),preserve=(key,))
    def _save_array(self,path,a):
        temp=path.with_suffix(".partial.npy")
        out=np.lib.format.open_memmap(temp,mode="w+",dtype=a.dtype,shape=a.shape)
        for y in range(0,a.shape[0],256):
            check_cancel(self.cancel); out[y:y+256]=a[y:y+256]
        out.flush(); del out; os.replace(temp,path)
    def _generic(self):
        warnings=["JPEG/PNG 等成品图像可能已锐化、降噪或套用曲线"]
        if pyvips is not None:
            self.vips=pyvips.Image.new_from_file(str(self.path),access="random",fail_on="error")
            if self.vips.format not in VIPS_DTYPES: raise ValueError("Unsupported image precision")
            self._base(self.vips.width,self.vips.height,self.vips.bands,VIPS_DTYPES[self.vips.format],decoder="libvips",warnings=warnings)
        else:
            with Image.open(self.path) as im:
                if im.width*im.height*4>self.config.budget_bytes()/3: raise MemoryError("Install libvips for large processed images")
                self.array=np.asarray(im.convert("RGB"))
            self._base(self.array.shape[1],self.array.shape[0],3,self.array.dtype,decoder="Pillow",warnings=warnings)
    def read_roi(self,box):
        check_cancel(self.cancel)
        x,y,w,h=map(int,box)
        x=max(0,x); y=max(0,y); w=min(w,self.metadata.width-x); h=min(h,self.metadata.height-y)
        if min(w,h)<=0: raise ValueError("ROI outside image")
        if w*h*self.metadata.channels*8>self.config.budget_bytes()/3:
            raise MemoryError("ROI 超过内存预算，请缩小测量区域")
        if self.array is not None: a=self.array[y:y+h,x:x+w]
        else:
            crop=self.vips.crop(x,y,w,h)
            a=np.frombuffer(crop.write_to_memory(),dtype=VIPS_DTYPES[crop.format]).reshape(h,w,crop.bands)
            if crop.bands==1: a=a[...,0]
        if getattr(self,"_invert",False): a=np.iinfo(a.dtype).max-a
        return a
    def preview(self,max_side=None):
        max_side=max_side or self.config.preview_size
        scale=min(1,max_side/max(self.metadata.width,self.metadata.height))
        if self.array is not None:
            step=max(1,math.ceil(1/scale)); a=self.array[::step,::step]
        else:
            v=self.vips.resize(scale,kernel="linear") if scale<1 else self.vips
            a=np.frombuffer(v.write_to_memory(),dtype=VIPS_DTYPES[v.format]).reshape(v.height,v.width,v.bands)
        if getattr(self,"_invert",False): a=np.iinfo(a.dtype).max-a
        return to_rgb8(a,linear=self.metadata.is_linear,white_balance=self.metadata.is_raw)
    def tile(self,x,y,w,h,level=0):
        """Display-only downsampling; measurement never uses this."""
        scale=2**level
        if self.array is not None:
            a=self.array[y:y+h:scale,x:x+w:scale]
        else:
            v=self.vips.crop(x,y,w,h)
            if scale>1: v=v.resize(1/scale,kernel="linear")
            a=np.frombuffer(v.write_to_memory(),dtype=VIPS_DTYPES[v.format]).reshape(v.height,v.width,v.bands)
        if getattr(self,"_invert",False): a=np.iinfo(a.dtype).max-a
        return to_rgb8(a,linear=self.metadata.is_linear,white_balance=False)
    def native_cache(self):
        if not self.metadata.is_raw:return None
        return {"pixels":str(self.array.filename),"cfa":self.raw_cfa_path}
    def verify_unchanged(self):
        if hasattr(self,"source_stat"):
            stat=self.path.stat()
            if (stat.st_size,stat.st_mtime_ns)!=self.source_stat:raise ValueError("源文件在分析期间发生变化，请等待采集完成后重新导入")
    @classmethod
    def from_cached_raw(cls,metadata,config,cache):
        obj=cls.__new__(cls);obj.path=Path(metadata.path);obj.config=config;obj.cancel=None
        obj.progress=lambda *a:None;obj.metadata=metadata;obj.fingerprint=metadata.fingerprint
        obj.array=np.load(cache["pixels"],mmap_mode="r");obj.vips=None
        obj.raw_cfa_path=cache.get("cfa");obj.raw_info={}
        if obj.array.shape!=(metadata.height,metadata.width,3) or obj.array.dtype!=np.uint16:raise ValueError("RAW display cache mismatch")
        return obj
    def close(self): self.array=None; self.vips=None
    def __enter__(self): return self
    def __exit__(self,*a): self.close()
