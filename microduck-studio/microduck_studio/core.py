from __future__ import annotations

import atexit
import json
import hashlib
import math
import os
import platform as platform_module
import re
import signal
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RULE_VERSIONS = {
    "continuous_test": "continuous-test-v1",
    "probe_process": "probe-process-v2",
    "training_smoke": "training-smoke-v1",
    "tensorboard_summary": "tensorboard-summary-v1",
    "controller_health": "controller-health-v1",
    "compatibility": "compatibility-v2",
    "bam_record_plan": "bam-record-plan-v1",
    "bam_record_run": "bam-record-run-v1",
}

EVIDENCE_SCOPES = {
    "preflight": "local_software",
    "compatibility": "local_software",
    "deployment_preflight": "local_software",
    "support_bundle": "local_software",
    "training_smoke": "training_or_simulation",
    "tensorboard_summary": "training_or_simulation",
    "bench_continuous": "bench_evidence",
    "continuous_test": "bench_evidence",
    "hl2915_read_only_probe": "real_hardware",
    "hl2915_bam_record": "real_hardware",
    "controller_diagnostic": "real_hardware",
    "deployment": "real_hardware",
}

RUN_TASKS = {
    "preflight": "preflight",
    "controller_diagnostic": "controller_read",
    "bench_continuous": "servo_read",
    "hl2915_read_only_probe": "servo_read",
    "hl2915_bam_record": "identification",
    "training_smoke": "smoke",
    "deployment_preflight": "deployment_preflight",
    "deployment": "deployment",
}
RUN_TERMINAL_STATUSES = {"passed", "failed", "insufficient_evidence", "interrupted"}

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str) -> Any:
    return json.loads(value)


def _with_schema(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "schema_version": SCHEMA_VERSION}


def evidence_scope_for_run(kind: str) -> str:
    return EVIDENCE_SCOPES.get(kind, "unknown")


def _known_hardware_value(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() not in {
        "", "待确认", "未确认", "unknown", "未填写",
    }


def hardware_completeness(data: dict[str, Any]) -> dict[str, Any]:
    servos = data.get("servos") if isinstance(data.get("servos"), dict) else {}
    controller = data.get("controller")
    controller_model = controller.get("model") if isinstance(controller, dict) else controller
    imu = data.get("imu")
    imu_model = imu.get("model") if isinstance(imu, dict) else imu
    power = data.get("power") if isinstance(data.get("power"), dict) else {}
    printed_parts = data.get("printed_parts") if isinstance(data.get("printed_parts"), dict) else {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    training = data.get("training") if isinstance(data.get("training"), dict) else {}
    missing: list[str] = []
    if not _known_hardware_value(servos.get("model")):
        missing.append("servos.model")
    if not isinstance(servos.get("count"), int) or isinstance(servos.get("count"), bool) or servos["count"] <= 0:
        missing.append("servos.count")
    for field, value in (
        ("controller.model", controller_model),
        ("imu.model", imu_model),
        ("printed_parts.version", printed_parts.get("version")),
        ("runtime.version", runtime.get("version")),
        ("training.repo", training.get("repo")),
        ("training.revision", training.get("revision")),
    ):
        if not _known_hardware_value(value):
            missing.append(field)
    voltage = power.get("voltage_v")
    if (
        isinstance(voltage, bool)
        or not isinstance(voltage, (int, float))
        or not math.isfinite(float(voltage))
        or float(voltage) <= 0
    ):
        missing.append("power.voltage_v")
    return {"status": "complete" if not missing else "incomplete", "missing_fields": missing}


def hardware_physical_contract(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return {key: data[key] for key in sorted(data) if key not in {"runtime", "training"}}


def hardware_records_match(
    profile_id: str | None,
    current_hardware_id: str | None,
    current_data: dict[str, Any] | None,
    profiles: dict[str, dict[str, Any]] | None = None,
) -> bool:
    if not profile_id:
        return False
    bound_data = (profiles or {}).get(profile_id)
    if bound_data is not None and current_data is not None:
        return hardware_physical_contract(bound_data) == hardware_physical_contract(current_data)
    return profile_id == current_hardware_id


def list_serial_ports() -> list[dict[str, Any]]:
    """List OS-visible serial ports without opening or probing any device."""
    ports: dict[str, dict[str, Any]] = {}
    if platform_module.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
            ) as key:
                value_count = winreg.QueryInfoKey(key)[1]
                for index in range(value_count):
                    _, value, _ = winreg.EnumValue(key, index)
                    if isinstance(value, str) and value.strip():
                        port = value.strip()
                        ports[port] = {
                            "port": port,
                            "description": "Windows serial device",
                            "source": "windows_registry",
                            "identity_confirmed": False,
                        }
        except (ImportError, OSError):
            pass
    elif platform_module.system() in {"Linux", "Darwin"}:
        for pattern in ("ttyUSB*", "ttyACM*", "cu.*", "tty.*"):
            try:
                paths = Path("/dev").glob(pattern)
            except OSError:
                continue
            for path in paths:
                if path.is_char_device():
                    ports[str(path)] = {
                        "port": str(path),
                        "description": path.name,
                        "source": "device_filesystem",
                        "identity_confirmed": False,
                    }
    return [ports[name] for name in sorted(ports)]


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _file_signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


def task_status_for_result(status: str) -> str:
    return {
        "passed": "success",
        "insufficient_evidence": "blocked",
    }.get(status, status)


def _bench_guidance(kind: str, status: str, reasons: list[str]) -> dict[str, Any]:
    current_facts = [f"当前判定原因：{', '.join(reasons) or 'none'}"]
    causes: list[str] = []
    missing: list[str] = []
    checks: list[str] = []
    guidance = {
        "continuous": {
            "packet_loss": (
                ["波特率或协议参数不匹配", "供电、共地或总线噪声", "USB 转接或线缆不稳定"],
                ["核对舵机型号对应的波特率和协议", "检查供电、共地和总线线缆", "确认端口未被其他进程占用"],
            ),
            "no_packets": (
                ["端口选择错误", "串口未打开或设备未响应"],
                ["重新确认物理接线与端口", "检查端口占用和设备响应"],
            ),
            "duration": ([], ["重新执行完整要求时长的测试"]),
            "cancelled": ([], ["确认安全条件后重新执行测试"]),
            "malformed_input": ([], ["补充原始发送数、丢包数和完整时长"]),
            "missing_fields": ([], ["补充原始发送数、丢包数和完整时长"]),
            "invalid_packet_counts": ([], ["从原始日志重新导出发送数和丢包数"]),
            "hardware_confirmation_required": ([], ["确认实际舵机型号并保存硬件档案"]),
        },
        "probe": {
            "timeout": (
                ["端口未响应", "波特率、供电或总线连接不匹配"],
                ["确认端口和实际接线", "核对波特率、供电、共地并检查端口占用"],
            ),
            "process_start": (
                ["探针程序或构建环境不可用", "端口被其他进程占用"],
                ["检查探针二进制/构建错误", "关闭占用端口的程序后重试"],
            ),
            "process_exit": (
                ["设备协议或参数不匹配", "探针程序报告通信错误"],
                ["查看 stderr 中的设备错误", "核对型号、波特率和端口"],
            ),
            "missing_probe_summary": (
                ["探针输出不完整或版本不匹配"],
                ["查看完整 stdout/stderr", "确认使用当前仓库的探针程序"],
            ),
            "missing_probe_fault_summary": (
                ["混合探针输出缺少舵机故障计数或版本过旧"],
                ["确认使用当前仓库的 hl2915_mixed_probe 并重新执行"],
            ),
            "probe_errors": (
                ["总线通信错误", "供电、共地或线缆不稳定"],
                ["检查错误计数与设备供电", "核对端口和波特率后重试"],
            ),
            "servo_faults": (
                ["舵机反馈了欠压、过热、过流或状态故障"],
                ["立即断电并检查供电、机械负载和温度", "确认故障计数归零后再重试"],
            ),
            "no_probe_samples": ([], ["确认设备响应并重新执行只读探针"]),
            "imu_samples": ([], ["把观察窗口延长到至少获得 25 个 IMU 样本"]),
            "imu_not_ready": (
                ["IMU 未就绪或保留 ID=200 不可达"],
                ["检查 IMU 接线、供电和 ID=200 响应"],
            ),
            "imu_frozen": (
                ["IMU 虽有响应，但连续至少 25 帧没有刷新"],
                ["检查 ID=200 固件刷新、供电和半双工总线"],
            ),
            "duration": ([], ["重新执行完整观察时长的探针"]),
        },
    }.get(kind, {})
    for reason in reasons:
        reason_guidance = guidance.get(reason)
        if reason_guidance:
            reason_causes, reason_checks = reason_guidance
            causes.extend(reason_causes)
            checks.extend(reason_checks)
        if reason in {
            "malformed_input", "invalid_packet_counts", "missing_probe_summary",
            "missing_probe_fault_summary", "missing_fields", "no_probe_samples",
            "hardware_confirmation_required",
        }:
            missing.append(reason)
    if not checks and status != "passed":
        checks.append("保留原始输出并根据任务卡重新执行或补充证据")
    return {
        "current_facts": current_facts,
        "possible_causes": list(dict.fromkeys(causes)),
        "missing_evidence": list(dict.fromkeys(missing)),
        "next_checks": list(dict.fromkeys(checks)),
    }


def evaluate_continuous_test(raw: dict[str, Any], required_duration_s: float) -> dict[str, Any]:
    """Judge raw bench evidence; a printed script PASS is not authoritative."""
    if (
        isinstance(required_duration_s, bool)
        or not isinstance(required_duration_s, (int, float))
        or not math.isfinite(float(required_duration_s))
        or required_duration_s <= 0
    ):
        return {
            "status": "insufficient_evidence",
            "rule_version": RULE_VERSIONS["continuous_test"],
            "packet_loss_rate": None,
            "duration_s": None,
            "required_duration_s": None,
            "reasons": ["invalid_required_duration"],
            "guidance": _bench_guidance("continuous", "insufficient_evidence", ["invalid_required_duration"]),
        }
    cancelled = raw.get("cancelled", False)
    if not isinstance(cancelled, bool):
        return {
            "status": "insufficient_evidence",
            "rule_version": RULE_VERSIONS["continuous_test"],
            "packet_loss_rate": None,
            "duration_s": None,
            "required_duration_s": required_duration_s,
            "reasons": ["malformed_input"],
            "guidance": _bench_guidance("continuous", "insufficient_evidence", ["malformed_input"]),
        }
    required_fields = ("packets_sent", "packets_lost", "duration_s")
    missing_fields = [field for field in required_fields if field not in raw or raw[field] is None]
    if missing_fields:
        status = "interrupted" if cancelled else "insufficient_evidence"
        reasons = ["missing_fields"] + (["cancelled"] if cancelled else [])
        return {
            "status": status,
            "rule_version": RULE_VERSIONS["continuous_test"],
            "packet_loss_rate": None,
            "duration_s": None,
            "required_duration_s": required_duration_s,
            "reasons": reasons,
            "missing_fields": missing_fields,
            "guidance": _bench_guidance("continuous", status, reasons),
        }
    try:
        sent = raw["packets_sent"]
        lost = raw["packets_lost"]
        duration = float(raw["duration_s"])
    except (TypeError, ValueError):
        return {
            "status": "insufficient_evidence",
            "rule_version": RULE_VERSIONS["continuous_test"],
            "packet_loss_rate": None,
            "duration_s": None,
            "required_duration_s": required_duration_s,
            "reasons": ["malformed_input"],
            "guidance": _bench_guidance("continuous", "insufficient_evidence", ["malformed_input"]),
        }
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (sent, lost)) or not math.isfinite(duration):
        return {
            "status": "insufficient_evidence",
            "rule_version": RULE_VERSIONS["continuous_test"],
            "packet_loss_rate": None,
            "duration_s": None,
            "required_duration_s": required_duration_s,
            "reasons": ["malformed_input"],
            "guidance": _bench_guidance("continuous", "insufficient_evidence", ["malformed_input"]),
        }
    reasons: list[str] = []
    invalid_counts = sent < 0 or lost < 0 or (sent >= 0 and lost > sent)
    if invalid_counts:
        reasons.append("invalid_packet_counts")
        packet_loss_rate = None
    elif sent <= 0:
        reasons.append("no_packets")
        packet_loss_rate = None
    else:
        packet_loss_rate = lost / sent
        if lost:
            reasons.append("packet_loss")
    if duration < required_duration_s:
        reasons.append("duration")
    if cancelled:
        reasons.append("cancelled")

    status = "passed"
    if cancelled or duration < required_duration_s:
        status = "interrupted"
    elif reasons:
        status = "failed"
    return {
        "status": status,
        "rule_version": RULE_VERSIONS["continuous_test"],
        "packet_loss_rate": packet_loss_rate,
        "duration_s": duration,
        "required_duration_s": required_duration_s,
        "reasons": reasons,
        "guidance": _bench_guidance("continuous", status, reasons),
    }


_PROBE_SUMMARY = re.compile(
    r"watch complete:\s*samples=(?P<samples>\d+),\s*errors=(?P<errors>\d+),\s*"
    r"stale_imu=(?P<stale_imu>\d+),\s*max_stale_run=(?P<max_stale_run>\d+),\s*"
    r"imu_ready=(?P<imu_ready>true|false)"
)
_SERVO_PROBE_SUMMARY = re.compile(
    r"watch complete:\s*samples=(?P<samples>\d+),\s*errors=(?P<errors>\d+),\s*"
    r"status_faults=(?P<status_faults>\d+),\s*voltage_faults=(?P<voltage_faults>\d+),\s*"
    r"temperature_faults=(?P<temperature_faults>\d+),\s*current_faults=(?P<current_faults>\d+)"
)
_PROBE_FAULT_SUMMARY = re.compile(
    r"status_faults=(?P<status_faults>\d+),\s*voltage_faults=(?P<voltage_faults>\d+),\s*"
    r"temperature_faults=(?P<temperature_faults>\d+),\s*current_faults=(?P<current_faults>\d+)"
)
_SSH_HOST = re.compile(r"[A-Za-z0-9_.:\-\[\]]{1,255}")
_SSH_USER = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_REMOTE_POLICY_PATH = re.compile(r"/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+")
_PROBE_RUN_LOCK = threading.Lock()
_ACTIVE_PROCESS_LOCK = threading.Lock()
_ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
_CANCELLED_RUNS: set[str] = set()
_TRAINING_RUN_LOCK = threading.Lock()
_SECRET_KEYS = {
    "api_key", "authorization", "credential", "credentials", "password", "passphrase",
    "pin", "private_key", "psk", "secret", "ssid", "token", "wifi_password", "wifi_ssid",
}
_SECRET_KEY_SUFFIXES = ("_password", "_passphrase", "_pin", "_private_key", "_psk", "_secret", "_token")
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER_TOKEN = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+")
_GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{6,}|github_pat_[A-Za-z0-9_]{6,})\b")
_SECRET_ENV = re.compile(
    r"(?im)^(\s*[A-Za-z_][A-Za-z0-9_]*(?:TOKEN|PASSWORD|PASSPHRASE|PSK|PIN|SECRET|PRIVATE_KEY)\s*=\s*).+$"
)


def _terminate_active_processes() -> None:
    with _ACTIVE_PROCESS_LOCK:
        processes = list(_ACTIVE_PROCESSES.values())
    for process in processes:
        _stop_process(process)


def _stop_process(process: subprocess.Popen, *, force: bool = False) -> None:
    pid = getattr(process, "pid", None)
    if os.name == "posix" and isinstance(pid, int):
        try:
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
            return
        except (AttributeError, OSError):
            pass
    try:
        (process.kill if force else process.terminate)()
    except OSError:
        pass


atexit.register(_terminate_active_processes)


def _output_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def redact_text(value: str) -> str:
    redacted = value
    home = str(Path.home())
    if home:
        redacted = redacted.replace(home, "<HOME>").replace(Path.home().as_posix(), "<HOME>")
    redacted = re.sub(r"(?i)[A-Z]:\\Users\\[^\\/\s\"]+", "<HOME>", redacted)
    redacted = re.sub(r"/(?:home|Users)/[^/\s\"]+", "<HOME>", redacted)
    redacted = _PRIVATE_KEY_BLOCK.sub("<redacted>", redacted)
    redacted = _BEARER_TOKEN.sub(r"\1<redacted>", redacted)
    redacted = _GITHUB_TOKEN.sub("<redacted>", redacted)
    redacted = _SECRET_ENV.sub(r"\1<redacted>", redacted)
    return redacted


def redact_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if str(key).lower().replace("-", "_") in _SECRET_KEYS
            or str(key).lower().replace("-", "_").endswith(_SECRET_KEY_SUFFIXES)
            else redact_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, tuple):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def evaluate_probe_process(
    *,
    returncode: int | None,
    timed_out: bool,
    stdout: Any,
    stderr: Any,
    duration_s: float,
    required_duration_s: float,
    include_imu: bool = True,
) -> dict[str, Any]:
    stdout_text = _output_text(stdout)
    stderr_text = _output_text(stderr)
    match = (_PROBE_SUMMARY if include_imu else _SERVO_PROBE_SUMMARY).search(stdout_text)
    faults = _PROBE_FAULT_SUMMARY.search(stdout_text)
    summary = None
    if match:
        summary = {
            "samples": int(match["samples"]),
            "errors": int(match["errors"]),
            "stale_imu": int(match["stale_imu"]) if include_imu else None,
            "max_stale_run": int(match["max_stale_run"]) if include_imu else None,
            "imu_ready": match["imu_ready"] == "true" if include_imu else None,
        }
        if not include_imu:
            summary.update({
                "mode": "servo",
                "status_faults": 0,
                "voltage_faults": 0,
                "temperature_faults": 0,
                "current_faults": 0,
            })
        if faults:
            for key in ("status_faults", "voltage_faults", "temperature_faults", "current_faults"):
                summary.setdefault(key, 0)
                summary[key] = int(faults[key])
            if include_imu:
                summary["mode"] = "mixed"
    reasons: list[str] = []
    if timed_out:
        status = "interrupted"
        reasons.append("timeout")
    elif returncode not in (0, None):
        status = "failed"
        reasons.append("process_exit")
    elif returncode is None:
        status = "failed"
        reasons.append("process_start")
    elif duration_s < required_duration_s:
        status = "interrupted"
        reasons.append("duration")
    elif summary is None:
        status = "insufficient_evidence"
        reasons.append("missing_probe_summary")
    elif include_imu and faults is None:
        status = "insufficient_evidence"
        reasons.append("missing_probe_fault_summary")
    elif summary["errors"] > 0:
        status = "failed"
        reasons.append("probe_errors")
    elif (include_imu and summary["samples"] < 25) or (not include_imu and summary["samples"] <= 0):
        status = "failed"
        reasons.append("imu_samples" if include_imu else "no_probe_samples")
    elif include_imu and not summary["imu_ready"]:
        status = "failed"
        reasons.append("imu_not_ready")
    elif include_imu and summary["max_stale_run"] >= 25:
        status = "failed"
        reasons.append("imu_frozen")
    elif any(summary.get(key, 0) > 0 for key in ("status_faults", "voltage_faults", "temperature_faults", "current_faults")):
        status = "failed"
        reasons.append("servo_faults")
    else:
        status = "passed"
    return {
        "status": status,
        "rule_version": RULE_VERSIONS["probe_process"],
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "required_duration_s": required_duration_s,
        "summary": summary,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "reasons": reasons,
        "guidance": _bench_guidance("probe", status, reasons),
    }


def evaluate_training_smoke(
    *,
    returncode: int | None,
    timed_out: bool,
    stdout: Any,
    stderr: Any,
    duration_s: float,
) -> dict[str, Any]:
    stdout_text = _output_text(stdout)
    stderr_text = _output_text(stderr)
    combined = f"{stdout_text}\n{stderr_text}".lower()
    reasons: list[str] = []
    if timed_out:
        status = "interrupted"
        reasons.append("timeout")
    elif returncode is None:
        status = "failed"
        reasons.append("process_start")
    elif returncode != 0:
        status = "failed"
        reasons.append("process_exit")
    else:
        status = "passed"
    if re.search(r"\bnan\b", combined):
        reasons.append("nan")
    if "shape error" in combined or "shape mismatch" in combined or "obs[1,61]" in combined:
        reasons.append("shape_error")
    if reasons and status == "passed":
        status = "failed"
    return {
        "status": status,
        "rule_version": RULE_VERSIONS["training_smoke"],
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "reasons": reasons,
    }


def evaluate_tensorboard_summary(
    *,
    returncode: int | None,
    timed_out: bool,
    stdout: Any,
    stderr: Any,
    duration_s: float,
    output_dir: Path | str,
    baseline: dict[str, tuple[int, int]] | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    expected = [output / "scalars.csv", output / "summary.md", output / "metrics.png"]
    reasons: list[str] = []
    if timed_out:
        status = "interrupted"
        reasons.append("timeout")
    elif returncode is None:
        status = "failed"
        reasons.append("process_start")
    elif returncode != 0:
        status = "failed"
        reasons.append("process_exit")
    elif not all(path.is_file() for path in expected):
        status = "insufficient_evidence"
        reasons.append("missing_summary_outputs")
    elif baseline is not None and all(
        baseline.get(path.name) == (path.stat().st_mtime_ns, path.stat().st_size)
        for path in expected
    ):
        status = "insufficient_evidence"
        reasons.append("stale_summary_outputs")
    else:
        status = "passed"
    return {
        "status": status,
        "rule_version": RULE_VERSIONS["tensorboard_summary"],
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "stdout": _output_text(stdout),
        "stderr": _output_text(stderr),
        "output_dir": str(output.resolve()),
        "expected_outputs": [str(path.resolve()) for path in expected],
        "reasons": reasons,
    }


def evaluate_bam_record_process(
    *,
    returncode: int | None,
    timed_out: bool,
    stdout: Any,
    stderr: Any,
    duration_s: float,
    output_path: Path | str,
    output_baseline: tuple[int, int] | None,
) -> dict[str, Any]:
    output = Path(output_path)
    reasons: list[str] = []
    raw_json_valid = False
    entry_count = 0
    if timed_out:
        status = "interrupted"
        reasons.append("timeout")
    elif returncode is None:
        status = "failed"
        reasons.append("process_start")
    elif returncode != 0:
        status = "failed"
        reasons.append("process_exit")
    elif not output.is_file():
        status = "insufficient_evidence"
        reasons.append("missing_raw_output")
    elif output_baseline is not None and (output.stat().st_mtime_ns, output.stat().st_size) == output_baseline:
        status = "insufficient_evidence"
        reasons.append("stale_raw_output")
    else:
        try:
            payload = json.loads(output.read_text(encoding="utf-8"))
            entries = payload.get("entries") if isinstance(payload, dict) else None
            raw_json_valid = isinstance(entries, list) and bool(entries)
            entry_count = len(entries) if isinstance(entries, list) else 0
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw_json_valid = False
        if raw_json_valid:
            status = "passed"
        else:
            status = "insufficient_evidence"
            reasons.append("invalid_raw_output")
    return {
        "status": status,
        "rule_version": RULE_VERSIONS["bam_record_run"],
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "output_path": str(output.resolve()),
        "raw_json_valid": raw_json_valid,
        "entry_count": entry_count,
        "stdout": _output_text(stdout),
        "stderr": _output_text(stderr),
        "reasons": reasons,
    }


def evaluate_controller_health(
    *,
    returncode: int | None,
    timed_out: bool,
    stdout: Any,
    stderr: Any,
    duration_s: float,
) -> dict[str, Any]:
    stdout_text = _output_text(stdout)
    stderr_text = _output_text(stderr)
    report: Any = None
    parse_error = None
    if stdout_text.strip():
        try:
            report = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    reasons: list[str] = []
    category = "insufficient_evidence"
    if timed_out:
        status, category = "interrupted", "timeout"
        reasons.append("timeout")
    elif returncode == 255:
        status, category = "failed", "controller_unreachable"
        reasons.append("ssh_unreachable")
    elif returncode is None:
        status, category = "failed", "process_start"
        reasons.append("process_start")
    elif not isinstance(report, dict):
        status = "failed" if returncode != 0 else "insufficient_evidence"
        category = "remote_command_failed" if returncode != 0 else "insufficient_evidence"
        reasons.append("invalid_health_json" if parse_error else "missing_health_json")
    else:
        robot = report.get("robot")
        software = report.get("software")
        if robot is None:
            status, category = "failed", "software_unhealthy"
            reasons.append("robotd_unreachable")
        elif not isinstance(robot, dict) or not isinstance(robot.get("healthy"), bool):
            status, category = "insufficient_evidence", "insufficient_evidence"
            reasons.append("missing_health_verdict")
        elif not robot["healthy"]:
            status, category = "failed", "robot_unhealthy"
            reasons.append("robot_unhealthy")
        else:
            warnings = software.get("warnings") if isinstance(software, dict) else None
            services = software.get("services") if isinstance(software, dict) else None
            services_valid = isinstance(services, list) and all(
                isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
                for item in services
            )
            if (
                not isinstance(warnings, list)
                or any(not isinstance(item, str) for item in warnings)
                or not services_valid
            ):
                status, category = "insufficient_evidence", "insufficient_evidence"
                reasons.append(
                    "missing_software_health"
                    if not isinstance(warnings, list) or not isinstance(services, list)
                    else "malformed_software_health"
                )
            else:
                service_errors = [
                    item.get("name", "unknown")
                    for item in services
                    if isinstance(item, dict) and item.get("error")
                ]
                if service_errors:
                    status, category = "failed", "software_unhealthy"
                    reasons.append("service_errors")
                elif warnings:
                    status, category = "failed", "version_or_software_mismatch"
                    reasons.append("software_warnings")
                elif returncode not in (0, 3, 5):
                    status, category = "failed", "remote_command_failed"
                    reasons.append("remote_exit_code")
                else:
                    status, category = "passed", "healthy"
    return {
        "status": status,
        "category": category,
        "rule_version": RULE_VERSIONS["controller_health"],
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration_s,
        "report": report,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "reasons": reasons,
        "guidance": controller_diagnostic_guidance(category, report, stderr_text),
    }


def controller_diagnostic_guidance(
    category: str, report: Any, stderr: str = ""
) -> dict[str, list[str]]:
    facts: list[str] = []
    possible_causes: list[str] = []
    missing_evidence: list[str] = []
    next_checks: list[str] = []
    if category == "healthy":
        facts.append("robotctl health 返回 healthy")
        next_checks.append("保存当前软件版本、策略和硬件档案，继续下一项验收")
    elif category == "controller_unreachable":
        facts.append("SSH 未建立，主控没有返回健康报告")
        possible_causes.extend(["主控地址或网络不可达", "主机密钥未被本机信任", "非交互 SSH 密钥不可用"])
        missing_evidence.append("主控返回的 robotctl health JSON")
        next_checks.append("确认主控地址、网络和 SSH 主机密钥")
    elif category == "software_unhealthy":
        robot_error = report.get("robot_error") if isinstance(report, dict) else None
        facts.append(str(robot_error or "robotd 没有提供健康结果"))
        possible_causes.extend(["robotd 未运行", "robotd socket 路径或权限不匹配"])
        missing_evidence.append("robotd 的健康 verdict")
        next_checks.append("检查 robotd 服务状态和启动日志")
    elif category == "robot_unhealthy":
        robot = report.get("robot") if isinstance(report, dict) else None
        reason = robot.get("reason") if isinstance(robot, dict) else None
        facts.append(f"robotd 报告 unhealthy{': ' + str(reason) if reason else ''}")
        possible_causes.extend(["供电或舵机总线异常", "IMU 或控制循环健康门未通过"])
        missing_evidence.append("robotd 的 bus、IMU、电池和控制循环字段")
        next_checks.append("先确认供电和急停，再读取 robotd 的 bus/IMU/电池字段")
    elif category == "version_or_software_mismatch":
        warnings = report.get("software", {}).get("warnings", []) if isinstance(report, dict) else []
        if warnings:
            facts.extend(str(item) for item in warnings)
        else:
            facts.append("软件报告包含告警")
        missing_evidence.append("运行中与已安装版本的 commit 对照")
        next_checks.append("记录运行/安装版本和 commit，再重新做策略兼容性核验")
    elif category == "timeout":
        facts.append("SSH 诊断超过本地 30 秒超时")
        possible_causes.extend(["网络延迟或丢包", "主控负载过高或 SSH 服务无响应"])
        next_checks.append("先做一次只读网络连通性检查，确认后再重试")
    elif category == "process_start":
        facts.append("本机没有成功启动 SSH 进程")
        missing_evidence.append("本机 ssh 执行文件和进程错误")
        next_checks.append("运行开发机预检，确认 ssh 已安装并在 PATH 中")
    else:
        facts.append("主控诊断证据不足或远程命令失败")
        if stderr:
            facts.append(f"stderr: {stderr[-500:]}")
        missing_evidence.append("完整的 robotctl health JSON")
        next_checks.append("检查 robotctl 是否支持 --json，并保留完整 stdout/stderr")
    return {
        "current_facts": facts,
        "possible_causes": possible_causes,
        "missing_evidence": missing_evidence,
        "next_checks": next_checks,
    }


def normalize_policy_manifest(manifest: Any, policy_name: str | None = None) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {"status": "insufficient_evidence", "reasons": ["manifest_not_object"]}
    entries = manifest.get("policies")
    entry: dict[str, Any] = {}
    if entries is not None:
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            return {"status": "insufficient_evidence", "reasons": ["policies_not_array"]}
        if policy_name:
            entry = next(
                (item for item in entries if item.get("name") == policy_name or item.get("file") == policy_name),
                {},
            )
            if not entry:
                return {"status": "insufficient_evidence", "reasons": ["policy_not_found"]}
        elif len(entries) == 1:
            entry = entries[0]
        else:
            return {"status": "insufficient_evidence", "reasons": ["policy_name_required"]}
    merged = {key: value for key, value in manifest.items() if key != "policies"}
    merged.update(entry)
    robot = dict(manifest.get("robot", {})) if isinstance(manifest.get("robot"), dict) else {}
    if isinstance(entry.get("robot"), dict):
        robot.update(entry["robot"])
    def manifest_value(*keys: str) -> Any:
        for source in (merged, robot):
            for key in keys:
                if key in source and source[key] is not None:
                    return source[key]
        return None

    obs_len = merged.get("obs_len")
    action_dim = manifest_value("action_len", "action_dim")
    reasons: list[str] = []
    if not isinstance(obs_len, int) or isinstance(obs_len, bool) or obs_len <= 0:
        reasons.append("missing_or_invalid_obs_len")
    if not isinstance(action_dim, int) or isinstance(action_dim, bool) or action_dim <= 0:
        reasons.append("missing_or_invalid_action_len")
    policy = {
        "name": merged.get("name") or Path(str(merged.get("file", policy_name or "policy"))).stem,
        "model_api": merged.get("model_api"),
        "obs_len": obs_len,
        "action_dim": action_dim,
        "servo_model": manifest_value("servo_model", "servos"),
        "hardware_rev": manifest_value("hardware_rev", "hw_rev"),
        "control_hz": manifest_value("control_hz"),
        "action_filter": merged.get("action_filter"),
        "action_scale": merged.get("action_scale"),
        "joint_order": merged.get("joint_order"),
        "joint_units": manifest_value("joint_units"),
        "joint_zero": manifest_value("joint_zero"),
        "imu_frame": manifest_value("imu_frame"),
        "training": merged.get("training") if isinstance(merged.get("training"), dict) else {},
    }
    return {
        "status": "ready" if not reasons else "insufficient_evidence",
        "reasons": reasons,
        "policy": policy,
        "manifest": manifest,
    }


def evaluate_compatibility(
    hardware: dict[str, Any], policy: dict[str, Any], runtime: dict[str, Any]
) -> dict[str, Any]:
    def first_present(values: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in values and values[key] is not None:
                return values[key]
        return None

    def nested(values: dict[str, Any], *path: str) -> Any:
        current: Any = values
        for key in path:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def canonical(values: dict[str, Any], *, hardware_shape: bool = False) -> dict[str, Any]:
        robot = values.get("robot") if isinstance(values.get("robot"), dict) else {}
        servos = values.get("servos") if isinstance(values.get("servos"), dict) else {}
        def first_value(*items: Any) -> Any:
            return next((item for item in items if item is not None), None)

        return {
            "servo_model": first_value(first_present(values, "servo_model"), servos.get("model"), robot.get("servos")),
            "obs_len": first_present(values, "obs_len", "observation_len")
            if not hardware_shape
            else None,
            "action_dim": first_present(values, "action_dim", "action_len")
            if not hardware_shape
            else None,
            "control_hz": first_value(first_present(values, "control_hz"), robot.get("control_hz")),
            "action_filter": values.get("action_filter") if not hardware_shape else None,
            "action_scale": values.get("action_scale") if not hardware_shape else None,
            "model_api": first_present(values, "model_api"),
            "hardware_rev": first_value(first_present(values, "hardware_rev"), robot.get("hw_rev")),
            "joint_order": first_value(first_present(values, "joint_order"), robot.get("joint_order")),
            "joint_units": first_value(first_present(values, "joint_units"), robot.get("joint_units")),
            "joint_zero": first_value(first_present(values, "joint_zero"), robot.get("joint_zero")),
            "imu_frame": first_value(first_present(values, "imu_frame"), robot.get("imu_frame")),
        }

    hardware = canonical(hardware, hardware_shape=True)
    policy = canonical(policy)
    runtime = canonical(runtime)
    missing: list[str] = []
    required = {
        "hardware": (hardware, ("servo_model", "control_hz")),
        "policy": (policy, ("obs_len", "action_dim", "control_hz", "action_filter")),
        "runtime": (runtime, ("obs_len", "action_dim", "control_hz", "action_filter")),
    }
    def invalid_required(field: str, value: Any) -> bool:
        if value is None:
            return True
        if field == "servo_model":
            return not isinstance(value, str) or not value.strip()
        if field in {"obs_len", "action_dim"}:
            return isinstance(value, bool) or not isinstance(value, int) or value <= 0
        if field == "control_hz":
            return isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
        if field == "action_filter":
            return not isinstance(value, bool)
        return False

    for source, (values, fields) in required.items():
        for field in fields:
            value = values.get(field)
            if field not in values or invalid_required(field, value):
                missing.append(f"missing_{source}_{field}")
    reasons: list[str] = []
    if hardware.get("servo_model") and not policy.get("servo_model"):
        missing.append("missing_policy_servo_model")
    if policy.get("servo_model") and not hardware.get("servo_model"):
        missing.append("missing_hardware_servo_model")

    contracts = {"hardware": hardware, "policy": policy, "runtime": runtime}

    def require_optional(field: str, sources: tuple[str, ...], reason: str) -> None:
        values = {source: contracts[source].get(field) for source in sources}
        if not any(value is not None for value in values.values()):
            return
        for source, value in values.items():
            if value is None:
                missing.append(f"missing_{source}_{field}")
        if all(value is not None for value in values.values()) and len(set(map(str, values.values()))) > 1:
            reasons.append(reason)

    require_optional("model_api", ("policy", "runtime"), "model_api_mismatch")
    require_optional("hardware_rev", ("hardware", "policy", "runtime"), "hardware_rev_mismatch")
    require_optional("joint_order", ("hardware", "policy", "runtime"), "joint_order_mismatch")
    require_optional("action_scale", ("policy", "runtime"), "action_scale_mismatch")
    require_optional("joint_units", ("hardware", "policy", "runtime"), "joint_units_mismatch")
    require_optional("joint_zero", ("hardware", "policy", "runtime"), "joint_zero_mismatch")
    require_optional("imu_frame", ("hardware", "policy", "runtime"), "imu_frame_mismatch")
    if missing:
        return {
            "status": "insufficient_evidence",
            "rule_version": RULE_VERSIONS["compatibility"],
            "reasons": missing,
        }

    if hardware.get("servo_model") and policy.get("servo_model"):
        if hardware["servo_model"] != policy["servo_model"]:
            reasons.append("servo_model_mismatch")
    if policy.get("action_dim") != runtime.get("action_dim"):
        reasons.append("action_dim_mismatch")
    if policy.get("obs_len") != runtime.get("obs_len"):
        reasons.append("obs_len_mismatch")
    if policy.get("control_hz") != runtime.get("control_hz"):
        reasons.append("control_frequency_mismatch")
    if hardware.get("control_hz") is not None and policy.get("control_hz") is not None:
        if hardware["control_hz"] != policy["control_hz"]:
            reasons.append("hardware_frequency_mismatch")
    if policy.get("action_filter") != runtime.get("action_filter"):
        reasons.append("action_filter_mismatch")
    return {
        "status": "passed" if not reasons else "failed",
        "rule_version": RULE_VERSIONS["compatibility"],
        "reasons": reasons,
    }


def _calibration_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"calibration {field} must be a finite number")
    return float(value)


def validate_calibration(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("calibration data must be an object")
    joints = data.get("joints")
    if not isinstance(joints, list) or not joints:
        raise ValueError("calibration joints must be a non-empty list")
    ids: set[int] = set()
    normalized_joints: list[dict[str, Any]] = []
    for index, joint in enumerate(joints):
        if not isinstance(joint, dict) or not str(joint.get("name", "")).strip():
            raise ValueError(f"calibration joint {index} requires name")
        servo_id = joint.get("id")
        if isinstance(servo_id, bool) or not isinstance(servo_id, int) or not 0 <= servo_id <= 253:
            raise ValueError(f"calibration joint {index} id must be an integer from 0 to 253")
        if servo_id in ids:
            raise ValueError("calibration joint ids must be unique; duplicate id")
        ids.add(servo_id)
        direction = joint.get("direction")
        if direction not in (-1, 1):
            raise ValueError(f"calibration joint {index} direction must be 1 or -1")
        zero = _calibration_number(joint.get("zero_deg"), f"joint {index} zero_deg")
        limits = joint.get("limits_deg")
        if not isinstance(limits, (list, tuple)) or len(limits) != 2:
            raise ValueError(f"calibration joint {index} limits must contain two values")
        lower = _calibration_number(limits[0], f"joint {index} limits")
        upper = _calibration_number(limits[1], f"joint {index} limits")
        if lower >= upper:
            raise ValueError(f"calibration joint {index} limits must be increasing")
        normalized_joints.append({
            "name": str(joint["name"]).strip(),
            "id": servo_id,
            "direction": direction,
            "zero_deg": zero,
            "limits_deg": [lower, upper],
        })

    verified = data.get("verified", False)
    if not isinstance(verified, bool):
        raise ValueError("calibration verified must be a boolean")
    if verified and not str(data.get("operator", "")).strip():
        raise ValueError("verified calibration requires operator")
    normalized: dict[str, Any] = {"joints": normalized_joints, "verified": verified}
    imu = data.get("imu")
    if imu is not None:
        if not isinstance(imu, dict) or not str(imu.get("frame", "")).strip():
            raise ValueError("calibration imu requires frame")
        rpy = imu.get("rpy_deg")
        if not isinstance(rpy, (list, tuple)) or len(rpy) != 3:
            raise ValueError("calibration imu rpy_deg must contain three values")
        normalized["imu"] = {
            "frame": str(imu["frame"]).strip(),
            "rpy_deg": [_calibration_number(value, "imu rpy_deg") for value in rpy],
        }
    if "conditions" in data:
        conditions = data["conditions"]
        if not isinstance(conditions, dict):
            raise ValueError("calibration conditions must be an object")
        normalized_conditions = dict(conditions)
        for field in ("voltage_v", "temperature_c"):
            if field in conditions:
                normalized_conditions[field] = _calibration_number(conditions[field], f"conditions {field}")
        normalized["conditions"] = normalized_conditions
    for field in ("tool_version", "operator", "notes"):
        if field in data:
            normalized[field] = data[field]
    return normalized


def validate_assembly(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(data, dict) or not str(data.get("title", "")).strip():
        raise ValueError("assembly requires title")
    source_refs = data.get("source_refs", [])
    if not isinstance(source_refs, list) or any(not isinstance(ref, str) or not ref.strip() for ref in source_refs):
        raise ValueError("assembly source_refs must be a list of non-empty strings")
    materials = data.get("materials", [])
    if not isinstance(materials, list):
        raise ValueError("assembly materials must be a list")
    normalized_materials: list[dict[str, Any]] = []
    material_statuses = {"missing", "ordered", "received", "used", "unknown"}
    for index, material in enumerate(materials):
        if not isinstance(material, dict) or not str(material.get("name", "")).strip():
            raise ValueError(f"assembly material {index} requires name")
        status = material.get("status", "unknown")
        if status not in material_statuses:
            raise ValueError(f"assembly material {index} has invalid status")
        normalized_material = {"name": str(material["name"]).strip(), "status": status}
        if "quantity" in material:
            quantity = _calibration_number(material["quantity"], f"material {index} quantity")
            if quantity <= 0:
                raise ValueError(f"assembly material {index} quantity must be positive")
            normalized_material["quantity"] = quantity
        for field in ("part_no", "spec", "source", "alternative", "currency", "notes"):
            if field in material:
                if not isinstance(material[field], str) or not material[field].strip():
                    raise ValueError(f"assembly material {index} {field} must be a non-empty string")
                normalized_material[field] = material[field].strip()
        if "price" in material:
            price = _calibration_number(material["price"], f"material {index} price")
            if price < 0:
                raise ValueError(f"assembly material {index} price must not be negative")
            normalized_material["price"] = price
        normalized_materials.append(normalized_material)

    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("assembly checks must be a non-empty list")
    normalized_checks: list[dict[str, Any]] = []
    check_ids: set[str] = set()
    check_statuses = {"pending", "passed", "failed", "blocked", "not_applicable"}
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(f"assembly check {index} must be an object")
        check_id = str(check.get("id", "")).strip()
        title = str(check.get("title", "")).strip()
        if not check_id or not title:
            raise ValueError(f"assembly check {index} requires id and title")
        if check_id in check_ids:
            raise ValueError("assembly check ids must be unique; duplicate id")
        check_ids.add(check_id)
        status = check.get("status", "pending")
        if status not in check_statuses:
            raise ValueError(f"assembly check {index} has invalid status")
        evidence = check.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(ref, str) or not ref.strip() for ref in evidence):
            raise ValueError(f"assembly check {index} evidence must be a list of non-empty strings")
        if status == "passed" and not evidence:
            raise ValueError(f"assembly check {index} passed requires evidence")
        normalized_checks.append({"id": check_id, "title": title, "status": status, "evidence": evidence})

    statuses = {check["status"] for check in normalized_checks}
    material_statuses_present = {material["status"] for material in normalized_materials}
    completion = (
        "failed" if "failed" in statuses else
        "blocked" if "blocked" in statuses or "missing" in material_statuses_present else
        "incomplete" if "pending" in statuses or material_statuses_present & {"ordered", "unknown"} else
        "passed"
    )
    normalized: dict[str, Any] = {
        "title": str(data["title"]).strip(),
        "source_refs": [ref.strip() for ref in source_refs],
        "materials": normalized_materials,
        "checks": normalized_checks,
    }
    for field in ("measurements", "photos"):
        if field in data:
            if not isinstance(data[field], (dict, list)):
                raise ValueError(f"assembly {field} must be an object or list")
            normalized[field] = data[field]
    for field in ("notes", "operator", "tool_version"):
        if field in data:
            normalized[field] = data[field]
    return normalized, completion


def summarize_assembly_materials(materials: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    quantity_total = 0.0
    for material in materials:
        status = material["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        quantity_total += material.get("quantity", 0.0)
    return {
        "item_count": len(materials),
        "quantity_total": quantity_total,
        "status_counts": status_counts,
    }


def validate_identification(
    data: dict[str, Any], expected_model: str | None, project_root: Path
) -> tuple[dict[str, Any], str, list[str]]:
    if not isinstance(data, dict) or not str(data.get("actuator_model", "")).strip():
        raise ValueError("identification requires actuator_model")
    actuator_model = str(data["actuator_model"]).strip()
    raw = data.get("raw_summary")
    fit = data.get("fit")
    validation = data.get("validation")
    if not isinstance(raw, dict):
        raise ValueError("identification raw_summary must be an object")
    if not isinstance(fit, dict):
        raise ValueError("identification fit must be an object")
    if not isinstance(validation, dict):
        raise ValueError("identification validation must be an object")
    fit_path_value = fit.get("path")
    if not isinstance(fit_path_value, str) or not fit_path_value.strip():
        raise ValueError("identification fit requires path")
    fit_path = Path(fit_path_value).resolve()
    if not fit_path.is_relative_to(project_root):
        raise ValueError("identification fit path must be inside the project root")
    fit_model = str(fit.get("model", "")).strip()
    if not fit_model:
        raise ValueError("identification fit requires model")
    trials = fit.get("trials")
    if isinstance(trials, bool) or not isinstance(trials, int) or trials <= 0:
        raise ValueError("identification fit trials must be a positive integer")
    normalized_raw = dict(raw)
    normalized_fit = {"path": str(fit_path), "model": fit_model, "trials": trials}
    if "sha256" in fit:
        normalized_fit["sha256"] = str(fit["sha256"])
    normalized_validation = {
        "dataset": str(validation.get("dataset", "")).strip(),
        "independent": validation.get("independent"),
    }
    if "mae" in validation:
        normalized_validation["mae"] = _calibration_number(validation["mae"], "validation mae")
    reasons: list[str] = []
    if expected_model and actuator_model != expected_model:
        reasons.append("servo_model_mismatch")
    if raw.get("status") != "passed":
        reasons.append("raw_summary_not_passed")
    if not isinstance(raw.get("rows"), int) or raw["rows"] <= 0:
        reasons.append("raw_summary_rows_missing")
    if not isinstance(raw.get("duration_s"), (int, float)) or raw["duration_s"] <= 0:
        reasons.append("raw_summary_duration_missing")
    if not isinstance(raw.get("expected_hz"), (int, float)) or raw["expected_hz"] <= 0:
        reasons.append("raw_summary_frequency_missing")
    if not isinstance(raw.get("ids"), list) or not raw["ids"]:
        reasons.append("raw_summary_ids_missing")
    for field in ("faults", "errors"):
        if raw.get(field):
            reasons.append(f"raw_summary_{field}")
    if not fit_path.is_file():
        reasons.append("fit_artifact_missing")
    else:
        if fit_path.suffix.lower() == ".json":
            try:
                fit_payload = json.loads(fit_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                fit_payload = None
            if not isinstance(fit_payload, dict):
                reasons.append("fit_artifact_invalid")
        if fit.get("sha256"):
            digest, _ = _file_sha256(fit_path)
            if digest != fit["sha256"]:
                reasons.append("fit_hash_mismatch")
    if not normalized_validation["dataset"]:
        reasons.append("validation_dataset_missing")
    if normalized_validation["independent"] is not True:
        reasons.append("independent_validation_required")
    if "mae" not in normalized_validation:
        reasons.append("validation_mae_missing")
    readiness = (
        "inconsistent" if any(reason in {"servo_model_mismatch", "fit_hash_mismatch"} for reason in reasons)
        else "failed" if any(reason.startswith("raw_summary_") for reason in reasons)
        else "incomplete" if reasons else "ready_for_simulation"
    )
    normalized: dict[str, Any] = {
        "actuator_model": actuator_model,
        "raw_summary": normalized_raw,
        "fit": normalized_fit,
        "validation": normalized_validation,
    }
    if "conditions" in data:
        normalized["conditions"] = data["conditions"]
    for field in ("notes", "operator"):
        if field in data:
            normalized[field] = data[field]
    return normalized, readiness, reasons


def validate_issue(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or not str(data.get("title", "")).strip():
        raise ValueError("issue requires title")
    if not str(data.get("symptom", "")).strip():
        raise ValueError("issue requires symptom")
    severity = data.get("severity", "warning")
    if severity not in {"info", "warning", "critical"}:
        raise ValueError("issue severity must be info, warning or critical")
    status = data.get("status", "open")
    if status not in {"open", "investigating", "resolved", "wont_fix"}:
        raise ValueError("issue status is invalid")
    normalized: dict[str, Any] = {
        "title": str(data["title"]).strip(),
        "severity": severity,
        "status": status,
        "symptom": str(data["symptom"]).strip(),
    }
    for field in ("suspected_causes", "next_checks", "evidence_refs"):
        value = data.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"issue {field} must be a list of non-empty strings")
        normalized[field] = [item.strip() for item in value]
    if "resolution" in data and data["resolution"] is not None:
        if not isinstance(data["resolution"], str):
            raise ValueError("issue resolution must be a string")
        normalized["resolution"] = data["resolution"].strip()
    else:
        normalized["resolution"] = None
    return normalized


TASKS = (
    ("hardware", "确认硬件路线", (), "needs_confirmation"),
    ("preflight", "开发机只读预检", (), "ready"),
    ("controller_read", "主控只读诊断", ("preflight",), "blocked"),
    ("servo_read", "舵机只读体检", ("hardware",), "blocked"),
    ("assembly", "装配与电气验收", ("hardware",), "blocked"),
    ("calibration", "标定记录确认", ("hardware", "servo_read"), "blocked"),
    ("identification", "执行器辨识", ("hardware", "servo_read"), "blocked"),
    ("smoke", "训练 smoke test", ("preflight", "hardware"), "blocked"),
    ("deployment_preflight", "部署前兼容性预检", ("hardware", "preflight", "smoke"), "blocked"),
    ("deployment", "部署策略与健康检查", ("deployment_preflight", "assembly", "calibration"), "blocked"),
    ("report", "生成复刻报告", ("hardware", "preflight"), "blocked"),
)

TASK_CARDS = {
    "hardware": {
        "preconditions": ["能访问现有物料记录和实际硬件"],
        "estimated_minutes": 15,
        "tools": ["实物标签或采购记录", "卡尺/万用表（按需）"],
        "steps": ["核对舵机型号和数量", "记录主控、IMU、供电、打印件和版本", "处理冲突项并保存档案"],
        "operation_scope": "记录实测型号、数量、主控、IMU、供电和打印件版本；不自动选择冲突路线",
        "evidence_required": ["实际型号或来源资料", "未决冲突的人工确认"],
        "acceptance": "当前硬件路线明确，关键冲突不再处于待确认",
        "failure_handling": "保留候选路线，补充资料或实测，不进入依赖型号的运动任务",
        "outputs": ["hardware_profile", "hardware_history"],
        "risk": "manual_confirmation",
        "read_only": False,
    },
    "preflight": {
        "preconditions": ["项目根目录可读取"],
        "estimated_minutes": 5,
        "tools": ["本机终端", "Git/Python/uv/Rust/Cargo"],
        "steps": ["运行只读预检", "查看缺失工具和版本", "保存环境基线"],
        "operation_scope": "只读检查 Git、Python、uv、Rust、Cargo 和系统摘要",
        "evidence_required": ["工具版本", "Git 基线", "检查结果"],
        "acceptance": "所有关键检查有明确 passed 或 unavailable 结果",
        "failure_handling": "显示缺失工具和可复制修复命令，不自动安装依赖",
        "outputs": ["environment_snapshot", "preflight_run"],
        "risk": "read_only",
        "read_only": True,
    },
    "controller_read": {
        "preconditions": ["开发机预检成功", "主控地址和 SSH 主机密钥已确认"],
        "estimated_minutes": 10,
        "tools": ["SSH 密钥", "robotctl"],
        "steps": ["先生成固定诊断计划", "确认目标主控", "读取 health JSON 并查看分类建议"],
        "operation_scope": "通过固定 SSH 参数读取 robotctl health --json",
        "evidence_required": ["SSH 返回码", "健康 JSON", "服务状态"],
        "acceptance": "主控可达、robotd 和机器人健康门均通过",
        "failure_handling": "按不可达、软件不健康、硬件不健康或证据不足分类，保留日志",
        "outputs": ["controller_diagnostic_run", "guidance"],
        "risk": "read_only_remote",
        "read_only": True,
    },
    "servo_read": {
        "preconditions": ["已确认舵机型号", "串口和急停条件已确认"],
        "estimated_minutes": 15,
        "tools": ["USB 转接板", "独立舵机", "实体急停"],
        "steps": ["确认串口和舵机 ID", "生成只读探针计划", "执行观察并核对摘要"],
        "operation_scope": "只读体检和受限观察；不写寄存器、不自动继续运动",
        "evidence_required": ["设备 ID/模式/位置", "完整时长", "响应错误和遥测可用性"],
        "acceptance": "原始证据完整、无通信错误且满足当前测试规则",
        "failure_handling": "中止或断线后保持非通过，重新确认设备状态再开始",
        "outputs": ["servo_probe_run", "telemetry_summary"],
        "risk": "read_only_bus",
        "read_only": True,
    },
    "assembly": {
        "preconditions": ["硬件路线已确认", "装配资料和物料状态可追溯"],
        "estimated_minutes": 90,
        "tools": ["BOM/装配图", "卡尺", "万用表", "照片记录"],
        "steps": ["核对物料和打印件", "按基准件试装", "完成接线与上电前检查", "为通过项附证据"],
        "operation_scope": "按当前硬件路线记录结构、接线和上电检查；不把教程阅读当作实测通过",
        "evidence_required": ["每项检查的状态", "通过项的照片、测量或日志证据"],
        "acceptance": "当前硬件的全部装配检查通过且证据齐全",
        "failure_handling": "保留未通过项和证据缺口，修正后重新记录",
        "outputs": ["assembly_record", "assembly_evidence"],
        "risk": "manual_confirmation",
        "read_only": False,
    },
    "calibration": {
        "preconditions": ["硬件路线已确认", "舵机只读体检成功"],
        "estimated_minutes": 45,
        "tools": ["关节标定夹具/量角工具", "IMU 朝向资料", "实体急停"],
        "steps": ["记录关节 ID 与方向", "测量零位和限位", "核对 IMU 坐标系", "由操作者复核并签名"],
        "operation_scope": "记录关节方向、零位、限位和 IMU 朝向；只有人工核验后才可作为部署前置",
        "evidence_required": ["关节标定数据", "适用电压/温度等条件", "操作者明确核验"],
        "acceptance": "当前硬件的标定记录结构有效，并由操作者明确核验",
        "failure_handling": "未核验的记录只能保留为记录，不得进入部署计划",
        "outputs": ["calibration_record"],
        "risk": "manual_confirmation",
        "read_only": False,
    },
    "identification": {
        "preconditions": ["已确认 HL-2915", "舵机只读体检成功", "摆锤和急停条件已确认"],
        "estimated_minutes": 60,
        "tools": ["单舵机摆锤台架", "电子秤/卡尺", "实体急停"],
        "steps": ["记录负载和环境条件", "生成受限运动计划", "双重确认后采样", "拟合并用独立数据验证"],
        "operation_scope": "单舵机、小幅摆动采样；固定输出到项目内 JSON，不直接修改仿真参数",
        "evidence_required": ["原始 BAM JSON", "质量/摆臂/电压/温度条件", "独立验证数据"],
        "acceptance": "原始摘要无故障、拟合文件有效且独立数据验证通过",
        "failure_handling": "保留原始日志和现场条件，标记辨识未完成，不进入部署",
        "outputs": ["bam_raw_json", "actuator_fit", "identification_record"],
        "risk": "confirmed_motion_only",
        "read_only": False,
    },
    "smoke": {
        "preconditions": ["硬件路线已确认", "开发机预检成功", "训练 checkout 可用"],
        "estimated_minutes": 30,
        "tools": ["Linux/macOS/WSL2", "训练 checkout", "uv"],
        "steps": ["检查训练来源与工作树", "生成 5 次迭代计划", "确认后运行", "核对新 ONNX 和合同证据"],
        "operation_scope": "固定小规模 CPU smoke；只写入指定训练 checkout",
        "evidence_required": ["命令和工作目录", "训练 checkout Git 版本/本地改动", "退出码", "完整日志", "NaN/维度检查", "未声明的模型/种子/checkpoint"],
        "acceptance": "命令成功且日志无 NaN、观测/动作维度错误",
        "failure_handling": "保留日志和运行 ID，可取消；不把 smoke 通过当作学会行走",
        "outputs": ["training_smoke_run", "training_logs", "onnx_contract_artifact", "onnx_external_hash"],
        "risk": "writes_training_checkout",
        "read_only": False,
    },
    "deployment_preflight": {
        "preconditions": ["硬件、预检和 smoke 均成功", "策略 manifest 可读取；生成部署计划还需当前装配和已核验标定成功"],
        "estimated_minutes": 10,
        "tools": ["ONNX", "策略 manifest", "运行时契约"],
        "steps": ["登记并哈希策略包", "比较硬件/策略/运行时契约", "处理缺失或不匹配项", "证据未变化后再生成部署计划"],
        "operation_scope": "只读比较策略、硬件和运行时契约",
        "evidence_required": ["策略 SHA-256", "观测/动作约定", "执行器型号和控制频率"],
        "acceptance": "所有必要字段齐全且严格兼容",
        "failure_handling": "列出缺失或不匹配字段，硬件或策略变化后重新预检",
        "outputs": ["compatibility_run", "policy_artifact"],
        "risk": "read_only",
        "read_only": True,
    },
    "deployment": {
        "preconditions": ["部署前兼容性、当前装配和已核验标定均成功", "机器人已架空或可靠约束，实体急停可用"],
        "estimated_minutes": 15,
        "tools": ["SSH/SCP", "robotctl", "实体急停"],
        "steps": ["确认固定部署计划", "备份当前策略并上传候选策略", "核对远端 SHA-256", "加载并执行健康检查", "失败时回滚"],
        "operation_scope": "向已确认主控的 walk 槽部署已通过预检的策略；不代表站立或行走验收通过",
        "evidence_required": ["部署前检运行", "上传与哈希结果", "加载结果", "健康检查和回滚结果"],
        "acceptance": "策略上传、哈希、加载和健康检查均通过，且部署期间硬件档案未变化",
        "failure_handling": "停止后续实机动作，恢复旧策略或重置槽位，保留所有阶段日志",
        "outputs": ["deployment_run", "rollback_evidence"],
        "risk": "confirmed_remote_mutation",
        "read_only": False,
    },
    "report": {
        "preconditions": ["项目和预检记录存在"],
        "estimated_minutes": 5,
        "tools": ["项目数据库", "本地产物目录"],
        "steps": ["刷新项目证据", "核对状态和缺口", "生成 JSON/Markdown 报告", "分享前人工复核脱敏内容"],
        "operation_scope": "汇总硬件、任务、运行、实验、问题和产物证据",
        "evidence_required": ["运行结果", "规则版本", "产物校验值"],
        "acceptance": "报告区分仿真、策略、主控和真机结论，不补填缺失数据",
        "failure_handling": "标记证据不足并保留原始记录，不把报告生成失败改成通过",
        "outputs": ["report.json", "report.md"],
        "risk": "read_only",
        "read_only": True,
    },
}


class StudioStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hardware_profiles (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    deps TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (project_id, id)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    run_id TEXT,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    variable TEXT NOT NULL,
                    baseline TEXT NOT NULL,
                    expected TEXT NOT NULL,
                    result TEXT,
                    decision TEXT,
                    status TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calibrations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    hardware_profile_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assembly_records (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    hardware_profile_id TEXT,
                    status TEXT NOT NULL,
                    completion TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identification_records (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    hardware_profile_id TEXT NOT NULL,
                    readiness TEXT NOT NULL,
                    reasons TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS issues (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    hardware_profile_id TEXT,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symptom TEXT NOT NULL,
                    suspected_causes TEXT NOT NULL,
                    next_checks TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    resolution TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    location TEXT NOT NULL,
                    revision TEXT,
                    license_status TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, kind)
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "deps" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN deps TEXT NOT NULL DEFAULT '[]'")
            experiment_columns = {row[1] for row in conn.execute("PRAGMA table_info(experiments)")}
            if "context" not in experiment_columns:
                conn.execute("ALTER TABLE experiments ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
            for task_id, _, deps, _ in TASKS:
                conn.execute(
                    "UPDATE tasks SET deps = ? WHERE id = ?",
                    (_json(list(deps)), task_id),
                )
            project_rows = conn.execute("SELECT id FROM projects").fetchall()
            for project in project_rows:
                for task_id, title, deps, status in TASKS:
                    conn.execute(
                        "INSERT OR IGNORE INTO tasks (id, project_id, title, status, deps) VALUES (?, ?, ?, ?, ?)",
                        (task_id, project["id"], title, status, _json(list(deps))),
                    )
            running = conn.execute(
                "SELECT id, project_id, kind, result FROM runs WHERE status = 'running'"
            ).fetchall()
            for run in running:
                result = _loads(run["result"])
                reasons = list(result.get("reasons", [])) if isinstance(result, dict) else []
                if "service_restarted" not in reasons:
                    reasons.append("service_restarted")
                if not isinstance(result, dict):
                    result = {}
                result["status"] = "interrupted"
                result["reasons"] = reasons
                conn.execute(
                    "UPDATE runs SET status = 'interrupted', ended_at = ?, result = ? WHERE id = ?",
                    (_now(), _json(result), run["id"]),
                )
                task_id = RUN_TASKS.get(run["kind"])
                if task_id:
                    conn.execute(
                        "UPDATE tasks SET status = 'interrupted' WHERE project_id = ? AND id = ? AND status = 'running'",
                        (run["project_id"], task_id),
                    )

    def create_project(self, name: str, root: Path | str) -> dict[str, Any]:
        project = _with_schema({
            "id": uuid.uuid4().hex,
            "name": name.strip() or "未命名项目",
            "root": str(Path(root).resolve()),
            "status": "needs_confirmation",
            "created_at": _now(),
        })
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO projects VALUES (:id, :name, :root, :status, :created_at)", project
            )
            conn.executemany(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
                [
                    (task_id, project["id"], title, status, _json(list(deps)))
                    for task_id, title, deps, status in TASKS
                ],
            )
        self._refresh_task_statuses(project["id"])
        return project

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _with_schema(dict(row)) if row else None

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
        return [_with_schema(dict(row)) for row in rows]

    def save_hardware(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        servos = data.get("servos") if isinstance(data.get("servos"), dict) else {}
        raw_model = servos.get("model")
        model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
        raw_candidates = servos.get("candidates")
        candidates_valid = raw_candidates is None or (
            isinstance(raw_candidates, list)
            and all(isinstance(candidate, str) and candidate.strip() for candidate in raw_candidates)
        )
        candidates = [
            candidate.strip()
            for candidate in (raw_candidates if isinstance(raw_candidates, list) else [])
            if isinstance(candidate, str) and candidate.strip()
        ]
        unresolved = not model or not candidates_valid or (candidates and candidates != [model])
        status = "needs_confirmation" if unresolved else "confirmed"
        completeness = hardware_completeness(data)
        profile = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "status": status,
            "data": data,
            "completeness": completeness,
            "updated_at": _now(),
        }
        with self._connect() as conn:
            previous = conn.execute(
                "SELECT data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            previous_data = _loads(previous["data"]) if previous else None
            hardware_changed = previous_data != data
            physical_changed = (
                previous_data is None
                or hardware_physical_contract(previous_data) != hardware_physical_contract(data)
            )
            previous_map = previous_data if isinstance(previous_data, dict) else {}
            invalidated_tasks: set[str] = set()
            if hardware_changed:
                if physical_changed:
                    invalidated_tasks.update(
                        {"controller_read", "servo_read", "assembly", "calibration", "identification", "smoke", "deployment_preflight", "deployment", "report"}
                    )
                else:
                    if previous_map.get("runtime") != data.get("runtime"):
                        invalidated_tasks.update({"controller_read", "deployment_preflight", "deployment", "report"})
                    if previous_map.get("training") != data.get("training"):
                        invalidated_tasks.update({"smoke", "deployment_preflight", "deployment", "report"})
                    if not invalidated_tasks:
                        invalidated_tasks.update(
                            {"controller_read", "servo_read", "assembly", "calibration", "identification", "smoke", "deployment_preflight", "deployment", "report"}
                        )
            conn.execute(
                "INSERT INTO hardware_profiles VALUES (?, ?, ?, ?, ?)",
                (profile["id"], project_id, status, _json(data), profile["updated_at"]),
            )
            conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
            if invalidated_tasks:
                conn.execute(
                    f"UPDATE tasks SET status = 'blocked' WHERE project_id = ? AND id IN ({','.join('?' for _ in invalidated_tasks)})",
                    (project_id, *sorted(invalidated_tasks)),
                )
            if status == "confirmed":
                conn.execute(
                    "UPDATE tasks SET status = 'success' WHERE project_id = ? AND id = 'hardware'",
                    (project_id,),
                )
        self._refresh_task_statuses(project_id)
        return _with_schema(profile)

    def build_training_smoke_plan(
        self, project_id: str, training_dir: Path | str
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        root = Path(project["root"]).resolve()
        script = root / "tools" / "microduck_learning" / "run_5_iteration_smoke.sh"
        if not script.is_file():
            raise ValueError("training smoke script missing")
        checkout = Path(training_dir).resolve()
        if not checkout.is_dir():
            raise ValueError("training checkout missing")
        bash = shutil.which("bash")
        if not bash:
            raise ValueError("bash executable not found")
        if not shutil.which("uv"):
            raise ValueError("uv executable not found")
        execution_supported = platform_module.system() in {"Linux", "Darwin"}
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id FROM hardware_profiles WHERE project_id = ? AND status = 'confirmed' ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            preflight = conn.execute(
                "SELECT status FROM tasks WHERE project_id = ? AND id = 'preflight'",
                (project_id,),
            ).fetchone()
        if not hardware:
            raise ValueError("hardware confirmation required")
        if not preflight or preflight["status"] != "success":
            raise ValueError("successful preflight required")
        constraints = {
            "task": "Mjlab-Velocity-Flat-MicroDuck",
            "num_envs": 8,
            "steps_per_env": 24,
            "max_iterations": 5,
            "gpu_ids": "None",
        }
        onnx_dir = checkout / "logs" / "rsl_rl" / "velocity"
        contract_path = root / "artifacts" / "onnx-contract-lesson-01-repro.json"
        output_baseline = {
            str(path): _file_signature(path)
            for path in ([contract_path] if contract_path.is_file() else [])
            + (list(onnx_dir.glob("*_lesson-01-repro.onnx")) if onnx_dir.is_dir() else [])
        }
        return {
            "kind": "training_smoke",
            "mutates": True,
            "hardware_profile_id": hardware["id"],
            "cwd": str(root),
            "training_dir": str(checkout),
            "command": [bash, str(script)],
            "env": {"MICRODUCK_RL_DIR": str(checkout)},
            "timeout_s": 1800,
            "execution_supported": execution_supported,
            "execution_note": "原生 Windows 仅支持计划检查；请在 Linux/macOS/WSL2 服务中执行。"
            if not execution_supported else None,
            "constraints": constraints,
            "training_outputs": {
                "onnx_dir": str(onnx_dir),
                "onnx_pattern": "*_lesson-01-repro.onnx",
                "contract_path": str(contract_path),
            },
            "output_baseline": output_baseline,
            "training_provenance": {
                "source": capture_git_snapshot(checkout),
                "config": constraints,
                "executor_model": None,
                "seed": None,
                "checkpoint": None,
                "unavailable": ["executor_model", "seed", "checkpoint"],
            },
        }

    def build_tensorboard_plan(
        self,
        project_id: str,
        training_dir: Path | str,
        run_dir: Path | str,
        output_dir: Path | str,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        root = Path(project["root"]).resolve()
        script = root / "tools" / "microduck_learning" / "analyze_tensorboard.py"
        if not script.is_file():
            raise ValueError("TensorBoard analyzer missing")
        checkout = Path(training_dir).resolve()
        event_dir = Path(run_dir).resolve()
        destination = Path(output_dir).resolve()
        if not checkout.is_dir():
            raise ValueError("training checkout missing")
        if not event_dir.is_dir() or not event_dir.is_relative_to(checkout):
            raise ValueError("TensorBoard run directory must be inside training checkout")
        if not destination.is_relative_to(root):
            raise ValueError("TensorBoard output directory must be inside project root")
        if destination.exists() and not destination.is_dir():
            raise ValueError("TensorBoard output path must be a directory")
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("uv executable not found")
        with self._connect() as conn:
            smoke = conn.execute(
                "SELECT status FROM tasks WHERE project_id = ? AND id = 'smoke'",
                (project_id,),
            ).fetchone()
        if not smoke or smoke["status"] != "success":
            raise ValueError("successful training smoke required")
        expected = [destination / "scalars.csv", destination / "summary.md", destination / "metrics.png"]
        return {
            "kind": "tensorboard_summary",
            "mutates": True,
            "cwd": str(checkout),
            "run_dir": str(event_dir),
            "output_dir": str(destination),
            "command": [
                uv, "run", "python", str(script),
                "--run-dir", str(event_dir),
                "--output-dir", str(destination),
            ],
            "timeout_s": 600,
            "expected_outputs": [str(path) for path in expected],
        }

    def execute_tensorboard_summary(
        self,
        project_id: str,
        training_dir: Path | str,
        run_dir: Path | str,
        output_dir: Path | str,
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        plan = self.build_tensorboard_plan(project_id, training_dir, run_dir, output_dir)
        run = self.start_run(project_id, "tensorboard_summary")
        started = time.monotonic()
        baseline = {
            Path(path).name: (Path(path).stat().st_mtime_ns, Path(path).stat().st_size)
            for path in plan["expected_outputs"]
            if Path(path).is_file()
        }
        try:
            completed = subprocess.run(
                plan["command"],
                cwd=plan["cwd"],
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=plan["timeout_s"],
            )
            result = evaluate_tensorboard_summary(
                returncode=completed.returncode,
                timed_out=False,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_s=time.monotonic() - started,
                output_dir=plan["output_dir"],
                baseline=baseline,
            )
        except subprocess.TimeoutExpired as exc:
            result = evaluate_tensorboard_summary(
                returncode=None,
                timed_out=True,
                stdout=exc.stdout,
                stderr=exc.stderr,
                duration_s=time.monotonic() - started,
                output_dir=plan["output_dir"],
                baseline=baseline,
            )
        except OSError as exc:
            result = evaluate_tensorboard_summary(
                returncode=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                output_dir=plan["output_dir"],
                baseline=baseline,
            )
        result.update({
            "command": plan["command"],
            "cwd": plan["cwd"],
            "run_dir": plan["run_dir"],
            "mutates": True,
        })
        if result["status"] == "passed":
            try:
                result["artifacts"] = [
                    self.register_artifact(
                        project_id,
                        path,
                        kind,
                        run_id=run["id"],
                        metadata={"run_dir": plan["run_dir"], "source": "analyze_tensorboard.py"},
                    )
                    for path, kind in zip(
                        plan["expected_outputs"],
                        ("tensorboard_scalars", "tensorboard_summary", "tensorboard_plot"),
                    )
                ]
            except ValueError as exc:
                result["status"] = "failed"
                result["reasons"].append("artifact_registration")
                result["stderr"] = f"{result['stderr']}\n{exc}".strip()
        self.finish_run(run["id"], result["status"], result)
        return {**run, "status": result["status"], "result": result}

    def build_read_only_probe_plan(
        self, project_id: str, port: str, ids: list[int], watch_seconds: int, *, include_imu: bool = True
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, status, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not row or row["status"] != "confirmed":
            raise ValueError("hardware confirmation required")
        hardware = _loads(row["data"])
        model = str(hardware.get("servos", {}).get("model", "")).strip().upper()
        if model != "HL-2915":
            raise ValueError("read-only probe only supports confirmed HL-2915 hardware")
        if not isinstance(port, str) or not port or any(character.isspace() for character in port) or "\x00" in port:
            raise ValueError("serial port must be a single non-empty value")
        if not ids:
            raise ValueError("at least one servo ID is required")
        if len(set(ids)) != len(ids):
            raise ValueError("servo IDs must be unique")
        if any(not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 199 for value in ids):
            raise ValueError("servo IDs must be integers from 1 to 199; ID=200 is the reserved IMU")
        if not isinstance(watch_seconds, int) or isinstance(watch_seconds, bool) or not 1 <= watch_seconds <= 300:
            raise ValueError("watch_seconds must be between 1 and 300")
        if not isinstance(include_imu, bool):
            raise ValueError("include_imu must be boolean")
        root = Path(project["root"]).resolve()
        binary = "hl2915_mixed_probe" if include_imu else "hl2915_probe"
        source = root / "duck-control" / "src" / "bin" / f"{binary}.rs"
        if not source.is_file():
            raise ValueError("read-only probe source missing")
        return {
            "kind": binary,
            "mutates": False,
            "hardware_profile_id": row["id"],
            "cwd": str(root),
            "source": str(source),
            "command": [
                "cargo", "run", "-p", "duck-control", "--bin", binary, "--",
                port, *(str(value) for value in ids), "--watch-seconds", str(watch_seconds),
            ],
            "constraints": {
                "servo_model": "HL-2915",
                "read_only": True,
                "requires_imu": include_imu,
                "max_watch_seconds": 300,
            },
            "parameters": {
                "port": port, "ids": list(ids), "watch_seconds": watch_seconds, "include_imu": include_imu,
            },
        }

    def build_bam_record_plan(
        self,
        project_id: str,
        port: str,
        servo_id: int,
        mass_kg: float,
        arm_length_m: float,
        output_path: Path | str,
        *,
        center_raw: int = 2048,
        direction: int = 1,
        arm_mass_kg: float = 0.0,
        kp: int = 16,
        vin: float = 12.0,
        amplitude_deg: float = 10.0,
        duration_s: float = 6.0,
        hz: float = 100.0,
        confirm_motion: bool = False,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id, status, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not hardware or hardware["status"] != "confirmed":
            raise ValueError("hardware confirmation required")
        with self._connect() as conn:
            servo_task = conn.execute(
                "SELECT status FROM tasks WHERE project_id = ? AND id = 'servo_read'",
                (project_id,),
            ).fetchone()
        if not servo_task or servo_task["status"] != "success":
            raise ValueError("successful servo read required before BAM recording")
        hardware_data = _loads(hardware["data"])
        model = str(hardware_data.get("servos", {}).get("model", "")).strip().upper()
        if model != "HL-2915":
            raise ValueError("BAM record plan only supports confirmed HL-2915 hardware")
        if not isinstance(port, str) or not port.strip() or any(character.isspace() for character in port) or "\x00" in port:
            raise ValueError("serial port must be a single non-empty value")
        if isinstance(servo_id, bool) or not isinstance(servo_id, int) or not 0 <= servo_id <= 199:
            raise ValueError("servo_id must be an integer from 0 to 199; ID=200 is reserved for IMU")
        if isinstance(center_raw, bool) or not isinstance(center_raw, int) or not 0 <= center_raw <= 4095:
            raise ValueError("center_raw must be between 0 and 4095")
        if direction not in {-1, 1}:
            raise ValueError("direction must be 1 or -1")
        ranges = (
            (mass_kg, 0.001, 1.0, "mass_kg"),
            (arm_mass_kg, 0.0, 1.0, "arm_mass_kg"),
            (arm_length_m, 0.01, 0.5, "arm_length_m"),
            (vin, 9.0, 14.0, "vin"),
            (amplitude_deg, 1.0, 30.0, "amplitude_deg"),
            (duration_s, 2.0, 30.0, "duration_s"),
            (hz, 20.0, 200.0, "hz"),
        )
        for value, lower, upper, name in ranges:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not lower <= float(value) <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}")
        if isinstance(kp, bool) or not isinstance(kp, int) or not 1 <= kp <= 255:
            raise ValueError("kp must be between 1 and 255")
        root = Path(project["root"]).resolve()
        source = root / "duck-control" / "src" / "bin" / "hl2915_bam_record.rs"
        if not source.is_file():
            raise ValueError("BAM record source missing")
        destination = Path(output_path)
        if not destination.is_absolute():
            destination = root / destination
        destination = destination.resolve()
        if destination.suffix != ".json":
            raise ValueError("BAM output path must use .json extension")
        if not destination.is_relative_to(root):
            raise ValueError("BAM output path must be inside project root")
        if destination.exists():
            raise ValueError("BAM output path already exists; choose a new evidence path")
        command = [
            "cargo", "run", "-p", "duck-control", "--bin", "hl2915_bam_record", "--",
            port.strip(), str(servo_id),
            "--center-raw", str(center_raw), "--direction", str(direction),
            "--mass-kg", str(mass_kg), "--arm-mass-kg", str(arm_mass_kg),
            "--arm-length-m", str(arm_length_m), "--kp", str(kp), "--vin", str(vin),
            "--amplitude-deg", str(amplitude_deg), "--duration-seconds", str(duration_s),
            "--hz", str(hz), "--output", str(destination), "--confirm-motion",
        ]
        return {
            "kind": "hl2915_bam_record",
            "rule_version": RULE_VERSIONS["bam_record_plan"],
            "mutates": True,
            "does_not_start_process": True,
            "hardware_profile_id": hardware["id"],
            "cwd": str(root),
            "source": str(source),
            "output_path": str(destination),
            "command": command,
            "operator_confirmed": bool(confirm_motion),
            "timeout_s": float(duration_s) + 30.0,
            "parameters": {
                "port": port.strip(),
                "servo_id": servo_id,
                "center_raw": center_raw,
                "direction": direction,
                "mass_kg": float(mass_kg),
                "arm_mass_kg": float(arm_mass_kg),
                "arm_length_m": float(arm_length_m),
                "kp": kp,
                "vin": float(vin),
                "amplitude_deg": float(amplitude_deg),
                "duration_s": float(duration_s),
                "hz": float(hz),
            },
            "safety": {
                "requires_confirm_motion": True,
                "emergency_stop": "实体急停或立即断电；确认输出轴卸载且不会夹伤或撞击结构",
                "max_amplitude_deg": 30.0,
                "max_duration_s": 30.0,
                "torque_after_run": "记录器结束时关闭扭矩，异常时保留现场并人工断电",
            },
            "constraints": {
                "servo_model": "HL-2915",
                "single_servo_id": servo_id,
                "amplitude_deg": float(amplitude_deg),
                "duration_s": float(duration_s),
                "hz": float(hz),
            },
        }

    def start_bam_record(
        self,
        project_id: str,
        port: str,
        servo_id: int,
        mass_kg: float,
        arm_length_m: float,
        output_path: Path | str,
        *,
        center_raw: int = 2048,
        direction: int = 1,
        arm_mass_kg: float = 0.0,
        kp: int = 16,
        vin: float = 12.0,
        amplitude_deg: float = 10.0,
        duration_s: float = 6.0,
        hz: float = 100.0,
        confirm: bool = False,
        confirm_motion: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        if not confirm_motion:
            raise PermissionError("explicit motion confirmation required")
        plan = self.build_bam_record_plan(
            project_id,
            port,
            servo_id,
            mass_kg,
            arm_length_m,
            output_path,
            center_raw=center_raw,
            direction=direction,
            arm_mass_kg=arm_mass_kg,
            kp=kp,
            vin=vin,
            amplitude_deg=amplitude_deg,
            duration_s=duration_s,
            hz=hz,
            confirm_motion=True,
        )
        run = self._start_exclusive_probe_run(project_id, "hl2915_bam_record")
        initial = {
            "status": "running",
            "command": plan["command"],
            "cwd": plan["cwd"],
            "output_path": plan["output_path"],
            "hardware_profile_id": plan["hardware_profile_id"],
            "mutates": True,
            "motion": True,
            "safety": plan["safety"],
            "parameters": plan["parameters"],
            "rule_version": RULE_VERSIONS["bam_record_run"],
        }
        self.update_run_result(run["id"], initial)
        self.set_task_status(project_id, "identification", "running")
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                plan["command"],
                cwd=plan["cwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
            )
        except OSError as exc:
            result = evaluate_bam_record_process(
                returncode=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                output_path=plan["output_path"],
                output_baseline=None,
            )
            result.update({key: initial[key] for key in initial if key != "status"})
            self.finish_run(run["id"], result["status"], result)
            self._set_hardware_bound_task_status(
                project_id, "identification", task_status_for_result(result["status"]), plan["hardware_profile_id"]
            )
            return {**run, "status": result["status"], "result": result}
        with _ACTIVE_PROCESS_LOCK:
            _ACTIVE_PROCESSES[run["id"]] = process
        threading.Thread(
            target=self._collect_bam_record,
            args=(run, process, plan, started),
            daemon=True,
        ).start()
        return {**run, "status": "running", "result": initial}

    def execute_read_only_probe(
        self,
        project_id: str,
        port: str,
        ids: list[int],
        watch_seconds: int,
        *,
        confirm: bool,
        include_imu: bool = True,
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        plan = self.build_read_only_probe_plan(
            project_id, port, ids, watch_seconds, include_imu=include_imu
        )
        run = self._start_exclusive_probe_run(project_id)
        self.set_task_status(project_id, "servo_read", "running")
        started = time.monotonic()
        timeout_s = watch_seconds + 45
        try:
            completed = subprocess.run(
                plan["command"],
                cwd=plan["cwd"],
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=timeout_s,
            )
            result = evaluate_probe_process(
                returncode=completed.returncode,
                timed_out=False,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_s=time.monotonic() - started,
                required_duration_s=watch_seconds,
                include_imu=include_imu,
            )
        except subprocess.TimeoutExpired as exc:
            result = evaluate_probe_process(
                returncode=None,
                timed_out=True,
                stdout=exc.stdout,
                stderr=exc.stderr,
                duration_s=time.monotonic() - started,
                required_duration_s=watch_seconds,
                include_imu=include_imu,
            )
        except OSError as exc:
            result = evaluate_probe_process(
                returncode=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                required_duration_s=watch_seconds,
                include_imu=include_imu,
            )
            result["reasons"] = ["process_start"]
        result.update({
            "command": plan["command"],
            "cwd": plan["cwd"],
            "hardware_profile_id": plan["hardware_profile_id"],
            "mutates": False,
            "parameters": {
                "port": port, "ids": list(ids), "watch_seconds": watch_seconds, "include_imu": include_imu,
            },
        })
        self.finish_run(run["id"], result["status"], result)
        self._set_hardware_bound_task_status(
            project_id, "servo_read", task_status_for_result(result["status"]), plan["hardware_profile_id"]
        )
        return {**run, "status": result["status"], "result": result}

    def start_read_only_probe(
        self,
        project_id: str,
        port: str,
        ids: list[int],
        watch_seconds: int,
        *,
        confirm: bool,
        include_imu: bool = True,
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        plan = self.build_read_only_probe_plan(
            project_id, port, ids, watch_seconds, include_imu=include_imu
        )
        run = self._start_exclusive_probe_run(project_id)
        initial = {
            "status": "running",
            "command": plan["command"],
            "cwd": plan["cwd"],
            "hardware_profile_id": plan["hardware_profile_id"],
            "mutates": False,
            "parameters": {
                "port": port, "ids": list(ids), "watch_seconds": watch_seconds, "include_imu": include_imu,
            },
        }
        self.update_run_result(run["id"], initial)
        self.set_task_status(project_id, "servo_read", "running")
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                plan["command"],
                cwd=plan["cwd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
            )
        except OSError as exc:
            result = evaluate_probe_process(
                returncode=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
                required_duration_s=watch_seconds,
                include_imu=include_imu,
            )
            result.update({
                key: initial[key]
                for key in ("command", "cwd", "hardware_profile_id", "mutates", "parameters")
            })
            result["reasons"] = ["process_start"]
            self.finish_run(run["id"], result["status"], result)
            self._set_hardware_bound_task_status(
                project_id, "servo_read", task_status_for_result(result["status"]), plan["hardware_profile_id"]
            )
            return {**run, "status": result["status"], "result": result}
        with _ACTIVE_PROCESS_LOCK:
            _ACTIVE_PROCESSES[run["id"]] = process
        threading.Thread(
            target=self._collect_read_only_probe,
            args=(run, process, plan, watch_seconds, started),
            daemon=True,
        ).start()
        return {**run, "status": "running", "result": initial}

    def _start_training_run(self, project_id: str) -> dict[str, Any]:
        with _TRAINING_RUN_LOCK:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                active = conn.execute(
                    "SELECT id FROM runs WHERE kind = 'training_smoke' AND status = 'running' LIMIT 1"
                ).fetchone()
                if active:
                    raise RuntimeError("a training smoke run is already running")
                run = {
                    "id": uuid.uuid4().hex,
                    "project_id": project_id,
                    "kind": "training_smoke",
                    "status": "running",
                    "started_at": _now(),
                    "ended_at": None,
                    "result": {},
                }
                conn.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run["id"], project_id, run["kind"], run["status"], run["started_at"], None, _json({})),
                )
                return run

    def start_training_smoke(
        self, project_id: str, training_dir: Path | str, *, confirm: bool
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        plan = self.build_training_smoke_plan(project_id, training_dir)
        if not plan["execution_supported"]:
            raise ValueError(plan["execution_note"])
        run = self._start_training_run(project_id)
        self.set_task_status(project_id, "smoke", "running")
        initial = {
            "status": "running",
            "command": plan["command"],
            "cwd": plan["cwd"],
            "training_dir": plan["training_dir"],
            "hardware_profile_id": plan["hardware_profile_id"],
            "mutates": True,
            "constraints": plan["constraints"],
            "training_outputs": plan["training_outputs"],
            "output_baseline": plan["output_baseline"],
            "training_provenance": plan["training_provenance"],
            "execution_supported": plan["execution_supported"],
            "execution_note": plan["execution_note"],
        }
        self.update_run_result(run["id"], initial)
        started = time.monotonic()
        environment = os.environ.copy()
        environment.update(plan["env"])
        try:
            process = subprocess.Popen(
                plan["command"],
                cwd=plan["cwd"],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
            )
        except OSError as exc:
            result = evaluate_training_smoke(
                returncode=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
            )
            result.update({key: initial[key] for key in initial if key != "status"})
            self.finish_run(run["id"], result["status"], result)
            self._set_hardware_bound_task_status(
                project_id, "smoke", task_status_for_result(result["status"]), plan["hardware_profile_id"]
            )
            return {**run, "status": result["status"], "result": result}
        with _ACTIVE_PROCESS_LOCK:
            _ACTIVE_PROCESSES[run["id"]] = process
        threading.Thread(
            target=self._collect_training_smoke,
            args=(run, process, plan, started),
            daemon=True,
        ).start()
        return {**run, "status": "running", "result": initial}

    def _collect_training_smoke(
        self,
        run: dict[str, Any],
        process: subprocess.Popen,
        plan: dict[str, Any],
        started: float,
    ) -> None:
        timed_out = False
        stdout: Any = ""
        stderr: Any = ""
        try:
            try:
                stdout, stderr = process.communicate(timeout=plan["timeout_s"])
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_process(process, force=True)
                stdout, stderr = process.communicate()
            result = evaluate_training_smoke(
                returncode=process.returncode,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
                duration_s=time.monotonic() - started,
            )
            with _ACTIVE_PROCESS_LOCK:
                cancelled = run["id"] in _CANCELLED_RUNS
            if cancelled:
                result["status"] = "interrupted"
                result["reasons"] = [reason for reason in result["reasons"] if reason != "process_exit"]
                result["reasons"].append("cancelled")
            output_plan = plan["training_outputs"]
            onnx_dir = Path(output_plan["onnx_dir"])
            baseline = plan["output_baseline"]
            fresh_onnx = [
                path for path in sorted(onnx_dir.glob(output_plan["onnx_pattern"]))
                if _file_signature(path) != baseline.get(str(path))
            ] if onnx_dir.is_dir() else []
            contract = Path(output_plan["contract_path"])
            fresh_contract = (
                contract.is_file() and _file_signature(contract) != baseline.get(str(contract))
            )
            outputs = {
                "onnx": [
                    {"path": str(path), "sha256": _file_sha256(path)[0], "size": path.stat().st_size}
                    for path in fresh_onnx
                ],
                "contract": None,
            }
            if fresh_contract:
                try:
                    contract_data = json.loads(contract.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    result["reasons"].append("training_outputs_invalid")
                else:
                    valid_contract = (
                        isinstance(contract_data, dict)
                        and isinstance(contract_data.get("input"), dict)
                        and contract_data["input"].get("shape") == [1, 61]
                        and isinstance(contract_data.get("output"), dict)
                        and contract_data["output"].get("shape") == [1, 14]
                        and contract_data.get("finite_zero_observation") is True
                    )
                    if not valid_contract:
                        result["reasons"].append("training_outputs_invalid")
                    else:
                        digest, size = _file_sha256(contract)
                        outputs["contract"] = {"path": str(contract), "sha256": digest, "size": size}
            result["training_outputs"] = outputs
            if result["status"] == "passed" and (not outputs["onnx"] or outputs["contract"] is None):
                result["status"] = "insufficient_evidence"
                if "training_outputs_invalid" not in result["reasons"]:
                    result["reasons"].append("training_outputs_missing")
            elif result["status"] == "passed":
                result["artifacts"] = [
                    self.register_artifact(
                        run["project_id"],
                        contract,
                        "onnx_contract",
                        run_id=run["id"],
                        metadata={"onnx_outputs": outputs["onnx"], "source": "check_onnx_contract.py"},
                    )
                ]
            result.update({
                "command": plan["command"],
                "cwd": plan["cwd"],
                "training_dir": plan["training_dir"],
                "hardware_profile_id": plan["hardware_profile_id"],
                "mutates": True,
                "constraints": plan["constraints"],
                "output_baseline": plan["output_baseline"],
                "training_provenance": plan["training_provenance"],
                "execution_supported": plan["execution_supported"],
                "execution_note": plan["execution_note"],
            })
        except Exception as exc:
            result = {
                "status": "failed",
                "returncode": process.poll(),
                "timed_out": False,
                "duration_s": time.monotonic() - started,
                "stdout": _output_text(stdout),
                "stderr": f"{_output_text(stderr)}\n{exc}".strip(),
                "reasons": ["collector_error"],
                "command": plan["command"],
                "cwd": plan["cwd"],
                "training_dir": plan["training_dir"],
                "hardware_profile_id": plan["hardware_profile_id"],
                "mutates": True,
                "constraints": plan["constraints"],
                "output_baseline": plan["output_baseline"],
                "training_provenance": plan["training_provenance"],
                "execution_supported": plan["execution_supported"],
                "execution_note": plan["execution_note"],
            }
        finally:
            with _ACTIVE_PROCESS_LOCK:
                _ACTIVE_PROCESSES.pop(run["id"], None)
                _CANCELLED_RUNS.discard(run["id"])
        self.finish_run(run["id"], result["status"], result)
        self._set_hardware_bound_task_status(
            run["project_id"], "smoke", task_status_for_result(result["status"]), plan["hardware_profile_id"]
        )

    def _collect_read_only_probe(
        self,
        run: dict[str, Any],
        process: subprocess.Popen,
        plan: dict[str, Any],
        watch_seconds: int,
        started: float,
    ) -> None:
        timed_out = False
        stdout: Any = ""
        stderr: Any = ""
        try:
            try:
                stdout, stderr = process.communicate(timeout=watch_seconds + 45)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_process(process, force=True)
                stdout, stderr = process.communicate()
            result = evaluate_probe_process(
                returncode=process.returncode,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
                duration_s=time.monotonic() - started,
                required_duration_s=watch_seconds,
                include_imu=bool(plan["parameters"].get("include_imu", True)),
            )
            with _ACTIVE_PROCESS_LOCK:
                cancelled = run["id"] in _CANCELLED_RUNS
            if cancelled:
                result["status"] = "interrupted"
                result["reasons"] = [reason for reason in result["reasons"] if reason != "process_exit"]
                result["reasons"].append("cancelled")
            result.update({
                "command": plan["command"],
                "cwd": plan["cwd"],
                "hardware_profile_id": plan["hardware_profile_id"],
                "mutates": False,
                "parameters": plan["parameters"],
            })
        except Exception as exc:  # keep a worker failure from leaving a permanent running row
            result = {
                "status": "failed",
                "returncode": process.poll(),
                "timed_out": False,
                "duration_s": time.monotonic() - started,
                "summary": None,
                "stdout": _output_text(stdout),
                "stderr": f"{_output_text(stderr)}\n{exc}".strip(),
                "reasons": ["collector_error"],
                "command": plan["command"],
                "cwd": plan["cwd"],
                "hardware_profile_id": plan["hardware_profile_id"],
                "mutates": False,
                "parameters": plan["parameters"],
            }
        finally:
            with _ACTIVE_PROCESS_LOCK:
                _ACTIVE_PROCESSES.pop(run["id"], None)
                _CANCELLED_RUNS.discard(run["id"])
        self.finish_run(run["id"], result["status"], result)
        self._set_hardware_bound_task_status(
            run["project_id"], "servo_read", task_status_for_result(result["status"]), plan["hardware_profile_id"]
        )

    def _collect_bam_record(
        self,
        run: dict[str, Any],
        process: subprocess.Popen,
        plan: dict[str, Any],
        started: float,
    ) -> None:
        stdout: Any = ""
        stderr: Any = ""
        try:
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=plan["timeout_s"])
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_process(process, force=True)
                stdout, stderr = process.communicate()
            result = evaluate_bam_record_process(
                returncode=process.returncode,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
                duration_s=time.monotonic() - started,
                output_path=plan["output_path"],
                output_baseline=None,
            )
            with _ACTIVE_PROCESS_LOCK:
                cancelled = run["id"] in _CANCELLED_RUNS
            if cancelled:
                result["status"] = "interrupted"
                result["reasons"] = [reason for reason in result["reasons"] if reason != "process_exit"]
                result["reasons"].append("cancelled")
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                    (run["project_id"],),
                ).fetchone()
            if not current or current["id"] != plan["hardware_profile_id"]:
                result["status"] = "failed"
                result["reasons"].append("hardware_changed_during_motion")
            result.update({
                "command": plan["command"],
                "cwd": plan["cwd"],
                "hardware_profile_id": plan["hardware_profile_id"],
                "mutates": True,
                "motion": True,
                "parameters": plan["parameters"],
            })
            output = Path(plan["output_path"])
            if output.is_file():
                try:
                    artifact = self.register_artifact(
                        run["project_id"],
                        output,
                        "bam_raw",
                        run_id=run["id"],
                        metadata={
                            "verified": result["status"] == "passed",
                            "rule_version": result.get("rule_version"),
                            "parameters": plan["parameters"],
                        },
                    )
                    result["artifact_id"] = artifact["id"]
                except ValueError as exc:
                    result["status"] = "failed"
                    result["reasons"].append("artifact_registration")
                    result["stderr"] = f"{result['stderr']}\n{exc}".strip()
        except Exception as exc:
            result = {
                "status": "failed",
                "rule_version": RULE_VERSIONS["bam_record_run"],
                "returncode": process.poll(),
                "timed_out": False,
                "duration_s": time.monotonic() - started,
                "output_path": plan["output_path"],
                "raw_json_valid": False,
                "entry_count": 0,
                "stdout": _output_text(stdout),
                "stderr": f"{_output_text(stderr)}\n{exc}".strip(),
                "reasons": ["collector_error"],
                "command": plan["command"],
                "cwd": plan["cwd"],
                "hardware_profile_id": plan["hardware_profile_id"],
                "mutates": True,
                "motion": True,
                "parameters": plan["parameters"],
            }
        finally:
            with _ACTIVE_PROCESS_LOCK:
                _ACTIVE_PROCESSES.pop(run["id"], None)
                _CANCELLED_RUNS.discard(run["id"])
        self.finish_run(run["id"], result["status"], result)
        task_status = "ready" if result["status"] == "passed" else task_status_for_result(result["status"])
        self._set_hardware_bound_task_status(
            run["project_id"], "identification", task_status, plan["hardware_profile_id"]
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        result = _with_schema(dict(row))
        result["result"] = _loads(result["result"])
        result["result"].setdefault("evidence_scope", evidence_scope_for_run(result["kind"]))
        return result

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["status"] != "running":
            return {"id": run_id, "status": run["status"]}
        with _ACTIVE_PROCESS_LOCK:
            process = _ACTIVE_PROCESSES.get(run_id)
            if process is None:
                raise RuntimeError("run is not cancellable")
            _CANCELLED_RUNS.add(run_id)
            _stop_process(process)
        return {"id": run_id, "status": "cancelling"}

    def retry_run(self, run_id: str, *, confirm: bool) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        run = self.get_run(run_id)
        if run["status"] not in {"failed", "interrupted"}:
            raise ValueError("only failed or interrupted runs can be retried")
        result = run["result"] if isinstance(run["result"], dict) else {}

        def mark_retry(retried: dict[str, Any]) -> dict[str, Any]:
            with self._connect() as conn:
                row = conn.execute("SELECT result FROM runs WHERE id = ?", (retried["id"],)).fetchone()
                if not row:
                    return {**retried, "result": {**retried.get("result", {}), "retry_of": run_id}}
                current = _loads(row["result"])
                current["retry_of"] = run_id
                conn.execute("UPDATE runs SET result = ? WHERE id = ?", (_json(current), retried["id"]))
            return self.get_run(retried["id"])

        if run["kind"] == "hl2915_read_only_probe":
            parameters = result.get("parameters")
            if not isinstance(parameters, dict):
                raise ValueError("retry parameters are unavailable")
            try:
                port = parameters["port"]
                ids = parameters["ids"]
                watch_seconds = parameters["watch_seconds"]
            except KeyError as exc:
                raise ValueError("retry parameters are unavailable") from exc
            retry_kwargs = {}
            if "include_imu" in parameters:
                if not isinstance(parameters["include_imu"], bool):
                    raise ValueError("retry parameters are invalid")
                retry_kwargs["include_imu"] = parameters["include_imu"]
            return mark_retry(self.start_read_only_probe(
                run["project_id"], port, ids, watch_seconds, confirm=True, **retry_kwargs
            ))
        if run["kind"] == "training_smoke":
            training_dir = result.get("training_dir")
            if not isinstance(training_dir, str) or not training_dir.strip():
                raise ValueError("retry parameters are unavailable")
            return mark_retry(self.start_training_smoke(run["project_id"], training_dir, confirm=True))
        raise ValueError(f"automatic retry is unavailable for {run['kind']}")

    def build_controller_diagnostic_plan(
        self, project_id: str, host: str, user: str, port: int
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        # ponytail: accept ASCII DNS names and IP literals; add IDNA conversion only if needed.
        if not isinstance(host, str) or not _SSH_HOST.fullmatch(host):
            raise ValueError("host must be an ASCII hostname or IP address")
        if not isinstance(user, str) or not _SSH_USER.fullmatch(user):
            raise ValueError("user must be a simple SSH account name")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535")
        root = Path(project["root"]).resolve()
        if not root.is_dir():
            raise ValueError("project root missing")
        ssh = shutil.which("ssh")
        if not ssh:
            raise ValueError("ssh executable not found")
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        target = f"{user}@{host}"
        return {
            "kind": "controller_diagnostic",
            "mutates": False,
            "hardware_profile_id": hardware["id"] if hardware else None,
            "target": target,
            "cwd": str(root),
            "timeout_s": 30,
            "command": [
                ssh,
                "-T",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=yes",
                "-p", str(port),
                target,
                "robotctl", "health", "--json",
            ],
        }

    def execute_controller_diagnostic(
        self, project_id: str, host: str, user: str, port: int
    ) -> dict[str, Any]:
        plan = self.build_controller_diagnostic_plan(project_id, host, user, port)
        run = self.start_run(project_id, "controller_diagnostic")
        self.set_task_status(project_id, "controller_read", "running")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                plan["command"],
                cwd=plan["cwd"],
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=plan["timeout_s"],
            )
            result = evaluate_controller_health(
                returncode=completed.returncode,
                timed_out=False,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_s=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            result = evaluate_controller_health(
                returncode=None,
                timed_out=True,
                stdout=exc.stdout,
                stderr=exc.stderr,
                duration_s=time.monotonic() - started,
            )
        except OSError as exc:
            result = evaluate_controller_health(
                returncode=None,
                timed_out=False,
                stdout="",
                stderr=str(exc),
                duration_s=time.monotonic() - started,
            )
        result.update({
            "command": plan["command"],
            "cwd": plan["cwd"],
            "target": plan["target"],
            "hardware_profile_id": plan["hardware_profile_id"],
            "mutates": False,
        })
        self.finish_run(run["id"], result["status"], result)
        self._set_hardware_bound_task_status(
            project_id,
            "controller_read",
            task_status_for_result(result["status"]),
            plan["hardware_profile_id"],
        )
        return {**run, "status": result["status"], "result": result}

    def _start_exclusive_probe_run(
        self, project_id: str, kind: str = "hl2915_read_only_probe"
    ) -> dict[str, Any]:
        with _PROBE_RUN_LOCK:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                active = conn.execute(
                    "SELECT id FROM runs WHERE kind IN ('hl2915_read_only_probe', 'hl2915_bam_record') AND status = 'running' LIMIT 1"
                ).fetchone()
                if active:
                    raise RuntimeError(
                        "a read-only probe is already running"
                        if kind == "hl2915_read_only_probe"
                        else "a bench bus run is already running"
                    )
                run = _with_schema({
                    "id": uuid.uuid4().hex,
                    "project_id": project_id,
                    "kind": kind,
                    "status": "running",
                    "started_at": _now(),
                    "ended_at": None,
                    "result": {},
                })
                conn.execute(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (run["id"], project_id, run["kind"], run["status"], run["started_at"], None, _json({})),
                )
                return run

    def record_continuous_test(
        self, project_id: str, raw: dict[str, Any], required_duration_s: float
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id, status FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        run = self.start_run(project_id, "bench_continuous")
        if not hardware or hardware["status"] != "confirmed":
            result = {
                "status": "insufficient_evidence",
                "rule_version": RULE_VERSIONS["continuous_test"],
                "reasons": ["hardware_confirmation_required"],
                "hardware_profile_id": hardware["id"] if hardware else None,
                "raw": raw,
                "required_duration_s": required_duration_s,
                "guidance": _bench_guidance(
                    "continuous", "insufficient_evidence", ["hardware_confirmation_required"]
                ),
            }
        else:
            result = evaluate_continuous_test(raw, required_duration_s)
            result.update({
                "hardware_profile_id": hardware["id"],
                "raw": raw,
            })
        self.finish_run(run["id"], result["status"], result)
        self._set_hardware_bound_task_status(
            project_id,
            "servo_read",
            task_status_for_result(result["status"]),
            hardware["id"] if hardware else None,
        )
        return {**run, "status": result["status"], "result": result}

    def start_run(self, project_id: str, kind: str) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        run = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "kind": kind,
            "status": "running",
            "started_at": _now(),
            "ended_at": None,
            "result": {"evidence_scope": evidence_scope_for_run(kind)},
        })
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run["id"], project_id, kind, run["status"], run["started_at"], None, _json({})),
            )
        return run

    def update_run_result(self, run_id: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT kind, status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] != "running":
                return
            if not isinstance(result, dict):
                raise ValueError("run result must be an object")
            if result.get("status") is not None and result["status"] != "running":
                raise ValueError("run result status must be running status while run is running")
            result = _with_schema({
                **result,
                "evidence_scope": result.get("evidence_scope", evidence_scope_for_run(row["kind"])),
            })
            updated = conn.execute(
                "UPDATE runs SET result = ? WHERE id = ?", (_json(result), run_id)
            ).rowcount
        if not updated:
            raise KeyError(run_id)

    def finish_run(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT kind, status, result FROM runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] != "running":
                return
            if status not in RUN_TERMINAL_STATUSES:
                raise ValueError(f"invalid run status: {status}")
            if not isinstance(result, dict):
                raise ValueError("run result must be an object")
            if result.get("status") is not None and result["status"] != status:
                raise ValueError("result status must match run status")
            existing_result = _loads(row["result"])
            metadata = {key: existing_result[key] for key in ("retry_of",) if key in existing_result}
            result = _with_schema({
                **metadata,
                **result,
                "status": status,
                "evidence_scope": result.get("evidence_scope", evidence_scope_for_run(row["kind"])),
            })
            conn.execute(
                "UPDATE runs SET status = ?, ended_at = ?, result = ? WHERE id = ?",
                (status, _now(), _json(result), run_id),
            )

    def register_artifact(
        self,
        project_id: str,
        path: Path | str,
        kind: str,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        artifact_path = Path(path).resolve()
        project_root = Path(project["root"]).resolve()
        if not artifact_path.is_relative_to(project_root):
            raise ValueError("artifact path must be inside the project root")
        if not artifact_path.is_file():
            raise ValueError("artifact path must be a file")
        digest, size = _file_sha256(artifact_path)
        artifact = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "run_id": run_id,
            "kind": kind,
            "path": str(artifact_path),
            "sha256": digest,
            "size": size,
            "metadata": {**(metadata or {}), "schema_version": SCHEMA_VERSION},
            "created_at": _now(),
        })
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact["id"],
                    project_id,
                    run_id,
                    kind,
                    artifact["path"],
                    artifact["sha256"],
                    size,
                    _json(artifact["metadata"]),
                    artifact["created_at"],
                ),
            )
        return artifact

    def inspect_policy_package(
        self,
        project_id: str,
        onnx_path: Path | str,
        manifest_path: Path | str,
        policy_name: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        root = Path(project["root"]).resolve()
        onnx = Path(onnx_path).resolve()
        manifest_file = Path(manifest_path).resolve()
        if not onnx.is_relative_to(root) or not manifest_file.is_relative_to(root):
            raise ValueError("policy package files must be inside the project root")
        if not onnx.is_file() or not manifest_file.is_file():
            raise ValueError("policy package files must be files")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"manifest JSON cannot be read: {exc}") from exc
        normalized = normalize_policy_manifest(manifest, policy_name)
        metadata = {
            "manifest_path": str(manifest_file),
            "policy": normalized.get("policy", {}),
            "status": normalized["status"],
            "reasons": normalized["reasons"],
        }
        artifacts = [
            self.register_artifact(project_id, onnx, "policy", run_id=run_id, metadata=metadata),
            self.register_artifact(project_id, manifest_file, "policy_manifest", run_id=run_id, metadata=metadata),
        ]
        return {**normalized, "artifacts": artifacts, "onnx_path": str(onnx), "manifest_path": str(manifest_file)}

    def deployment_preflight(
        self,
        project_id: str,
        onnx_path: Path | str,
        manifest_path: Path | str,
        runtime: dict[str, Any],
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id, status, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not hardware or hardware["status"] != "confirmed":
            run = self.start_run(project_id, "deployment_preflight")
            result = {
                "status": "insufficient_evidence",
                "reasons": ["hardware_confirmation_required"],
                "hardware_profile_id": hardware["id"] if hardware else None,
                "mutates": False,
            }
            self.finish_run(run["id"], result["status"], result)
            self._set_deployment_preflight_task_status(
                project_id, task_status_for_result(result["status"]), None
            )
            return {**run, "status": result["status"], "result": result}
        run = self.start_run(project_id, "deployment_preflight")
        try:
            package = self.inspect_policy_package(project_id, onnx_path, manifest_path, run_id=run["id"])
        except ValueError as exc:
            result = {
                "status": "insufficient_evidence",
                "reasons": ["policy_package_error"],
                "error": str(exc),
                "hardware_profile_id": hardware["id"],
                "mutates": False,
            }
            self.finish_run(run["id"], result["status"], result)
            self._set_deployment_preflight_task_status(
                project_id, task_status_for_result(result["status"]), hardware["id"]
            )
            raise
        compatibility_hardware = _loads(hardware["data"])
        policy_contract = package.get("policy", {})
        with self._connect() as conn:
            calibration = conn.execute(
                "SELECT id, hardware_profile_id, data FROM calibrations WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            profile_rows = conn.execute(
                "SELECT id, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        calibration_data = _loads(calibration["data"]) if calibration else {}
        hardware_profiles = {row["id"]: _loads(row["data"]) for row in profile_rows}
        calibration_is_current = bool(
            calibration
            and hardware_records_match(
                calibration["hardware_profile_id"], hardware["id"],
                compatibility_hardware, hardware_profiles
            )
            and calibration_data.get("verified") is True
        )
        requested_fields = {
            field
            for field in ("joint_order", "joint_zero", "imu_frame")
            if policy_contract.get(field) is not None or runtime.get(field) is not None
        }
        if calibration_is_current:
            joints = calibration_data.get("joints")
            if isinstance(joints, list):
                derived = {
                    "joint_order": [joint.get("name") for joint in joints],
                    "joint_zero": [joint.get("zero_deg") for joint in joints],
                }
                imu = calibration_data.get("imu")
                if isinstance(imu, dict):
                    derived["imu_frame"] = imu.get("frame")
                for field in requested_fields:
                    if compatibility_hardware.get(field) is None and derived.get(field) is not None:
                        compatibility_hardware[field] = derived[field]
        result = evaluate_compatibility(compatibility_hardware, policy_contract, runtime)
        result.update({
            "hardware_profile_id": hardware["id"],
            "policy_status": package["status"],
            "policy_reasons": package["reasons"],
            "policy": package.get("policy", {}),
            "runtime": runtime,
            "hardware_contract": compatibility_hardware,
            "calibration_record_id": calibration["id"] if calibration_is_current else None,
            "artifacts": package["artifacts"],
            "onnx_path": package["onnx_path"],
            "manifest_path": package["manifest_path"],
            "mutates": False,
        })
        self.finish_run(run["id"], result["status"], result)
        self._set_deployment_preflight_task_status(
            project_id, task_status_for_result(result["status"]), hardware["id"]
        )
        return {**run, "status": result["status"], "result": result}

    def build_deployment_plan(
        self,
        project_id: str,
        onnx_path: Path | str,
        manifest_path: Path | str,
        host: str,
        user: str,
        port: int,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        if not isinstance(host, str) or not _SSH_HOST.fullmatch(host):
            raise ValueError("host must be an ASCII hostname or IP address")
        if not isinstance(user, str) or not _SSH_USER.fullmatch(user):
            raise ValueError("user must be a simple SSH account name")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535")
        ssh = shutil.which("ssh")
        if not ssh:
            raise ValueError("ssh executable not found")
        scp = shutil.which("scp")
        if not scp:
            raise ValueError("scp executable not found")
        root = Path(project["root"]).resolve()
        onnx = Path(onnx_path).resolve()
        manifest = Path(manifest_path).resolve()
        if not onnx.is_relative_to(root) or not manifest.is_relative_to(root):
            raise ValueError("policy package files must be inside the project root")
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            preflight = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? AND kind = 'deployment_preflight' AND status = 'passed' ORDER BY started_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            task = conn.execute(
                "SELECT status FROM tasks WHERE project_id = ? AND id = 'deployment_preflight'",
                (project_id,),
            ).fetchone()
            evidence_tasks = {
                row["id"]: row["status"]
                for row in conn.execute(
                    "SELECT id, status FROM tasks WHERE project_id = ? AND id IN ('assembly', 'calibration')",
                    (project_id,),
                ).fetchall()
            }
            calibration = conn.execute(
                "SELECT id FROM calibrations WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not hardware or not preflight:
            raise ValueError("fresh passed deployment preflight required")
        evidence = _loads(preflight["result"])
        if not task or task["status"] != "success":
            if evidence.get("calibration_record_id") != (calibration["id"] if calibration else None):
                raise ValueError("calibration evidence changed; fresh deployment preflight required")
            raise ValueError("deployment preflight task is stale; hardware or prerequisite evidence changed")
        if evidence_tasks.get("assembly") != "success":
            raise ValueError("current assembly evidence required before deployment")
        if evidence_tasks.get("calibration") != "success":
            raise ValueError("verified calibration evidence required before deployment")
        if evidence.get("calibration_record_id") != (calibration["id"] if calibration else None):
            raise ValueError("calibration evidence changed; fresh deployment preflight required")
        if evidence.get("hardware_profile_id") != hardware["id"]:
            raise ValueError("deployment preflight hardware evidence is stale")
        if evidence.get("onnx_path") != str(onnx) or evidence.get("manifest_path") != str(manifest):
            raise ValueError("deployment preflight policy package does not match")
        policy_artifacts = evidence.get("artifacts")
        if not isinstance(policy_artifacts, list):
            raise ValueError("deployment preflight policy artifacts missing")
        policy_artifact = next(
            (item for item in policy_artifacts if isinstance(item, dict) and item.get("kind") == "policy"),
            None,
        )
        for expected_path, kind in ((onnx, "policy"), (manifest, "policy_manifest")):
            artifact = next(
                (item for item in policy_artifacts if isinstance(item, dict) and item.get("kind") == kind),
                None,
            )
            if not artifact or not expected_path.is_file():
                raise ValueError("policy package artifact missing")
            digest, _ = _file_sha256(expected_path)
            if digest != artifact.get("sha256"):
                raise ValueError("policy package changed since deployment preflight")
        if not policy_artifact or not policy_artifact.get("sha256"):
            raise ValueError("policy package hash missing")
        return {
            "status": "ready",
            "kind": "deployment_plan",
            "mutates": True,
            "target": f"{user}@{host}",
            "port": port,
            "ssh": ssh,
            "scp": scp,
            "policy_path": str(onnx),
            "manifest_path": str(manifest),
            "policy_sha256": policy_artifact["sha256"],
            "remote_policy_path": f"/tmp/microduck-studio/{policy_artifact['sha256']}.onnx",
            "slot": "walk",
            "preflight_run_id": preflight["id"],
            "hardware_profile_id": hardware["id"],
            "policy_artifacts": policy_artifacts,
            "runtime": evidence.get("runtime", {}),
            "steps": [
                "backup_current_policy",
                "upload_policy",
                "verify_sha256",
                "health_check",
                "rollback_on_failure",
            ],
            "safety": {
                "requires_explicit_confirmation": True,
                "does_not_start_motion": False,
                "requires_robot_lifted_or_restrained": True,
                "requires_estop_ready": True,
                "rollback_program_and_policy_separately": True,
            },
        }

    def execute_deployment(
        self,
        project_id: str,
        onnx_path: Path | str,
        manifest_path: Path | str,
        host: str,
        user: str,
        port: int,
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        plan = self.build_deployment_plan(project_id, onnx_path, manifest_path, host, user, port)
        run = self.start_run(project_id, "deployment")
        self.set_task_status(project_id, "deployment", "running")
        started = time.monotonic()
        ssh_options = [
            "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=yes", "-p", str(plan["port"]), plan["target"],
        ]
        scp_options = [
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=yes", "-P", str(plan["port"]),
        ]
        stages: dict[str, Any] = {}

        def call(command: list[str]) -> dict[str, Any]:
            began = time.monotonic()
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    shell=False,
                    check=False,
                    timeout=90,
                )
                return {
                    "returncode": completed.returncode,
                    "timed_out": False,
                    "duration_s": time.monotonic() - began,
                    "stdout": _output_text(completed.stdout),
                    "stderr": _output_text(completed.stderr),
                    "command": command,
                }
            except subprocess.TimeoutExpired as exc:
                return {
                    "returncode": None,
                    "timed_out": True,
                    "duration_s": time.monotonic() - began,
                    "stdout": _output_text(exc.stdout),
                    "stderr": _output_text(exc.stderr),
                    "command": command,
                }
            except OSError as exc:
                return {
                    "returncode": None,
                    "timed_out": False,
                    "duration_s": time.monotonic() - began,
                    "stdout": "",
                    "stderr": str(exc),
                    "command": command,
                }

        result: dict[str, Any] = {
            "status": "failed",
            "mutates": True,
            "hardware_profile_id": plan["hardware_profile_id"],
            "preflight_run_id": plan["preflight_run_id"],
            "target": plan["target"],
            "slot": plan["slot"],
            "remote_policy_path": plan["remote_policy_path"],
            "reasons": [],
            "stages": stages,
            "duration_s": 0,
        }
        list_result = call([plan["ssh"], *ssh_options, "robotctl", "policy", "list", "--json"])
        stages["policy_list"] = list_result
        old_path: str | None = None
        if list_result["returncode"] == 0 and not list_result["timed_out"]:
            try:
                payload = json.loads(list_result["stdout"])
                policies = payload.get("policies", payload) if isinstance(payload, dict) else {}
                slots = policies.get("slots", []) if isinstance(policies, dict) else []
                slot = next((item for item in slots if isinstance(item, dict) and item.get("slot") == plan["slot"]), {})
                candidate = slot.get("path") if isinstance(slot, dict) else None
                if isinstance(candidate, str) and _REMOTE_POLICY_PATH.fullmatch(candidate):
                    old_path = candidate
            except (json.JSONDecodeError, TypeError, AttributeError):
                result["reasons"].append("invalid_policy_list")
        else:
            result["reasons"].append("policy_list_failed")

        def rollback() -> None:
            command = [
                plan["ssh"], *ssh_options, "sudo", "robotctl", "policy",
                "load", plan["slot"], old_path, "--json",
            ] if old_path else [
                plan["ssh"], *ssh_options, "sudo", "robotctl", "policy",
                "reset", plan["slot"], "--json",
            ]
            rollback_result = call(command)
            stages["rollback"] = rollback_result
            if rollback_result["returncode"] != 0 or rollback_result["timed_out"]:
                result["reasons"].append("rollback_failed")

        if not result["reasons"]:
            prepare = call([plan["ssh"], *ssh_options, "mkdir", "-p", "/tmp/microduck-studio"])
            stages["prepare"] = prepare
            if prepare["returncode"] != 0 or prepare["timed_out"]:
                result["reasons"].append("staging_prepare_failed")
            else:
                upload = call([
                    plan["scp"], *scp_options,
                    plan["policy_path"], f"{plan['target']}:{plan['remote_policy_path']}",
                ])
                stages["upload"] = upload
                if upload["returncode"] != 0 or upload["timed_out"]:
                    result["reasons"].append("upload_failed")
                else:
                    verify = call([plan["ssh"], *ssh_options, "sha256sum", plan["remote_policy_path"]])
                    stages["verify_sha256"] = verify
                    if verify["returncode"] != 0 or verify["timed_out"]:
                        result["reasons"].append("remote_hash_failed")
                    elif verify["stdout"].split(maxsplit=1)[:1] != [plan["policy_sha256"]]:
                        result["reasons"].append("remote_hash_mismatch")
                    else:
                        load = call([
                            plan["ssh"], *ssh_options, "sudo", "robotctl", "policy",
                            "load", plan["slot"], plan["remote_policy_path"], "--json",
                        ])
                        stages["load"] = load
                        if load["returncode"] != 0 or load["timed_out"]:
                            result["reasons"].append("policy_load_failed")
                            rollback()
                        else:
                            health_stage = call([plan["ssh"], *ssh_options, "robotctl", "health", "--json"])
                            stages["health"] = health_stage
                            health = evaluate_controller_health(
                                returncode=health_stage["returncode"],
                                timed_out=health_stage["timed_out"],
                                stdout=health_stage["stdout"],
                                stderr=health_stage["stderr"],
                                duration_s=health_stage["duration_s"],
                            )
                            result["health"] = health
                            with self._connect() as conn:
                                current = conn.execute(
                                    "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                                    (project_id,),
                                ).fetchone()
                            if current and current["id"] != plan["hardware_profile_id"]:
                                health["status"] = "failed"
                                result["reasons"].append("hardware_changed_during_deployment")
                            if health["status"] != "passed":
                                result["reasons"].append("health_gate")
                                rollback()

        cleanup = call([plan["ssh"], *ssh_options, "rm", "-f", plan["remote_policy_path"]])
        stages["cleanup"] = cleanup
        if cleanup["returncode"] != 0 or cleanup["timed_out"]:
            result["reasons"].append("cleanup_failed")
        result["status"] = "passed" if not result["reasons"] else "failed"
        result["duration_s"] = time.monotonic() - started
        self.finish_run(run["id"], result["status"], result)
        self._set_hardware_bound_task_status(
            project_id, "deployment", task_status_for_result(result["status"]), plan["hardware_profile_id"]
        )
        return {**run, "status": result["status"], "result": result}

    def create_experiment(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        required = ("title", "hypothesis", "variable", "baseline", "expected")
        if any(not str(data.get(key, "")).strip() for key in required[:3]) or "baseline" not in data or "expected" not in data:
            raise ValueError("experiment requires title, hypothesis, variable, baseline and expected")
        supplied_context = data.get("context", {})
        if not isinstance(supplied_context, dict):
            raise ValueError("experiment context must be an object")
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            preflight = conn.execute(
                "SELECT id, result FROM runs WHERE project_id = ? AND kind = 'preflight' ORDER BY started_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        now = _now()
        context = {
            "captured_at": now,
            "hardware_profile_id": hardware["id"] if hardware else None,
            "hardware": _loads(hardware["data"]) if hardware else None,
            "preflight_run_id": preflight["id"] if preflight else None,
            "preflight": _loads(preflight["result"]) if preflight else None,
            "user": supplied_context,
        }
        experiment = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "title": str(data["title"]).strip(),
            "hypothesis": str(data["hypothesis"]).strip(),
            "variable": str(data["variable"]).strip(),
            "baseline": data["baseline"],
            "expected": data["expected"],
            "result": None,
            "decision": None,
            "status": "planned",
            "evidence_refs": [],
            "context": context,
            "created_at": now,
            "updated_at": now,
        })
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO experiments
                    (id, project_id, title, hypothesis, variable, baseline, expected, result,
                     decision, status, evidence_refs, created_at, updated_at, context)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    experiment["id"], project_id, experiment["title"], experiment["hypothesis"],
                    experiment["variable"], _json(experiment["baseline"]), _json(experiment["expected"]),
                    None, None, experiment["status"], _json([]), now, now, _json(context),
                ),
            )
        return experiment

    def save_source(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        kind = str(data.get("kind", "")).strip()
        location = str(data.get("location", "")).strip()
        if not kind or not location:
            raise ValueError("source requires kind and location")
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("source metadata must be an object")
        metadata = {**metadata, "schema_version": SCHEMA_VERSION}
        revision = str(data["revision"]).strip() if data.get("revision") is not None else None
        source_path = Path(location)
        if not source_path.is_absolute():
            source_path = Path(project["root"]) / source_path
        if source_path.is_dir():
            git = capture_git_snapshot(source_path)
            metadata.update({"scanned_at": _now(), "resolved_location": str(source_path.resolve()), "git": git})
            if not revision and git["commit"]:
                revision = git["commit"]
            metadata["revision_matches"] = revision == git["commit"] if revision and git["commit"] else None
        now = _now()
        source = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "kind": kind,
            "location": location,
            "revision": revision,
            "license_status": str(data.get("license_status", "unknown")),
            "metadata": metadata,
            "updated_at": now,
        })
        with self._connect() as conn:
            old = conn.execute(
                "SELECT id FROM sources WHERE project_id = ? AND kind = ?", (project_id, kind)
            ).fetchone()
            if old:
                source["id"] = old["id"]
                conn.execute(
                    "UPDATE sources SET location = ?, revision = ?, license_status = ?, metadata = ?, updated_at = ? WHERE id = ?",
                    (
                        location, source["revision"], source["license_status"], _json(source["metadata"]),
                        now, source["id"],
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        source["id"], project_id, kind, location, source["revision"],
                        source["license_status"], _json(source["metadata"]), now,
                    ),
                )
        return source

    def list_sources(self, project_id: str) -> list[dict[str, Any]]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sources WHERE project_id = ? ORDER BY kind",
                (project_id,),
            ).fetchall()
        return [
            _with_schema({**dict(row), "metadata": _loads(row["metadata"])})
            for row in rows
        ]

    def search_project(self, project_id: str, query: str, limit: int = 50) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("search query must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("search limit must be between 1 and 200")
        root = Path(project["root"]).resolve()
        if not root.is_dir():
            raise ValueError("project root missing")
        ignored_dirs = {".git", ".venv", "__pycache__", ".pytest_cache", "target", "node_modules"}
        needle = query.casefold()
        results: list[dict[str, Any]] = []
        for directory, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(name for name in dirnames if name not in ignored_dirs)
            for filename in sorted(filenames):
                path = Path(directory) / filename
                try:
                    resolved = path.resolve()
                    if not resolved.is_relative_to(root) or resolved.stat().st_size > 2_000_000:
                        continue
                    lines = resolved.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeError):
                    continue
                for line_number, line in enumerate(lines, 1):
                    if needle not in line.casefold():
                        continue
                    results.append({
                        "path": resolved.relative_to(root).as_posix(),
                        "line": line_number,
                        "text": redact_text(line.strip())[:400],
                    })
                    if len(results) >= limit:
                        return {"query": query, "limit": limit, "truncated": True, "results": results}
        return {"query": query, "limit": limit, "truncated": False, "results": results}

    def search_evidence(
        self,
        project_id: str,
        query: str,
        limit: int = 50,
        *,
        record_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("evidence search query must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("evidence search limit must be between 1 and 200")
        allowed_record_types = {"run", "artifact", "source", "experiment", "issue"}
        if record_type is not None and record_type not in allowed_record_types:
            raise ValueError("evidence search record type is invalid")
        if status is not None and (not isinstance(status, str) or not status.strip()):
            raise ValueError("evidence search status must be a non-empty string")
        needle = query.casefold()
        results: list[dict[str, Any]] = []

        def add_record(item_type: str, record_id: str, label: str, item_status: str | None, fields: dict[str, Any]) -> bool:
            if record_type is not None and item_type != record_type:
                return False
            if status is not None and item_status != status:
                return False
            redacted_fields = {name: redact_data(value) for name, value in fields.items()}
            serialized = json.dumps(redacted_fields, ensure_ascii=False, default=str)
            if needle not in serialized.casefold():
                return False
            matched_fields = [
                name for name, value in redacted_fields.items()
                if needle in json.dumps(value, ensure_ascii=False, default=str).casefold()
            ]
            results.append({
                "type": item_type,
                "id": record_id,
                "label": redact_text(label),
                "status": item_status,
                "matched_fields": matched_fields,
            })
            return len(results) >= limit

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, status, result FROM runs WHERE project_id = ? ORDER BY started_at DESC",
                (project_id,),
            ).fetchall()
            for row in rows:
                if add_record(
                    "run", row["id"], row["kind"], row["status"],
                    {"id": row["id"], "kind": row["kind"], "status": row["status"], "result": _loads(row["result"])},
                ):
                    return {"query": query, "limit": limit, "truncated": True, "results": results}
            rows = conn.execute(
                "SELECT id, kind, path, metadata FROM artifacts WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
            for row in rows:
                if add_record(
                    "artifact", row["id"], row["path"], None,
                    {"id": row["id"], "kind": row["kind"], "path": row["path"], "metadata": _loads(row["metadata"])},
                ):
                    return {"query": query, "limit": limit, "truncated": True, "results": results}
            rows = conn.execute(
                "SELECT id, kind, location, revision, metadata FROM sources WHERE project_id = ? ORDER BY kind",
                (project_id,),
            ).fetchall()
            for row in rows:
                if add_record(
                    "source", row["id"], row["location"], None,
                    {"id": row["id"], "kind": row["kind"], "location": row["location"], "revision": row["revision"], "metadata": _loads(row["metadata"])},
                ):
                    return {"query": query, "limit": limit, "truncated": True, "results": results}
            rows = conn.execute(
                "SELECT id, title, status, decision, evidence_refs FROM experiments WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
            for row in rows:
                if add_record(
                    "experiment", row["id"], row["title"], row["status"],
                    {"id": row["id"], "title": row["title"], "status": row["status"], "decision": row["decision"], "evidence_refs": _loads(row["evidence_refs"])},
                ):
                    return {"query": query, "limit": limit, "truncated": True, "results": results}
            rows = conn.execute(
                "SELECT id, title, severity, status, symptom, resolution, evidence_refs FROM issues WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            for row in rows:
                if add_record(
                    "issue", row["id"], row["title"], row["status"],
                    {"id": row["id"], "title": row["title"], "severity": row["severity"], "status": row["status"], "symptom": row["symptom"], "resolution": row["resolution"], "evidence_refs": _loads(row["evidence_refs"])},
                ):
                    return {"query": query, "limit": limit, "truncated": True, "results": results}
        return {"query": query, "limit": limit, "truncated": False, "results": results}

    def get_evidence_detail(self, project_id: str, evidence_id: str) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            run = conn.execute(
                "SELECT * FROM runs WHERE id = ? AND project_id = ?", (evidence_id, project_id)
            ).fetchone()
            if run:
                return {"type": "run", "id": evidence_id, "record": redact_data(self._run_dict(run))}
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND project_id = ?", (evidence_id, project_id)
            ).fetchone()
            if artifact:
                return {"type": "artifact", "id": evidence_id, "record": redact_data(self._artifact_dict(artifact))}
            source = conn.execute(
                "SELECT * FROM sources WHERE id = ? AND project_id = ?", (evidence_id, project_id)
            ).fetchone()
            if source:
                record = {**dict(source), "metadata": _loads(source["metadata"])}
                return {"type": "source", "id": evidence_id, "record": redact_data(_with_schema(record))}
            experiment = conn.execute(
                "SELECT * FROM experiments WHERE id = ? AND project_id = ?", (evidence_id, project_id)
            ).fetchone()
            if experiment:
                return {"type": "experiment", "id": evidence_id, "record": redact_data(_with_schema(self._experiment_dict(experiment)))}
            issue = conn.execute(
                "SELECT * FROM issues WHERE id = ? AND project_id = ?", (evidence_id, project_id)
            ).fetchone()
            if issue:
                return {"type": "issue", "id": evidence_id, "record": redact_data(_with_schema(self._issue_dict(issue)))}
        raise KeyError("evidence")

    def update_experiment(self, experiment_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {"status", "result", "decision", "evidence_refs"}
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"unsupported experiment fields: {', '.join(sorted(unknown))}")
        if "status" in patch and patch["status"] not in {"planned", "running", "concluded", "abandoned"}:
            raise ValueError(f"invalid experiment status: {patch['status']}")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
            if not row:
                raise KeyError(experiment_id)
            values = {
                "status": patch.get("status", row["status"]),
                "result": patch.get("result", _loads(row["result"]) if row["result"] else None),
                "decision": patch.get("decision", row["decision"]),
                "evidence_refs": patch.get("evidence_refs", _loads(row["evidence_refs"])),
            }
            conn.execute(
                "UPDATE experiments SET status = ?, result = ?, decision = ?, evidence_refs = ?, updated_at = ? WHERE id = ?",
                (
                    values["status"], _json(values["result"]) if values["result"] is not None else None,
                    values["decision"], _json(values["evidence_refs"]), _now(), experiment_id,
                ),
            )
            updated = conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        return self._experiment_dict(updated)

    def link_run_to_experiment(self, project_id: str, experiment_id: str, run_id: str) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            experiment = conn.execute(
                "SELECT id, evidence_refs FROM experiments WHERE id = ? AND project_id = ?",
                (experiment_id, project_id),
            ).fetchone()
            if not experiment:
                raise KeyError("experiment")
            run = conn.execute(
                "SELECT id, status FROM runs WHERE id = ? AND project_id = ?",
                (run_id, project_id),
            ).fetchone()
            if not run:
                raise KeyError("run")
            if run["status"] not in RUN_TERMINAL_STATUSES:
                raise ValueError("experiment evidence requires a terminal run")
            evidence_refs = _loads(experiment["evidence_refs"])
            if run_id not in evidence_refs:
                evidence_refs.append(run_id)
                conn.execute(
                    "UPDATE experiments SET evidence_refs = ?, updated_at = ? WHERE id = ?",
                    (_json(evidence_refs), _now(), experiment_id),
                )
            updated = conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        return self._experiment_dict(updated)

    def compare_experiments(self, project_id: str, left_id: str, right_id: str) -> dict[str, Any]:
        if left_id == right_id:
            raise ValueError("experiments to compare must be different")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM experiments WHERE project_id = ? AND id IN (?, ?)",
                (project_id, left_id, right_id),
            ).fetchall()
        by_id = {row["id"]: row for row in rows}
        if left_id not in by_id or right_id not in by_id:
            raise KeyError("experiment")
        left = self._experiment_dict(by_id[left_id])
        right = self._experiment_dict(by_id[right_id])
        fields = ("variable", "baseline", "expected", "result", "decision", "status", "evidence_refs", "context")

        def comparable(field: str, value: Any) -> Any:
            if field == "context" and isinstance(value, dict):
                return {key: item for key, item in value.items() if key != "captured_at"}
            return value

        changes = []
        for field in fields:
            before_value = comparable(field, left[field])
            after_value = comparable(field, right[field])
            if before_value != after_value:
                changes.append({"field": field, "before": before_value, "after": after_value})
        return {
            "status": "changed" if changes else "unchanged",
            "left": left,
            "right": right,
            "changed_fields": [change["field"] for change in changes],
            "changes": changes,
        }

    def save_calibration(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        normalized = validate_calibration(data)
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id, status FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if not hardware or hardware["status"] != "confirmed":
                raise ValueError("confirmed hardware is required for calibration")
        record = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "hardware_profile_id": hardware["id"],
            "status": "recorded",
            "data": normalized,
            "created_at": _now(),
        })
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO calibrations VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record["id"], record["project_id"], record["hardware_profile_id"],
                    record["status"], _json(record["data"]), record["created_at"],
                ),
            )
        self._refresh_task_statuses(project_id)
        return record

    def _hardware_context(
        self, project_id: str
    ) -> tuple[str | None, dict[str, Any] | None, dict[str, dict[str, Any]]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        profiles = {row["id"]: _loads(row["data"]) for row in rows}
        current_id = rows[0]["id"] if rows else None
        return current_id, profiles.get(current_id), profiles

    def list_calibrations(self, project_id: str) -> list[dict[str, Any]]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM calibrations WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        current_id, current_data, profiles = self._hardware_context(project_id)
        return [self._calibration_dict(row, current_id, current_data, profiles) for row in rows]

    def save_assembly(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        normalized, completion = validate_assembly(data)
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        record = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "hardware_profile_id": hardware["id"] if hardware else None,
            "status": "recorded",
            "completion": completion,
            "data": normalized,
            "created_at": _now(),
        })
        record["material_summary"] = summarize_assembly_materials(normalized["materials"])
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO assembly_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], record["project_id"], record["hardware_profile_id"],
                    record["status"], record["completion"], _json(record["data"]), record["created_at"],
                ),
            )
        self._refresh_task_statuses(project_id)
        return record

    def list_assemblies(self, project_id: str) -> list[dict[str, Any]]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assembly_records WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        current_id, current_data, profiles = self._hardware_context(project_id)
        return [self._assembly_dict(row, current_id, current_data, profiles) for row in rows]

    def save_identification(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        root = Path(project["root"]).resolve()
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id, status, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if not hardware or hardware["status"] != "confirmed":
            raise ValueError("confirmed hardware is required for actuator identification")
        hardware_data = _loads(hardware["data"])
        servos = hardware_data.get("servos") if isinstance(hardware_data, dict) else {}
        expected_model = servos.get("model") if isinstance(servos, dict) else None
        normalized, readiness, reasons = validate_identification(data, expected_model, root)
        record = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "hardware_profile_id": hardware["id"],
            "readiness": readiness,
            "reasons": reasons,
            "data": normalized,
            "created_at": _now(),
        })
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO identification_records VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], record["project_id"], record["hardware_profile_id"],
                    record["readiness"], _json(record["reasons"]), _json(record["data"]), record["created_at"],
                ),
            )
            prerequisites = conn.execute(
                "SELECT id, status FROM tasks WHERE project_id = ? AND id IN ('hardware', 'servo_read')",
                (project_id,),
            ).fetchall()
        prerequisite_statuses = {row["id"]: row["status"] for row in prerequisites}
        prerequisites_passed = prerequisite_statuses == {"hardware": "success", "servo_read": "success"}
        if prerequisites_passed and readiness == "ready_for_simulation":
            self.set_task_status(project_id, "identification", "success")
        elif prerequisites_passed:
            self.set_task_status(project_id, "identification", "failed")
        else:
            self._refresh_task_statuses(project_id)
        return record

    def list_identifications(self, project_id: str) -> list[dict[str, Any]]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM identification_records WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        current_id, current_data, profiles = self._hardware_context(project_id)
        return [self._identification_dict(row, current_id, current_data, profiles) for row in rows]

    def create_issue(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        normalized = validate_issue(data)
        with self._connect() as conn:
            hardware = conn.execute(
                "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        now = _now()
        issue = _with_schema({
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "hardware_profile_id": hardware["id"] if hardware else None,
            **normalized,
            "created_at": now,
            "updated_at": now,
        })
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    issue["id"], issue["project_id"], issue["hardware_profile_id"], issue["title"],
                    issue["severity"], issue["status"], issue["symptom"], _json(issue["suspected_causes"]),
                    _json(issue["next_checks"]), _json(issue["evidence_refs"]), issue["resolution"], now, now,
                ),
            )
        return issue

    def create_issue_from_run(
        self, project_id: str, run_id: str, title: str | None = None
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE id = ? AND project_id = ?", (run_id, project_id)
            ).fetchone()
        if not row:
            raise KeyError(run_id)
        if row["status"] not in {"failed", "interrupted"}:
            raise ValueError("issue source run must be failed or interrupted")
        result = _loads(row["result"]) if row["result"] else {}
        result = result if isinstance(result, dict) else {}
        guidance = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
        facts = guidance.get("current_facts") if isinstance(guidance.get("current_facts"), list) else []
        causes = guidance.get("possible_causes") if isinstance(guidance.get("possible_causes"), list) else []
        next_checks = guidance.get("next_checks") if isinstance(guidance.get("next_checks"), list) else []
        reasons = result.get("reasons") if isinstance(result.get("reasons"), list) else []
        suspected = [str(item) for item in causes if str(item).strip()]
        if not suspected:
            suspected = [f"运行原因：{item}" for item in reasons if str(item).strip()]
        category = str(result.get("category", "")).strip()
        issue_title = title.strip() if isinstance(title, str) and title.strip() else f"{row['kind']}: {category or row['status']}"
        symptom = str(facts[0]).strip() if facts and str(facts[0]).strip() else category or f"运行状态：{row['status']}"
        return self.create_issue(
            project_id,
            {
                "title": issue_title,
                "severity": "warning",
                "symptom": symptom,
                "suspected_causes": suspected,
                "next_checks": [str(item) for item in next_checks if str(item).strip()],
                "evidence_refs": [run_id],
            },
        )

    def update_issue(self, issue_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "severity", "status", "symptom", "suspected_causes", "next_checks", "evidence_refs", "resolution"}
        unknown = set(patch) - allowed
        if unknown:
            raise ValueError(f"unsupported issue fields: {', '.join(sorted(unknown))}")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
            if not row:
                raise KeyError(issue_id)
        current = self._issue_dict(row)
        candidate = {field: current[field] for field in allowed}
        candidate.update(patch)
        normalized = validate_issue(candidate)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE issues SET title = ?, severity = ?, status = ?, symptom = ?, suspected_causes = ?, next_checks = ?, evidence_refs = ?, resolution = ?, updated_at = ? WHERE id = ?",
                (
                    normalized["title"], normalized["severity"], normalized["status"], normalized["symptom"],
                    _json(normalized["suspected_causes"]), _json(normalized["next_checks"]),
                    _json(normalized["evidence_refs"]), normalized["resolution"], now, issue_id,
                ),
            )
            updated = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        return self._issue_dict(updated)

    def link_run_to_issue(self, project_id: str, issue_id: str, run_id: str) -> dict[str, Any]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        run = self.get_run(run_id)
        if run["project_id"] != project_id:
            raise KeyError("run")
        if run["status"] not in RUN_TERMINAL_STATUSES:
            raise ValueError("issue evidence requires a terminal run")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM issues WHERE id = ? AND project_id = ?", (issue_id, project_id)
            ).fetchone()
        if not row:
            raise KeyError("issue")
        issue = self._issue_dict(row)
        if run_id in issue["evidence_refs"]:
            return issue
        return self.update_issue(issue_id, {"evidence_refs": [*issue["evidence_refs"], run_id]})

    def list_issues(self, project_id: str) -> list[dict[str, Any]]:
        if not self.get_project(project_id):
            raise KeyError(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        current_id, current_data, profiles = self._hardware_context(project_id)
        return [self._issue_dict(row, current_id, current_data, profiles) for row in rows]

    @staticmethod
    def _experiment_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for field in ("baseline", "expected", "result", "evidence_refs", "context"):
            value[field] = _loads(value[field]) if value[field] is not None else None
        if value.get("context") is None:
            value["context"] = {}
        return value

    @staticmethod
    def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["result"] = _loads(value["result"])
        value["result"].setdefault("evidence_scope", evidence_scope_for_run(value["kind"]))
        return _with_schema(value)

    @staticmethod
    def _artifact_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["metadata"] = _loads(value["metadata"])
        path = Path(value["path"])
        if not path.is_file():
            value.update({"integrity_status": "missing", "current_sha256": None, "current_size": None})
            return value
        try:
            digest, size = _file_sha256(path)
        except OSError:
            value.update({"integrity_status": "unreadable", "current_sha256": None, "current_size": None})
            return value
        value.update({
            "integrity_status": "verified"
            if digest == value["sha256"] and size == value["size"]
            else "changed",
            "current_sha256": digest,
            "current_size": size,
        })
        return value

    @staticmethod
    def _calibration_dict(
        row: sqlite3.Row,
        current_hardware_id: str | None,
        current_data: dict[str, Any] | None = None,
        profiles: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = dict(row)
        value["data"] = _loads(value["data"])
        value["valid_for_current_hardware"] = hardware_records_match(
            value["hardware_profile_id"], current_hardware_id, current_data, profiles
        )
        return value

    @staticmethod
    def _assembly_dict(
        row: sqlite3.Row,
        current_hardware_id: str | None,
        current_data: dict[str, Any] | None = None,
        profiles: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = dict(row)
        value["data"] = _loads(value["data"])
        value["material_summary"] = summarize_assembly_materials(value["data"].get("materials", []))
        value["valid_for_current_hardware"] = hardware_records_match(
            value["hardware_profile_id"], current_hardware_id, current_data, profiles
        )
        return value

    @staticmethod
    def _identification_dict(
        row: sqlite3.Row,
        current_hardware_id: str | None,
        current_data: dict[str, Any] | None = None,
        profiles: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = dict(row)
        value["reasons"] = _loads(value["reasons"])
        value["data"] = _loads(value["data"])
        value["valid_for_current_hardware"] = hardware_records_match(
            value["hardware_profile_id"], current_hardware_id, current_data, profiles
        )
        return value

    @staticmethod
    def _issue_dict(
        row: sqlite3.Row,
        current_hardware_id: str | None = None,
        current_data: dict[str, Any] | None = None,
        profiles: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = dict(row)
        for field in ("suspected_causes", "next_checks", "evidence_refs"):
            value[field] = _loads(value[field])
        if current_hardware_id is not None:
            value["valid_for_current_hardware"] = hardware_records_match(
                value["hardware_profile_id"], current_hardware_id, current_data, profiles
            )
        return value

    def _set_hardware_bound_task_status(
        self, project_id: str, task_id: str, status: str, expected_profile_id: str | None
    ) -> None:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT id FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            task = conn.execute(
                "SELECT status FROM tasks WHERE project_id = ? AND id = ?",
                (project_id, task_id),
            ).fetchone()
        if current and current["id"] == expected_profile_id and task and task["status"] != "interrupted":
            self.set_task_status(project_id, task_id, status)
        else:
            self._refresh_task_statuses(project_id)

    def _set_deployment_preflight_task_status(
        self, project_id: str, status: str, expected_profile_id: str | None
    ) -> None:
        if status == "success":
            with self._connect() as conn:
                prerequisites = conn.execute(
                    "SELECT id, status FROM tasks WHERE project_id = ? AND id IN ('hardware', 'preflight', 'smoke')",
                    (project_id,),
                ).fetchall()
            if {row["id"] for row in prerequisites} != {"hardware", "preflight", "smoke"} or any(
                row["status"] != "success" for row in prerequisites
            ):
                self._refresh_task_statuses(project_id)
                return
        self._set_hardware_bound_task_status(
            project_id, "deployment_preflight", status, expected_profile_id
        )

    def set_task_status(self, project_id: str, task_id: str, status: str) -> None:
        allowed = {"needs_confirmation", "ready", "running", "success", "failed", "blocked", "interrupted"}
        if status not in allowed:
            raise ValueError(f"invalid task status: {status}")
        with self._connect() as conn:
            updated = conn.execute(
                "UPDATE tasks SET status = ? WHERE project_id = ? AND id = ?",
                (status, project_id, task_id),
            ).rowcount
        if not updated:
            raise KeyError(task_id)
        self._refresh_task_statuses(project_id)

    def _refresh_task_statuses(self, project_id: str) -> None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, status, deps FROM tasks WHERE project_id = ? ORDER BY rowid",
                (project_id,),
            ).fetchall()
            statuses = {row["id"]: row["status"] for row in rows}
            hardware = conn.execute(
                "SELECT id, status, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            current_hardware_id = hardware["id"] if hardware else None
            current_hardware_data = _loads(hardware["data"]) if hardware else None
            profile_rows = conn.execute(
                "SELECT id, data FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            hardware_profiles = {row["id"]: _loads(row["data"]) for row in profile_rows}
            latest_assembly = conn.execute(
                "SELECT hardware_profile_id, completion FROM assembly_records WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            latest_calibration = conn.execute(
                "SELECT id, hardware_profile_id, data FROM calibrations WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            latest_deployment_preflight = conn.execute(
                "SELECT status, result FROM runs WHERE project_id = ? AND kind = 'deployment_preflight' ORDER BY started_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            for row in rows:
                current = row["status"]
                if row["id"] == "hardware":
                    desired = "success" if hardware and hardware["status"] == "confirmed" else "needs_confirmation"
                    if current != desired:
                        conn.execute(
                            "UPDATE tasks SET status = ? WHERE project_id = ? AND id = ?",
                            (desired, project_id, row["id"]),
                        )
                        statuses[row["id"]] = desired
                    continue
                if row["id"] == "assembly":
                    valid = bool(
                        hardware
                        and hardware["status"] == "confirmed"
                        and latest_assembly
                        and hardware_records_match(
                            latest_assembly["hardware_profile_id"], current_hardware_id,
                            current_hardware_data, hardware_profiles
                        )
                    )
                    if valid and latest_assembly["completion"] == "passed":
                        desired = "success"
                    elif valid and latest_assembly["completion"] == "failed":
                        desired = "failed"
                    else:
                        desired = "ready" if hardware and hardware["status"] == "confirmed" else "blocked"
                    if current != desired:
                        conn.execute(
                            "UPDATE tasks SET status = ? WHERE project_id = ? AND id = ?",
                            (desired, project_id, row["id"]),
                        )
                        statuses[row["id"]] = desired
                    continue
                if row["id"] == "calibration":
                    calibration_data = _loads(latest_calibration["data"]) if latest_calibration else {}
                    deps_ready = all(statuses.get(dep) == "success" for dep in _loads(row["deps"]))
                    valid = bool(
                        latest_calibration
                        and hardware_records_match(
                            latest_calibration["hardware_profile_id"], current_hardware_id,
                            current_hardware_data, hardware_profiles
                        )
                        and calibration_data.get("verified") is True
                    )
                    desired = "success" if deps_ready and valid else "ready" if deps_ready else "blocked"
                    if current != desired:
                        conn.execute(
                            "UPDATE tasks SET status = ? WHERE project_id = ? AND id = ?",
                            (desired, project_id, row["id"]),
                        )
                        statuses[row["id"]] = desired
                    continue
                if row["id"] == "deployment_preflight" and current == "success":
                    deps_ready = all(statuses.get(dep) == "success" for dep in _loads(row["deps"]))
                    result = _loads(latest_deployment_preflight["result"]) if latest_deployment_preflight else {}
                    required_artifacts = {"policy", "policy_manifest"}
                    artifact_kinds: set[str] = set()
                    artifacts_fresh = isinstance(result.get("artifacts"), list)
                    if artifacts_fresh:
                        for artifact in result["artifacts"]:
                            if not isinstance(artifact, dict) or artifact.get("kind") not in required_artifacts:
                                continue
                            artifact_kinds.add(artifact["kind"])
                            path = Path(str(artifact.get("path", "")))
                            try:
                                digest, size = _file_sha256(path) if path.is_file() else (None, None)
                            except OSError:
                                digest, size = None, None
                            if digest != artifact.get("sha256") or size != artifact.get("size"):
                                artifacts_fresh = False
                                break
                    artifacts_fresh = artifacts_fresh and artifact_kinds == required_artifacts
                    fresh = bool(
                        latest_deployment_preflight
                        and latest_deployment_preflight["status"] == "passed"
                        and deps_ready
                        and result.get("calibration_record_id")
                        == (latest_calibration["id"] if latest_calibration else None)
                        and artifacts_fresh
                    )
                    if not fresh:
                        desired = "ready" if deps_ready else "blocked"
                        conn.execute(
                            "UPDATE tasks SET status = ? WHERE project_id = ? AND id = ?",
                            (desired, project_id, row["id"]),
                        )
                        statuses[row["id"]] = desired
                    continue
                deps = _loads(row["deps"])
                deps_ready = all(statuses.get(dep) == "success" for dep in deps)
                if current == "success" and not deps_ready:
                    conn.execute(
                        "UPDATE tasks SET status = 'blocked' WHERE project_id = ? AND id = ?",
                        (project_id, row["id"]),
                    )
                    statuses[row["id"]] = "blocked"
                    continue
                if current in {"success", "failed", "interrupted", "running"}:
                    continue
                next_status = "ready" if deps_ready else "blocked"
                if current != next_status:
                    conn.execute(
                        "UPDATE tasks SET status = ? WHERE project_id = ? AND id = ?",
                        (next_status, project_id, row["id"]),
                    )
                    statuses[row["id"]] = next_status

    def next_task(self, project_id: str) -> dict[str, Any] | None:
        self._refresh_task_statuses(project_id)
        report = self.project_report(project_id)
        for task in report["tasks"]:
            if task["status"] in {"needs_confirmation", "ready"}:
                return task
        return None

    def project_report(self, project_id: str) -> dict[str, Any]:
        self._refresh_task_statuses(project_id)
        with self._connect() as conn:
            project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            hardware_rows = conn.execute(
                "SELECT * FROM hardware_profiles WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY rowid", (project_id,)
            ).fetchall()
            runs = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY started_at DESC", (project_id,)
            ).fetchall()
            artifacts = conn.execute(
                "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            experiments = conn.execute(
                "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            calibrations = conn.execute(
                "SELECT * FROM calibrations WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            assemblies = conn.execute(
                "SELECT * FROM assembly_records WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            identifications = conn.execute(
                "SELECT * FROM identification_records WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
            issues = conn.execute(
                "SELECT * FROM issues WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)
            ).fetchall()
            sources = conn.execute(
                "SELECT * FROM sources WHERE project_id = ? ORDER BY kind", (project_id,)
            ).fetchall()
        if not project:
            raise KeyError(project_id)
        hardware_history = [
            _with_schema({
                **dict(row),
                "data": _loads(row["data"]),
                "completeness": hardware_completeness(_loads(row["data"])),
            })
            for row in hardware_rows
        ]
        current_hardware_id = hardware_history[0]["id"] if hardware_history else None
        current_hardware_data = hardware_history[0]["data"] if hardware_history else None
        hardware_profiles = {item["id"]: item["data"] for item in hardware_history}
        task_statuses = {row["id"]: row["status"] for row in tasks}
        latest_assembly = assemblies[0] if assemblies else None
        if not latest_assembly or not hardware_records_match(
            latest_assembly["hardware_profile_id"], current_hardware_id,
            current_hardware_data, hardware_profiles
        ):
            assembly_evidence_reasons = ["current_assembly_record_required"]
        elif latest_assembly["completion"] != "passed":
            assembly_evidence_reasons = [f"assembly_completion_{latest_assembly['completion']}"]
        else:
            assembly_evidence_reasons = []
        latest_calibration = calibrations[0] if calibrations else None
        calibration_data = _loads(latest_calibration["data"]) if latest_calibration else {}
        if not latest_calibration or not hardware_records_match(
            latest_calibration["hardware_profile_id"], current_hardware_id,
            current_hardware_data, hardware_profiles
        ):
            calibration_evidence_reasons = ["current_calibration_record_required"]
        elif calibration_data.get("verified") is not True:
            calibration_evidence_reasons = ["operator_verification_required"]
        else:
            calibration_evidence_reasons = []
        latest_deployment_run = next(
            (run for run in runs if run["kind"] == "deployment_preflight"), None
        )

        def evidence_reasons(task_id: str) -> list[str]:
            if task_id == "assembly":
                return assembly_evidence_reasons
            if task_id == "calibration":
                return calibration_evidence_reasons
            if task_id == "deployment_preflight":
                reasons = []
                if task_statuses.get("assembly") != "success":
                    reasons.append("assembly_task_required")
                if task_statuses.get("calibration") != "success":
                    reasons.append("calibration_task_required")
                if task_statuses.get(task_id) != "success":
                    reasons.append(
                        "deployment_preflight_evidence_stale"
                        if latest_deployment_run and latest_deployment_run["status"] == "passed"
                        else "deployment_preflight_run_required"
                    )
                return reasons
            return []

        report_runs = [self._run_dict(run) for run in runs]
        runs_by_id = {run["id"]: run for run in report_runs}
        report_artifacts = [_with_schema(self._artifact_dict(artifact)) for artifact in artifacts]
        artifacts_by_id = {artifact["id"]: artifact for artifact in report_artifacts}
        report_sources = [
            _with_schema({**dict(source), "metadata": _loads(source["metadata"])})
            for source in sources
        ]
        sources_by_id = {source["id"]: source for source in report_sources}

        def resolve_evidence(refs: Any) -> list[dict[str, Any]]:
            if not isinstance(refs, list):
                return []
            details = []
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                run = runs_by_id.get(ref)
                if run:
                    details.append({
                        "run_id": ref,
                        "kind": run["kind"],
                        "status": run["status"],
                        "evidence_scope": run["result"].get(
                            "evidence_scope", evidence_scope_for_run(run["kind"])
                        ),
                    })
                    continue
                artifact = artifacts_by_id.get(ref)
                if artifact:
                    details.append({
                        "artifact_id": ref,
                        "artifact_kind": artifact["kind"],
                        "integrity_status": artifact["integrity_status"],
                        "path": artifact["path"],
                    })
                    continue
                source = sources_by_id.get(ref)
                if source:
                    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
                    details.append({
                        "source_id": ref,
                        "source_kind": source["kind"],
                        "location": source["location"],
                        "revision": source["revision"],
                        "revision_matches": metadata.get("revision_matches"),
                    })
            return details

        report_experiments = []
        for experiment in experiments:
            item = _with_schema(self._experiment_dict(experiment))
            item["evidence_details"] = resolve_evidence(item.get("evidence_refs"))
            report_experiments.append(item)
        report_issues = []
        for issue in issues:
            item = _with_schema(self._issue_dict(issue, current_hardware_id, current_hardware_data, hardware_profiles))
            item["evidence_details"] = resolve_evidence(item.get("evidence_refs"))
            report_issues.append(item)

        return {
            "schema_version": SCHEMA_VERSION,
            "project": _with_schema(dict(project)),
            "hardware": hardware_history[0] if hardware_history else None,
            "hardware_history": hardware_history,
            "tasks": [
                {
                    **dict(task),
                    "deps": _loads(task["deps"]),
                    "blocked_by": [
                        dep for dep in _loads(task["deps"])
                        if next((item["status"] for item in tasks if item["id"] == dep), None) != "success"
                    ],
                    "card": dict(TASK_CARDS.get(task["id"], {})),
                    "evidence_reasons": evidence_reasons(task["id"]),
                }
                for task in tasks
            ],
            "runs": report_runs,
            # ponytail: report-time hashing is fine for personal-scale evidence; cache by mtime if measured latency grows.
            "artifacts": report_artifacts,
            "experiments": report_experiments,
            "calibrations": [
                _with_schema(self._calibration_dict(calibration, current_hardware_id, current_hardware_data, hardware_profiles))
                for calibration in calibrations
            ],
            "assemblies": [
                _with_schema(self._assembly_dict(assembly, current_hardware_id, current_hardware_data, hardware_profiles))
                for assembly in assemblies
            ],
            "identifications": [
                _with_schema(self._identification_dict(item, current_hardware_id, current_hardware_data, hardware_profiles))
                for item in identifications
            ],
            "issues": report_issues,
            "sources": report_sources,
        }

    def project_report_markdown(self, project_id: str) -> str:
        report = self.project_report(project_id)
        project = report["project"]
        hardware = report["hardware"]
        lines = [
            "# Microduck Studio report",
            "",
            f"- 项目：{project['name']}",
            f"- 根目录：`{project['root']}`",
            f"- 状态：`{project['status']}`",
            f"- 硬件档案：`{hardware['status'] if hardware else '未建立'}`",
            "",
            "## 任务",
            "",
            "| 任务 | 状态 | 证据缺口 |",
            "|---|---|---|",
        ]
        if hardware and isinstance(hardware.get("completeness"), dict):
            completeness = hardware["completeness"]
            lines[6:6] = [
                f"- 硬件档案完整性：`{completeness.get('status', 'unknown')}`",
                f"- 缺失字段：{'；'.join(completeness.get('missing_fields', [])) or '无'}",
                "",
            ]
        lines.extend(
            f"| {task['title']} | `{task['status']}` | {'；'.join(task.get('evidence_reasons', [])) or '-'} |"
            for task in report["tasks"]
        )
        lines.extend(["", "## 运行记录", ""])
        for run in report["runs"]:
            rule_version = run["result"].get("rule_version", "unknown")
            scope = run["result"].get("evidence_scope", evidence_scope_for_run(run["kind"]))
            lines.append(f"- `{run['kind']}` → `{run['status']}` · 规则：`{rule_version}` · 证据范围：`{scope}` ({run['started_at']})")
            if run["result"].get("retry_of"):
                lines.append(f"  - 重试自：`{run['result']['retry_of']}`")
            reasons = run["result"].get("reasons") if isinstance(run["result"].get("reasons"), list) else []
            guidance = run["result"].get("guidance") if isinstance(run["result"].get("guidance"), dict) else {}
            if reasons:
                lines.append(f"  - 原因：{'；'.join(str(reason) for reason in reasons)}")
            if guidance.get("next_checks"):
                lines.append(f"  - 下一项检查：{'；'.join(str(check) for check in guidance['next_checks'])}")
        preflight_runs = [run for run in report["runs"] if run["kind"] == "preflight"]
        if preflight_runs:
            baseline = preflight_runs[0]["result"].get("baseline")
            if isinstance(baseline, dict):
                git = baseline.get("git") if isinstance(baseline.get("git"), dict) else {}
                platform = baseline.get("platform") if isinstance(baseline.get("platform"), dict) else {}
                lines.extend(["", "## 环境基线", ""])
                lines.append(
                    f"- Git：`{git.get('commit') or 'unknown'}` · 分支：`{git.get('branch') or 'detached/unknown'}` · 工作树：`{'dirty' if git.get('dirty') else 'clean/unknown'}`"
                )
                lines.append(
                    f"- 平台：`{platform.get('system', 'unknown')} {platform.get('release', '')}` · 架构：`{platform.get('machine', 'unknown')}` · Python：`{platform.get('python', 'unknown')}`"
                )
                tools = baseline.get("tools") if isinstance(baseline.get("tools"), dict) else {}
                versions = [
                    f"{name}={value.get('version')}"
                    for name, value in tools.items()
                    if isinstance(value, dict) and value.get("version")
                ]
                if versions:
                    lines.append(f"- 工具：{' · '.join(versions)}")
        controller_runs = [run for run in report["runs"] if run["kind"] == "controller_diagnostic"]
        if controller_runs:
            lines.extend(["", "## 主控诊断", ""])
        for run in controller_runs:
                result = run["result"]
                lines.append(f"- 分类：`{result.get('category', 'unknown')}` · 状态：`{run['status']}`")
                guidance = result.get("guidance") if isinstance(result.get("guidance"), dict) else {}
                for label, key in (
                    ("当前事实", "current_facts"),
                    ("可能原因", "possible_causes"),
                    ("缺失证据", "missing_evidence"),
                    ("下一项检查", "next_checks"),
                ):
                    values = guidance.get(key) if isinstance(guidance.get(key), list) else []
                    if values:
                        lines.append(f"  - {label}：{'；'.join(str(value).replace(chr(10), ' ') for value in values)}")
        training_runs = [run for run in report["runs"] if run["kind"] == "training_smoke"]
        if training_runs:
            lines.extend(["", "## 训练 smoke", ""])
            for run in training_runs:
                result = run["result"]
                lines.append(
                    f"- 状态：`{run['status']}` · 迭代：`{result.get('constraints', {}).get('max_iterations', 'unknown')}` · 原因：{', '.join(result.get('reasons', [])) or 'none'}"
                )
                provenance = result.get("training_provenance") if isinstance(result.get("training_provenance"), dict) else {}
                source = provenance.get("source") if isinstance(provenance.get("source"), dict) else {}
                if source:
                    lines.append(
                        f"  - 来源：`{source.get('commit') or 'unknown'}` · 分支：`{source.get('branch') or 'detached/unknown'}` · 工作树：`{'dirty' if source.get('dirty') else 'clean/unknown'}`"
                    )
                unavailable = provenance.get("unavailable") if isinstance(provenance.get("unavailable"), list) else []
                if unavailable:
                    lines.append(f"  - 未声明：{', '.join(str(value) for value in unavailable)}")
                outputs = result.get("training_outputs") if isinstance(result.get("training_outputs"), dict) else {}
                contract = outputs.get("contract") if isinstance(outputs.get("contract"), dict) else {}
                onnx = outputs.get("onnx") if isinstance(outputs.get("onnx"), list) else []
                if contract or onnx:
                    lines.append(
                        f"  - 策略证据：ONNX {len(onnx)} 个 · 合同：`{contract.get('path', 'missing')}`"
                    )
        deployment_runs = [run for run in report["runs"] if run["kind"] == "deployment_preflight"]
        if deployment_runs:
            lines.extend(["", "## 部署前兼容性", ""])
            for run in deployment_runs:
                result = run["result"]
                policy = result.get("policy") if isinstance(result.get("policy"), dict) else {}
                lines.append(
                    f"- 状态：`{run['status']}` · 原因：{', '.join(result.get('reasons', [])) or 'none'} · 策略：`{policy.get('name', 'unknown')}`"
                )
        if report["calibrations"]:
            lines.extend(["", "## 标定记录", ""])
            for calibration in report["calibrations"]:
                data = calibration["data"] if isinstance(calibration.get("data"), dict) else {}
                joints = data.get("joints") if isinstance(data.get("joints"), list) else []
                names = [str(joint.get("name")) for joint in joints if isinstance(joint, dict) and joint.get("name")]
                validity = "当前硬件" if calibration.get("valid_for_current_hardware") else "旧硬件，需重新验证"
                lines.append(
                    f"- 状态：`{calibration['status']}` · 适用性：`{validity}` · 舵机：{', '.join(names) or 'unknown'}"
                )
        if report["assemblies"]:
            lines.extend(["", "## 装配记录", ""])
            for assembly in report["assemblies"]:
                data = assembly["data"] if isinstance(assembly.get("data"), dict) else {}
                checks = data.get("checks") if isinstance(data.get("checks"), list) else []
                passed = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "passed")
                validity = "当前硬件" if assembly.get("valid_for_current_hardware") else "未绑定或旧硬件，需重新验证"
                lines.append(
                    f"- `{data.get('title', '未命名')}` · 完成度：`{assembly['completion']}` · 检查：`{passed}/{len(checks)}` · 适用性：`{validity}`"
                )
        if report["identifications"]:
            lines.extend(["", "## 执行器辨识", ""])
            for identification in report["identifications"]:
                data = identification["data"] if isinstance(identification.get("data"), dict) else {}
                validity = "当前硬件" if identification.get("valid_for_current_hardware") else "旧硬件，需重新验证"
                reasons = ", ".join(identification.get("reasons", [])) or "none"
                lines.append(
                    f"- 型号：`{data.get('actuator_model', 'unknown')}` · 就绪度：`{identification['readiness']}` · 适用性：`{validity}` · 原因：{reasons}"
                )
        if report["issues"]:
            lines.extend(["", "## 问题台账", ""])
            for issue in report["issues"]:
                lines.append(
                    f"- `{issue['title']}` · 严重度：`{issue['severity']}` · 状态：`{issue['status']}` · 症状：{issue['symptom']}"
                )
                if issue["next_checks"]:
                    lines.append(f"  - 下一项检查：{'；'.join(issue['next_checks'])}")
                if issue["resolution"]:
                    lines.append(f"  - 解决结论：{issue['resolution']}")
                evidence_refs = [str(ref) for ref in issue.get("evidence_refs", []) if str(ref).strip()]
                if evidence_refs:
                    lines.append(f"  - 证据引用：{'；'.join(evidence_refs)}")
        lines.extend(["", "## 产物", ""])
        for artifact in report["artifacts"]:
            lines.append(
                f"- `{artifact['kind']}` `{artifact['path']}` · {artifact['size']} bytes · `{artifact['sha256']}` · 完整性：`{artifact['integrity_status']}`"
            )
        lines.extend(["", "## 实验", ""])
        for experiment in report["experiments"]:
            lines.append(f"- `{experiment['title']}` → `{experiment['status']}`：{experiment['decision'] or '未决策'}")
            context = experiment.get("context") if isinstance(experiment.get("context"), dict) else {}
            hardware = context.get("hardware") if isinstance(context.get("hardware"), dict) else {}
            servos = hardware.get("servos") if isinstance(hardware.get("servos"), dict) else {}
            lines.append(
                f"  - 条件快照：硬件档案 `{context.get('hardware_profile_id') or 'unknown'}` · "
                f"舵机 `{servos.get('model') or 'unknown'}` · 预检运行 `{context.get('preflight_run_id') or 'unknown'}`"
            )
            evidence_refs = [str(ref) for ref in experiment.get("evidence_refs", []) if str(ref).strip()]
            if evidence_refs:
                lines.append(f"  - 证据引用：{'；'.join(evidence_refs)}")
        lines.extend(["", "## 来源", ""])
        for source in report["sources"]:
            lines.append(
                f"- `{source['kind']}` `{source['location']}` @ `{source['revision'] or 'unknown'}` · license `{source['license_status']}`"
            )
        return "\n".join(lines) + "\n"

    def create_support_bundle(
        self,
        project_id: str,
        output_path: Path | str | None = None,
        *,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("explicit confirmation required")
        project = self.get_project(project_id)
        if not project:
            raise KeyError(project_id)
        root = Path(project["root"]).resolve()
        if not root.is_dir():
            raise ValueError("project root must exist before creating a support bundle")
        output = (
            root / "artifacts" / "support" / f"support-{uuid.uuid4().hex[:12]}.zip"
            if output_path is None else Path(output_path)
        )
        if not output.is_absolute():
            output = root / output
        output = output.resolve()
        if not output.is_relative_to(root):
            raise ValueError("support bundle path must be inside the project root")
        if output.suffix.lower() != ".zip":
            raise ValueError("support bundle path must end in .zip")
        if output.exists():
            raise ValueError("support bundle path already exists")

        report = redact_data(self.project_report(project_id))
        markdown = redact_text(self.project_report_markdown(project_id))
        run = self.start_run(project_id, "support_bundle")
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            manifest = {
                "schema_version": 1,
                "created_at": _now(),
                "project_id": project_id,
                "redaction": ["secret_keys", "tokens", "private_keys", "user_home"],
                "contents": ["manifest.json", "report.json", "report.md"],
            }
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))
                archive.writestr("report.md", markdown)
            artifact = self.register_artifact(
                project_id,
                output,
                "support_bundle",
                run_id=run["id"],
                metadata={"redaction": manifest["redaction"], "contents": manifest["contents"]},
            )
        except Exception as exc:
            if output.exists():
                output.unlink()
            result = {
                "status": "failed",
                "reasons": ["support_bundle_error"],
                "error": redact_text(str(exc)),
                "output_path": redact_text(str(output)),
                "mutates": True,
            }
            self.finish_run(run["id"], result["status"], result)
            raise
        result = {
            "status": "passed",
            "reasons": [],
            "output_path": str(output),
            "artifact_id": artifact["id"],
            "redaction": manifest["redaction"],
            "mutates": True,
        }
        self.finish_run(run["id"], result["status"], result)
        return {**run, "status": result["status"], "result": result, "artifact": artifact}


def _read_command(executable: str | None, args: list[str], cwd: Path | None) -> dict[str, Any]:
    if not executable:
        return {"available": False, "returncode": None, "output": ""}
    try:
        completed = subprocess.run(
            [executable, *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "returncode": None, "output": ""}
    output = _output_text(completed.stdout).strip() or _output_text(completed.stderr).strip()
    return {"available": completed.returncode == 0, "returncode": completed.returncode, "output": output}


def capture_git_snapshot(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    if not root.is_dir():
        return {"available": False, "commit": None, "branch": None, "dirty": None, "tracked_change_count": 0}
    git_executable = shutil.which("git")
    commit = _read_command(git_executable, ["rev-parse", "HEAD"], root)
    branch = _read_command(git_executable, ["symbolic-ref", "--short", "HEAD"], root)
    status = _read_command(git_executable, ["status", "--short", "--untracked-files=no"], root)
    return {
        "available": commit["available"],
        "commit": commit["output"].splitlines()[0] if commit["available"] and commit["output"] else None,
        "branch": branch["output"].splitlines()[0] if branch["available"] and branch["output"] else None,
        "dirty": bool(status["output"]) if status["available"] else None,
        "tracked_change_count": len(status["output"].splitlines()) if status["available"] and status["output"] else 0,
    }


def capture_baseline(root: Path | str) -> dict[str, Any]:
    root = Path(root).resolve()
    cwd = root if root.is_dir() else None
    tools: dict[str, Any] = {}
    for name, args in (
        ("python", ["--version"]),
        ("uv", ["--version"]),
        ("rustc", ["--version"]),
        ("cargo", ["--version"]),
    ):
        executable = shutil.which(name)
        result = _read_command(executable, args, cwd)
        tools[name] = {
            "available": result["available"],
            "version": result["output"].splitlines()[0] if result["output"] else None,
        }

    git = capture_git_snapshot(root)
    return {
        "captured_at": _now(),
        "root": str(root),
        "platform": {
            "system": platform_module.system(),
            "release": platform_module.release(),
            "machine": platform_module.machine(),
            "python": platform_module.python_version(),
        },
        "tools": tools,
        "git": git,
    }


def preflight(root: Path | str) -> dict[str, Any]:
    root = Path(root)
    tools = ["git", "python", "uv", "cargo"]
    checks = [
        {
            "name": tool,
            "ok": bool(shutil.which(tool)),
            "value": shutil.which(tool) or "missing",
            "mutates": False,
            "required": True,
        }
        for tool in tools
    ]
    checks.append(
        {
            "name": "project_root",
            "ok": root.exists(),
            "value": str(root),
            "mutates": False,
            "required": True,
        }
    )
    checks.append(
        {
            "name": "ssh",
            "ok": bool(shutil.which("ssh")),
            "value": shutil.which("ssh") or "missing",
            "mutates": False,
            "required": False,
        }
    )
    checks.extend(
        [
            {
                "name": "platform",
                "ok": True,
                "value": f"{platform_module.system()} {platform_module.release()}",
                "mutates": False,
                "required": True,
            },
            {
                "name": "architecture",
                "ok": True,
                "value": platform_module.machine(),
                "mutates": False,
                "required": True,
            },
            {
                "name": "disk_free_bytes",
                "ok": root.exists(),
                "value": shutil.disk_usage(root).free if root.exists() else None,
                "mutates": False,
                "required": True,
            },
            {
                "name": "docker",
                "ok": bool(shutil.which("docker")),
                "value": shutil.which("docker") or "missing",
                "mutates": False,
                "required": False,
            },
            {
                "name": "gpu",
                "ok": bool(shutil.which("nvidia-smi")),
                "value": shutil.which("nvidia-smi") or "not detected",
                "mutates": False,
                "required": False,
            },
        ]
    )
    required_ok = all(item["ok"] for item in checks if item["required"])
    return {
        "status": "passed" if required_ok else "failed",
        "checks": checks,
        "baseline": capture_baseline(root),
    }
