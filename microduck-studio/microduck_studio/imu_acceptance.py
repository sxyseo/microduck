"""IMU installation acceptance records (docs/deep-dive/68 §3.4).

The five-step numeric protocol from 解读 68 becomes structured evidence: the operator
measures each step (live numbers come from the Web Serial IMU panel or any readout), the
service re-judges every value against the documented thresholds with a stable rule
version, and only a complete, passing, operator-signed record counts as IMU installation
evidence. Missing steps stay insufficient_evidence — never silently dropped, never
zero-filled. Mount rotation is declared by the operator; the service cannot see wiring.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

RULE_VERSION = "imu-acceptance-v1"
SCHEMA_VERSION = 1
SCHEMA_RECORD_VERSION = 1

GYRO_STATIONARY_LIMIT_RAD_S = 0.05
GYRO_STATIONARY_MIN_DURATION_S = 30.0
GRAVITY_NORM_RANGE = (0.95, 1.05)
GRAVITY_AXIS_LIMIT = 0.9
SOAK_MIN_DURATION_S = 600.0
SOAK_MIN_HZ = 50.0
SOAK_MAX_CONSECUTIVE_STALE = 3

CHECK_IDS = (
    "gyro_stationary",
    "gravity_upright",
    "gravity_inverted",
    "pitch_sign",
    "quat_rotation",
    "soak_50hz",
)

# The imu.rs DEFAULT_MOUNT trunk mapping the training convention expects; operators whose
# physical install differs must change mount, not downstream sign tables (解读 68).
DEFAULT_MOUNT_MAPPING = "trunk = [+raw_z, +raw_y, -raw_x]"


def _finite(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _vector(value, length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != length or not all(_finite(v) for v in value):
        return None
    return [float(v) for v in value]


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(component * component for component in vector))


def _norm_ok(vector: list[float]) -> bool:
    return GRAVITY_NORM_RANGE[0] <= _norm(vector) <= GRAVITY_NORM_RANGE[1]


def judge_gyro_stationary(measured: dict) -> tuple[str, list[str]]:
    axes = {axis: measured.get(axis) for axis in ("gx_rad_s", "gy_rad_s", "gz_rad_s")}
    duration = measured.get("duration_s")
    reasons = []
    for axis, value in axes.items():
        if not _finite(value):
            return "insufficient_evidence", [f"{axis} 缺失或不是有限数"]
    if not _finite(duration):
        return "insufficient_evidence", ["duration_s 缺失或不是有限数"]
    verdict = "passed"
    for axis, value in axes.items():
        if abs(float(value)) >= GYRO_STATIONARY_LIMIT_RAD_S:
            verdict = "failed"
            reasons.append(f"{axis}={value} 达到/超过 {GYRO_STATIONARY_LIMIT_RAD_S} rad/s 静止门槛")
    if float(duration) < GYRO_STATIONARY_MIN_DURATION_S:
        verdict = "failed"
        reasons.append(f"静止时长 {duration}s 不足 {GYRO_STATIONARY_MIN_DURATION_S:.0f}s")
    return verdict, reasons


def judge_gravity_upright(measured: dict) -> tuple[str, list[str]]:
    gravity = _vector(measured.get("gravity"), 3)
    if gravity is None:
        return "insufficient_evidence", ["gravity 必须为 [x,y,z] 三个有限数"]
    if not _norm_ok(gravity):
        return "failed", [f"重力向量模长 {_norm(gravity):.3f} 偏离 1"]
    if gravity[2] > -GRAVITY_AXIS_LIMIT:
        return "failed", [f"正立时 z={gravity[2]:.3f}，应为 [0,0,−1] 方向（z ≤ −{GRAVITY_AXIS_LIMIT}）"]
    return "passed", []


def judge_gravity_inverted(measured: dict) -> tuple[str, list[str]]:
    gravity = _vector(measured.get("gravity"), 3)
    if gravity is None:
        return "insufficient_evidence", ["gravity 必须为 [x,y,z] 三个有限数"]
    if not _norm_ok(gravity):
        return "failed", [f"重力向量模长 {_norm(gravity):.3f} 偏离 1"]
    if gravity[2] < GRAVITY_AXIS_LIMIT:
        return "failed", [f"倒立时 z={gravity[2]:.3f}，应为 [0,0,+1] 方向（z ≥ +{GRAVITY_AXIS_LIMIT}）"]
    return "passed", []


def judge_pitch_sign(measured: dict) -> tuple[str, list[str]]:
    gyro_y = measured.get("gyro_y_rad_s")
    matches = measured.get("matches_convention")
    if not _finite(gyro_y):
        return "insufficient_evidence", ["gyro_y_rad_s 缺失或不是有限数"]
    if not isinstance(matches, bool):
        return "insufficient_evidence", ["matches_convention 必须为布尔值（低头方向与训练约定是否一致）"]
    if not matches:
        return "failed", [f"低头 gyro_y={gyro_y} 的方向与训练约定不一致；按解读 68 应改 mount，不在下游改符号表"]
    return "passed", []


def judge_quat_rotation(measured: dict) -> tuple[str, list[str]]:
    before = _vector(measured.get("quat_before"), 4)
    after = _vector(measured.get("quat_after"), 4)
    no_jump = measured.get("no_jump")
    if before is None or after is None:
        return "insufficient_evidence", ["quat_before/quat_after 必须为 [w,x,y,z] 四个有限分量"]
    if not isinstance(no_jump, bool):
        return "insufficient_evidence", ["no_jump 必须为布尔值（慢转 90° 过程四元数是否无跳变）"]
    for name, quat in (("quat_before", before), ("quat_after", after)):
        if not _norm_ok(quat):
            return "failed", [f"{name} 模长 {_norm(quat):.3f} 偏离 1"]
    if not no_jump:
        return "failed", ["慢转 90° 过程四元数出现跳变或模长异常"]
    return "passed", []


def judge_soak(measured: dict) -> tuple[str, list[str]]:
    duration = measured.get("duration_s")
    hz = measured.get("hz")
    samples = measured.get("samples")
    stale = measured.get("max_consecutive_stale")
    fields = {"duration_s": duration, "hz": hz, "samples": samples, "max_consecutive_stale": stale}
    missing = [name for name, value in fields.items() if not _finite(value)]
    if missing:
        return "insufficient_evidence", [f"{name} 缺失或不是有限数" for name in missing]
    reasons = []
    verdict = "passed"
    if float(duration) < SOAK_MIN_DURATION_S:
        verdict = "failed"
        reasons.append(f"连读时长 {duration}s 不足 {SOAK_MIN_DURATION_S:.0f}s")
    if float(hz) < SOAK_MIN_HZ:
        verdict = "failed"
        reasons.append(f"采样率 {hz}Hz 低于 {SOAK_MIN_HZ:.0f}Hz")
    if float(samples) <= 0:
        verdict = "failed"
        reasons.append(f"样本数 {samples} 不可信")
    if float(stale) > SOAK_MAX_CONSECUTIVE_STALE:
        verdict = "failed"
        reasons.append(f"最大连续 stale 帧 {int(stale)} 超过 {SOAK_MAX_CONSECUTIVE_STALE} 帧")
    return verdict, reasons


JUDGES = {
    "gyro_stationary": judge_gyro_stationary,
    "gravity_upright": judge_gravity_upright,
    "gravity_inverted": judge_gravity_inverted,
    "pitch_sign": judge_pitch_sign,
    "quat_rotation": judge_quat_rotation,
    "soak_50hz": judge_soak,
}


def validate_acceptance(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("IMU 验收数据必须为对象")
    operator = data.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        raise ValueError("验收必须记录操作者；通过状态依赖人工核验")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("checks 必须为非空数组")
    seen: dict[str, dict] = {}
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("checks 项必须为对象")
        check_id = check.get("id")
        if check_id not in JUDGES:
            raise ValueError(f"未知验收步骤：{check_id!r}")
        if check_id in seen:
            raise ValueError(f"验收步骤重复：{check_id}")
        measured = check.get("measured")
        if not isinstance(measured, dict):
            raise ValueError(f"步骤 {check_id} 缺少 measured 对象")
        seen[check_id] = measured

    entries = []
    for check_id in CHECK_IDS:
        measured = seen.get(check_id)
        if measured is None:
            entries.append({"id": check_id, "verdict": "insufficient_evidence", "reasons": ["未提交实测值"]})
            continue
        verdict, reasons = JUDGES[check_id](measured)
        entries.append({"id": check_id, "measured": measured, "verdict": verdict, "reasons": reasons})

    measured_count = sum(1 for entry in entries if "measured" in entry)
    all_present = measured_count == len(CHECK_IDS)
    any_failed = any(entry["verdict"] == "failed" for entry in entries)
    any_unresolved = any(entry["verdict"] == "insufficient_evidence" for entry in entries)
    if not all_present or any_unresolved:
        status = "insufficient_evidence"
    elif any_failed:
        status = "failed"
    else:
        status = "passed"

    imu_model = data.get("imu_model")
    if imu_model is not None and (not isinstance(imu_model, str) or not imu_model.strip()):
        raise ValueError("imu_model 应为非空字符串")
    mount = data.get("mount_mapping")
    if mount is not None and (not isinstance(mount, str) or not mount.strip()):
        raise ValueError("mount_mapping 应为非空字符串")
    note = data.get("note")
    result = {
        "rule_version": RULE_VERSION,
        "status": status,
        "checks": entries,
        "measured_steps": measured_count,
        "required_steps": len(CHECK_IDS),
        "mount_mapping": (mount or DEFAULT_MOUNT_MAPPING).strip(),
        "operator": operator.strip(),
        **({"imu_model": imu_model.strip()} if imu_model else {}),
        **({"note": note} if isinstance(note, str) and note.strip() else {}),
    }
    if status == "insufficient_evidence":
        missing = [entry["id"] for entry in entries if "measured" not in entry]
        result["missing_steps"] = missing
        result["warnings"] = [f"缺少 {len(missing)} 步实测值：{'、'.join(missing)}；缺失时不能判定 IMU 安装验收。"]
    if status == "failed":
        result["warnings"] = [
            f"{entry['id']}：{'；'.join(entry['reasons'])}" for entry in entries if entry["verdict"] == "failed"
        ]
    return result


class ImuAcceptanceStore:
    """Append-only IMU acceptance records; judged server-side with a stable rule version."""

    def __init__(self, db_path):
        self.db_path = db_path
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS imu_acceptances (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _require_project(self, conn, project_id: str) -> None:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise KeyError(project_id)

    def save(self, project_id: str, data: dict) -> dict:
        with self.connect() as conn:
            self._require_project(conn, project_id)
        normalized = validate_acceptance(data)
        record = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "status": normalized["status"],
            "data": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_RECORD_VERSION,
        }
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO imu_acceptances VALUES (?, ?, ?, ?, ?)",
                (record["id"], project_id, record["status"], json.dumps(normalized, ensure_ascii=False, allow_nan=False), record["created_at"]),
            )
        return record

    def list(self, project_id: str) -> list[dict]:
        with self.connect() as conn:
            self._require_project(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM imu_acceptances WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [
            {**dict(row), "data": json.loads(row["data"]), "schema_version": SCHEMA_RECORD_VERSION}
            for row in rows
        ]
