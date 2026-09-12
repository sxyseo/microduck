import json
import hashlib
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import pytest

from microduck_studio.core import (
    StudioStore,
    evaluate_compatibility,
    evaluate_bam_record_process,
    evaluate_continuous_test,
    evaluate_controller_health,
    evaluate_probe_process,
    evaluate_tensorboard_summary,
    evaluate_training_smoke,
    list_serial_ports,
    normalize_policy_manifest,
    preflight,
    task_status_for_result,
)


def _complete_deployment_evidence(store: StudioStore, project_id: str) -> None:
    store.save_assembly(
        project_id,
        {"title": "整机装配", "checks": [{"id": "frame", "title": "结构", "status": "passed", "evidence": ["photo://frame"]}]},
    )
    store.save_calibration(
        project_id,
        {
            "operator": "test",
            "verified": True,
            "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}],
        },
    )
    store.set_task_status(project_id, "servo_read", "success")


def test_serial_port_listing_is_read_only_and_never_claims_servo_identity():
    ports = list_serial_ports()

    assert isinstance(ports, list)
    assert all(
        set(item) >= {"port", "description", "source", "identity_confirmed"}
        and isinstance(item["port"], str)
        and item["port"]
        and item["identity_confirmed"] is False
        for item in ports
    )


def test_frontend_uses_separate_bench_and_training_run_slots():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "const activeRuns = {bench: null, training: null};" in html
    assert html.count("pollRun(run, 'bench')") == 2
    assert html.count("pollRun(run, 'training')") == 1
    assert "activeRuns.bench" in html
    assert "activeRuns.training" in html
    assert "activeRunId" not in html


def test_frontend_exposes_servo_only_probe_switch():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="probe-include-imu"' in html
    assert "已接入 ID=200 IMU" in html
    assert "include_imu:$('probe-include-imu').checked" in html
    assert "probe-include-imu').checked, confirm:true" in html


def test_frontend_does_not_guess_a_serial_port():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="probe-port" value=""' in html
    assert 'placeholder="例如 COM3 或 /dev/ttyUSB0"' in html
    assert '"port":""' in html


def test_frontend_hl2915_examples_do_not_claim_old_voltage_or_passed_data():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'placeholder="例如 12.0"' in html
    assert 'value="HL-2915"' in html
    assert '"voltage_v":12' in html
    assert '"voltage_v":[12,12]' in html
    assert '"status":"pending"' in html
    assert '"voltage_v":7.6' not in html
    assert '"voltage_v":[7.4,7.6]' not in html


def test_frontend_resumes_persisted_long_running_jobs_from_report():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "run.kind === 'training_smoke'" in html
    assert "['hl2915_read_only_probe','hl2915_bam_record'].includes(run.kind)" in html
    assert "if (slot && !activeRuns[slot]) pollRun(run, slot);" in html


def test_frontend_hydrates_hardware_form_for_selected_project():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "const hydrateHardwareForm = (hardware) =>" in html
    assert "const data = hardware?.data || {};" in html
    assert "hydrateHardwareForm(data.hardware);" in html
    assert "hydrateHardwareForm(null);" in html
    assert "Array.isArray(servos.candidates) ? servos.candidates.join(',') : ''" in html


def test_frontend_keeps_async_state_scoped_to_selected_project():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "const resetActiveRuns = () => { activeRuns.bench = null; activeRuns.training = null; };" in html
    assert html.count("resetActiveRuns();") >= 2
    assert "const requestedProjectId = projectId;" in html
    assert "if (projectId !== requestedProjectId) return;" in html
    assert "if (activeRuns[slot] === run.id && projectId === run.project_id) show('status', run);" in html


def test_frontend_releases_run_slot_when_polling_fails():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "const runId = run.id;" in html
    assert "fetch(`/api/runs/${runId}`)" in html
    assert "finally {" in html
    assert "if (activeRuns[slot] === runId) activeRuns[slot] = null;" in html


def test_frontend_refreshes_report_after_terminal_run_and_hardware_save():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "const refreshReport = () =>" in html
    assert "!['running','cancelling'].includes(run.status)" in html
    assert "refreshReport();" in html


def test_frontend_exposes_safe_retry_action():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="retry-last-run"' in html
    assert "/api/runs/${candidate.id}/retry" in html
    assert "body:JSON.stringify({confirm:true})" in html
    assert "run.result?.retry_of" in html


def test_frontend_exposes_issue_draft_from_failed_run():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="issue-from-latest-run"' in html
    assert "/issues/from-run/${candidate.id}" in html
    assert "确认将失败运行记录为问题草稿" in html


def test_frontend_issue_can_update_status_resolution_and_evidence():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="issue-update-id"' in html
    assert 'id="issue-update-resolution"' in html
    assert 'id="issue-update-evidence"' in html
    assert "fetch(`/api/issues/${encodeURIComponent(issueId)}`" in html
    assert "method:'PATCH'" in html
    assert 'id="issue-link-run-id"' in html
    assert "/issues/${encodeURIComponent(issueId)}/link-run/${encodeURIComponent(runId)}" in html


def test_frontend_experiment_accepts_explicit_baseline():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="exp-baseline"' in html
    assert 'id="exp-context"' in html
    assert "JSON.parse($('exp-baseline').value)" in html
    assert "JSON.parse($('exp-context').value || '{}'" in html


def test_frontend_experiment_can_record_outcome_and_evidence():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="exp-update-id"' in html
    assert 'id="exp-update-result"' in html
    assert 'id="exp-update-evidence"' in html
    assert "fetch(`/api/experiments/${encodeURIComponent(experimentId)}`" in html
    assert "method:'PATCH'" in html
    assert "if (created.id) $('exp-update-id').value = created.id;" in html
    assert 'id="exp-link-run-id"' in html
    assert "/link-run/${encodeURIComponent(runId)}" in html
    assert "fetch(`/api/runs/${encodeURIComponent(runId)}`" in html
    assert "JSON.stringify({run_id: run.id" in html


def test_frontend_report_lists_experiment_ids_and_decisions():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "data.experiments?.length" in html
    assert "实验记录：" in html
    assert "exp.id" in html
    assert "exp.decision" in html
    assert "exp.evidence_details?.length" in html
    assert "运行证据" in html


def test_frontend_report_lists_current_assembly_material_summary():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "data.assemblies?.length" in html
    assert "assembly.material_summary" in html
    assert "物料状态：" in html


def test_frontend_report_lists_issue_status_resolution_and_evidence():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "data.issues?.length" in html
    assert "issue.evidence_details?.length" in html
    assert "item.source_kind" in html
    assert "问题台账：" in html


def test_frontend_exposes_structured_evidence_search():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'id="record-search-query"' in html
    assert 'id="record-search-type"' in html
    assert 'id="record-search-status"' in html
    assert 'id="record-search-body"' in html
    assert "/evidence-search?q=${encodeURIComponent(query)}" in html
    assert "&type=${encodeURIComponent(recordType)}" in html
    assert "&status=${encodeURIComponent(recordStatus)}" in html
    assert 'id="record-detail-id"' in html
    assert "/evidence/${encodeURIComponent(evidenceId)}" in html


def test_frontend_report_prefills_first_evidence_detail_id():
    html = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert "const reportEvidenceRefs" in html
    assert "$('record-detail-id').value" in html


def test_preflight_route_marks_task_running_before_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from microduck_studio import app as studio_app

    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("预检状态", tmp_path)
    monkeypatch.setattr(studio_app, "store", store)

    def fake_preflight(root):
        task = next(item for item in store.project_report(project["id"])["tasks"] if item["id"] == "preflight")
        assert task["status"] == "running"
        return {"status": "passed", "root": root}

    monkeypatch.setattr(studio_app, "preflight", fake_preflight)

    result = studio_app.run_preflight(project["id"])

    assert result["status"] == "passed"


def test_project_search_returns_safe_relative_matches(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "docs").mkdir()
    (project_root / "docs" / "guide.md").write_text(
        "先确认 HL-2915 路线\nAPI_TOKEN=do-not-leak\n", encoding="utf-8"
    )
    (project_root / ".git").mkdir()
    (project_root / ".git" / "ignored.md").write_text("HL-2915", encoding="utf-8")
    project = store.create_project("资料搜索", project_root)

    result = store.search_project(project["id"], "HL-2915")

    assert result["query"] == "HL-2915"
    assert result["truncated"] is False
    assert result["results"] == [
        {"path": "docs/guide.md", "line": 1, "text": "先确认 HL-2915 路线"}
    ]
    assert "ignored.md" not in str(result)
    secret = store.search_project(project["id"], "API_TOKEN")
    assert "do-not-leak" not in str(secret)


def test_evidence_search_finds_records_without_returning_full_logs(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("证据检索", tmp_path)
    source = store.save_source(project["id"], {"kind": "training", "location": "microduck_rl", "revision": "abc123"})
    issue = store.create_issue(
        project["id"], {"title": "串口占用", "symptom": "打开端口超时", "evidence_refs": [source["id"]]}
    )
    run = store.start_run(project["id"], "bench_continuous")
    store.finish_run(run["id"], "failed", {"status": "failed", "stderr": "secret-token", "reasons": ["timeout"]})

    result = store.search_evidence(project["id"], "串口占用")
    run_result = store.search_evidence(project["id"], run["id"])

    assert result["results"][0]["type"] == "issue"
    assert result["results"][0]["id"] == issue["id"]
    assert run_result["results"][0]["type"] == "run"
    assert "secret-token" not in str(run_result)


def test_evidence_search_rejects_empty_query(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("证据检索校验", tmp_path)

    with pytest.raises(ValueError, match="must not be empty"):
        store.search_evidence(project["id"], " ")


def test_evidence_search_filters_by_record_type_and_status(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("证据筛选", tmp_path)
    failed = store.start_run(project["id"], "bench_continuous")
    store.finish_run(failed["id"], "failed", {"status": "failed", "reasons": ["timeout"]})
    passed = store.start_run(project["id"], "bench_continuous")
    store.finish_run(passed["id"], "passed", {"status": "passed", "reasons": ["timeout"]})

    filtered = store.search_evidence(project["id"], "timeout", record_type="run", status="failed")
    no_issue = store.search_evidence(project["id"], "timeout", record_type="issue")

    assert [item["id"] for item in filtered["results"]] == [failed["id"]]
    assert no_issue["results"] == []

    with pytest.raises(ValueError, match="record type"):
        store.search_evidence(project["id"], "timeout", record_type="unknown")


def test_evidence_detail_resolves_owned_record_and_redacts_run_output(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("证据详情", tmp_path)
    run = store.start_run(project["id"], "bench_continuous")
    store.finish_run(run["id"], "failed", {"status": "failed", "stderr": "Authorization: Bearer secret-value"})

    detail = store.get_evidence_detail(project["id"], run["id"])

    assert detail["type"] == "run"
    assert detail["id"] == run["id"]
    assert "secret-value" not in str(detail)


def test_evidence_detail_rejects_record_from_other_project(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    first = store.create_project("证据详情甲", tmp_path / "first")
    second = store.create_project("证据详情乙", tmp_path / "second")
    run = store.start_run(first["id"], "bench_continuous")

    with pytest.raises(KeyError, match="evidence"):
        store.get_evidence_detail(second["id"], run["id"])


def test_hardware_conflict_stays_unresolved(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("我的鸭子", tmp_path)

    profile = store.save_hardware(
        project["id"],
        {
            "servos": {"model": None, "candidates": ["HL-1910", "HL-2915"]},
            "controller": "Radxa Zero 3W",
        },
    )

    assert profile["status"] == "needs_confirmation"
    assert profile["data"]["servos"]["model"] is None
    assert profile["data"]["servos"]["candidates"] == ["HL-1910", "HL-2915"]
    assert "servos.model" in profile["completeness"]["missing_fields"]

    unknown = store.save_hardware(project["id"], {"servos": {}})
    assert unknown["status"] == "needs_confirmation"

    malformed = store.save_hardware(project["id"], {"servos": {"model": 2915, "candidates": [2915]}})
    assert malformed["status"] == "needs_confirmation"

    malformed_candidates = store.save_hardware(
        project["id"], {"servos": {"model": "HL-2915", "candidates": 2915}}
    )
    assert malformed_candidates["status"] == "needs_confirmation"


def test_hardware_profile_reports_completeness_without_changing_route_status(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("档案显示", tmp_path)

    incomplete = store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "controller": "待确认"},
    )

    assert incomplete["status"] == "confirmed"
    assert incomplete["completeness"]["status"] == "incomplete"
    assert {
        "servos.count",
        "controller.model",
        "imu.model",
        "power.voltage_v",
        "printed_parts.version",
        "runtime.version",
        "training.repo",
        "training.revision",
    } <= set(incomplete["completeness"]["missing_fields"])

    malformed = store.save_hardware(
        project["id"],
        {
            "servos": {"model": "HL-2915", "count": 12, "candidates": ["HL-2915"]},
            "controller": {"model": 123},
            "imu": {"model": []},
            "power": {"voltage_v": 0},
            "printed_parts": {"version": {}},
            "runtime": {"version": True},
            "training": {"repo": [], "revision": 0},
        },
    )
    assert {
        "controller.model",
        "imu.model",
        "power.voltage_v",
        "printed_parts.version",
        "runtime.version",
        "training.repo",
        "training.revision",
    } <= set(malformed["completeness"]["missing_fields"])

    complete = store.save_hardware(
        project["id"],
        {
            "servos": {"model": "HL-2915", "count": 12, "candidates": ["HL-2915"]},
            "controller": {"model": "Radxa Zero 3W"},
            "imu": {"model": "BMI270"},
            "power": {"voltage_v": 7.4},
            "printed_parts": {"version": "v1"},
            "runtime": {"version": "abc123"},
            "training": {"repo": "microduck_rl", "revision": "def456"},
        },
    )

    assert complete["status"] == "confirmed"
    assert complete["completeness"] == {"status": "complete", "missing_fields": []}
    assert store.project_report(project["id"])["hardware"]["completeness"]["status"] == "complete"
    assert "`complete`" in store.project_report_markdown(project["id"])


def test_save_hardware_rejects_unknown_project(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")

    with pytest.raises(KeyError):
        store.save_hardware("missing-project", {"servos": {"model": "HL-2915"}})


def test_start_run_rejects_unknown_project(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")

    with pytest.raises(KeyError):
        store.start_run("missing-project", "preflight")


def test_next_task_exposes_evidence_and_failure_contract(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("任务卡契约", tmp_path)

    task = store.next_task(project["id"])

    assert task["id"] == "hardware"
    assert task["card"]["preconditions"]
    assert task["card"]["evidence_required"]
    assert task["card"]["acceptance"]
    assert task["card"]["failure_handling"]
    assert task["card"]["outputs"]
    for item in store.project_report(project["id"])["tasks"]:
        assert item["card"]["estimated_minutes"] > 0
        assert item["card"]["tools"]
        assert item["card"]["steps"]


def test_task_report_explains_missing_assembly_and_calibration_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("证据原因", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    store.set_task_status(project["id"], "servo_read", "success")
    store.save_calibration(
        project["id"],
        {
            "operator": "abel",
            "verified": False,
            "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}],
        },
    )

    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}

    assert tasks["assembly"]["evidence_reasons"] == ["current_assembly_record_required"]
    assert tasks["calibration"]["evidence_reasons"] == ["operator_verification_required"]


def test_continuous_test_uses_raw_packet_loss_not_script_pass():
    result = evaluate_continuous_test(
        {"packets_sent": 1000, "packets_lost": 1, "duration_s": 60, "script_pass": True},
        required_duration_s=60,
    )

    assert result["status"] == "failed"
    assert result["rule_version"] == "continuous-test-v1"
    assert result["packet_loss_rate"] == pytest.approx(0.001)
    assert "packet_loss" in result["reasons"]


def test_continuous_test_record_requires_hardware_and_saves_binding(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("连续测试绑定", tmp_path)
    raw = {"packets_sent": 10, "packets_lost": 0, "duration_s": 60}

    missing = store.record_continuous_test(project["id"], raw, 60)

    assert missing["status"] == "insufficient_evidence"
    assert "hardware_confirmation_required" in missing["result"]["reasons"]
    assert missing["result"]["guidance"]["next_checks"]
    tasks = {item["id"]: item for item in store.project_report(project["id"])["tasks"]}
    assert tasks["servo_read"]["status"] == "blocked"

    hardware = store.save_hardware(
        project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}}
    )
    passed = store.record_continuous_test(project["id"], raw, 60)

    assert passed["status"] == "passed"
    assert passed["result"]["hardware_profile_id"] == hardware["id"]
    assert passed["result"]["raw"] == raw


def test_continuous_test_rejects_impossible_packet_counts():
    result = evaluate_continuous_test(
        {"packets_sent": 10, "packets_lost": 11, "duration_s": 60},
        required_duration_s=60,
    )

    assert result["status"] == "failed"
    assert "invalid_packet_counts" in result["reasons"]


def test_bench_failures_include_evidence_guidance():
    continuous = evaluate_continuous_test(
        {"packets_sent": 100, "packets_lost": 2, "duration_s": 60}, 60
    )
    probe = evaluate_probe_process(
        returncode=0,
        timed_out=False,
        stdout="protocol Ping 正常",
        stderr="",
        duration_s=10,
        required_duration_s=10,
    )

    assert "packet_loss" in continuous["guidance"]["current_facts"][0]
    assert continuous["guidance"]["next_checks"]
    assert "missing_probe_summary" in probe["guidance"]["current_facts"][0]
    assert probe["guidance"]["missing_evidence"]
    assert probe["guidance"]["next_checks"]


def test_continuous_test_marks_malformed_raw_data_as_insufficient():
    result = evaluate_continuous_test(
        {"packets_sent": "unknown", "packets_lost": 0, "duration_s": 60},
        required_duration_s=60,
    )

    assert result["status"] == "insufficient_evidence"
    assert "malformed_input" in result["reasons"]


def test_continuous_test_rejects_non_boolean_cancel_flag():
    result = evaluate_continuous_test(
        {"packets_sent": 100, "packets_lost": 0, "duration_s": 60, "cancelled": "false"},
        60,
    )

    assert result["status"] == "insufficient_evidence"
    assert result["reasons"] == ["malformed_input"]


def test_continuous_test_rejects_fractional_packet_counts():
    result = evaluate_continuous_test(
        {"packets_sent": 1000.5, "packets_lost": 0, "duration_s": 60},
        required_duration_s=60,
    )

    assert result["status"] == "insufficient_evidence"
    assert "malformed_input" in result["reasons"]


def test_continuous_test_rejects_nonfinite_duration():
    result = evaluate_continuous_test(
        {"packets_sent": 1000, "packets_lost": 0, "duration_s": float("nan")},
        required_duration_s=60,
    )

    assert result["status"] == "insufficient_evidence"
    assert "malformed_input" in result["reasons"]


def test_continuous_test_rejects_invalid_required_duration():
    result = evaluate_continuous_test(
        {"packets_sent": 1000, "packets_lost": 0, "duration_s": 60},
        required_duration_s=float("nan"),
    )

    assert result["status"] == "insufficient_evidence"
    assert "invalid_required_duration" in result["reasons"]


def test_continuous_test_does_not_fill_missing_fields_with_zero():
    result = evaluate_continuous_test(
        {"packets_sent": 1000, "duration_s": 60},
        required_duration_s=60,
    )

    assert result["status"] == "insufficient_evidence"
    assert result["packet_loss_rate"] is None
    assert result["missing_fields"] == ["packets_lost"]
    assert "missing_fields" in result["reasons"]


def test_result_status_maps_to_task_status_vocabulary():
    assert task_status_for_result("passed") == "success"
    assert task_status_for_result("insufficient_evidence") == "blocked"
    assert task_status_for_result("failed") == "failed"


def test_interrupted_or_short_run_can_never_pass():
    result = evaluate_continuous_test(
        {"packets_sent": 1000, "packets_lost": 0, "duration_s": 4, "cancelled": True},
        required_duration_s=60,
    )

    assert result["status"] == "interrupted"
    assert "duration" in result["reasons"]
    assert "cancelled" in result["reasons"]


def test_compatibility_checks_hardware_and_action_filter():
    result = evaluate_compatibility(
        hardware={"servo_model": "HL-2915", "control_hz": 50, "obs_len": 61},
        policy={"servo_model": "HL-2915", "obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
        runtime={"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": True},
    )

    assert result["status"] == "failed"
    assert "action_filter_mismatch" in result["reasons"]


def test_compatibility_reads_policy_manifest_shape():
    result = evaluate_compatibility(
        hardware={"servos": {"model": "HL-2915"}, "control_hz": 50},
        policy={
            "obs_len": 61,
            "action_len": 14,
            "robot": {"servos": "HL-2915", "control_hz": 50},
            "action_filter": False,
        },
        runtime={
            "obs_len": 61,
            "action_len": 14,
            "robot": {"servos": "HL-2915", "control_hz": 50},
            "action_filter": False,
        },
    )

    assert result["status"] == "passed"


def test_compatibility_does_not_treat_missing_contract_as_pass():
    result = evaluate_compatibility(hardware={}, policy={}, runtime={})

    assert result["status"] == "insufficient_evidence"
    assert "missing_policy_action_dim" in result["reasons"]


def test_compatibility_checks_model_api_hardware_revision_and_joint_order():
    result = evaluate_compatibility(
        hardware={
            "servo_model": "HL-2915",
            "control_hz": 50,
            "hardware_rev": 2,
            "joint_order": ["a", "b"],
        },
        policy={
            "servo_model": "HL-2915",
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "model_api": 2,
            "hardware_rev": 1,
            "joint_order": ["a", "b"],
        },
        runtime={
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "model_api": 1,
            "hardware_rev": 2,
            "joint_order": ["b", "a"],
        },
    )

    assert result["status"] == "failed"
    assert "model_api_mismatch" in result["reasons"]
    assert "hardware_rev_mismatch" in result["reasons"]
    assert "joint_order_mismatch" in result["reasons"]


def test_compatibility_checks_scale_units_zero_and_imu_frame():
    result = evaluate_compatibility(
        hardware={
            "servo_model": "HL-2915",
            "control_hz": 50,
            "joint_units": "rad",
            "joint_zero": [0.0, 0.0],
            "imu_frame": "base_link",
        },
        policy={
            "servo_model": "HL-2915",
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "action_scale": 0.8,
            "joint_units": "rad",
            "joint_zero": [0.0, 0.0],
            "imu_frame": "base_link",
        },
        runtime={
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "action_scale": 0.9,
            "joint_units": "deg",
            "joint_zero": [0.0, 1.0],
            "imu_frame": "imu_link",
        },
    )

    assert result["status"] == "failed"
    assert result["rule_version"] == "compatibility-v2"
    assert set(result["reasons"]) >= {
        "action_scale_mismatch",
        "joint_units_mismatch",
        "joint_zero_mismatch",
        "imu_frame_mismatch",
    }


def test_compatibility_does_not_replace_explicit_zero_with_nested_frequency():
    result = evaluate_compatibility(
        hardware={"servo_model": "HL-2915", "control_hz": 0, "robot": {"control_hz": 50}},
        policy={"servo_model": "HL-2915", "obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
        runtime={"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
    )

    assert result["status"] != "passed"
    assert "hardware_frequency_mismatch" in result["reasons"]


def test_compatibility_requires_extended_field_on_both_policy_and_runtime():
    result = evaluate_compatibility(
        hardware={"servo_model": "HL-2915", "control_hz": 50},
        policy={
            "servo_model": "HL-2915",
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "action_scale": 0.8,
        },
        runtime={
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "servo_model": "HL-2915",
        },
    )

    assert result["status"] == "insufficient_evidence"
    assert "missing_runtime_action_scale" in result["reasons"]


def test_compatibility_does_not_hide_missing_declared_servo_model():
    result = evaluate_compatibility(
        hardware={"servo_model": "HL-2915", "control_hz": 50},
        policy={"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
        runtime={"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
    )

    assert result["status"] == "insufficient_evidence"
    assert "missing_policy_servo_model" in result["reasons"]


def test_compatibility_does_not_treat_empty_servo_model_as_evidence():
    result = evaluate_compatibility(
        hardware={"servo_model": "", "control_hz": 50},
        policy={"servo_model": "", "obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
        runtime={"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False},
    )

    assert result["status"] == "insufficient_evidence"
    assert "missing_hardware_servo_model" in result["reasons"]


def test_compatibility_does_not_treat_empty_control_frequency_as_valid():
    result = evaluate_compatibility(
        hardware={"servo_model": "HL-2915", "control_hz": ""},
        policy={"servo_model": "HL-2915", "obs_len": 61, "action_dim": 14, "control_hz": "", "action_filter": False},
        runtime={"obs_len": 61, "action_dim": 14, "control_hz": "", "action_filter": False},
    )

    assert result["status"] == "insufficient_evidence"
    assert "missing_hardware_control_hz" in result["reasons"]


def test_policy_manifest_normalizes_single_policy_contract():
    normalized = normalize_policy_manifest(
        {
            "schema_version": 2,
            "model_api": 1,
            "obs_len": 61,
            "action_len": 14,
            "robot": {"model": "microduck", "servos": "HL-2915", "control_hz": 50},
            "training": {"repo": "microduck_rl", "commit": "abc123"},
        }
    )

    assert normalized["status"] == "ready"
    assert normalized["policy"]["obs_len"] == 61
    assert normalized["policy"]["action_dim"] == 14
    assert normalized["policy"]["servo_model"] == "HL-2915"
    assert normalized["policy"]["training"]["commit"] == "abc123"


def test_policy_manifest_requires_selection_for_multiple_entries():
    manifest = {
        "schema_version": 2,
        "policies": [
            {"file": "walk.onnx", "name": "walk", "obs_len": 61, "action_len": 14},
            {"file": "stand.onnx", "name": "stand", "obs_len": 61, "action_len": 14},
        ],
    }

    missing = normalize_policy_manifest(manifest)
    selected = normalize_policy_manifest(manifest, "stand")

    assert missing["status"] == "insufficient_evidence"
    assert "policy_name_required" in missing["reasons"]
    assert selected["status"] == "ready"
    assert selected["policy"]["name"] == "stand"


def test_policy_package_registers_manifest_and_onnx_hashes(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "robot": {"servos": "HL-2915"}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("策略包", tmp_path)

    package = store.inspect_policy_package(project["id"], onnx_path, manifest_path)

    assert package["status"] == "ready"
    assert {artifact["kind"] for artifact in package["artifacts"]} == {"policy", "policy_manifest"}
    assert package["policy"]["servo_model"] == "HL-2915"


def test_deployment_preflight_uses_confirmed_hardware_and_policy_manifest(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({
            "obs_len": 61,
            "action_len": 14,
            "action_filter": False,
            "robot": {"servos": "HL-2915", "control_hz": 50},
        }),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("部署预检", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50},
    )
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")

    result = store.deployment_preflight(
        project["id"],
        onnx_path,
        manifest_path,
        {
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "servo_model": "HL-2915",
        },
    )

    assert result["status"] == "passed"
    assert result["result"]["mutates"] is False
    assert result["result"]["hardware_profile_id"]
    assert {artifact["kind"] for artifact in result["result"]["artifacts"]} == {"policy", "policy_manifest"}
    assert {artifact["run_id"] for artifact in result["result"]["artifacts"]} == {result["id"]}
    assert store.project_report(project["id"])["runs"][0]["kind"] == "deployment_preflight"
    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}
    assert tasks["deployment_preflight"]["status"] == "success"


def test_deployment_preflight_keeps_filter_mismatch_as_failed(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("部署不兼容", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")

    result = store.deployment_preflight(
        project["id"], onnx_path, manifest_path,
        {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": True, "servo_model": "HL-2915"},
    )

    assert result["status"] == "failed"
    assert "action_filter_mismatch" in result["result"]["reasons"]


def test_deployment_preflight_checks_extended_manifest_contract(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps(
            {
                "obs_len": 61,
                "action_len": 14,
                "action_filter": False,
                "action_scale": 0.8,
                "joint_units": "rad",
                "joint_zero": [0.0, 0.0],
                "imu_frame": "base_link",
                "robot": {"servos": "HL-2915", "control_hz": 50},
            }
        ),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("扩展部署契约", tmp_path)
    store.save_hardware(
        project["id"],
        {
            "servos": {"model": "HL-2915", "candidates": ["HL-2915"]},
            "control_hz": 50,
            "joint_units": "rad",
            "joint_zero": [0.0, 0.0],
            "imu_frame": "base_link",
        },
    )
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")

    result = store.deployment_preflight(
        project["id"],
        onnx_path,
        manifest_path,
        {
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "action_scale": 0.9,
            "servo_model": "HL-2915",
            "joint_units": "rad",
            "joint_zero": [0.0, 0.0],
            "imu_frame": "base_link",
        },
    )

    assert result["status"] == "failed"
    assert result["result"]["rule_version"] == "compatibility-v2"
    assert result["result"]["reasons"] == ["action_scale_mismatch"]
    assert result["result"]["policy"]["imu_frame"] == "base_link"


def test_deployment_preflight_uses_verified_calibration_contract(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps(
            {
                "obs_len": 61,
                "action_len": 14,
                "action_filter": False,
                "joint_order": ["hip"],
                "joint_zero": [0.0],
                "imu_frame": "base_link",
                "robot": {"servos": "HL-2915", "control_hz": 50},
            }
        ),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定契约", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50},
    )
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    store.save_calibration(
        project["id"],
        {
            "operator": "abel",
            "verified": True,
            "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}],
            "imu": {"frame": "base_link", "rpy_deg": [0, 0, 0]},
        },
    )
    store.set_task_status(project["id"], "servo_read", "success")

    result = store.deployment_preflight(
        project["id"],
        onnx_path,
        manifest_path,
        {
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "servo_model": "HL-2915",
            "joint_order": ["hip"],
            "joint_zero": [1.0],
            "imu_frame": "imu_link",
        },
    )

    assert result["status"] == "failed"
    assert set(result["result"]["reasons"]) >= {"joint_zero_mismatch", "imu_frame_mismatch"}


def test_deployment_preflight_reuses_physical_calibration_after_metadata_update(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps(
            {
                "obs_len": 61,
                "action_len": 14,
                "action_filter": False,
                "joint_order": ["hip"],
                "joint_zero": [0.0],
                "imu_frame": "base_link",
                "robot": {"servos": "HL-2915", "control_hz": 50},
            }
        ),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("元数据后的预检", tmp_path)
    base = {
        "servos": {"model": "HL-2915", "candidates": ["HL-2915"]},
        "control_hz": 50,
        "runtime": {"version": "runtime-a"},
        "training": {"repo": "microduck_rl", "revision": "train-a"},
    }
    store.save_hardware(project["id"], base)
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    calibration = store.save_calibration(
        project["id"],
        {
            "operator": "abel",
            "verified": True,
            "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}],
            "imu": {"frame": "base_link", "rpy_deg": [0, 0, 0]},
        },
    )
    store.set_task_status(project["id"], "servo_read", "success")
    store.save_hardware(
        project["id"],
        {**base, "runtime": {"version": "runtime-b"}, "training": {"repo": "microduck_rl", "revision": "train-b"}},
    )

    result = store.deployment_preflight(
        project["id"],
        onnx_path,
        manifest_path,
        {
            "obs_len": 61,
            "action_dim": 14,
            "control_hz": 50,
            "action_filter": False,
            "servo_model": "HL-2915",
            "joint_order": ["hip"],
            "joint_zero": [0.0],
            "imu_frame": "base_link",
        },
    )

    assert result["status"] == "passed"
    assert result["result"]["calibration_record_id"] == calibration["id"]
    assert result["result"]["hardware_contract"]["joint_order"] == ["hip"]


def test_deployment_preflight_records_invalid_policy_input(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("无效策略", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})

    with pytest.raises(ValueError, match="policy package files"):
        store.deployment_preflight(project["id"], tmp_path / "missing.onnx", tmp_path / "missing.json", {})

    run = store.project_report(project["id"])["runs"][0]
    assert run["kind"] == "deployment_preflight"
    assert run["status"] == "insufficient_evidence"
    assert run["result"]["reasons"] == ["policy_package_error"]


def test_deployment_plan_requires_fresh_compatibility_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("部署计划", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    runtime = {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"}
    store.deployment_preflight(project["id"], onnx_path, manifest_path, runtime)
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"ssh", "scp"} else None)

    plan = store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)

    assert plan["status"] == "ready"
    assert plan["mutates"] is True
    assert plan["target"] == "rock@duck.local"
    assert plan["steps"] == ["backup_current_policy", "upload_policy", "verify_sha256", "health_check", "rollback_on_failure"]
    assert plan["safety"]["does_not_start_motion"] is False
    assert plan["safety"]["requires_robot_lifted_or_restrained"] is True

    store.save_hardware(project["id"], {"servos": {"model": "HL-1910", "candidates": ["HL-1910"]}, "control_hz": 50})
    with pytest.raises(ValueError, match="hardware"):
        store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)


def test_deployment_plan_requires_current_assembly_and_verified_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("部署证据门", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    runtime = {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"}
    store.deployment_preflight(project["id"], onnx_path, manifest_path, runtime)
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}" if name in {"ssh", "scp"} else None)

    with pytest.raises(ValueError, match="assembly"):
        store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)

    store.save_assembly(
        project["id"],
        {"title": "整机装配", "checks": [{"id": "frame", "title": "结构", "status": "passed", "evidence": ["photo://frame"]}]},
    )
    with pytest.raises(ValueError, match="calibration"):
        store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)

    store.save_calibration(
        project["id"],
        {
            "operator": "abel",
            "verified": True,
            "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}],
        },
    )
    with pytest.raises(ValueError, match="calibration"):
        store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)

    store.set_task_status(project["id"], "servo_read", "success")
    store.deployment_preflight(project["id"], onnx_path, manifest_path, runtime)
    plan = store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)
    assert plan["status"] == "ready"


def test_deployment_plan_rejects_calibration_change_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定变更", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    runtime = {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"}
    store.deployment_preflight(project["id"], onnx_path, manifest_path, runtime)
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")

    store.save_calibration(
        project["id"],
        {
            "operator": "abel",
            "verified": True,
            "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 1.0, "limits_deg": [-30, 30]}],
        },
    )

    with pytest.raises(ValueError, match="calibration"):
        store.build_deployment_plan(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22)


def test_deployment_execution_uses_fixed_commands_and_health_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("部署执行", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    runtime = {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"}
    store.deployment_preflight(project["id"], onnx_path, manifest_path, runtime)
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert kwargs["shell"] is False
        if command[0].endswith("ssh") and command[-4:] == ["robotctl", "policy", "list", "--json"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"policies": {"slots": [{"slot": "walk", "path": "/opt/old.onnx"}]}}), stderr="")
        if "sha256sum" in command:
            return subprocess.CompletedProcess(command, 0, stdout=f"{hashlib.sha256(b'fake-onnx').hexdigest()}  remote.onnx\n", stderr="")
        if command[-3:] == ["robotctl", "health", "--json"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"robot": {"healthy": True}, "software": {"warnings": [], "services": []}}), stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("microduck_studio.core.subprocess.run", fake_run)
    result = store.execute_deployment(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22, confirm=True)

    assert result["status"] == "passed"
    deployment_task = next(task for task in store.project_report(project["id"])["tasks"] if task["id"] == "deployment")
    assert deployment_task["status"] == "success"
    assert deployment_task["deps"] == ["deployment_preflight", "assembly", "calibration"]
    assert deployment_task["card"]["risk"] == "confirmed_remote_mutation"
    assert result["result"]["health"]["category"] == "healthy"
    assert any(command[0].endswith("scp") for command in calls)
    assert any("sha256sum" in command for command in calls)
    assert any("policy" in command and "load" in command for command in calls)
    assert "rollback" not in result["result"]["stages"]
    assert all(";" not in token and "&&" not in token for command in calls for token in command)


def test_deployment_execution_requires_explicit_confirmation(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("部署确认", tmp_path)

    with pytest.raises(PermissionError, match="explicit confirmation"):
        store.execute_deployment(project["id"], tmp_path / "policy.onnx", tmp_path / "manifest.json", "duck.local", "rock", 22, confirm=False)


def test_deployment_stops_before_load_when_remote_hash_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("哈希失败", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    store.deployment_preflight(
        project["id"], onnx_path, manifest_path,
        {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"},
    )
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-4:] == ["robotctl", "policy", "list", "--json"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"policies": {"slots": []}}), stderr="")
        if "sha256sum" in command:
            return subprocess.CompletedProcess(command, 0, stdout=f"{'0' * 64}  remote.onnx\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("microduck_studio.core.subprocess.run", fake_run)
    result = store.execute_deployment(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22, confirm=True)

    assert result["status"] == "failed"
    assert "remote_hash_mismatch" in result["result"]["reasons"]
    assert not any("policy" in command and "load" in command for command in calls)


def test_deployment_health_failure_restores_previous_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"fake-onnx")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("失败回滚", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    store.deployment_preflight(
        project["id"], onnx_path, manifest_path,
        {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"},
    )
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-4:] == ["robotctl", "policy", "list", "--json"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"policies": {"slots": [{"slot": "walk", "path": "/opt/old.onnx"}]}}), stderr="")
        if "sha256sum" in command:
            return subprocess.CompletedProcess(command, 0, stdout=f"{hashlib.sha256(b'fake-onnx').hexdigest()}  remote.onnx\n", stderr="")
        if command[-3:] == ["robotctl", "health", "--json"]:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"robot": {"healthy": False}, "software": {"warnings": [], "services": []}}), stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr("microduck_studio.core.subprocess.run", fake_run)
    result = store.execute_deployment(project["id"], onnx_path, manifest_path, "duck.local", "rock", 22, confirm=True)

    assert result["status"] == "failed"
    assert "health_gate" in result["result"]["reasons"]
    assert result["result"]["stages"]["rollback"]["returncode"] == 0
    assert any(command[-3:] == ["walk", "/opt/old.onnx", "--json"] for command in calls)


def test_report_round_trip_keeps_run_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("报告测试", tmp_path)
    run = store.start_run(project["id"], "preflight")
    store.finish_run(run["id"], "failed", {"checks": [{"name": "uv", "ok": False}]})

    report = store.project_report(project["id"])

    assert report["project"]["name"] == "报告测试"
    assert report["runs"][0]["status"] == "failed"
    assert report["runs"][0]["result"]["checks"][0]["name"] == "uv"
    json.dumps(report)


def test_runs_are_labeled_by_evidence_scope(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("证据范围", tmp_path)
    for kind in ("preflight", "training_smoke", "hl2915_read_only_probe", "controller_diagnostic"):
        run = store.start_run(project["id"], kind)
        store.finish_run(run["id"], "failed", {"reasons": ["test"]})

    report = store.project_report(project["id"])
    scopes = {run["kind"]: run["result"]["evidence_scope"] for run in report["runs"]}

    assert scopes["preflight"] == "local_software"
    assert scopes["training_smoke"] == "training_or_simulation"
    assert scopes["hl2915_read_only_probe"] == "real_hardware"
    assert scopes["controller_diagnostic"] == "real_hardware"


def test_new_calibration_requires_deployment_preflight_again(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定变更", tmp_path)
    store.save_hardware(
        project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}}
    )
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    calibration_data = {
        "operator": "abel",
        "verified": True,
        "joints": [{"name": "hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}],
    }
    store.save_calibration(project["id"], calibration_data)
    store.set_task_status(project["id"], "servo_read", "success")
    store.set_task_status(project["id"], "deployment_preflight", "success")

    store.save_calibration(
        project["id"],
        {**calibration_data, "joints": [{**calibration_data["joints"][0], "zero_deg": 2}]},
    )

    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}
    assert tasks["calibration"]["status"] == "success"
    assert tasks["deployment_preflight"]["status"] == "ready"


def test_changed_policy_artifact_requires_deployment_preflight_again(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"original-policy")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("策略变更", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    store.deployment_preflight(
        project["id"],
        onnx_path,
        manifest_path,
        {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"},
    )

    onnx_path.write_bytes(b"changed-policy")

    report = store.project_report(project["id"])
    tasks = {task["id"]: task for task in report["tasks"]}
    assert tasks["deployment_preflight"]["status"] == "ready"
    assert "deployment_preflight_evidence_stale" in tasks["deployment_preflight"]["evidence_reasons"]


def test_failed_preflight_blocks_previous_deployment_success(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    onnx_path = tmp_path / "policy.onnx"
    manifest_path.write_text(
        json.dumps({"obs_len": 61, "action_len": 14, "action_filter": False, "robot": {"servos": "HL-2915", "control_hz": 50}}),
        encoding="utf-8",
    )
    onnx_path.write_bytes(b"policy")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("前置失败", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    _complete_deployment_evidence(store, project["id"])
    store.deployment_preflight(
        project["id"],
        onnx_path,
        manifest_path,
        {"obs_len": 61, "action_dim": 14, "control_hz": 50, "action_filter": False, "servo_model": "HL-2915"},
    )

    store.set_task_status(project["id"], "preflight", "failed")

    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}
    assert tasks["deployment_preflight"]["status"] == "blocked"
    assert tasks["smoke"]["status"] == "blocked"


def test_project_runs_and_artifacts_expose_schema_version(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("版本证据", tmp_path)
    run = store.start_run(project["id"], "diagnostic")
    artifact_path = tmp_path / "evidence.log"
    artifact_path.write_text("ok", encoding="utf-8")
    artifact = store.register_artifact(project["id"], artifact_path, "log", run_id=run["id"])

    report = store.project_report(project["id"])

    assert report["schema_version"] == 1
    assert report["project"]["schema_version"] == 1
    assert run["schema_version"] == 1
    assert artifact["schema_version"] == 1
    assert report["runs"][0]["schema_version"] == 1
    assert report["artifacts"][0]["schema_version"] == 1


def test_task_status_can_be_updated_and_reported(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("任务测试", tmp_path)
    first = store.next_task(project["id"])

    assert first["id"] == "hardware"
    assert first["status"] == "needs_confirmation"
    assert next(task for task in store.project_report(project["id"])["tasks"] if task["id"] == "servo_read")["status"] == "blocked"

    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50},
    )
    ready = store.next_task(project["id"])

    assert ready["id"] == "preflight"
    assert next(task for task in store.project_report(project["id"])["tasks"] if task["id"] == "servo_read")["status"] == "ready"

    store.set_task_status(project["id"], "preflight", "success")

    tasks = store.project_report(project["id"])["tasks"]

    assert next(task for task in tasks if task["id"] == "preflight")["status"] == "success"
    assert next(task for task in tasks if task["id"] == "smoke")["status"] == "ready"

    store.save_hardware(project["id"], {"servos": {"model": None, "candidates": ["HL-1910", "HL-2915"]}})
    report = store.project_report(project["id"])

    assert next(task for task in report["tasks"] if task["id"] == "hardware")["status"] == "needs_confirmation"
    assert next(task for task in report["tasks"] if task["id"] == "servo_read")["status"] == "blocked"


def test_hardware_change_invalidates_completed_downstream_tasks(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("硬件失效", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50},
    )
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "servo_read", "success")
    store.set_task_status(project["id"], "smoke", "success")
    store.set_task_status(project["id"], "report", "success")

    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-1910", "candidates": ["HL-1910"]}, "control_hz": 50},
    )
    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}

    assert tasks["hardware"]["status"] == "success"
    assert tasks["servo_read"]["status"] == "ready"
    assert tasks["smoke"]["status"] == "ready"
    assert tasks["report"]["status"] == "ready"


def test_software_metadata_change_does_not_stale_physical_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("软件元数据变更", tmp_path)
    base = {
        "servos": {"model": "HL-2915", "count": 12, "candidates": ["HL-2915"]},
        "controller": {"model": "Radxa Zero 3W"},
        "imu": {"model": "BMI270"},
        "power": {"voltage_v": 7.4},
        "printed_parts": {"version": "v1"},
        "runtime": {"version": "runtime-a"},
        "training": {"repo": "microduck_rl", "revision": "train-a"},
    }
    store.save_hardware(project["id"], base)
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "servo_read", "success")
    _complete_deployment_evidence(store, project["id"])
    store.set_task_status(project["id"], "controller_read", "success")
    store.set_task_status(project["id"], "smoke", "success")
    store.set_task_status(project["id"], "report", "success")

    updated = {**base, "runtime": {"version": "runtime-b"}, "training": {"repo": "microduck_rl", "revision": "train-b"}}
    store.save_hardware(project["id"], updated)

    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}
    report = store.project_report(project["id"])

    assert tasks["servo_read"]["status"] == "success"
    assert tasks["assembly"]["status"] == "success"
    assert tasks["calibration"]["status"] == "success"
    assert tasks["controller_read"]["status"] == "ready"
    assert tasks["smoke"]["status"] == "ready"
    assert tasks["report"]["status"] == "ready"
    assert report["assemblies"][0]["valid_for_current_hardware"] is True
    assert report["calibrations"][0]["valid_for_current_hardware"] is True


def test_report_markdown_is_human_readable(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("Markdown 测试", tmp_path)

    report = store.project_report_markdown(project["id"])

    assert report.startswith("# Microduck Studio report")
    assert "Markdown 测试" in report
    assert "确认硬件路线" in report


def test_report_markdown_shows_retry_parent(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("重试报告", tmp_path)
    run = store.start_run(project["id"], "training_smoke")
    store.finish_run(run["id"], "interrupted", {"training_dir": "training", "retry_of": "previous-run"})

    assert "重试自：`previous-run`" in store.project_report_markdown(project["id"])


def test_report_markdown_includes_preflight_baseline(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("基线报告", tmp_path)
    run = store.start_run(project["id"], "preflight")
    store.finish_run(
        run["id"],
        "passed",
        {
            "baseline": {
                "captured_at": "2026-09-12T00:00:00+00:00",
                "platform": {"system": "Windows", "release": "11", "machine": "AMD64", "python": "3.12"},
                "tools": {"python": {"available": True, "version": "Python 3.12"}},
                "git": {"available": True, "commit": "abc123", "branch": "main", "dirty": True, "tracked_change_count": 2},
            }
        },
    )

    report = store.project_report_markdown(project["id"])

    assert "环境基线" in report
    assert "abc123" in report


def test_report_markdown_includes_training_provenance(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("训练证据报告", tmp_path)
    run = store.start_run(project["id"], "training_smoke")
    store.finish_run(
        run["id"],
        "passed",
        {
            "constraints": {"max_iterations": 5},
            "reasons": [],
            "training_provenance": {
                "source": {"commit": "training-abc123", "branch": "main", "dirty": True},
                "executor_model": None,
                "seed": None,
                "checkpoint": None,
                "unavailable": ["executor_model", "seed", "checkpoint"],
            },
            "training_outputs": {
                "onnx": [{"path": "C:/training/walk.onnx", "sha256": "onnx-hash", "size": 12}],
                "contract": {"path": "C:/project/artifacts/onnx-contract.json", "sha256": "contract-hash", "size": 34},
            },
        },
    )

    report = store.project_report_markdown(project["id"])

    assert "training-abc123" in report
    assert "dirty" in report
    assert "executor_model, seed, checkpoint" in report
    assert "onnx-contract.json" in report


def test_report_markdown_includes_controller_guidance(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("诊断报告", tmp_path)
    run = store.start_run(project["id"], "controller_diagnostic")
    store.finish_run(
        run["id"],
        "failed",
        {
            "category": "controller_unreachable",
            "guidance": {
                "current_facts": ["SSH 未建立"],
                "possible_causes": ["网络不可达"],
                "missing_evidence": ["health JSON"],
                "next_checks": ["确认主控地址、网络和 SSH 主机密钥"],
            },
        },
    )

    report = store.project_report_markdown(project["id"])

    assert "主控诊断" in report
    assert "确认主控地址、网络和 SSH 主机密钥" in report


def test_report_markdown_includes_deployment_compatibility(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("兼容性报告", tmp_path)
    run = store.start_run(project["id"], "deployment_preflight")
    store.finish_run(
        run["id"],
        "failed",
        {"reasons": ["action_filter_mismatch"], "policy": {"name": "walk"}},
    )

    report = store.project_report_markdown(project["id"])

    assert "部署前兼容性" in report
    assert "action_filter_mismatch" in report


def test_report_markdown_includes_calibration_record(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定报告", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.save_calibration(
        project["id"],
        {"joints": [{"name": "left_hip", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}]},
    )

    report = store.project_report_markdown(project["id"])

    assert "标定记录" in report
    assert "left_hip" in report


def test_report_markdown_includes_assembly_record(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("装配报告", tmp_path)
    store.save_assembly(
        project["id"],
        {
            "title": "干装配",
            "source_refs": ["docs/course/20-组装与上电.md"],
            "checks": [{"id": "trunk", "title": "躯干基准", "status": "passed", "evidence": ["photo://1"]}],
        },
    )

    report = store.project_report_markdown(project["id"])

    assert "装配记录" in report
    assert "干装配" in report


def test_report_markdown_includes_identification_readiness(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("辨识报告", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")
    store.save_identification(
        project["id"],
        {
            "actuator_model": "HL-2915",
            "raw_summary": {"status": "passed", "rows": 10, "duration_s": 1, "expected_hz": 50, "ids": [1], "faults": [], "errors": []},
            "fit": {"path": str(model), "model": "m6", "trials": 100},
            "validation": {"dataset": "held-out", "independent": False, "mae": 0.2},
        },
    )

    report = store.project_report_markdown(project["id"])

    assert "执行器辨识" in report
    assert "independent_validation_required" in report


def test_report_markdown_includes_issue_guidance(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("问题报告", tmp_path)
    store.create_issue(
        project["id"],
        {
            "title": "端口占用",
            "severity": "warning",
            "symptom": "串口打开失败",
            "suspected_causes": ["其他进程占用"],
            "next_checks": ["检查端口占用者"],
        },
    )

    report = store.project_report_markdown(project["id"])

    assert "问题台账" in report
    assert "检查端口占用者" in report


def test_report_markdown_includes_run_rule_version(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("规则版本报告", tmp_path)
    run = store.start_run(project["id"], "continuous_test")
    store.finish_run(
        run["id"],
        "failed",
        {
            "rule_version": "continuous-test-v1",
            "reasons": ["packet_loss"],
            "guidance": {"next_checks": ["核对舵机型号对应的波特率和协议"]},
        },
    )

    assert "continuous-test-v1" in store.project_report_markdown(project["id"])
    assert "核对舵机型号对应的波特率和协议" in store.project_report_markdown(project["id"])
    assert "证据范围：`bench_evidence`" in store.project_report_markdown(project["id"])


def test_artifact_is_hashed_and_included_in_report(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("产物测试", tmp_path)
    artifact_path = tmp_path / "policy.onnx"
    artifact_path.write_bytes(b"fake-policy")

    artifact = store.register_artifact(project["id"], artifact_path, "policy")
    report = store.project_report(project["id"])

    assert artifact["sha256"] == hashlib.sha256(b"fake-policy").hexdigest()
    assert report["artifacts"][0]["path"] == str(artifact_path.resolve())


def test_report_rechecks_registered_artifact_integrity(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("产物完整性", tmp_path)
    artifact_path = tmp_path / "evidence.json"
    artifact_path.write_bytes(b"original")
    store.register_artifact(project["id"], artifact_path, "evidence")

    verified = store.project_report(project["id"])["artifacts"][0]
    artifact_path.write_bytes(b"modified")
    changed = store.project_report(project["id"])["artifacts"][0]
    artifact_path.unlink()
    missing = store.project_report(project["id"])["artifacts"][0]

    assert verified["integrity_status"] == "verified"
    assert verified["current_sha256"] == verified["sha256"]
    assert changed["integrity_status"] == "changed"
    assert changed["current_sha256"] != changed["sha256"]
    assert missing["integrity_status"] == "missing"
    assert missing["current_sha256"] is None
    assert "完整性：`missing`" in store.project_report_markdown(project["id"])


def test_artifact_outside_project_root_is_rejected(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("产物边界", tmp_path / "project")
    outside = tmp_path / "outside.log"
    outside.write_text("not in project", encoding="utf-8")

    with pytest.raises(ValueError, match="project root"):
        store.register_artifact(project["id"], outside, "log")


def test_experiment_keeps_hypothesis_and_decision(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("实验测试", tmp_path)
    experiment = store.create_experiment(
        project["id"],
        {
            "title": "关闭动作滤波",
            "hypothesis": "训练与运行时一致后抖动会减少",
            "variable": "action_filter",
            "baseline": True,
            "expected": "更稳定",
        },
    )
    store.update_experiment(
        experiment["id"],
        {"status": "concluded", "result": "尚未在真机验证", "decision": "保留为待验证"},
    )

    saved = store.project_report(project["id"])["experiments"][0]

    assert saved["hypothesis"] == "训练与运行时一致后抖动会减少"
    assert saved["status"] == "concluded"
    assert saved["decision"] == "保留为待验证"


def test_experiment_can_link_terminal_run_as_evidence_without_duplicates(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("实验证据关联", tmp_path)
    experiment = store.create_experiment(
        project["id"],
        {"title": "台架验证", "hypothesis": "h", "variable": "v", "baseline": 1, "expected": 2},
    )
    run = store.start_run(project["id"], "bench_continuous")

    with pytest.raises(ValueError, match="terminal"):
        store.link_run_to_experiment(project["id"], experiment["id"], run["id"])

    store.finish_run(run["id"], "passed", {"status": "passed", "packets_lost": 0})
    linked = store.link_run_to_experiment(project["id"], experiment["id"], run["id"])
    linked_again = store.link_run_to_experiment(project["id"], experiment["id"], run["id"])

    assert linked["evidence_refs"] == [run["id"]]
    assert linked_again["evidence_refs"] == [run["id"]]
    assert linked_again["status"] == "planned"
    evidence = store.project_report(project["id"])["experiments"][0]["evidence_details"]
    assert evidence == [{
        "run_id": run["id"],
        "kind": "bench_continuous",
        "status": "passed",
        "evidence_scope": "bench_evidence",
    }]
    assert f"证据引用：{run['id']}" in store.project_report_markdown(project["id"])


def test_experiment_captures_hardware_and_preflight_context(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("实验条件", tmp_path)
    hardware = store.save_hardware(
        project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}}
    )
    preflight = store.start_run(project["id"], "preflight")
    store.finish_run(
        preflight["id"],
        "passed",
        {"baseline": {"git": {"commit": "abc123"}, "tools": {"uv": {"version": "0.6"}}}},
    )

    experiment = store.create_experiment(
        project["id"],
        {"title": "条件快照", "hypothesis": "x", "variable": "x", "baseline": 1, "expected": 2},
    )

    assert experiment["context"]["hardware_profile_id"] == hardware["id"]
    assert experiment["context"]["hardware"]["servos"]["model"] == "HL-2915"
    assert experiment["context"]["preflight_run_id"] == preflight["id"]
    assert experiment["context"]["preflight"]["baseline"]["git"]["commit"] == "abc123"
    markdown = store.project_report_markdown(project["id"])
    assert f"硬件档案 `{hardware['id']}`" in markdown
    assert f"预检运行 `{preflight['id']}`" in markdown


def test_reopen_migrates_experiment_context_column(tmp_path: Path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE experiments (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
                hypothesis TEXT NOT NULL, variable TEXT NOT NULL, baseline TEXT NOT NULL,
                expected TEXT NOT NULL, result TEXT, decision TEXT, status TEXT NOT NULL,
                evidence_refs TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )

    store = StudioStore(db)
    project = store.create_project("旧实验库", tmp_path)
    experiment = store.create_experiment(
        project["id"], {"title": "迁移", "hypothesis": "x", "variable": "x", "baseline": 1, "expected": 2}
    )

    assert experiment["context"]["hardware_profile_id"] is None


def test_experiment_comparison_reports_changed_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("实验比较", tmp_path)
    before = store.create_experiment(
        project["id"],
        {
            "title": "基线",
            "hypothesis": "滤波影响稳定性",
            "variable": "action_filter",
            "baseline": True,
            "expected": "更稳定",
        },
    )
    after = store.create_experiment(
        project["id"],
        {
            "title": "调整后",
            "hypothesis": "滤波影响稳定性",
            "variable": "action_filter",
            "baseline": False,
            "expected": "更稳定",
        },
    )
    store.update_experiment(
        after["id"],
        {"status": "concluded", "result": {"fall_rate": 0.1}, "decision": "保留", "evidence_refs": ["run-2"]},
    )

    comparison = store.compare_experiments(project["id"], before["id"], after["id"])

    assert comparison["status"] == "changed"
    assert comparison["left"]["id"] == before["id"]
    assert comparison["right"]["id"] == after["id"]
    assert {change["field"] for change in comparison["changes"]} >= {"baseline", "result", "status", "decision", "evidence_refs"}


def test_experiment_comparison_reports_context_change_without_timestamp_noise(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("实验条件比较", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    before = store.create_experiment(
        project["id"], {"title": "旧硬件", "hypothesis": "h", "variable": "v", "baseline": 1, "expected": 2}
    )
    store.save_hardware(project["id"], {"servos": {"model": "HL-1910", "candidates": ["HL-1910"]}})
    after = store.create_experiment(
        project["id"], {"title": "新硬件", "hypothesis": "h", "variable": "v", "baseline": 1, "expected": 2}
    )

    comparison = store.compare_experiments(project["id"], before["id"], after["id"])

    context_change = next(change for change in comparison["changes"] if change["field"] == "context")
    assert context_change["before"]["hardware_profile_id"] != context_change["after"]["hardware_profile_id"]


def test_experiment_comparison_rejects_other_project(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    first = store.create_project("实验甲", tmp_path / "first")
    second = store.create_project("实验乙", tmp_path / "second")
    experiment = store.create_experiment(
        first["id"],
        {"title": "甲", "hypothesis": "h", "variable": "v", "baseline": 1, "expected": 2},
    )
    other = store.create_experiment(
        second["id"],
        {"title": "乙", "hypothesis": "h", "variable": "v", "baseline": 1, "expected": 2},
    )

    with pytest.raises(KeyError, match="experiment"):
        store.compare_experiments(first["id"], experiment["id"], other["id"])


def test_calibration_record_is_bound_to_confirmed_hardware(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定记录", tmp_path)
    hardware = store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}, "control_hz": 50},
    )
    data = {
        "joints": [
            {"name": "left_hip", "id": 1, "direction": 1, "zero_deg": 0.2, "limits_deg": [-30, 30]},
            {"name": "right_hip", "id": 2, "direction": -1, "zero_deg": -0.1, "limits_deg": [-30, 30]},
        ],
        "imu": {"frame": "base_link", "rpy_deg": [0.0, 0.0, 180.0]},
        "conditions": {"voltage_v": 7.6, "temperature_c": 24.0, "load": "bench"},
    }

    record = store.save_calibration(project["id"], data)
    report = store.project_report(project["id"])

    assert record["hardware_profile_id"] == hardware["id"]
    assert record["status"] == "recorded"
    assert report["calibrations"][0]["valid_for_current_hardware"] is True
    assert report["calibrations"][0]["data"]["imu"]["frame"] == "base_link"


def test_calibration_validation_rejects_duplicate_ids_and_bad_limits(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定校验", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    base = {"name": "joint", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}

    with pytest.raises(ValueError, match="duplicate"):
        store.save_calibration(project["id"], {"joints": [base, {**base, "name": "other"}]})
    with pytest.raises(ValueError, match="limits"):
        store.save_calibration(project["id"], {"joints": [{**base, "limits_deg": [30, -30]}]})


def test_unverified_calibration_does_not_unlock_calibration_task(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定未核验", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "servo_read", "success")

    store.save_calibration(
        project["id"],
        {"operator": "abel", "joints": [{"name": "joint", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}]},
    )

    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}
    assert tasks["calibration"]["status"] == "ready"


def test_calibration_is_marked_stale_after_hardware_change(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("标定失效", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    record = store.save_calibration(
        project["id"],
        {"joints": [{"name": "joint", "id": 1, "direction": 1, "zero_deg": 0, "limits_deg": [-30, 30]}]},
    )

    store.save_hardware(project["id"], {"servos": {"model": "HL-1910", "candidates": ["HL-1910"]}})
    saved = next(item for item in store.project_report(project["id"])["calibrations"] if item["id"] == record["id"])

    assert saved["valid_for_current_hardware"] is False


def test_assembly_record_keeps_materials_checks_and_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("装配记录", tmp_path)
    hardware = store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    data = {
        "title": "第一次干装配",
        "source_refs": ["docs/course/20-组装与上电.md"],
        "materials": [{
            "name": "M2 自攻螺丝", "status": "received", "quantity": 20,
            "spec": "M2×8", "source": "旧物料记录", "alternative": "M2×6", "price": 0.12,
        }],
        "checks": [
            {"id": "trunk", "title": "躯干作为基准件", "status": "passed", "evidence": ["photo://trunk"]},
            {"id": "free_motion", "title": "断电手动转动无卡滞", "status": "pending", "evidence": []},
        ],
        "notes": "先不接电",
    }

    record = store.save_assembly(project["id"], data)
    saved = store.project_report(project["id"])["assemblies"][0]

    assert record["hardware_profile_id"] == hardware["id"]
    assert record["completion"] == "incomplete"
    assert saved["valid_for_current_hardware"] is True
    assert saved["data"]["materials"][0]["status"] == "received"
    assert saved["data"]["materials"][0]["spec"] == "M2×8"
    assert saved["data"]["materials"][0]["alternative"] == "M2×6"
    assert saved["data"]["materials"][0]["price"] == 0.12
    assert record["material_summary"] == {
        "item_count": 1,
        "quantity_total": 20,
        "status_counts": {"received": 1},
    }
    assert saved["material_summary"] == record["material_summary"]


def test_assembly_passed_check_requires_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("装配证据", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})

    with pytest.raises(ValueError, match="evidence"):
        store.save_assembly(
            project["id"],
            {"title": "缺证据", "checks": [{"id": "power", "title": "供电", "status": "passed", "evidence": []}]},
        )
    with pytest.raises(ValueError, match="price"):
        store.save_assembly(
            project["id"],
            {
                "title": "负价格",
                "materials": [{"name": "M2", "price": -1}],
                "checks": [{"id": "power", "title": "供电", "status": "pending", "evidence": []}],
            },
        )


def test_assembly_material_shortage_cannot_complete_assembly_task(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("装配缺料", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})

    record = store.save_assembly(
        project["id"],
        {
            "title": "缺料装配",
            "materials": [{"name": "M2 螺丝", "status": "missing", "quantity": 20}],
            "checks": [{"id": "frame", "title": "结构", "status": "passed", "evidence": ["photo://frame"]}],
        },
    )

    tasks = {task["id"]: task for task in store.project_report(project["id"])["tasks"]}
    assert record["completion"] == "blocked"
    assert record["material_summary"]["status_counts"] == {"missing": 1}
    assert record["material_summary"]["quantity_total"] == 20
    assert tasks["assembly"]["status"] == "ready"


def test_assembly_record_is_marked_stale_after_hardware_change(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("装配失效", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    record = store.save_assembly(
        project["id"],
        {"title": "旧路线装配", "checks": [{"id": "frame", "title": "结构", "status": "pending", "evidence": []}]},
    )

    store.save_hardware(project["id"], {"servos": {"model": "HL-1910", "candidates": ["HL-1910"]}})
    saved = next(item for item in store.project_report(project["id"])["assemblies"] if item["id"] == record["id"])

    assert saved["valid_for_current_hardware"] is False


def test_support_bundle_redacts_secrets_and_registers_artifact(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("支持包", tmp_path)
    run = store.start_run(project["id"], "diagnostic")
    store.finish_run(
        run["id"],
        "failed",
        {
            "stdout": "Authorization: Bearer abcdef123456\nGITHUB_TOKEN=github_pat_secretvalue",
            "connection": {"ssid": "Home-Wifi", "psk": "super-secret", "access_token": "plain-access-secret"},
            "private_key": "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nsecret\n-----END OPENSSH PRIVATE KEY-----",
            "path": str(Path.home() / "private" / "log.txt"),
        },
    )
    output = tmp_path / "artifacts" / "support" / "bundle.zip"

    result = store.create_support_bundle(project["id"], output, confirm=True)

    assert result["status"] == "passed"
    assert result["artifact"]["kind"] == "support_bundle"
    with zipfile.ZipFile(output) as archive:
        report = archive.read("report.json").decode("utf-8")
        names = set(archive.namelist())
    assert names == {"manifest.json", "report.json", "report.md"}
    assert "abcdef123456" not in report
    assert "github_pat_secretvalue" not in report
    assert "Home-Wifi" not in report
    assert "super-secret" not in report
    assert "plain-access-secret" not in report
    assert str(Path.home()) not in report
    assert "<redacted>" in report
    assert "<HOME>" in report
    with pytest.raises(ValueError, match="already exists"):
        store.create_support_bundle(project["id"], output, confirm=True)


def test_support_bundle_requires_confirmation_and_project_path(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("支持包边界", tmp_path / "project")

    with pytest.raises(PermissionError, match="confirmation"):
        store.create_support_bundle(project["id"], tmp_path / "project" / "bundle.zip", confirm=False)
    with pytest.raises(ValueError, match="project root"):
        store.create_support_bundle(project["id"], tmp_path / "outside.zip", confirm=True)


def test_identification_record_requires_independent_validation(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("辨识记录", tmp_path)
    hardware = store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    model = tmp_path / "artifacts" / "bam" / "hl2915-m6.json"
    model.parent.mkdir(parents=True)
    model.write_text('{"motor":"hl2915","model":"m6"}', encoding="utf-8")
    data = {
        "actuator_model": "HL-2915",
        "raw_summary": {"status": "passed", "rows": 1000, "duration_s": 20, "expected_hz": 50, "ids": [1], "faults": [], "errors": []},
        "fit": {"path": str(model), "model": "m6", "trials": 2000},
        "validation": {"dataset": "held-out-bench", "independent": False, "mae": 0.3},
        "conditions": {"voltage_v": [7.4, 7.6], "temperature_c": [22, 31], "load": "120g pendulum"},
    }

    record = store.save_identification(project["id"], data)

    assert record["hardware_profile_id"] == hardware["id"]
    assert record["readiness"] == "incomplete"
    assert "independent_validation_required" in record["reasons"]


def test_identification_record_can_be_ready_for_simulation(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("辨识通过", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    model = tmp_path / "hl2915-m6.json"
    model.write_text('{"motor":"hl2915","model":"m6"}', encoding="utf-8")

    record = store.save_identification(
        project["id"],
        {
            "actuator_model": "HL-2915",
            "raw_summary": {"status": "passed", "rows": 1000, "duration_s": 20, "expected_hz": 50, "ids": [1], "faults": [], "errors": []},
            "fit": {"path": str(model), "model": "m6", "trials": 2000},
            "validation": {"dataset": "held-out-bench", "independent": True, "mae": 0.3},
            "conditions": {"voltage_v": [7.4, 7.6], "temperature_c": [22, 31], "load": "120g pendulum"},
        },
    )

    assert record["readiness"] == "ready_for_simulation"
    assert record["reasons"] == []
    assert next(
        task for task in store.project_report(project["id"])["tasks"] if task["id"] == "identification"
    )["status"] == "blocked"


def test_ready_identification_unlocks_identification_task_after_servo_read(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("辨识任务", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "servo_read", "success")
    model = tmp_path / "hl2915-m6.json"
    model.write_text('{"motor":"hl2915","model":"m6"}', encoding="utf-8")

    store.save_identification(
        project["id"],
        {
            "actuator_model": "HL-2915",
            "raw_summary": {"status": "passed", "rows": 1000, "duration_s": 20, "expected_hz": 50, "ids": [1], "faults": [], "errors": []},
            "fit": {"path": str(model), "model": "m6", "trials": 2000},
            "validation": {"dataset": "held-out-bench", "independent": True, "mae": 0.3},
        },
    )

    task = next(task for task in store.project_report(project["id"])["tasks"] if task["id"] == "identification")
    assert task["status"] == "success"


def test_identification_rejects_servo_model_mismatch(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("辨识型号冲突", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    model = tmp_path / "model.json"
    model.write_text("{}", encoding="utf-8")

    record = store.save_identification(
        project["id"],
        {
            "actuator_model": "HL-1910",
            "raw_summary": {"status": "passed", "rows": 10, "duration_s": 1, "expected_hz": 50, "ids": [1], "faults": [], "errors": []},
            "fit": {"path": str(model), "model": "m6", "trials": 100},
            "validation": {"dataset": "held-out", "independent": True, "mae": 0.2},
        },
    )

    assert record["readiness"] == "inconsistent"
    assert "servo_model_mismatch" in record["reasons"]


def test_identification_rejects_invalid_fit_json(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("辨识文件损坏", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    model = tmp_path / "model.json"
    model.write_text("not json", encoding="utf-8")

    record = store.save_identification(
        project["id"],
        {
            "actuator_model": "HL-2915",
            "raw_summary": {"status": "passed", "rows": 10, "duration_s": 1, "expected_hz": 50, "ids": [1], "faults": [], "errors": []},
            "fit": {"path": str(model), "model": "m6", "trials": 100},
            "validation": {"dataset": "held-out", "independent": True, "mae": 0.2},
        },
    )

    assert record["readiness"] == "incomplete"
    assert "fit_artifact_invalid" in record["reasons"]


def test_issue_record_keeps_diagnosis_and_resolution(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("问题台账", tmp_path)
    hardware = store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    issue = store.create_issue(
        project["id"],
        {
            "title": "主控不可达",
            "severity": "critical",
            "symptom": "SSH 连接超时",
            "suspected_causes": ["网络不可达", "主机密钥未确认"],
            "next_checks": ["确认地址和网络", "检查 known_hosts"],
            "evidence_refs": ["run-1"],
        },
    )
    updated = store.update_issue(issue["id"], {"status": "resolved", "resolution": "已补充主机密钥"})
    saved = store.project_report(project["id"])["issues"][0]

    assert issue["hardware_profile_id"] == hardware["id"]
    assert updated["status"] == "resolved"
    assert saved["next_checks"] == ["确认地址和网络", "检查 known_hosts"]
    assert saved["valid_for_current_hardware"] is True
    assert "解决结论：已补充主机密钥" in store.project_report_markdown(project["id"])


def test_issue_can_link_terminal_run_as_evidence_without_closing(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("问题证据关联", tmp_path)
    issue = store.create_issue(
        project["id"],
        {"title": "通信抖动", "symptom": "间歇丢包", "evidence_refs": ["photo://wiring"]},
    )
    run = store.start_run(project["id"], "bench_continuous")

    with pytest.raises(ValueError, match="terminal"):
        store.link_run_to_issue(project["id"], issue["id"], run["id"])

    store.finish_run(run["id"], "passed", {"status": "passed", "packets_lost": 0})
    linked = store.link_run_to_issue(project["id"], issue["id"], run["id"])
    linked_again = store.link_run_to_issue(project["id"], issue["id"], run["id"])

    assert linked["evidence_refs"] == ["photo://wiring", run["id"]]
    assert linked_again["evidence_refs"] == linked["evidence_refs"]
    assert linked_again["status"] == "open"
    evidence = store.project_report(project["id"])["issues"][0]["evidence_details"]
    assert evidence == [{
        "run_id": run["id"],
        "kind": "bench_continuous",
        "status": "passed",
        "evidence_scope": "bench_evidence",
    }]
    assert f"证据引用：photo://wiring；{run['id']}" in store.project_report_markdown(project["id"])


def test_issue_report_resolves_artifact_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("问题产物证据", tmp_path)
    output = tmp_path / "probe.log"
    output.write_text("packets_lost=0", encoding="utf-8")
    artifact = store.register_artifact(project["id"], output, "log")
    issue = store.create_issue(
        project["id"],
        {"title": "已验证问题", "symptom": "待确认", "evidence_refs": [artifact["id"]]},
    )

    evidence = store.project_report(project["id"])["issues"][0]["evidence_details"]

    assert evidence == [{
        "artifact_id": artifact["id"],
        "artifact_kind": "log",
        "integrity_status": "verified",
        "path": str(output.resolve()),
    }]
    assert issue["id"]


def test_issue_report_resolves_source_evidence(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("问题来源证据", tmp_path)
    source = store.save_source(
        project["id"], {"kind": "assembly", "location": "docs/assembly.md", "revision": "abc123"}
    )
    store.create_issue(
        project["id"],
        {"title": "资料待核对", "symptom": "型号冲突", "evidence_refs": [source["id"]]},
    )

    evidence = store.project_report(project["id"])["issues"][0]["evidence_details"]

    assert evidence == [{
        "source_id": source["id"],
        "source_kind": "assembly",
        "location": "docs/assembly.md",
        "revision": "abc123",
        "revision_matches": None,
    }]


def test_issue_can_be_created_from_run_guidance(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("运行问题", tmp_path)
    run = store.start_run(project["id"], "controller_diagnostic")
    store.finish_run(
        run["id"],
        "failed",
        {
            "category": "controller_unreachable",
            "reasons": ["ssh_unreachable"],
            "guidance": {
                "current_facts": ["SSH 未建立"],
                "possible_causes": ["网络不可达"],
                "next_checks": ["确认主控地址"],
            },
        },
    )

    issue = store.create_issue_from_run(project["id"], run["id"])

    assert issue["status"] == "open"
    assert issue["symptom"] == "SSH 未建立"
    assert issue["suspected_causes"] == ["网络不可达"]
    assert issue["next_checks"] == ["确认主控地址"]
    assert run["id"] in issue["evidence_refs"]


def test_issue_validation_rejects_unknown_state(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("问题校验", tmp_path)

    with pytest.raises(ValueError, match="severity"):
        store.create_issue(project["id"], {"title": "x", "severity": "urgent", "symptom": "y"})


def test_issue_from_run_rejects_successful_run(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("成功运行不可作故障", tmp_path)
    run = store.start_run(project["id"], "controller_diagnostic")
    store.finish_run(run["id"], "passed", {"category": "healthy"})

    with pytest.raises(ValueError, match="failed or interrupted"):
        store.create_issue_from_run(project["id"], run["id"])


def test_projects_can_be_listed_after_store_reopen(tmp_path: Path):
    db = tmp_path / "studio.db"
    first = StudioStore(db)
    project = first.create_project("可恢复项目", tmp_path)

    reopened = StudioStore(db)
    projects = reopened.list_projects()

    assert projects[0]["id"] == project["id"]
    assert projects[0]["name"] == "可恢复项目"


def test_reopening_store_migrates_new_deployment_tasks(tmp_path: Path):
    db = tmp_path / "studio.db"
    first = StudioStore(db)
    project = first.create_project("任务迁移", tmp_path)
    with first._connect() as conn:
        conn.execute(
            "DELETE FROM tasks WHERE project_id = ? AND id IN ('deployment_preflight', 'deployment')",
            (project["id"],),
        )

    reopened = StudioStore(db)

    task_ids = {task["id"] for task in reopened.project_report(project["id"])["tasks"]}
    assert {"deployment_preflight", "deployment"} <= task_ids


def test_preflight_reports_machine_facts_and_optional_capabilities(tmp_path: Path):
    result = preflight(tmp_path)
    checks = {item["name"]: item for item in result["checks"]}

    assert {"platform", "architecture", "disk_free_bytes", "docker", "gpu"} <= set(checks)
    assert {"captured_at", "platform", "tools", "git"} <= set(result["baseline"])
    assert {"python", "uv", "rustc", "cargo"} <= set(result["baseline"]["tools"])
    assert checks["ssh"]["required"] is False
    assert checks["platform"]["mutates"] is False
    assert checks["docker"]["required"] is False
    assert checks["gpu"]["required"] is False


def test_sources_are_versioned_per_project(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("来源测试", tmp_path)
    source = store.save_source(
        project["id"],
        {
            "kind": "training",
            "location": "https://example.invalid/microduck_rl",
            "revision": "abc123",
            "license_status": "unknown",
        },
    )

    report = store.project_report(project["id"])

    assert source["revision"] == "abc123"
    assert report["sources"][0]["kind"] == "training"


def test_sources_can_be_listed_without_loading_full_report(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("来源列表", tmp_path)
    store.save_source(
        project["id"],
        {
            "kind": "training",
            "location": "microduck_rl",
            "revision": "abc123",
            "license_status": "unknown",
        },
    )

    sources = store.list_sources(project["id"])

    assert len(sources) == 1
    assert sources[0]["kind"] == "training"
    assert sources[0]["revision"] == "abc123"
    assert sources[0]["schema_version"] == 1


def test_local_git_source_captures_actual_revision_and_dirty_state(tmp_path: Path):
    repository = tmp_path / "training"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "studio@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Microduck Studio Test"], cwd=repository, check=True)
    (repository / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=repository, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repository / "README.md").write_text("dirty\n", encoding="utf-8")

    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("本地来源", tmp_path)
    source = store.save_source(
        project["id"],
        {"kind": "training", "location": str(repository), "revision": None},
    )

    assert source["revision"] == commit
    assert source["metadata"]["git"]["branch"]
    assert source["metadata"]["git"]["dirty"] is True
    assert source["metadata"]["revision_matches"] is True
    assert source["metadata"]["scanned_at"]


def test_hardware_profile_history_is_preserved(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("硬件历史", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": None, "candidates": ["HL-1910", "HL-2915"]}})
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})

    report = store.project_report(project["id"])

    assert report["hardware"]["status"] == "confirmed"
    assert len(report["hardware_history"]) == 2


def test_reopening_store_interrupts_incomplete_runs(tmp_path: Path):
    db = tmp_path / "studio.db"
    first = StudioStore(db)
    project = first.create_project("恢复运行", tmp_path)
    first.set_task_status(project["id"], "smoke", "running")
    run = first.start_run(project["id"], "training_smoke")

    reopened = StudioStore(db)
    saved = reopened.project_report(project["id"])["runs"][0]
    task = next(item for item in reopened.project_report(project["id"])["tasks"] if item["id"] == "smoke")

    assert saved["id"] == run["id"]
    assert saved["status"] == "interrupted"
    assert saved["result"]["status"] == "interrupted"
    assert "service_restarted" in saved["result"]["reasons"]
    assert task["status"] == "interrupted"


def test_terminal_run_cannot_be_overwritten_by_late_worker(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("终态保护", tmp_path)
    run = store.start_run(project["id"], "training_smoke")

    store.finish_run(run["id"], "interrupted", {"reasons": ["service_restarted"]})
    store.finish_run(run["id"], "passed", {"reasons": []})

    saved = store.get_run(run["id"])
    assert saved["status"] == "interrupted"
    assert saved["result"]["reasons"] == ["service_restarted"]


def test_terminal_run_result_cannot_be_updated_by_late_worker(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("终态证据保护", tmp_path)
    run = store.start_run(project["id"], "training_smoke")

    store.finish_run(run["id"], "interrupted", {"reasons": ["service_restarted"]})
    store.update_run_result(run["id"], {"progress": 1.0, "reasons": []})

    saved = store.get_run(run["id"])
    assert saved["status"] == "interrupted"
    assert saved["result"]["reasons"] == ["service_restarted"]


def test_finish_run_keeps_result_status_consistent(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("运行状态一致", tmp_path)
    run = store.start_run(project["id"], "preflight")

    with pytest.raises(ValueError, match="result status"):
        store.finish_run(run["id"], "passed", {"status": "failed"})

    store.finish_run(run["id"], "passed", {"checks": []})
    assert store.get_run(run["id"])["result"]["status"] == "passed"


def test_update_run_result_cannot_write_terminal_status_while_running(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("运行中状态保护", tmp_path)
    run = store.start_run(project["id"], "preflight")

    with pytest.raises(ValueError, match="running status"):
        store.update_run_result(run["id"], {"status": "passed"})

    store.update_run_result(run["id"], {"status": "running", "progress": 0.5})
    assert store.get_run(run["id"])["result"]["progress"] == 0.5


def test_retry_reuses_persisted_probe_parameters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("探针重试", tmp_path)
    run = store.start_run(project["id"], "hl2915_read_only_probe")
    store.finish_run(
        run["id"],
        "failed",
        {"parameters": {"port": "COM7", "ids": [1, 2], "watch_seconds": 12}},
    )
    captured = {}

    def fake_retry(project_id, port, ids, watch_seconds, *, confirm):
        captured.update(project_id=project_id, port=port, ids=ids, watch_seconds=watch_seconds, confirm=confirm)
        return {"id": "retry-run", "status": "running"}

    monkeypatch.setattr(store, "start_read_only_probe", fake_retry)

    retried = store.retry_run(run["id"], confirm=True)
    assert retried["id"] == "retry-run"
    assert retried["status"] == "running"
    assert captured == {
        "project_id": project["id"], "port": "COM7", "ids": [1, 2], "watch_seconds": 12, "confirm": True,
    }


def test_retry_reuses_persisted_training_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("训练重试", tmp_path)
    training_dir = tmp_path / "training"
    run = store.start_run(project["id"], "training_smoke")
    store.finish_run(run["id"], "interrupted", {"training_dir": str(training_dir)})
    captured = {}

    def fake_retry(project_id, training_dir_value, *, confirm):
        captured.update(project_id=project_id, training_dir=training_dir_value, confirm=confirm)
        return {"id": "retry-training", "status": "running"}

    monkeypatch.setattr(store, "start_training_smoke", fake_retry)

    retried = store.retry_run(run["id"], confirm=True)
    assert retried["id"] == "retry-training"
    assert retried["status"] == "running"
    assert captured == {
        "project_id": project["id"], "training_dir": str(training_dir), "confirm": True,
    }


def test_retry_requires_confirmation_and_does_not_retry_motion(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("安全边界", tmp_path)
    run = store.start_run(project["id"], "preflight")
    store.finish_run(run["id"], "failed", {})

    with pytest.raises(PermissionError, match="explicit confirmation"):
        store.retry_run(run["id"], confirm=False)
    with pytest.raises(ValueError, match="automatic retry is unavailable"):
        store.retry_run(run["id"], confirm=True)


def test_retry_records_parent_run_for_traceability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("重试溯源", tmp_path)
    original = store.start_run(project["id"], "hl2915_read_only_probe")
    store.finish_run(
        original["id"],
        "failed",
        {"parameters": {"port": "COM7", "ids": [1], "watch_seconds": 5}},
    )

    def fake_retry(project_id, port, ids, watch_seconds, *, confirm):
        retry = store.start_run(project_id, "hl2915_read_only_probe")
        store.update_run_result(retry["id"], {"status": "running", "parameters": {"port": port, "ids": ids, "watch_seconds": watch_seconds}})
        return store.get_run(retry["id"])

    monkeypatch.setattr(store, "start_read_only_probe", fake_retry)

    retried = store.retry_run(original["id"], confirm=True)
    assert store.get_run(retried["id"])["result"]["retry_of"] == original["id"]


def test_retry_rejects_malformed_persisted_probe_options(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("重试参数校验", tmp_path)
    run = store.start_run(project["id"], "hl2915_read_only_probe")
    store.finish_run(
        run["id"],
        "failed",
        {"parameters": {"port": "COM7", "ids": [1], "watch_seconds": 5, "include_imu": "false"}},
    )

    with pytest.raises(ValueError, match="retry parameters are invalid"):
        store.retry_run(run["id"], confirm=True)


def test_probe_plan_requires_confirmed_hl2915_hardware(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("探针计划", tmp_path)

    with pytest.raises(ValueError, match="hardware confirmation"):
        store.build_read_only_probe_plan(project["id"], "COM3", [1], 10)


def test_probe_plan_is_fixed_to_read_only_command(tmp_path: Path):
    (tmp_path / "duck-control" / "src" / "bin").mkdir(parents=True)
    (tmp_path / "duck-control" / "src" / "bin" / "hl2915_mixed_probe.rs").write_text(
        "// read-only probe", encoding="utf-8"
    )
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("探针计划", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )

    plan = store.build_read_only_probe_plan(project["id"], "COM3", [1, 2], 10)

    assert plan["mutates"] is False
    assert plan["command"] == [
        "cargo", "run", "-p", "duck-control", "--bin", "hl2915_mixed_probe", "--",
        "COM3", "1", "2", "--watch-seconds", "10",
    ]
    assert plan["cwd"] == str(tmp_path.resolve())


def test_servo_only_probe_plan_does_not_require_imu(tmp_path: Path):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_probe.rs").write_text("// servo-only read-only probe", encoding="utf-8")
    (source / "hl2915_mixed_probe.rs").write_text("// mixed read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("无 IMU 探针计划", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )

    plan = store.build_read_only_probe_plan(project["id"], "COM3", [1, 2], 10, include_imu=False)

    assert plan["command"] == [
        "cargo", "run", "-p", "duck-control", "--bin", "hl2915_probe", "--",
        "COM3", "1", "2", "--watch-seconds", "10",
    ]
    assert plan["parameters"]["include_imu"] is False
    assert plan["constraints"]["requires_imu"] is False


def test_servo_only_probe_output_is_valid_without_imu_summary():
    result = evaluate_probe_process(
        returncode=0,
        timed_out=False,
        stdout=(
            "watch complete: samples=5, errors=0, status_faults=0, "
            "voltage_faults=0, temperature_faults=0, current_faults=0, "
            "min_voltage=12.0V, max_temperature=32°C"
        ),
        stderr="",
        duration_s=10,
        required_duration_s=10,
        include_imu=False,
    )

    assert result["status"] == "passed"
    assert result["summary"]["mode"] == "servo"
    assert result["summary"]["imu_ready"] is None


def test_probe_plan_rejects_imu_id_and_long_watch(tmp_path: Path):
    (tmp_path / "duck-control" / "src" / "bin").mkdir(parents=True)
    (tmp_path / "duck-control" / "src" / "bin" / "hl2915_mixed_probe.rs").write_text(
        "// read-only probe", encoding="utf-8"
    )
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("探针边界", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})

    with pytest.raises(ValueError, match="ID=200"):
        store.build_read_only_probe_plan(project["id"], "COM3", [200], 10)
    with pytest.raises(ValueError, match="300"):
        store.build_read_only_probe_plan(project["id"], "COM3", [1], 301)
    with pytest.raises(ValueError, match="serial port"):
        store.build_read_only_probe_plan(project["id"], 3, [1], 10)


def test_bam_record_plan_is_safe_and_bound_to_confirmed_hardware(tmp_path: Path):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_bam_record.rs").write_text("// bounded motion recorder", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("BAM计划", tmp_path)
    hardware = store.save_hardware(
        project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}}
    )
    store.set_task_status(project["id"], "servo_read", "success")

    plan = store.build_bam_record_plan(
        project["id"],
        port="COM3",
        servo_id=1,
        mass_kg=0.05,
        arm_length_m=0.1,
        output_path="artifacts/bam/raw/test.json",
        amplitude_deg=10,
        duration_s=6,
        confirm_motion=False,
    )

    assert plan["hardware_profile_id"] == hardware["id"]
    assert plan["mutates"] is True
    assert plan["safety"]["requires_confirm_motion"] is True
    assert "--confirm-motion" in plan["command"]
    assert plan["output_path"].startswith(str(tmp_path.resolve()))
    assert plan["does_not_start_process"] is True


def test_bam_record_plan_rejects_unsafe_parameters(tmp_path: Path):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_bam_record.rs").write_text("// bounded motion recorder", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("BAM参数", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "servo_read", "success")

    with pytest.raises(ValueError, match="amplitude"):
        store.build_bam_record_plan(
            project["id"], "COM3", 1, 0.05, 0.1, "artifacts/test.json", amplitude_deg=31
        )


def test_bam_record_process_requires_new_parseable_output(tmp_path: Path):
    output = tmp_path / "bam.json"
    missing = evaluate_bam_record_process(
        returncode=0,
        timed_out=False,
        stdout="ok",
        stderr="",
        duration_s=6,
        output_path=output,
        output_baseline=None,
    )
    assert missing["status"] == "insufficient_evidence"
    assert "missing_raw_output" in missing["reasons"]

    output.write_text('{"entries":[{"timestamp":0,"position":0}]}', encoding="utf-8")
    passed = evaluate_bam_record_process(
        returncode=0,
        timed_out=False,
        stdout="ok",
        stderr="",
        duration_s=6,
        output_path=output,
        output_baseline=None,
    )
    assert passed["status"] == "passed"
    assert passed["raw_json_valid"] is True


def test_bam_record_run_requires_double_confirmation_and_persists_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_bam_record.rs").write_text("// bounded motion recorder", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("BAM执行", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "servo_read", "success")

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "recorded", ""

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    def fake_popen(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"entries":[{"timestamp":0,"position":0}]}', encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", fake_popen)
    with pytest.raises(PermissionError, match="motion"):
        store.start_bam_record(
            project["id"], "COM3", 1, 0.05, 0.1, "artifacts/bam/raw/run.json", confirm=True, confirm_motion=False
        )

    run = store.start_bam_record(
        project["id"], "COM3", 1, 0.05, 0.1, "artifacts/bam/raw/run.json", confirm=True, confirm_motion=True
    )
    deadline = time.time() + 2
    saved = store.get_run(run["id"])
    while saved["status"] == "running" and time.time() < deadline:
        time.sleep(0.01)
        saved = store.get_run(run["id"])

    assert saved["status"] == "passed"
    assert saved["result"]["artifact_id"]
    assert saved["result"]["parameters"]["mass_kg"] == 0.05
    assert saved["result"]["parameters"]["amplitude_deg"] == 10.0
    assert store.project_report(project["id"])["artifacts"][0]["kind"] == "bam_raw"


def test_bam_record_cannot_share_the_servo_bus_with_probe(tmp_path: Path):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_bam_record.rs").write_text("// bounded motion recorder", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("BAM总线互斥", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "servo_read", "success")
    store.start_run(project["id"], "hl2915_read_only_probe")

    with pytest.raises(RuntimeError, match="bench bus"):
        store.start_bam_record(
            project["id"], "COM3", 1, 0.05, 0.1, "artifacts/bam/raw/blocked.json", confirm=True, confirm_motion=True
        )


def test_probe_process_requires_complete_error_free_summary():
    result = evaluate_probe_process(
        returncode=0,
        timed_out=False,
        stdout=(
            "watch complete: samples=40, errors=0, stale_imu=2, max_stale_run=2, imu_ready=true, "
            "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0"
        ),
        stderr="",
        duration_s=10,
        required_duration_s=10,
    )

    assert result["status"] == "passed"
    assert result["summary"] == {
        "samples": 40, "errors": 0, "stale_imu": 2, "max_stale_run": 2,
        "imu_ready": True, "mode": "mixed", "status_faults": 0,
        "voltage_faults": 0, "temperature_faults": 0, "current_faults": 0,
    }


def test_probe_process_rejects_too_few_or_frozen_imu_samples():
    def evaluate(samples: int, max_stale_run: int):
        return evaluate_probe_process(
            returncode=0,
            timed_out=False,
            stdout=(
                f"watch complete: samples={samples}, errors=0, stale_imu={max_stale_run}, "
                f"max_stale_run={max_stale_run}, imu_ready=true, status_faults=0, "
                "voltage_faults=0, temperature_faults=0, current_faults=0"
            ),
            stderr="",
            duration_s=10,
            required_duration_s=10,
        )

    too_few = evaluate(5, 0)
    frozen = evaluate(100, 25)

    assert too_few["status"] == "failed"
    assert "imu_samples" in too_few["reasons"]
    assert frozen["status"] == "failed"
    assert "imu_frozen" in frozen["reasons"]


def test_probe_process_rejects_timeout_and_missing_summary():
    timeout = evaluate_probe_process(
        returncode=None,
        timed_out=True,
        stdout="",
        stderr="",
        duration_s=3,
        required_duration_s=10,
    )
    missing = evaluate_probe_process(
        returncode=0,
        timed_out=False,
        stdout="protocol Ping 正常",
        stderr="",
        duration_s=10,
        required_duration_s=10,
    )

    assert timeout["status"] == "interrupted"
    assert "timeout" in timeout["reasons"]
    assert missing["status"] == "insufficient_evidence"
    assert "missing_probe_summary" in missing["reasons"]


def test_probe_execution_requires_explicit_confirmation(tmp_path: Path):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("执行确认", tmp_path)
    with pytest.raises(PermissionError, match="explicit confirmation"):
        store.execute_read_only_probe(project["id"], "COM3", [1], 1, confirm=False)


def test_probe_execution_persists_structured_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_mixed_probe.rs").write_text("// read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("执行记录", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )

    def fake_run(command, **kwargs):
        assert command[-2:] == ["--watch-seconds", "1"]
        assert kwargs["shell"] is False
        task = next(item for item in store.project_report(project["id"])["tasks"] if item["id"] == "servo_read")
        assert task["status"] == "running"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                "watch complete: samples=50, errors=0, stale_imu=0, max_stale_run=0, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("microduck_studio.core.subprocess.run", fake_run)
    clock = iter([100.0, 101.1])
    monkeypatch.setattr("microduck_studio.core.time.monotonic", lambda: next(clock))
    result = store.execute_read_only_probe(project["id"], "COM3", [1], 1, confirm=True)
    saved = store.project_report(project["id"])["runs"][0]

    assert result["status"] == "passed"
    assert saved["kind"] == "hl2915_read_only_probe"
    assert saved["result"]["summary"]["imu_ready"] is True
    assert saved["result"]["command"][-2:] == ["--watch-seconds", "1"]


def test_probe_execution_blocks_a_second_running_bus_use(tmp_path: Path):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_mixed_probe.rs").write_text("// read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("总线互斥", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    store.start_run(project["id"], "hl2915_read_only_probe")

    with pytest.raises(RuntimeError, match="already running"):
        store.execute_read_only_probe(project["id"], "COM3", [1], 1, confirm=True)


def test_probe_can_be_cancelled_and_persists_interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_mixed_probe.rs").write_text("// read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("取消探针", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )

    class FakeProcess:
        def __init__(self):
            self.stopped = threading.Event()
            self.returncode = None

        def communicate(self, timeout=None):
            if not self.stopped.wait(timeout):
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = -15
            return "", "terminated"

        def terminate(self):
            self.stopped.set()

        def kill(self):
            self.stopped.set()

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: process)
    run = store.start_read_only_probe(project["id"], "COM3", [1], 30, confirm=True)

    assert run["status"] == "running"
    task = next(item for item in store.project_report(project["id"])["tasks"] if item["id"] == "servo_read")
    assert task["status"] == "running"
    cancel = store.cancel_run(run["id"])
    assert cancel["status"] == "cancelling"
    for _ in range(100):
        saved = store.get_run(run["id"])
        if saved["status"] != "running":
            break
        time.sleep(0.01)

    assert saved["status"] == "interrupted"
    assert "cancelled" in saved["result"]["reasons"]


def test_cancel_run_stops_posix_process_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from microduck_studio import core as studio_core

    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("进程组取消", tmp_path)
    run = store.start_run(project["id"], "training_smoke")

    class FakeProcess:
        pid = 4321

        def terminate(self):
            raise AssertionError("parent-only termination should not be used")

        def kill(self):
            raise AssertionError("parent-only kill should not be used")

    process = FakeProcess()
    calls = []
    monkeypatch.setitem(studio_core._ACTIVE_PROCESSES, run["id"], process)
    monkeypatch.setattr(studio_core.os, "name", "posix")
    monkeypatch.setattr(studio_core.os, "killpg", lambda pid, sig: calls.append((pid, sig)), raising=False)

    assert store.cancel_run(run["id"])["status"] == "cancelling"
    assert calls and calls[0][0] == process.pid


def test_probe_start_failure_is_not_left_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_mixed_probe.rs").write_text("// read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("探针启动失败", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    monkeypatch.setattr(
        "microduck_studio.core.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ssh/serial process missing")),
    )

    result = store.start_read_only_probe(project["id"], "COM3", [1], 1, confirm=True)

    assert result["status"] == "failed"
    assert store.get_run(result["id"])["status"] == "failed"


def test_probe_result_cannot_restore_success_after_hardware_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_mixed_probe.rs").write_text("// read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("旧探针证据", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )

    class FakeProcess:
        def __init__(self):
            self.released = threading.Event()
            self.returncode = None

        def communicate(self, timeout=None):
            if not self.released.wait(timeout):
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = 0
            return (
                "watch complete: samples=50, errors=0, stale_imu=0, max_stale_run=0, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0",
                "",
            )

        def terminate(self):
            self.released.set()

        def kill(self):
            self.released.set()

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: process)
    run = store.start_read_only_probe(project["id"], "COM3", [1], 1, confirm=True)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-1910", "candidates": ["HL-1910"]}},
    )
    time.sleep(1.05)
    process.released.set()
    for _ in range(100):
        saved = store.get_run(run["id"])
        if saved["status"] != "running":
            break
        time.sleep(0.01)

    task = next(item for item in store.project_report(project["id"])["tasks"] if item["id"] == "servo_read")
    assert saved["status"] == "passed"
    assert task["status"] == "ready"


def test_restarted_probe_worker_cannot_restore_interrupted_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "duck-control" / "src" / "bin"
    source.mkdir(parents=True)
    (source / "hl2915_mixed_probe.rs").write_text("// read-only probe", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("重启探针任务", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )

    class FakeProcess:
        def __init__(self):
            self.released = threading.Event()
            self.finished = threading.Event()
            self.returncode = None

        def communicate(self, timeout=None):
            if not self.released.wait(timeout):
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = 0
            self.finished.set()
            return (
                "watch complete: samples=50, errors=0, stale_imu=0, max_stale_run=0, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0",
                "",
            )

        def terminate(self):
            self.released.set()

        def kill(self):
            self.released.set()

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: process)
    clock = iter([100.0, 101.1])
    monkeypatch.setattr("microduck_studio.core.time.monotonic", lambda: next(clock))
    task_updated = threading.Event()
    original_set_task = store._set_hardware_bound_task_status

    def observe_task_update(*args, **kwargs):
        task_updated.set()
        return original_set_task(*args, **kwargs)

    monkeypatch.setattr(store, "_set_hardware_bound_task_status", observe_task_update)
    run = store.start_read_only_probe(project["id"], "COM3", [1], 1, confirm=True)

    StudioStore(tmp_path / "studio.db")
    process.released.set()
    assert process.finished.wait(1.0)
    assert task_updated.wait(1.0)
    task = next(item for item in store.project_report(project["id"])["tasks"] if item["id"] == "servo_read")

    assert store.get_run(run["id"])["status"] == "interrupted"
    assert task["status"] == "interrupted"


def test_controller_plan_is_fixed_and_rejects_unsafe_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("主控诊断", tmp_path)
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: "/usr/bin/ssh" if name == "ssh" else None)

    plan = store.build_controller_diagnostic_plan(project["id"], "duck.local", "rock", 22)

    assert plan["mutates"] is False
    assert plan["command"] == [
        "/usr/bin/ssh",
        "-T",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=yes",
        "-p", "22",
        "rock@duck.local",
        "robotctl", "health", "--json",
    ]
    with pytest.raises(ValueError, match="host"):
        store.build_controller_diagnostic_plan(project["id"], "-oProxyCommand=bad", "rock", 22)


def test_controller_health_distinguishes_healthy_and_version_warning():
    healthy = evaluate_controller_health(
        returncode=0,
        timed_out=False,
        stdout=json.dumps({"robot": {"healthy": True}, "software": {"warnings": [], "services": []}}),
        stderr="",
        duration_s=1,
    )
    warning = evaluate_controller_health(
        returncode=0,
        timed_out=False,
        stdout=json.dumps({"robot": {"healthy": True}, "software": {"warnings": ["robotd revision mismatch"], "services": []}}),
        stderr="",
        duration_s=1,
    )

    assert healthy["status"] == "passed"
    assert healthy["category"] == "healthy"
    assert warning["status"] == "failed"
    assert warning["category"] == "version_or_software_mismatch"


def test_controller_health_marks_unreachable_and_missing_robot():
    unreachable = evaluate_controller_health(
        returncode=255,
        timed_out=False,
        stdout="",
        stderr="ssh: connect to host duck.local port 22: Connection refused",
        duration_s=2,
    )
    missing_robot = evaluate_controller_health(
        returncode=0,
        timed_out=False,
        stdout=json.dumps({"robot": None, "robot_error": "robotd unavailable", "software": {}}),
        stderr="",
        duration_s=1,
    )

    assert unreachable["status"] == "failed"
    assert unreachable["category"] == "controller_unreachable"
    assert "确认主控地址、网络和 SSH 主机密钥" in unreachable["guidance"]["next_checks"]
    assert missing_robot["status"] == "failed"
    assert missing_robot["category"] == "software_unhealthy"
    assert "检查 robotd 服务状态和启动日志" in missing_robot["guidance"]["next_checks"]


def test_controller_health_does_not_fill_missing_software_health():
    partial = evaluate_controller_health(
        returncode=0,
        timed_out=False,
        stdout=json.dumps({"robot": {"healthy": True}}),
        stderr="",
        duration_s=1,
    )

    assert partial["status"] == "insufficient_evidence"
    assert partial["category"] == "insufficient_evidence"
    assert "missing_software_health" in partial["reasons"]


def test_controller_health_rejects_malformed_software_lists():
    malformed = evaluate_controller_health(
        returncode=0,
        timed_out=False,
        stdout=json.dumps({"robot": {"healthy": True}, "software": {"warnings": [], "services": ["robotd"]}}),
        stderr="",
        duration_s=1,
    )

    assert malformed["status"] == "insufficient_evidence"
    assert "malformed_software_health" in malformed["reasons"]


def test_controller_execution_persists_health_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("主控执行", tmp_path)
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: "/usr/bin/ssh" if name == "ssh" else None)

    def fake_run(command, **kwargs):
        assert command[-3:] == ["robotctl", "health", "--json"]
        assert kwargs["shell"] is False
        task = next(item for item in store.project_report(project["id"])["tasks"] if item["id"] == "controller_read")
        assert task["status"] == "running"
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"robot": {"healthy": True}, "software": {"warnings": [], "services": []}}),
            stderr="",
        )

    monkeypatch.setattr("microduck_studio.core.subprocess.run", fake_run)
    clock = iter([100.0, 101.0])
    monkeypatch.setattr("microduck_studio.core.time.monotonic", lambda: next(clock))
    result = store.execute_controller_diagnostic(project["id"], "duck.local", "rock", 22)
    saved = store.project_report(project["id"])["runs"][0]

    assert result["status"] == "passed"
    assert saved["kind"] == "controller_diagnostic"
    assert saved["result"]["category"] == "healthy"


def test_training_smoke_plan_is_fixed_and_requires_ready_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("训练计划", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    store.set_task_status(project["id"], "preflight", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")

    plan = store.build_training_smoke_plan(project["id"], training)

    assert plan["kind"] == "training_smoke"
    assert plan["mutates"] is True
    assert plan["command"][-1].endswith("run_5_iteration_smoke.sh")
    assert plan["env"]["MICRODUCK_RL_DIR"] == str(training.resolve())
    assert plan["constraints"] == {
        "task": "Mjlab-Velocity-Flat-MicroDuck",
        "num_envs": 8,
        "steps_per_env": 24,
        "max_iterations": 5,
        "gpu_ids": "None",
    }
    assert plan["training_outputs"]["onnx_pattern"] == "*_lesson-01-repro.onnx"
    assert plan["training_outputs"]["onnx_dir"] == str(
        (training / "logs" / "rsl_rl" / "velocity").resolve()
    )
    assert plan["output_baseline"] == {}


def test_training_smoke_plan_records_training_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    subprocess.run(["git", "init"], cwd=training, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "studio@example.invalid"], cwd=training, check=True)
    subprocess.run(["git", "config", "user.name", "Microduck Studio Test"], cwd=training, check=True)
    (training / "README.md").write_text("training\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=training, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "training baseline"], cwd=training, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=training, check=True, capture_output=True, text=True
    ).stdout.strip()
    (training / "README.md").write_text("training with local changes\n", encoding="utf-8")
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("训练来源", tmp_path)
    store.save_hardware(
        project["id"],
        {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}},
    )
    store.set_task_status(project["id"], "preflight", "success")
    real_which = shutil.which
    monkeypatch.setattr(
        "microduck_studio.core.shutil.which",
        lambda name: real_which(name) if name == "git" else f"/usr/bin/{name}",
    )
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")

    plan = store.build_training_smoke_plan(project["id"], training)

    provenance = plan["training_provenance"]
    assert provenance["source"]["commit"] == commit
    assert provenance["source"]["dirty"] is True
    assert provenance["source"]["tracked_change_count"] == 1
    assert provenance["config"] == plan["constraints"]
    assert provenance["executor_model"] is None
    assert provenance["seed"] is None
    assert provenance["checkpoint"] is None
    assert set(provenance["unavailable"]) == {"executor_model", "seed", "checkpoint"}


def test_training_smoke_evidence_rejects_nan_and_shape_errors():
    clean = evaluate_training_smoke(
        returncode=0, timed_out=False, stdout="training finished\n", stderr="", duration_s=4
    )
    broken = evaluate_training_smoke(
        returncode=0,
        timed_out=False,
        stdout="NaN detected in observation; obs[1,61] -> actions[1,14] shape error",
        stderr="",
        duration_s=4,
    )

    assert clean["status"] == "passed"
    assert broken["status"] == "failed"
    assert "nan" in broken["reasons"]
    assert "shape_error" in broken["reasons"]


def test_training_smoke_plan_marks_native_windows_as_plan_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("Windows 计划", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Windows")

    plan = store.build_training_smoke_plan(project["id"], training)

    assert plan["execution_supported"] is False
    with pytest.raises(ValueError, match="Linux/macOS/WSL2"):
        store.start_training_smoke(project["id"], training, confirm=True)


def test_training_smoke_can_be_cancelled_and_persists_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("取消训练", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")

    class FakeProcess:
        def __init__(self):
            self.stopped = threading.Event()
            self.returncode = None

        def communicate(self, timeout=None):
            if not self.stopped.wait(timeout):
                raise subprocess.TimeoutExpired("fake", timeout)
            self.returncode = -15
            return "", "terminated"

        def terminate(self):
            self.stopped.set()

        def kill(self):
            self.stopped.set()

        def poll(self):
            return self.returncode

    process = FakeProcess()
    monkeypatch.setattr(
        "microduck_studio.core.capture_git_snapshot",
        lambda path: {"available": False, "commit": None, "branch": None, "dirty": None, "tracked_change_count": 0},
    )
    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: process)
    run = store.start_training_smoke(project["id"], training, confirm=True)

    assert run["status"] == "running"
    assert run["result"]["training_provenance"]["source"]["available"] is False
    assert next(task for task in store.project_report(project["id"])["tasks"] if task["id"] == "smoke")["status"] == "running"
    assert store.cancel_run(run["id"])["status"] == "cancelling"
    for _ in range(100):
        saved = store.get_run(run["id"])
        if saved["status"] != "running":
            break
        time.sleep(0.01)

    assert saved["status"] == "interrupted"
    assert "cancelled" in saved["result"]["reasons"]
    assert saved["result"]["training_provenance"] == run["result"]["training_provenance"]


def test_training_smoke_success_without_fresh_outputs_is_insufficient_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("缺少训练产物", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    stale_onnx = training / "logs" / "rsl_rl" / "velocity" / "old_lesson-01-repro.onnx"
    stale_onnx.parent.mkdir(parents=True)
    stale_onnx.write_bytes(b"old")
    stale_contract = tmp_path / "artifacts" / "onnx-contract-lesson-01-repro.json"
    stale_contract.parent.mkdir(parents=True)
    stale_contract.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")
    monkeypatch.setattr(
        "microduck_studio.core.capture_git_snapshot",
        lambda path: {"available": False, "commit": None, "branch": None, "dirty": None, "tracked_change_count": 0},
    )

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "training finished", ""

        def poll(self):
            return self.returncode

    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: FakeProcess())

    run = store.start_training_smoke(project["id"], training, confirm=True)
    for _ in range(100):
        saved = store.get_run(run["id"])
        if saved["status"] != "running":
            break
        time.sleep(0.01)

    assert saved["status"] == "insufficient_evidence"
    assert "training_outputs_missing" in saved["result"]["reasons"]
    assert saved["result"]["training_outputs"]["onnx"] == []
    assert saved["result"]["training_outputs"]["contract"] is None
    assert str(stale_onnx.resolve()) in saved["result"]["output_baseline"]
    assert str(stale_contract.resolve()) in saved["result"]["output_baseline"]


def test_training_smoke_rejects_invalid_fresh_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("无效合同", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")
    monkeypatch.setattr(
        "microduck_studio.core.capture_git_snapshot",
        lambda path: {"available": False, "commit": None, "branch": None, "dirty": None, "tracked_change_count": 0},
    )
    contract = tmp_path / "artifacts" / "onnx-contract-lesson-01-repro.json"
    onnx = training / "logs" / "rsl_rl" / "velocity" / "20260912_lesson-01-repro.onnx"

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            onnx.parent.mkdir(parents=True)
            onnx.write_bytes(b"fake-onnx")
            contract.parent.mkdir(parents=True)
            contract.write_text("{}", encoding="utf-8")
            return "training finished", ""

        def poll(self):
            return self.returncode

    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: FakeProcess())

    run = store.start_training_smoke(project["id"], training, confirm=True)
    for _ in range(100):
        saved = store.get_run(run["id"])
        if saved["status"] != "running":
            break
        time.sleep(0.01)

    assert saved["status"] == "insufficient_evidence"
    assert "training_outputs_invalid" in saved["result"]["reasons"]
    assert "training_outputs_missing" not in saved["result"]["reasons"]


def test_training_smoke_registers_fresh_contract_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    script = tmp_path / "tools" / "microduck_learning"
    script.mkdir(parents=True)
    (script / "run_5_iteration_smoke.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    training = tmp_path / "microduck_rl"
    training.mkdir()
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("有效合同", tmp_path)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("microduck_studio.core.platform_module.system", lambda: "Linux")
    monkeypatch.setattr(
        "microduck_studio.core.capture_git_snapshot",
        lambda path: {"available": False, "commit": None, "branch": None, "dirty": None, "tracked_change_count": 0},
    )
    contract = tmp_path / "artifacts" / "onnx-contract-lesson-01-repro.json"
    onnx = training / "logs" / "rsl_rl" / "velocity" / "20260912_lesson-01-repro.onnx"

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            onnx.parent.mkdir(parents=True)
            onnx.write_bytes(b"fake-onnx")
            contract.parent.mkdir(parents=True)
            contract.write_text(
                json.dumps(
                    {
                        "input": {"shape": [1, 61]},
                        "output": {"shape": [1, 14]},
                        "finite_zero_observation": True,
                    }
                ),
                encoding="utf-8",
            )
            return "training finished", ""

        def poll(self):
            return self.returncode

    monkeypatch.setattr("microduck_studio.core.subprocess.Popen", lambda *args, **kwargs: FakeProcess())

    run = store.start_training_smoke(project["id"], training, confirm=True)
    for _ in range(100):
        saved = store.get_run(run["id"])
        if saved["status"] != "running":
            break
        time.sleep(0.01)

    assert saved["status"] == "passed"
    assert saved["result"]["training_outputs"]["onnx"][0]["sha256"]
    assert saved["result"]["training_outputs"]["contract"]["path"] == str(contract.resolve())
    assert saved["result"]["artifacts"][0]["kind"] == "onnx_contract"


def test_tensorboard_plan_is_fixed_and_binds_training_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "project"
    training = tmp_path / "microduck_rl"
    run_dir = training / "logs" / "run-1"
    output = root / "artifacts" / "tensorboard" / "run-1"
    (root / "tools" / "microduck_learning").mkdir(parents=True)
    (root / "tools" / "microduck_learning" / "analyze_tensorboard.py").write_text("# analyzer", encoding="utf-8")
    run_dir.mkdir(parents=True)
    training.mkdir(exist_ok=True)
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("曲线计划", root)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")

    plan = store.build_tensorboard_plan(project["id"], training, run_dir, output)

    assert plan["kind"] == "tensorboard_summary"
    assert plan["command"] == [
        "/usr/bin/uv", "run", "python", str((root / "tools" / "microduck_learning" / "analyze_tensorboard.py").resolve()),
        "--run-dir", str(run_dir.resolve()), "--output-dir", str(output.resolve()),
    ]
    assert plan["mutates"] is True


def test_tensorboard_summary_requires_all_generated_outputs(tmp_path: Path):
    output = tmp_path / "summary"
    output.mkdir()
    (output / "scalars.csv").write_text("tag,step,value\n", encoding="utf-8")
    complete = evaluate_tensorboard_summary(
        returncode=0, timed_out=False, stdout="done", stderr="", duration_s=2, output_dir=output
    )
    incomplete = evaluate_tensorboard_summary(
        returncode=0, timed_out=False, stdout="done", stderr="", duration_s=2, output_dir=tmp_path / "missing"
    )

    assert complete["status"] == "insufficient_evidence"
    assert "missing_summary_outputs" in complete["reasons"]
    assert incomplete["status"] == "insufficient_evidence"


def test_tensorboard_summary_rejects_unchanged_previous_outputs(tmp_path: Path):
    output = tmp_path / "summary"
    output.mkdir()
    for name in ("scalars.csv", "summary.md", "metrics.png"):
        (output / name).write_bytes(b"previous")
    baseline = {
        path.name: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in output.iterdir()
    }

    result = evaluate_tensorboard_summary(
        returncode=0,
        timed_out=False,
        stdout="done",
        stderr="",
        duration_s=2,
        output_dir=output,
        baseline=baseline,
    )

    assert result["status"] == "insufficient_evidence"
    assert "stale_summary_outputs" in result["reasons"]


def test_tensorboard_execution_registers_generated_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "project"
    training = tmp_path / "microduck_rl"
    run_dir = training / "logs" / "run-1"
    output = root / "artifacts" / "tensorboard" / "run-1"
    analyzer = root / "tools" / "microduck_learning" / "analyze_tensorboard.py"
    analyzer.parent.mkdir(parents=True)
    analyzer.write_text("# analyzer", encoding="utf-8")
    run_dir.mkdir(parents=True)
    store = StudioStore(tmp_path / "studio.db")
    project = store.create_project("曲线执行", root)
    store.save_hardware(project["id"], {"servos": {"model": "HL-2915", "candidates": ["HL-2915"]}})
    store.set_task_status(project["id"], "preflight", "success")
    store.set_task_status(project["id"], "smoke", "success")
    monkeypatch.setattr("microduck_studio.core.shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(command, **kwargs):
        assert kwargs["shell"] is False
        output.mkdir(parents=True)
        (output / "scalars.csv").write_text("tag,step,value\n", encoding="utf-8")
        (output / "summary.md").write_text("# summary\n", encoding="utf-8")
        (output / "metrics.png").write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr("microduck_studio.core.subprocess.run", fake_run)
    result = store.execute_tensorboard_summary(
        project["id"], training, run_dir, output, confirm=True
    )

    assert result["status"] == "passed"
    assert {artifact["kind"] for artifact in result["result"]["artifacts"]} == {
        "tensorboard_scalars", "tensorboard_summary", "tensorboard_plot"
    }
