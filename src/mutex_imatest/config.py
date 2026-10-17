from __future__ import annotations
from dataclasses import dataclass, asdict, fields, field
from pathlib import Path
import json
import psutil, platformdirs

@dataclass
class AnalysisConfig:
    channels: str = "G"
    transfer: str = "unknown"
    gamma: float = 2.2
    oecf_path: str = ""
    oversampling: int = 4
    window: str = "hamming"
    edge_fit: str = "linear"
    ctf_threshold: float = .2
    target_frequency: float = .15
    minimum_contrast: float = .03
    maximum_clip_fraction: float = .01
    reject_clipping: bool = True
    registration: str = "template"
    anchors: list | None = None
    auto_refine: bool = False
    memory_mb: int = 0
    cache_gb: float = 32
    tile_cache_mb: int = 256
    workers: int = 1
    preview_size: int = 2048
    cache_dir: str = ""
    device_mode: str = "scanner"
    scan_direction: str = "y"
    focus_objective: str = "balanced"
    focus_unit: str = "index"
    metric: str = "mtf50"
    analysis_metrics: list[str] | None = None
    chart_id: str = ""
    heatmap_unit: str = "cy/px"
    heatmap_alpha: float = .48
    interpolate: bool = True
    demosaic: str = "AHD"
    backend: str = "native"
    mtf_mapper_path: str = ""
    sensor_pixel_um: float = 0
    device_notes: str = ""
    usaf_threshold_mode: str = "relative"
    rgb_max_shift_px: float = 24.0
    gray_weights: tuple = (.2126,.7152,.0722)
    picture_height_px: int = 0
    color_matrix_path: str = ""
    evaluation_engineering: bool = True
    evaluation_limits: dict = field(default_factory=dict)
    def budget_bytes(self):
        return self.memory_mb*2**20 if self.memory_mb else min(int(psutil.virtual_memory().total*.4), 8*2**30)
    def cache_path(self):
        p = Path(self.cache_dir or platformdirs.user_cache_dir("MUTEX Imatest", "MUTEX"))
        p.mkdir(parents=True, exist_ok=True)
        return p
    def validate(self):
        from .evaluation import validate_limits
        validate_limits(self.evaluation_limits)
        if not isinstance(self.evaluation_engineering,bool):raise ValueError('Invalid engineering evaluation switch')
        from .analysis_catalog import IMAGE_METRICS
        if self.analysis_metrics is not None:
            if not isinstance(self.analysis_metrics,list) or any(not isinstance(k,str) or k not in IMAGE_METRICS for k in self.analysis_metrics):raise ValueError('Invalid selected analyses')
            self.analysis_metrics=list(dict.fromkeys(self.analysis_metrics))
        if self.channels not in {"G","R","B","Y","RGB","RGBY"}: raise ValueError("Invalid channels")
        if self.usaf_threshold_mode not in {"relative","absolute"}:raise ValueError("Invalid USAF threshold mode")
        if not 0<self.rgb_max_shift_px<=128:raise ValueError("RGB shift search must be greater than 0 and at most 128 px")
        if len(self.gray_weights)!=3 or any(not 0<=v<=1 for v in self.gray_weights) or abs(sum(self.gray_weights)-1)>.0001:raise ValueError("Gray weights must be nonnegative and sum to one")
        if not 0<=self.picture_height_px<=1000000:raise ValueError("Invalid picture height")
        if self.transfer not in {"unknown","linear","srgb","gamma","oecf"}: raise ValueError("Invalid transfer")
        if self.oversampling not in {4,8}: raise ValueError("Oversampling must be 4 or 8")
        if self.window not in {"hamming","hann"} or self.edge_fit not in {"linear","quadratic"}: raise ValueError("Invalid SFR settings")
        if self.registration not in {"template","features","anchors","usaf","none","auto_chart"}: raise ValueError("Invalid registration")
        if self.backend not in {"native","mtf_mapper"}: raise ValueError("Invalid backend")
        if self.auto_refine:raise ValueError("自动 ROI 细化尚未启用，请使用四点配准或手工调整")
        if self.workers!=1:raise ValueError("本版逐个文件分析；workers 必须为 1")
        if not 0<self.gamma<=5 or not 0<self.ctf_threshold<1 or not 0<self.target_frequency<.5: raise ValueError("Invalid response settings")
        if not 0<=self.maximum_clip_fraction<1 or not 0<=self.heatmap_alpha<=1: raise ValueError("Invalid clipping/overlay settings")
        if self.memory_mb < 0 or self.cache_gb <= 0 or self.tile_cache_mb < 16: raise ValueError("Invalid resource settings")
        if self.focus_unit not in {"index","mm","um"}: raise ValueError("Invalid focus unit")
        if self.focus_objective not in {"balanced","mean","center"}: raise ValueError("Invalid focus objective")
        if self.transfer=="oecf" and not Path(self.oecf_path).is_file(): raise ValueError("OECF file not found")
        if self.color_matrix_path and not Path(self.color_matrix_path).is_file(): raise ValueError("CCM file not found")
        if self.backend=="mtf_mapper" and not Path(self.mtf_mapper_path).is_file(): raise ValueError("MTF Mapper executable not found")
        return self
    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, data):
        return cls(**{k:v for k,v in data.items() if k in {f.name for f in fields(cls)}})

def config_file():
    p = Path(platformdirs.user_config_dir("MUTEX Imatest", "MUTEX"))
    p.mkdir(parents=True, exist_ok=True)
    return p/"settings.json"

def load_config():
    try:
        config=AnalysisConfig.from_dict(json.loads(config_file().read_text(encoding="utf-8"))).validate()
        # Desktop launchers may start in a read-only installation directory.
        # Old result imports could persist another process's relative cache;
        # preferences use the per-user default when that base is ambiguous.
        if config.cache_dir and not Path(config.cache_dir).is_absolute():config.cache_dir=''
        return config
    except (ValueError, OSError, TypeError): return AnalysisConfig()

def save_config(config):
    from .utils import atomic_json
    config.validate()
    atomic_json(config_file(), config.to_dict())
