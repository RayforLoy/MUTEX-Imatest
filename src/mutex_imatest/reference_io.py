"""Local CSV/CGATS chart references. Patch identifiers are never silently reordered."""
from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import io
import shlex
import numpy as np


def read_reference(path, kind="auto", illuminant="D50"):
    path = Path(path)
    payload = path.read_bytes()
    if len(payload) > 8*2**20:
        raise ValueError("图卡参考文件超过 8 MiB")
    try:text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:text = payload.decode('cp1252',errors='strict')
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError("参考文件为空")
    fields, rows = None, []
    upper = [line.upper() for line in lines]
    if "BEGIN_DATA_FORMAT" in upper:
        start, end = upper.index("BEGIN_DATA_FORMAT"), upper.index("END_DATA_FORMAT")
        fields = shlex.split(" ".join(lines[start+1:end]))
        start, end = upper.index("BEGIN_DATA"), upper.index("END_DATA")
        rows = [shlex.split(line) for line in lines[start+1:end]]
        for line in lines:
            tokens = shlex.split(line)
            if len(tokens) >= 2 and tokens[0].upper() in {"ILLUMINANT", "REFERENCE_ILLUMINANT"} and tokens[1].upper() in {"D50", "D65"}:
                illuminant = tokens[1].upper()
    else:
        delimiter = ";" if ";" in lines[0] else "," if "," in lines[0] else "\t" if "\t" in lines[0] else None
        rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter)) if delimiter else [shlex.split(line) for line in lines]
        try:
            [float(v) for v in rows[0]]
        except ValueError:
            fields = rows.pop(0)
    if not rows or (fields is not None and any(len(row) != len(fields) for row in rows)):
        raise ValueError("参考文件的表头与数据列数不一致")
    if fields is None:
        columns = len(rows[0])
        if columns == 1:
            fields = ["DENSITY"]
        elif columns == 3 and kind in {"auto", "color"}:
            fields = ["LAB_L", "LAB_A", "LAB_B"]
        else:
            raise ValueError("无表头文件仅接受单列密度或三列 Lab；请为其他格式补充表头")
    fields = [f.strip().upper().replace("*", "").replace(" ", "_") for f in fields]
    aliases = {"L": "LAB_L", "A": "LAB_A", "B": "LAB_B", "LSTAR": "LAB_L", "ASTAR": "LAB_A", "BSTAR": "LAB_B",
               "ID": "SAMPLE_ID", "PATCH": "SAMPLE_ID", "PATCH_ID": "SAMPLE_ID", "D": "DENSITY", "D_VIS": "DENSITY",
               "REFERENCE_DENSITY": "DENSITY", "REFERENCE_LUMINANCE": "LUMINANCE"}
    fields = [aliases.get(f, f) for f in fields]
    if len(set(fields)) != len(fields):
        raise ValueError("参考文件包含重复字段")
    records = []
    for number, row in enumerate(rows, 1):
        if len(row) != len(fields):
            raise ValueError(f"参考第 {number} 行列数不一致")
        data = dict(zip(fields, row))
        record = {"id": str(data.get("SAMPLE_ID", number)), "reference_illuminant": illuminant}
        if {"LAB_L", "LAB_A", "LAB_B"} <= data.keys() and any(data[k].strip() for k in ("LAB_L", "LAB_A", "LAB_B")):
            record["reference_lab"] = [float(data[k]) for k in ("LAB_L", "LAB_A", "LAB_B")]
        elif {"XYZ_X", "XYZ_Y", "XYZ_Z"} <= data.keys() and any(data[k].strip() for k in ("XYZ_X", "XYZ_Y", "XYZ_Z")):
            import colour
            white = colour.CCS_ILLUMINANTS["CIE 1931 2 Degree Standard Observer"][illuminant]
            record["reference_lab"] = colour.XYZ_to_Lab(np.array([float(data[k]) for k in ("XYZ_X", "XYZ_Y", "XYZ_Z")])/100, illuminant=white).tolist()
        if data.get("DENSITY",'').strip():
            record["reference_density"] = float(data["DENSITY"])
        if data.get("LUMINANCE",'').strip():
            record["reference_luminance"] = float(data["LUMINANCE"])
        if len(record) == 2:
            raise ValueError("参考文件需要 Lab、XYZ、density 或 luminance 字段；不支持从未知光谱或 RGB 猜测参考值")
        numeric = [v for k, v in record.items() if k not in {"id", "reference_illuminant"}]
        if not all(np.all(np.isfinite(v)) for v in numeric):
            raise ValueError("参考值包含非有限数字")
        if "reference_lab" in record and not 0 <= record["reference_lab"][0] <= 100:
            raise ValueError("Lab L 必须位于 0–100")
        if record.get("reference_luminance", 1) <= 0 or not -2 <= record.get("reference_density", 0) <= 15:
            raise ValueError("无效密度或亮度参考")
        records.append(record)
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("参考文件包含重复色块编号")
    return {"records": records, "sha256": hashlib.sha256(payload).hexdigest(),
            "filename": path.name, "illuminant": illuminant, "format": "CGATS" if "BEGIN_DATA_FORMAT" in upper else "CSV/text"}


def attach_references(regions, reference, *, match="id", transmissive=False):
    from copy import deepcopy
    regions = deepcopy(regions)
    patches = [r for r in regions if r.kind in {"color", "step"}]
    records = reference["records"]
    if match not in {"id", "order"}:
        raise ValueError("参考匹配只能选择 id 或 order")
    if len(patches) != len(records):
        raise ValueError(f"参考块数 {len(records)} 与测量块数 {len(patches)} 不一致")
    by_id = {r["id"]: r for r in records}
    for index, region in enumerate(patches):
        record = records[index] if match == "order" else by_id.get(str(region.params.get("patch_id", region.id)))
        if record is None:
            raise ValueError(f"参考文件没有编号 {region.params.get('patch_id', region.id)}；请明确选择按顺序匹配或修正编号")
        region.params.update({k: v for k, v in record.items() if k != "id"})
        region.params["reference_sha256"] = reference["sha256"]
        region.params["transmissive"] = bool(transmissive)
        if region.kind == "color" and "reference_lab" not in record:
            if "reference_density" in record or "reference_luminance" in record:
                region.kind = "step"
            else:
                raise ValueError("色块缺少 Lab 参考")
        if region.kind == "color":
            region.params["rgb_space"] = "sRGB"
        elif region.kind=='step' and not {'reference_density','reference_luminance'} & record.keys() and 'reference_lab' in record:
            lightness=float(record['reference_lab'][0])
            region.params['reference_luminance']=((lightness+16)/116)**3 if lightness>8 else lightness/903.3
            if region.params['reference_luminance']<=0:raise ValueError('灰阶 Lab 参考亮度必须大于 0')
            region.params['reference_conversion']='CIE L* to relative Y'
    return regions
