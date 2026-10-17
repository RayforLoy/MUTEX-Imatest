from __future__ import annotations

import json
import numpy as np
import pytest
import tifffile

from mutex_imatest.lab import WORKFLOWS, run_workflow, export_lab_report
from mutex_imatest.lab_evaluation import (
    RULES, RULE_VERSION, assess_workflow, evaluation_html, evaluation_text,
    workflow_reference_text,
)


def item(result, metric):
    return next(row for row in result["items"] if row["metric"] == metric)


@pytest.mark.parametrize("kind", list(WORKFLOWS))
def test_all_workflows_have_reference_criteria_and_missing_values_never_pass(kind):
    assert set(RULES) == set(WORKFLOWS)
    result = assess_workflow(kind, {})
    assert result["rule_version"] == RULE_VERSION
    assert result["items"]
    for row in result["items"]:
        assert all(row[key] for key in ("name", "unit", "reference", "criteria", "basis", "verdict", "explanation", "action"))
        assert row["verdict"] not in {"within_target", "complete"}
    assert "工程建议" in workflow_reference_text(kind)
    json.dumps(result, allow_nan=False)


def test_identical_images_keep_psnr_infinity_distinct_from_missing_and_zero():
    result = assess_workflow("compare", {"identical": True, "mse": 0., "ssim": 1., "psnr_db": None})
    psnr = item(result, "psnr_db")
    assert psnr["value"] is None and psnr["display_value"].startswith("+∞")
    assert psnr["verdict"] == "reference"
    assert "+∞（MSE=0）" in evaluation_html(result)
    assert item(assess_workflow("compare", {}), "psnr_db")["verdict"] == "insufficient"
    assert item(assess_workflow("compare", {"psnr_db": 0}), "psnr_db")["value"] == 0


@pytest.mark.parametrize("value,verdict", [(39.99, "outside_target"), (40., "within_target"), (50., "within_target"), (50.01, "outside_target"), (None, "insufficient"), (float("nan"), "insufficient"), (float("inf"), "insufficient")])
def test_targets_are_native_unit_inclusive_and_finite(value, verdict):
    result = assess_workflow("compare", {"psnr_db": value}, {"evaluation_targets": {"psnr_db": {"min": 40., "max": 50.}}})
    row = item(result, "psnr_db")
    assert row["verdict"] == verdict
    assert row["target"] == {"min": 40., "max": 50.}
    assert "用户目标" in row["basis"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("target", [{"min": float("inf")}, {"min": 2, "max": 1}, {}, {"max": True}, {"min": None}])
def test_invalid_target_cannot_pass(target):
    result = assess_workflow("compare", {"ssim": .99}, {"evaluation_targets": {"ssim": target}})
    assert item(result, "ssim")["verdict"] == "invalid"


@pytest.mark.parametrize("markers", [{"valid": False}, {"status": "invalid"}, {"flags": ["missing_reference"]}, {"flags": ["uncalibrated"]}])
def test_invalid_or_uncalibrated_output_is_not_rescued_by_good_numbers(markers):
    result = assess_workflow("compare", {"ssim": 1., **markers}, {"evaluation_targets": {"ssim": {"min": .9}}})
    assert item(result, "ssim")["verdict"] == "invalid"


def test_bound_is_not_reported_as_exact_qualified_measurement():
    result = assess_workflow("rank", {"ranking": [{"mtf50": .4}], "flags": ["lower_bound"]}, {"evaluation_targets": {"best_mtf50": {"min": .3}}})
    assert item(result, "best_mtf50")["verdict"] == "estimate"


def test_ptc_engineering_fit_advice_is_distinct_from_sensor_quality():
    output = {"ptc_r_squared": .98, "gain_dn_per_e": .25, "gain_e_per_dn": 4., "estimated_full_well_e": 90000, "estimated_dynamic_range_stops": 14, "read_noise_e": 2}
    targets = {"evaluation_targets": {"gain_e_per_dn": {"min": 3}, "estimated_full_well_e": {"min": 10000}}}
    result = assess_workflow("ptc", output, targets)
    assert item(result, "gain_e_per_dn")["verdict"] == "within_target"
    assert item(result, "ptc_r_squared")["verdict"] == "reference"
    assert item(result, "estimated_full_well_e")["verdict"] == "estimate"
    assert item(result, "estimated_dynamic_range_stops")["verdict"] == "estimate"
    assert "工程" in item(result, "ptc_r_squared")["basis"]
    output["ptc_r_squared"] = .979999
    assert item(assess_workflow("ptc", output, targets), "gain_e_per_dn")["verdict"] == "review"
    output["ptc_r_squared"] = .999
    output["gain_e_per_dn"] = 5.
    assert item(assess_workflow("ptc", output, targets), "gain_e_per_dn")["verdict"] == "invalid"


def temporal_output(within=True):
    block = {"settling_seconds": .5 if within else None, "within_tolerance": within, "overshoot_pct": 2.}
    return {"summary": {"ae": block, "focus": block, "awb_r_g": block, "awb_b_g": block},
            "frames": [{"dx_px": 0, "dy_px": 0}, {"dx_px": None, "dy_px": None}, {"dx_px": 1, "dy_px": 2}]}


def test_temporal_metrics_require_real_step_or_confirmed_neutral_roi():
    targets = {"evaluation_targets": {"ae.settling_seconds": {"max": 1}, "awb_r_g.settling_seconds": {"max": 1}}}
    result = assess_workflow("video", temporal_output(), targets)
    assert item(result, "ae.settling_seconds")["verdict"] == "insufficient"
    assert item(result, "awb_r_g.settling_seconds")["verdict"] == "insufficient"
    result = assess_workflow("video", temporal_output(), {**targets, "step_declared": True, "neutral_roi_confirmed": True})
    assert item(result, "ae.settling_seconds")["verdict"] == "within_target"
    assert item(result, "awb_r_g.settling_seconds")["verdict"] == "within_target"
    assert item(result, "motion_valid_fraction")["value"] == .5
    result = assess_workflow("video", temporal_output(False), {**targets, "step_declared": True})
    assert item(result, "ae.settling_seconds")["verdict"] == "review"
    assert item(result, "ae.settling_seconds")["value"] is None


def test_sequence_prnu_requires_flat_confirmation_and_is_not_read_noise():
    output = {"noise": {"prnu_pct": .2, "temporal_noise": .001}}
    params = {"evaluation_targets": {"noise.prnu_pct": {"max": 1}}}
    assert item(assess_workflow("sequence", output, params), "noise.prnu_pct")["verdict"] == "insufficient"
    row = item(assess_workflow("sequence", output, {**params, "uniform_roi_confirmed": True}), "noise.prnu_pct")
    assert row["verdict"] == "within_target"
    assert "e⁻" in item(assess_workflow("sequence", output), "noise.temporal_noise")["criteria"]


def test_ccm_is_training_error_and_unknown_transfer_cannot_pass():
    output = {"mean_delta_e_before": 4, "mean_delta_e_after": 2, "delta_e_2000_after": [1, 3]}
    params = {"evaluation_targets": {"mean_delta_e_after": {"max": 2}}, "_input_transfer": "unknown"}
    result = assess_workflow("ccm", output, params)
    assert item(result, "mean_delta_e_after")["verdict"] == "review"
    assert item(result, "max_delta_e_after")["value"] == 3
    assert item(result, "delta_e_reduction_pct")["value"] == 50
    assert "拟合色块" in item(result, "mean_delta_e_after")["name"]
    output["mean_delta_e_before"] = 0
    assert item(assess_workflow("ccm", output), "delta_e_reduction_pct")["value"] is None


def test_oecf_coverage_and_monotonicity_do_not_claim_full_range_calibration():
    output = {"encoded": [.1, .3, .6, .8], "linear": [.01, .1, .4, 1]}
    result = assess_workflow("oecf", output)
    assert item(result, "monotonic")["verdict"] == "reference"
    assert item(result, "encoded_coverage")["value"] == pytest.approx(.7)
    assert "饱和" in item(result, "encoded_max")["criteria"]
    output["encoded"][2] = .3
    assert item(assess_workflow("oecf", output), "monotonic")["verdict"] == "invalid"


def test_calibration_rms_has_no_universal_pass_line_and_reports_worst_view():
    result = assess_workflow("calibrate", {"rms_px": .1, "per_view_rms_px": [.05, .7], "view_count": 5})
    assert item(result, "rms_px")["verdict"] == "needs_target"
    assert item(result, "max_per_view_rms_px")["value"] == .7
    assert item(result, "view_count")["verdict"] == "reference"


def test_file_operations_and_simulation_are_not_quality_passes():
    result = assess_workflow("undistort", {"corrected_count": 3})
    assert item(result, "corrected_count")["verdict"] == "complete"
    assert item(result, "validation_residual_px")["verdict"] == "insufficient"
    result = assess_workflow("simulate", {"read_noise_e": 1}, {"evaluation_targets": {"read_noise_e": {"max": 3}}})
    assert item(result, "read_noise_e")["verdict"] == "configured"
    result = assess_workflow("capture", {"captured": 3, "requested": 4, "complete": True})
    assert item(result, "complete")["verdict"] == "incomplete"


def test_plan_pass_string_requires_auditable_rules_and_values():
    assert item(assess_workflow("test_plan", {"status": "pass", "tests": []}), "status")["verdict"] == "insufficient"
    rule = {"metric": "mtf50", "status": "pass", "min": .2, "valid_count": 2, "minimum_count": 2, "matched_count": 2, "values": [.25, .3]}
    output = {"status": "pass", "tests": [{"name": "check", "status": "pass", "rules": [rule]}]}
    result = assess_workflow("test_plan", output)
    assert item(result, "status")["verdict"] == "within_target"
    rule["values"] = []
    assert item(assess_workflow("test_plan", output), "status")["verdict"] == "insufficient"
    rule["values"] = [.25]
    rule["valid_count"] = 0
    assert item(assess_workflow("test_plan", output), "status")["verdict"] == "insufficient"


def test_plan_keeps_individual_rule_pass_when_a_different_rule_fails():
    passed = {"metric": "mtf50", "status": "pass", "min": .2, "valid_count": 1, "minimum_count": 1, "matched_count": 1, "values": [.25]}
    failed = {**passed, "status": "fail", "values": [.1]}
    output = {"status": "fail", "tests": [{"name": "mixed", "status": "fail", "rules": [passed, failed]}]}
    result = assess_workflow("test_plan", output)
    assert item(result, "status")["verdict"] == "outside_target"
    assert item(result, "test.1.rule.1")["verdict"] == "within_target"
    assert item(result, "test.1.rule.2")["verdict"] == "outside_target"


def test_saved_workflow_assessment_matches_html_and_simulation_accepts_targets(tmp_path, config):
    source = tmp_path/"source.tif"
    tifffile.imwrite(source, np.full((32, 32), 20000, np.uint16))
    spec = {"workflow": "compare", "files": [str(source)]*2,
            "parameters": {"roi": [0, 0, 32, 32], "evaluation_targets": {"ssim": {"min": .99}}}}
    report = run_workflow(spec, tmp_path/"comparison", config)
    saved = json.loads((tmp_path/"comparison/lab-result.json").read_text(encoding="utf-8"))
    assert saved["evaluation"] == report["evaluation"]
    assert item(report["evaluation"], "ssim")["verdict"] == "within_target"
    content = (tmp_path/"comparison/report.html").read_text(encoding="utf-8")
    assert "达到用户目标" in content and "规则版本" in content and "+∞（MSE=0）" in content
    assert "ece.uwaterloo.ca" in content
    result = run_workflow({"workflow": "simulate", "files": [str(source)], "parameters": {"roi": [0, 0, 32, 32], "evaluation_targets": {"clipped_fraction": {"max": .01}}}}, tmp_path/"simulation", config)
    assert result["evaluation"]["items"]


def test_html_escapes_user_text_and_legacy_report_can_show_assessment(tmp_path):
    report = {"workflow": "capture", "name": "capture", "created_utc": "test", "output": {"captured": 1, "requested": 1, "complete": True}, "specification": {}}
    export_lab_report(report, tmp_path)
    assert "采集任务完整性" in (tmp_path/"report.html").read_text(encoding="utf-8")
    result = assess_workflow("compare", {"ssim": .99}, {"evaluation_targets": {"ssim": {"min": "<script>x</script>"}}})
    assert "<script>" not in evaluation_html(result)
    assert "参考" in evaluation_text(result)


def test_workbench_shows_reference_help_and_result_evaluation(qtbot, config, tmp_path):
    from mutex_imatest.ui.iq_workbench import WorkbenchDialog
    dialog = WorkbenchDialog(config); qtbot.addWidget(dialog)
    assert "结构相似度" in dialog.result.toPlainText()
    dialog.workflow.setCurrentIndex(dialog.workflow.findData("video"))
    assert "step_declared" in dialog.hint.text()
    assert dialog.specification()["parameters"]["step_declared"] is False
    data = {"workflow": "compare", "output": {"ssim": .98}, "evaluation": assess_workflow("compare", {"ssim": .98})}
    path = tmp_path/"lab-result.json"; path.write_text(json.dumps(data), encoding="utf-8")
    dialog.on_event("test", {"type": "done", "lab_result": str(path), "report": str(tmp_path/"report.html")})
    assert "结构相似度" in dialog.result.toPlainText() and "待设目标" in dialog.result.toPlainText()
    dialog.reject()
