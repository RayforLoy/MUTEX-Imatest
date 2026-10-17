"""Repeatable test plans and auditable pass/fail records, separate from sessions."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import uuid
import numpy as np
from .models import plain


def evaluate_limits(result, limits):
    if not isinstance(limits, list) or not limits:
        raise ValueError("判定计划必须至少含一条 limits 规则")
    rows = []
    from .resolution import RAW_METRIC_KINDS
    for limit in limits:
        if not isinstance(limit, dict) or not isinstance(limit.get("metric"), str) or not ({"min", "max"} & limit.keys()):
            raise ValueError("每条规则需要 metric 与 min/max")
        low, high = limit.get("min"), limit.get("max")
        if (low is None and high is None) or any(v is not None and (isinstance(v,bool) or not isinstance(v, (int, float)) or not np.isfinite(v)) for v in (low, high)) or (low is not None and high is not None and low > high):
            raise ValueError("判定上下限无效")
        aggregation = limit.get("aggregation", "all")
        if aggregation not in {"all", "mean", "min", "max", "median"}:
            raise ValueError("aggregation 需为 all/mean/min/max/median")
        expected_kinds=set(limit.get('kinds') or RAW_METRIC_KINDS.get(limit['metric'],set()))
        selected = [m for m in result.measurements if (not limit.get("channel") or m.channel == limit["channel"])
                    and (not limit.get("region_ids") or m.region_id in limit["region_ids"])
                    and (not limit.get("kinds") or m.kind in limit["kinds"])
                    and (limit["metric"] in m.values or m.kind in expected_kinds or bool(limit.get('region_ids')))]
        confidence=float(limit.get('minimum_confidence',.05))
        if not np.isfinite(confidence) or not 0<=confidence<=1:raise ValueError('minimum_confidence 必须位于 0–1')
        valid_measurements=[m for m in selected if m.valid and m.confidence>=confidence and m.metric(limit['metric']) is not None]
        valid = [m.metric(limit["metric"]) for m in valid_measurements]
        minimum_count = limit.get("minimum_count", 1)
        if type(minimum_count) is not int or minimum_count < 1:
            raise ValueError("minimum_count 必须至少为 1")
        complete = len(valid) >= minimum_count
        # Default: every matching measured point must be valid, even when a mean is requested.
        if limit.get("require_all_valid", True) and len(valid) != len(selected):
            complete = False
        if limit.get("region_ids") and not set(limit["region_ids"]) <= {m.region_id for m in selected}:
            complete = False
        key=limit['metric']
        bound_key=(key[:-6] if key.endswith('_stops') else key)+'_lower_bound'
        bounded=[m for m in valid_measurements if m.values.get(bound_key) or
                 (key.startswith('resolution_limit') and {'target_limited','resolution_chart_limited'} & set(m.flags))]
        unit_mismatch=bool(limit.get('unit') and any(m.units.get(key)!=limit['unit'] for m in valid_measurements))
        if (bounded and high is not None) or unit_mismatch:complete=False
        checked = valid if aggregation == "all" else [float(getattr(np, aggregation)(valid))] if valid else []
        passed = bool(complete and checked and all((low is None or v >= low) and (high is None or v <= high) for v in checked))
        rows.append({"metric": limit["metric"], "channel": limit.get("channel", "all"), "aggregation": aggregation,
                     "min": low, "max": high, "valid_count": len(valid), "matched_count": len(selected),
                     "minimum_count": minimum_count, "values": checked, "status": "pass" if passed else "fail",
                     'lower_bound_count':len(bounded),'unit':limit.get('unit'),
                     "reason": "" if passed else '测量单位与规则不一致' if unit_mismatch else '仅测得下界，无法确认该限值' if bounded else "缺少足够有效测点 / 指定区域" if not complete else "指标超出限值"})
    return {"status": "pass" if all(r["status"] == "pass" for r in rows) else "fail", "rules": rows}


class TestDatabase:
    __test__ = False
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS iq_runs (id TEXT PRIMARY KEY, created_utc TEXT NOT NULL, plan_name TEXT NOT NULL, plan_sha256 TEXT NOT NULL, status TEXT NOT NULL, report_json TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def add(self, plan, report):
        run_id = uuid.uuid4().hex
        stamp = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(json.dumps(plain(plan), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.connect() as connection:
            connection.execute("INSERT INTO iq_runs VALUES (?,?,?,?,?,?)", (run_id, stamp, plan.get("name", "测试计划"), digest, report["status"], json.dumps(plain(report), ensure_ascii=False, allow_nan=False)))
        return run_id

    def list(self, limit=100):
        if not 1 <= limit <= 10000:
            raise ValueError("查询数量必须在 1–10000")
        with self.connect() as connection:
            return [dict(zip(("id", "created_utc", "plan_name", "plan_sha256", "status"), row)) for row in connection.execute("SELECT id,created_utc,plan_name,plan_sha256,status FROM iq_runs ORDER BY created_utc DESC LIMIT ?", (limit,))]


def run_plan(plan, destination, config=None, cancel=None, progress=None):
    from .models import AnalysisResult
    from .config import AnalysisConfig
    from .templates import load_chart
    from .analysis.engine import analyze
    from .utils import check_cancel, atomic_json
    if plan.get("version") != 1 or not isinstance(plan.get("tests"), list) or not plan["tests"]:
        raise ValueError("测试计划需要 version:1 和非空 tests")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    report = {"name": plan.get("name", "测试计划"), "status": "pass", "tests": []}
    progress = progress or (lambda *args: None)
    for i, test in enumerate(plan["tests"]):
        check_cancel(cancel)
        progress(int(100*i/len(plan["tests"])), f"运行 {test.get('name', i+1)}")
        row = {"name": test.get("name", str(i+1)), "image": test.get("image")}
        try:
            if test.get("result"):
                result = AnalysisResult.load(test["result"])
            else:
                settings = AnalysisConfig.from_dict({**(config or AnalysisConfig()).to_dict(), **test.get("config", {})}).validate()
                result = analyze(test["image"], load_chart(test["chart"]), settings, cancel)
            result_path = destination/f"test-{i+1:03d}-result.json"
            result.save(result_path)
            row.update(evaluate_limits(result, test.get("limits", plan.get("limits", []))))
            row.update(result_file=str(result_path), source_sha256=result.image.fingerprint, algorithm=result.settings.get("algorithm_version"))
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            row.update(status="error", reason=str(exc))
        if row["status"] != "pass":
            report["status"] = "fail"
        report["tests"].append(row)
    database = TestDatabase(plan.get("database") or destination/"test-history.sqlite")
    report["run_id"] = database.add(plan, report)
    report["database"] = str(database.path)
    atomic_json(destination/"test-plan-result.json", report)
    return report
