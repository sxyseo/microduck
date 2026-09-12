#!/usr/bin/env python3
"""Screen a cheaper servo from a datasheet before buying a batch.

This is a document-level gate only.  It never claims that a candidate passed power, bus,
mechanical, or dynamics testing; every candidate still needs a one-sample bench test.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "model",
    "voltage_min_v",
    "voltage_max_v",
    "protocol",
    "signal",
    "position_counts",
    "position_range_deg",
    "spline_teeth",
    "torque_kgcm",
    "datasheet_confirmed",
)
BASELINE_TORQUE_KGCM = 14.2


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("candidate JSON root must be an object")

    missing = [name for name in REQUIRED_FIELDS if name not in candidate]
    if missing:
        return {
            "status": "insufficient_data",
            "model": candidate.get("model"),
            "missing_fields": missing,
            "blockers": ["missing_datasheet_fields"],
            "hardware_passed": False,
            "screening_only": True,
            "next_steps": ["补齐规格书字段，再对 1 只样品做 bench-test"],
        }

    numeric_fields = (
        "voltage_min_v",
        "voltage_max_v",
        "position_counts",
        "position_range_deg",
        "spline_teeth",
        "torque_kgcm",
    )
    invalid = [name for name in numeric_fields if not _finite_number(candidate[name])]
    invalid.extend(
        name
        for name in ("model", "protocol", "signal")
        if not isinstance(candidate[name], str) or not candidate[name].strip()
    )
    if not invalid:
        constraints = {
            "voltage_min_v": candidate["voltage_min_v"] > 0,
            "voltage_max_v": candidate["voltage_max_v"] > 0,
            "position_counts": candidate["position_counts"] > 0,
            "position_range_deg": candidate["position_range_deg"] > 0,
            "spline_teeth": candidate["spline_teeth"] > 0,
            "torque_kgcm": candidate["torque_kgcm"] > 0,
        }
        invalid.extend(name for name, valid in constraints.items() if not valid)
        if candidate["voltage_min_v"] > candidate["voltage_max_v"]:
            invalid.extend(("voltage_min_v", "voltage_max_v", "voltage_range"))
    invalid = list(dict.fromkeys(invalid))
    if invalid or not isinstance(candidate["datasheet_confirmed"], bool):
        return {
            "status": "insufficient_data",
            "model": candidate.get("model"),
            "missing_fields": invalid + (["datasheet_confirmed"] if not isinstance(candidate["datasheet_confirmed"], bool) else []),
            "blockers": ["invalid_datasheet_value"],
            "hardware_passed": False,
            "screening_only": True,
            "next_steps": ["修正规格书字段类型和值，再对 1 只样品做 bench-test"],
        }

    if not candidate["datasheet_confirmed"]:
        return {
            "status": "insufficient_data",
            "model": candidate["model"],
            "missing_fields": [],
            "blockers": ["datasheet_unconfirmed"],
            "hardware_passed": False,
            "screening_only": True,
            "next_steps": ["先取得该型号的官方协议手册、内存表和线序"],
        }

    voltage_ok = candidate["voltage_min_v"] <= 12.0 <= candidate["voltage_max_v"]
    bus_ok = candidate["protocol"] == "feetech_v1" and candidate["signal"] == "ttl_half_duplex"
    position_ok = candidate["position_counts"] == 4096 and math.isclose(
        candidate["position_range_deg"], 360.0, abs_tol=0.1
    )
    spline_ok = candidate["spline_teeth"] == 25
    low_torque = candidate["torque_kgcm"] < BASELINE_TORQUE_KGCM * 0.5

    blockers: list[str] = []
    if not voltage_ok:
        blockers.append("separate_power")
    if not bus_ok:
        blockers.append("new_driver")
    if not position_ok:
        blockers.append("new_mapping")
    if not spline_ok:
        blockers.append("new_mechanical_adapter")
    if low_torque:
        blockers.append("low_load_only")

    if not bus_ok:
        status = "new_bus_driver"
    elif not voltage_ok and low_torque:
        status = "low_load_power_variant"
    elif not voltage_ok:
        status = "new_power_variant"
    elif low_torque:
        status = "low_load_profile"
    else:
        status = "profile_candidate"

    next_steps = ["bench-test one sample before purchase"]
    if not voltage_ok:
        next_steps.append("单独设计该型号电源树，禁止直接接 HL-2915 的 12V 总线")
    if not bus_ok:
        next_steps.append("实现并验证新的总线收发器和协议驱动")
    if not position_ok:
        next_steps.append("重新确认位置单位、寄存器地址和动作映射")
    if not spline_ok:
        next_steps.append("重新测量输出花键、安装孔和打印适配件")
    if low_torque:
        next_steps.append("只考虑嘴部/头部等低负载关节，不用于腿部")
    next_steps.extend(["记录 10 分钟 CSV", "测量阶跃、温升、电流和回差", "修改 MJCF/BAM 后重新训练"])

    return {
        "status": status,
        "model": candidate["model"],
        "missing_fields": [],
        "blockers": blockers,
        "hardware_passed": False,
        "screening_only": True,
        "comparison": {
            "voltage_includes_12v": voltage_ok,
            "hl2915_bus_shape": bus_ok,
            "hl2915_position_shape": position_ok,
            "hl2915_spline_shape": spline_ok,
            "low_load_torque": low_torque,
        },
        "next_steps": next_steps,
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        f"candidate: {report.get('model')}",
        f"status: {report['status']}",
        f"hardware_passed: {report['hardware_passed']}",
    ]
    if report.get("blockers"):
        lines.append(f"blockers: {', '.join(report['blockers'])}")
    for step in report.get("next_steps", []):
        lines.append(f"next: {step}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, help="candidate datasheet JSON")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.json.read_text(encoding="utf-8"))
        report = evaluate_candidate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"candidate screening failed: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(render_text(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
