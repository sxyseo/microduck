"""IMU acceptance records judge the 解读 68 §3.4 protocol server-side.

Every submitted step is re-judged against the documented thresholds with rule version
imu-acceptance-v1. Partial submissions stay insufficient_evidence with the missing steps
named; a failed step makes the record failed even when others pass; only a complete,
passing, operator-signed record counts as IMU installation evidence.
"""
from __future__ import annotations

import pytest

from microduck_studio.core import StudioStore
from microduck_studio.imu_acceptance import ImuAcceptanceStore, validate_acceptance


def full_checks(**overrides) -> list[dict]:
    checks = [
        {"id": "gyro_stationary", "measured": {"gx_rad_s": 0.002, "gy_rad_s": -0.003, "gz_rad_s": 0.001, "duration_s": 60}},
        {"id": "gravity_upright", "measured": {"gravity": [0.01, -0.02, -0.998]}},
        {"id": "gravity_inverted", "measured": {"gravity": [-0.01, 0.02, 0.998]}},
        {"id": "pitch_sign", "measured": {"gyro_y_rad_s": 0.31, "matches_convention": True}},
        {"id": "quat_rotation", "measured": {"quat_before": [1, 0, 0, 0], "quat_after": [0.7, 0, 0, 0.71], "no_jump": True}},
        {"id": "soak_50hz", "measured": {"duration_s": 600, "hz": 50, "samples": 30000, "max_consecutive_stale": 1}},
    ]
    for check in checks:
        if check["id"] in overrides:
            check["measured"] = overrides[check["id"]]
    return checks


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "studio.db"
    core = StudioStore(db)
    project = core.create_project("test", str(tmp_path / "repo"))
    (tmp_path / "repo").mkdir()
    return ImuAcceptanceStore(db), project["id"]


def submission(checks, **extra):
    return {"checks": checks, "operator": "abel", **extra}


def test_complete_passing_submission(store):
    imu, project_id = store
    record = imu.save(project_id, submission(full_checks()))
    assert record["status"] == "passed"
    data = record["data"]
    assert data["rule_version"] == "imu-acceptance-v1"
    assert data["measured_steps"] == data["required_steps"] == 6
    assert data["mount_mapping"] == "trunk = [+raw_z, +raw_y, -raw_x]"


def test_partial_submission_names_missing_steps(store):
    imu, project_id = store
    record = imu.save(project_id, submission(full_checks()[:2]))
    assert record["status"] == "insufficient_evidence"
    data = record["data"]
    assert set(data["missing_steps"]) == {"gravity_inverted", "pitch_sign", "quat_rotation", "soak_50hz"}
    assert "不能判定 IMU 安装验收" in data["warnings"][0]


def test_failed_threshold_makes_record_failed(store):
    imu, project_id = store
    checks = full_checks(gyro_stationary={"gx_rad_s": 0.08, "gy_rad_s": 0.0, "gz_rad_s": 0.0, "duration_s": 60})
    record = imu.save(project_id, submission(checks))
    assert record["status"] == "failed"
    failed = next(check for check in record["data"]["checks"] if check["id"] == "gyro_stationary")
    assert failed["verdict"] == "failed"
    assert any("0.05" in reason for reason in failed["reasons"])


def test_short_or_slow_soak_fails(store):
    imu, project_id = store
    short = full_checks(soak_50hz={"duration_s": 300, "hz": 50, "samples": 15000, "max_consecutive_stale": 1})
    slow = full_checks(soak_50hz={"duration_s": 600, "hz": 20, "samples": 12000, "max_consecutive_stale": 1})
    stale = full_checks(soak_50hz={"duration_s": 600, "hz": 50, "samples": 30000, "max_consecutive_stale": 5})
    assert imu.save(project_id, submission(short))["data"]["status"] == "failed"
    assert imu.save(project_id, submission(slow))["data"]["status"] == "failed"
    assert imu.save(project_id, submission(stale))["data"]["status"] == "failed"


def test_inverted_gravity_must_flip_z(store):
    imu, project_id = store
    same = full_checks(gravity_inverted={"gravity": [0.0, 0.0, -0.99]})
    record = imu.save(project_id, submission(same))
    assert record["status"] == "failed"


def test_operator_is_required(store):
    imu, project_id = store
    with pytest.raises(ValueError, match="操作者"):
        imu.save(project_id, {"checks": full_checks()})


def test_unjudgeable_steps_block_passing(store):
    imu, project_id = store
    unjudgeable = full_checks(
        pitch_sign={"gyro_y_rad_s": 0.3, "matches_convention": "yes"},
        quat_rotation={"quat_before": [1, 0, 0], "quat_after": [0.7, 0, 0, 0.7], "no_jump": True},
    )
    record = imu.save(project_id, submission(unjudgeable))
    # Submitted but unjudgeable steps degrade to per-step insufficient_evidence and must
    # never let the whole record pass.
    assert record["status"] == "insufficient_evidence"
    verdicts = {check["id"]: check["verdict"] for check in record["data"]["checks"]}
    assert verdicts["pitch_sign"] == "insufficient_evidence"
    assert verdicts["quat_rotation"] == "insufficient_evidence"
    assert verdicts["gyro_stationary"] == "passed"


def test_records_are_project_scoped_and_appended(store):
    imu, project_id = store
    first = imu.save(project_id, submission(full_checks()))
    second = imu.save(project_id, submission(full_checks(quat_rotation={
        "quat_before": [1, 0, 0, 0], "quat_after": [0.7, 0, 0, 0.71], "no_jump": False})))
    assert first["status"] == "passed" and second["status"] == "failed"
    listed = imu.list(project_id)
    assert [item["id"] for item in listed] == [second["id"], first["id"]]
    with pytest.raises(KeyError):
        imu.list("missing-project")
