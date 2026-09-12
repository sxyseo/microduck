#!/usr/bin/env python3
"""Summarise HL-2915 bring-up evidence without touching hardware.

The command only reads JSON/text artifacts already saved by the other tools. Missing evidence is
reported as ``pending``; ``--strict`` returns non-zero until every requested gate passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from validate_bam_log import validate as validate_bam
from hat_smoke import validate as validate_hat_smoke
from media_smoke import validate as validate_media_smoke


def _load_json(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None:
        return None, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"无法读取 {path}: {exc}"
    if not isinstance(value, dict):
        return None, f"{path} 不是 JSON 对象"
    return value, None


def _gate(name: str, status: str, evidence: str, next_action: str) -> dict[str, str]:
    return {"gate": name, "status": status, "evidence": evidence, "next": next_action}


def _valid_identity(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    digest = value.get("sha256")
    size = value.get("size_bytes")
    return (
        isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size > 0
    )


def _servo_gate(
    servo_a: dict[str, Any] | None,
    servo_a_error: str | None,
    servo_b: dict[str, Any] | None,
    servo_b_error: str | None,
    confirmed: bool,
) -> dict[str, str]:
    if servo_a_error or servo_b_error:
        return _gate(
            "S0/S1/S2 servo IDs",
            "failed",
            servo_a_error or servo_b_error or "无法读取舵机验证结果",
            "重新生成两只舵机的探针验证 JSON",
        )
    reports = [report for report in (servo_a, servo_b) if report is not None]
    if any(report.get("status") != "passed" for report in reports):
        return _gate(
            "S0/S1/S2 servo IDs",
            "failed",
            f"验证状态={[report.get('status') for report in reports]}",
            "检查原始探针日志、电源、线序和舵机 ID",
        )
    if len(reports) == 1:
        return _gate(
            "S0/S1/S2 servo IDs",
            "pending",
            "只有一只舵机的通过记录",
            "补齐另一只舵机的探针验证 JSON",
        )
    logs_passed = len(reports) == 2
    if logs_passed and confirmed:
        return _gate(
            "S0/S1/S2 servo IDs",
            "passed",
            "ID=1/2 日志通过，操作者已确认电源、线序和现场照片",
            "继续 S3 台架观察",
        )
    if logs_passed:
        return _gate(
            "S0/S1/S2 servo IDs",
            "manual",
            "ID=1/2 日志通过；仍需人工确认电源、线序和现场照片",
            "核对现场记录后增加 --confirm-ids",
        )
    return _gate(
        "S0/S1/S2 servo IDs",
        "pending",
        "人工确认不能替代两份舵机探针验证 JSON" if confirmed else "没有两只舵机的探针验证 JSON",
        "先生成 servo-a-id1-validation.json 和 servo-b-id2-validation.json",
    )


def _board_gate(report: dict[str, Any] | None, error: str | None) -> tuple[dict[str, str], dict[str, str]]:
    if error:
        board = _gate("S4 Radxa", "failed", error, "重新生成 board-readonly-report.json")
        media = _gate("S6 camera/HAT media", "failed", error, "重新生成 board-readonly-report.json")
        return board, media
    if report is None:
        command = "python tools/microduck_learning/board_readonly_report.py --json-out artifacts/board-readonly-report.json"
        board = _gate("S4 Radxa", "pending", "没有板卡报告", command)
        media = _gate("S6 camera/HAT media", "pending", "没有板卡报告", command)
        return board, media
    checks = {item.get("name"): item for item in report.get("checks", []) if isinstance(item, dict)}
    architecture_ok = checks.get("architecture", {}).get("status") == "pass"
    serial_ok = checks.get("serial", {}).get("status") == "pass"
    board_ready = architecture_ok and serial_ok
    board = _gate(
        "S4 Radxa",
        "passed" if board_ready else "pending",
        "aarch64 且串口节点存在" if board_ready else "必须同时满足 aarch64 和 ttyS2/ttyUSB0/ttyACM0",
        "在 Radxa 上重跑只读报告；确认架构和串口" if not board_ready else "继续 S5 IMU/混合总线",
    )
    media_names = ("hat_i2c", "hat_audio", "camera", "camera_mainpath", "mpp", "rga", "gstreamer")
    media_ok = all(checks.get(name, {}).get("status") == "pass" for name in media_names)
    media = _gate(
        "S6 camera/HAT media",
        "passed" if media_ok else "pending",
        "HAT I2C/音频、CSI ISP、MPP、RGA 和 GStreamer 均通过" if media_ok else "需同时通过 HAT I2C/音频、camera/mainpath、MPP、RGA 和 GStreamer",
        "执行 setup-gstreamer.sh --check，并先修 overlay/vendor kernel" if not media_ok else "继续 S7 模型合同",
    )
    return board, media


def _media_gate(
    inventory_gate: dict[str, str],
    smoke: dict[str, Any] | None,
    smoke_error: str | None,
    hat: dict[str, Any] | None,
    hat_error: str | None,
) -> dict[str, str]:
    if inventory_gate["status"] == "failed":
        return inventory_gate
    if smoke_error or hat_error:
        return _gate(
            "S6 camera/HAT media",
            "failed",
            smoke_error or hat_error or "无法读取功能 smoke",
            "重新生成 media-smoke.json 或 hat-smoke.json",
        )
    if smoke is not None:
        smoke_result = validate_media_smoke(smoke)
        if smoke_result["status"] != "passed":
            return _gate(
                "S6 camera/HAT media",
                "failed",
                "; ".join(smoke_result["errors"]),
                "检查 CSI overlay、rkisp、MPP 权限、GStreamer 插件和摄像头排线",
            )
    if hat is not None:
        hat_result = validate_hat_smoke(hat)
        if hat_result["status"] != "passed":
            return _gate(
                "S6 camera/HAT media",
                "failed",
                "; ".join(hat_result["errors"]),
                "检查官方 HAT、I²C 0x18、AIC3104 录放音和人工听音确认",
            )

    missing: list[str] = []
    next_steps: list[str] = []
    if inventory_gate["status"] != "passed":
        missing.append(inventory_gate["evidence"])
        next_steps.append(inventory_gate["next"])
    if hat is None:
        missing.append("没有 HAT I²C/录放音功能 smoke JSON")
        next_steps.append(
            "在 Radxa 执行 python tools/microduck_learning/hat_smoke.py --run --confirm-official-hat --confirm-audible --json-out artifacts/hat-smoke.json"
        )
    if smoke is None:
        missing.append("没有实际摄像头采集/编码 smoke JSON")
        next_steps.append(
            "在 Radxa 执行 python tools/microduck_learning/media_smoke.py --run --json-out artifacts/media-smoke.json"
        )
    if missing:
        return _gate(
            "S6 camera/HAT media",
            "pending",
            "；".join(missing),
            "；".join(next_steps),
        )
    return _gate(
        "S6 camera/HAT media",
        "passed",
        "板卡节点、HAT I²C/录放音、实际摄像头采集、硬件 H.264 编解码和 WebRTC 均通过",
        "继续 S7 模型合同",
    )


def _mixed_gate(path: Path | None) -> dict[str, str]:
    if path is None:
        return _gate(
            "S5 IMU/mixed",
            "pending",
            "没有混合协议日志",
            "cargo +1.89.0 run -p duck-control --bin hl2915_mixed_probe -- COMx 1 2 --watch-seconds 60",
        )
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _gate("S5 IMU/mixed", "failed", str(exc), "重新保存混合协议日志")
    line = next((line for line in text.splitlines() if "watch complete:" in line), "")
    if not line:
        return _gate("S5 IMU/mixed", "failed", "日志没有 watch complete 行", "让探针完整运行后重新保存日志")
    fields = dict(re.findall(r"([a-z_]+)=([^, ]+)", line))
    required = (
        "samples",
        "errors",
        "stale_imu",
        "max_stale_run",
        "imu_ready",
        "status_faults",
        "voltage_faults",
        "temperature_faults",
        "current_faults",
    )
    if any(key not in fields for key in required):
        return _gate("S5 IMU/mixed", "failed", line, "使用当前版本 hl2915_mixed_probe 重新记录")
    try:
        samples = int(fields["samples"])
        stale_imu = int(fields["stale_imu"])
        max_stale_run = int(fields["max_stale_run"])
    except ValueError:
        return _gate("S5 IMU/mixed", "failed", line, "样本计数格式错误；使用当前探针重新记录")
    imu_fresh = (
        samples >= 25
        and 0 <= max_stale_run <= stale_imu < samples
        and max_stale_run < 25
    )
    fault_keys = ("status_faults", "voltage_faults", "temperature_faults", "current_faults")
    passed = (
        fields["errors"] == "0"
        and fields["imu_ready"] == "true"
        and imu_fresh
        and all(fields[key] == "0" for key in fault_keys)
    )
    if not imu_fresh:
        next_action = "IMU 样本不足或数据冻结；检查 ID=200 固件刷新、供电和半双工总线"
    elif not passed:
        next_action = "协议切换或 IMU/舵机故障，先断电检查线束、电压和 ID"
    else:
        next_action = "进入 15 只舵机和机械标定"
    return _gate(
        "S5 IMU/mixed",
        "passed" if passed else "failed",
        line,
        next_action,
    )


def _bench_gate(summary: dict[str, Any] | None, error: str | None) -> dict[str, str]:
    if error:
        return _gate("S3 bench CSV", "failed", error, "重新生成 bench summary")
    if summary is None:
        return _gate(
            "S3 bench CSV",
            "pending",
            "没有 CSV 摘要",
            "cargo +1.89.0 run -p duck-control --bin hl2915_record -- COMx 1 2 --seconds 600 --output artifacts/hl2915-bench.csv --hz 50",
        )
    passed = summary.get("status") == "passed" and len(summary.get("ids", [])) >= 2
    return _gate(
        "S3 bench CSV",
        "passed" if passed else "failed",
        f"status={summary.get('status')}, ids={summary.get('ids')}",
        "检查通信错误、故障状态和采样频率" if not passed else "保存原始 CSV，继续 IMU/机械测试",
    )


def _bam_gate(path: Path | None) -> dict[str, str]:
    if path is None:
        return _gate("BAM data", "pending", "没有 BAM 原始 JSON", "先完成 S3，再用 hl2915_bam_record 做受限摆锤采样")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(payload, dict)
            and "entries" not in payload
            and ("actuator" in payload or "model" in payload)
        ):
            return _gate(
                "BAM data",
                "failed",
                "传入的是拟合模型 JSON，不是原始摆锤日志",
                "把 --bam-log 指向 artifacts/bam/raw/*.json；拟合模型单独传给 --bam-model-contract",
            )
        result = validate_bam(payload)
    except (OSError, json.JSONDecodeError) as exc:
        return _gate("BAM data", "failed", str(exc), "重新保存 BAM JSON")
    passed = result.get("status") == "passed"
    return _gate(
        "BAM data",
        "passed" if passed else "failed",
        f"samples={result.get('samples')}, errors={len(result.get('errors', []))}",
        "修复温度/电流/时间戳/状态错误" if not passed else "运行 bam.process 与 bam.fit",
    )


def _bam_model_gate(contract: dict[str, Any] | None, error: str | None) -> dict[str, str]:
    if error:
        return _gate("BAM model", "failed", error, "重新运行 python tools/microduck_learning/check_bam_model.py")
    if contract is None:
        return _gate("BAM model", "pending", "没有拟合后的 HL-2915 参数合同", "先运行 python tools/microduck_learning/check_bam_model.py")
    passed = (
        contract.get("status") == "passed"
        and contract.get("actuator") == "hl2915"
        and contract.get("model") == "m6"
        and isinstance(contract.get("adapter_metadata"), dict)
        and contract.get("data_provenance") == "measured"
        and _valid_identity(contract)
    )
    return _gate(
        "BAM model",
        "passed" if passed else "failed",
        f"actuator={contract.get('actuator')}, model={contract.get('model')}, provenance={contract.get('data_provenance')}",
        "确认参数来自真实 HL-2915 摆锤数据（synthetic 只能跑 smoke）" if not passed else "继续 ONNX 导出和 CPU 合同检查",
    )


def _onnx_gate(contract: dict[str, Any] | None, error: str | None) -> dict[str, str]:
    if error:
        return _gate("S7 ONNX", "failed", error, "重新运行 python tools/microduck_learning/check_onnx_contract.py")
    if contract is None:
        return _gate(
            "S7 ONNX",
            "pending",
            "没有 ONNX 合同报告",
            "导出 ONNX 后运行 python tools/microduck_learning/check_onnx_contract.py",
        )
    digest = contract.get("sha256")
    size_bytes = contract.get("size_bytes")
    identity_ok = _valid_identity(contract)
    input_spec = contract.get("input")
    output_spec = contract.get("output")
    passed = (
        isinstance(input_spec, dict)
        and input_spec.get("shape") == [1, 61]
        and isinstance(output_spec, dict)
        and output_spec.get("shape") == [1, 14]
        and contract.get("finite_zero_observation") is True
        and identity_ok
    )
    evidence = f"input={input_spec.get('shape') if isinstance(input_spec, dict) else None}, output={output_spec.get('shape') if isinstance(output_spec, dict) else None}"
    if identity_ok:
        evidence += f", SHA-256={digest[:12]}…, bytes={size_bytes}"
    else:
        evidence += ", 缺少有效 SHA-256/size_bytes"
    return _gate(
        "S7 ONNX",
        "passed" if passed else "failed",
        evidence,
        "重新运行合同检查；修复模型导出/维度或文件身份" if not passed else "按 SHA-256 校验后才允许拷到 Radxa",
    )


def _training_lineage_gate(
    lineage: dict[str, Any] | None,
    error: str | None,
    bam_contract: dict[str, Any] | None,
    onnx_contract: dict[str, Any] | None,
) -> dict[str, str]:
    command = "python tools/microduck_learning/check_training_lineage.py --help"
    if error:
        return _gate("S7 training lineage", "failed", error, command)
    if lineage is None:
        return _gate("S7 training lineage", "pending", "没有训练血缘报告", command)
    if lineage.get("status") != "passed":
        errors = lineage.get("errors")
        evidence = "; ".join(map(str, errors)) if isinstance(errors, list) else "训练血缘校验未通过"
        return _gate("S7 training lineage", "failed", evidence, command)

    repo = lineage.get("training_repo")
    bam = lineage.get("bam_model")
    onnx = lineage.get("onnx")
    purpose = lineage.get("purpose")
    valid = (
        lineage.get("schema_version") == 1
        and purpose in {"smoke", "candidate"}
        and isinstance(repo, dict)
        and repo.get("clean") is True
        and isinstance(repo.get("commit"), str)
        and re.fullmatch(r"[0-9a-f]{40}", repo["commit"]) is not None
        and isinstance(bam, dict)
        and bam.get("actuator") == "hl2915"
        and bam.get("model") == "m6"
        and bam.get("data_provenance") in {"measured", "synthetic"}
        and _valid_identity(bam)
        and _valid_identity(onnx)
    )
    if not valid:
        return _gate("S7 training lineage", "failed", "训练血缘字段、提交或文件身份无效", command)
    if bam_contract is not None and bam_contract.get("sha256") != bam.get("sha256"):
        return _gate("S7 training lineage", "failed", "BAM 合同与训练血缘不是同一个文件", command)
    if onnx_contract is not None and onnx_contract.get("sha256") != onnx.get("sha256"):
        return _gate("S7 training lineage", "failed", "ONNX 合同与训练血缘不是同一个文件", command)
    if purpose != "candidate" or bam.get("data_provenance") != "measured":
        return _gate(
            "S7 training lineage",
            "pending",
            f"purpose={purpose}, provenance={bam.get('data_provenance')}；只能证明 smoke，不能上真机",
            "用真实 BAM 数据完成正式训练后生成 purpose=candidate 报告",
        )
    return _gate(
        "S7 training lineage",
        "passed",
        f"candidate，measured BAM，clean commit={repo['commit'][:12]}",
        "先做仿真回放，再进入吊装真机测试",
    )


def build_status(args: argparse.Namespace) -> dict[str, Any]:
    board, board_error = _load_json(args.board_report)
    summary, summary_error = _load_json(args.bench_summary)
    servo_a, servo_a_error = _load_json(getattr(args, "servo_a_validation", None))
    servo_b, servo_b_error = _load_json(getattr(args, "servo_b_validation", None))
    media_smoke, media_smoke_error = _load_json(getattr(args, "media_smoke", None))
    hat_smoke, hat_smoke_error = _load_json(getattr(args, "hat_smoke", None))
    bam_model, bam_model_error = _load_json(getattr(args, "bam_model_contract", None))
    contract, contract_error = _load_json(args.onnx_contract)
    lineage, lineage_error = _load_json(getattr(args, "training_lineage", None))
    board_gate, media_inventory_gate = _board_gate(board, board_error)
    media_gate = _media_gate(
        media_inventory_gate,
        media_smoke,
        media_smoke_error,
        hat_smoke,
        hat_smoke_error,
    )
    ids_confirmed = bool(getattr(args, "confirm_ids", False))
    robot_confirmed = bool(getattr(args, "confirm_s8", False))
    gates = [
        _servo_gate(servo_a, servo_a_error, servo_b, servo_b_error, ids_confirmed),
        _bench_gate(summary, summary_error),
        board_gate,
        _mixed_gate(args.mixed_log),
        media_gate,
        _bam_gate(args.bam_log),
        _bam_model_gate(bam_model, bam_model_error),
        _onnx_gate(contract, contract_error),
        _training_lineage_gate(lineage, lineage_error, bam_model, contract),
        _gate(
            "S8 real robot",
            "passed" if robot_confirmed else "manual",
            "操作者已确认 15 只舵机、结构、吊装和策略测试记录" if robot_confirmed else "15 只舵机、结构、吊装和策略尚无现场证据",
            "保留最终现场记录" if robot_confirmed else "逐级执行 S8 测试金字塔",
        ),
    ]
    failed = any(item["status"] == "failed" for item in gates)
    pending = any(item["status"] in {"pending", "manual"} for item in gates)
    return {"schema_version": 1, "status": "failed" if failed else "pending" if pending else "ready", "gates": gates}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-report", type=Path)
    parser.add_argument("--bench-summary", type=Path)
    parser.add_argument("--servo-a-validation", type=Path)
    parser.add_argument("--servo-b-validation", type=Path)
    parser.add_argument("--media-smoke", type=Path)
    parser.add_argument("--hat-smoke", type=Path)
    parser.add_argument("--mixed-log", type=Path)
    parser.add_argument("--bam-log", type=Path)
    parser.add_argument("--bam-model-contract", type=Path)
    parser.add_argument("--onnx-contract", type=Path)
    parser.add_argument("--training-lineage", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--confirm-ids", action="store_true", help="操作者已人工核对 S0/S1/S2 记录")
    parser.add_argument("--confirm-s8", action="store_true", help="操作者已人工核对 S8 现场记录")
    parser.add_argument("--strict", action="store_true", help="缺证据或失败时返回 1")
    args = parser.parse_args()
    report = build_status(args)
    for gate in report["gates"]:
        print(f"{gate['status']:>7}  {gate['gate']:<20} {gate['evidence']}")
        print(f"         下一步：{gate['next']}")
    print(f"overall: {report['status']}")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"json: {args.json_out}")
    return 1 if args.strict and report["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
