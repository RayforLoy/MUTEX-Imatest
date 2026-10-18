from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json, math
import numpy as np
from . import __version__

SCHEMA_VERSION = 1
RAW_EXTENSIONS = {".arw", ".srf", ".sr2", ".nef", ".nrw", ".raf", ".cr2", ".cr3", ".crw", ".dng", ".rw2", ".orf", ".pef", ".3fr", ".fff", ".iiq", ".rwl", ".mos", ".kdc"}
IMAGE_EXTENSIONS = RAW_EXTENSIONS | {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".bmp"}
REGION_KINDS = {"edge", "usaf", "star", "wedge", "flat", "step", "color", "grid", "point", "texture"}
REGION_KINDS.update({"dot", "logf", "flare", "rings"})
FATAL_FLAGS = {"clipped", "low_contrast", "invalid_edge", "insufficient_samples", "aliasing", "missing_frequency", "unsupported_pattern", "roi_outside", "fit_failed", "missing_reference", "missing_calibration", "registration_failed"}
FATAL_FLAGS.update({"rgb_alignment_failed","invalid_ctf_reference","insufficient_frequency_samples","template_occluded"})
FATAL_FLAGS.update({"target_mismatch","star_geometry_invalid"})

def plain(value):
    if isinstance(value, np.ndarray): return plain(value.tolist())
    if isinstance(value, np.generic): return plain(value.item())
    if isinstance(value, Path): return str(value)
    if isinstance(value, float): return value if math.isfinite(value) else None
    if isinstance(value, dict): return {str(k): plain(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [plain(v) for v in value]
    return value

@dataclass
class Region:
    id: str
    kind: str
    box: tuple[float,float,float,float]
    label: str = ""
    params: dict = field(default_factory=dict)
    enabled: bool = True
    def __post_init__(self):
        self.box = tuple(float(v) for v in self.box)
        if not self.id or self.kind not in REGION_KINDS: raise ValueError("Invalid region id or kind")
        if len(self.box) != 4 or not all(math.isfinite(v) for v in self.box): raise ValueError("Invalid ROI")
        x,y,w,h = self.box
        if min(x,y) < 0 or min(w,h) <= 0 or x+w > 1.00001 or y+h > 1.00001: raise ValueError("ROI must be inside normalized chart coordinates")

@dataclass
class ChartDefinition:
    id: str
    name: str
    regions: list[Region]
    physical_size_mm: tuple[float,float] | None = None
    reference_size: tuple[int,int] = (1,1)
    calibrated: bool = False
    fiducials: list = field(default_factory=list)
    preview: str | None = None
    source_path: str | None = None
    source_page: int = 0
    asset_license: str = "User supplied; no redistribution permission assumed"
    schema_version: int = SCHEMA_VERSION
    notes: str = ""
    aliases: list[str] = field(default_factory=list)
    def __post_init__(self):
        self.regions = [r if isinstance(r, Region) else Region(**r) for r in self.regions]
        if not self.id or not self.name: raise ValueError("Chart id/name required")
        if len({r.id for r in self.regions}) != len(self.regions): raise ValueError("Duplicate ROI ids")
        if self.physical_size_mm:
            self.physical_size_mm = tuple(map(float, self.physical_size_mm))
            if len(self.physical_size_mm)!=2 or min(self.physical_size_mm)<=0: raise ValueError("Invalid chart dimensions")
        if self.calibrated and not self.physical_size_mm: raise ValueError("Calibrated chart needs physical dimensions")
        if self.schema_version != SCHEMA_VERSION: raise ValueError("Unsupported chart schema")
    def to_dict(self): return plain(asdict(self))
    @classmethod
    def from_dict(cls, data): return cls(**data)

@dataclass
class ImageMetadata:
    path: str
    width: int
    height: int
    channels: int
    dtype: str
    bits_per_sample: int
    file_bytes: int
    fingerprint: str
    is_raw: bool = False
    is_linear: bool = False
    orientation: int = 1
    dpi: tuple[float,float] | None = None
    decoder: str = ""
    camera: str = ""
    exposure: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    original_path: str | None = None

@dataclass
class Measurement:
    region_id: str
    label: str
    kind: str
    channel: str
    position: tuple[float,float]
    box_pixels: tuple[int,int,int,int]
    values: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    confidence: float = 1.0
    method: str = ""
    direction_deg: float | None = None
    object_scale_px_per_mm: float | None = None
    diagnostics: dict = field(default_factory=dict)
    @property
    def valid(self): return not bool(FATAL_FLAGS.intersection(self.flags))
    def metric(self, name):
        value = self.values.get(name)
        return float(value) if value is not None and np.isfinite(value) else None

@dataclass
class AnalysisResult:
    image: ImageMetadata
    chart_id: str
    chart_name: str
    measurements: list[Measurement]
    settings: dict
    template: dict
    registration: dict = field(default_factory=dict)
    focus_position: float | None = None
    focus_unit: str = "index"
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)
    app_version: str = __version__
    schema_version: int = SCHEMA_VERSION
    optical_summary: dict = field(default_factory=dict)
    analysis_summary: dict = field(default_factory=dict)
    evaluation_summary: dict = field(default_factory=dict)
    def to_dict(self): return plain(asdict(self))
    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if data.get("schema_version", 1) != 1: raise ValueError("Unsupported result schema")
        data.setdefault("app_version","unknown")
        data["image"] = ImageMetadata(**data["image"])
        data["measurements"] = [Measurement(**r) for r in data["measurements"]]
        return cls(**data)
    def save(self, path):
        from .utils import atomic_json
        atomic_json(path, self.to_dict())
    @classmethod
    def load(cls, path): return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
