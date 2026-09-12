#!/usr/bin/env python3
"""Validate one HL-2915 BAM JSON log before sending it to bam.process."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


REQUIRED_META = {"mass", "arm_mass", "length", "kp", "vin", "motor", "trajectory", "entries"}
REQUIRED_ENTRY = {
    "timestamp",
    "goal_position",
    "torque_enable",
    "position",
    "speed",
    "input_volts",
    "temp",
    "current_ma",
    "status",
    "moving",
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(payload: dict[str, Any], *, expected_motor: str = "hl2915") -> dict[str, Any]:
    errors: list[str] = []
    missing = REQUIRED_META - payload.keys()
    errors.extend(f"missing metadata: {key}" for key in sorted(missing))
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) < 2:
        errors.append("entries must contain at least two samples")
        entries = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry {index}: not an object")
            continue
        errors.extend(
            f"entry {index}: missing {key}" for key in sorted(REQUIRED_ENTRY - entry.keys())
        )
        for key in REQUIRED_ENTRY & entry.keys():
            if key != "torque_enable" and not _finite(entry[key]):
                errors.append(f"entry {index}: {key} is not finite")
        if entry.get("status", 0) != 0:
            errors.append(f"entry {index}: non-zero status {entry.get('status')}")
        if entry.get("temp", 0) >= 55:
            errors.append(f"entry {index}: temperature reached the 55 C stop threshold")
        if entry.get("current_ma", 0) >= 1400:
            errors.append(f"entry {index}: current reached the 1400 mA stop threshold")
        if entry.get("torque_enable") is not True:
            errors.append(f"entry {index}: torque_enable is not true")
        previous = entries[index - 1]
        if (
            index
            and isinstance(previous, dict)
            and _finite(entry.get("timestamp"))
            and _finite(previous.get("timestamp"))
        ):
            if entry["timestamp"] <= previous["timestamp"]:
                errors.append(f"entry {index}: timestamp is not increasing")

    for key in ("mass", "length", "vin"):
        if not _finite(payload.get(key)) or payload[key] <= 0:
            errors.append(f"metadata {key} must be positive and finite")
    if payload.get("motor") != expected_motor:
        errors.append(f"metadata motor must be {expected_motor!r}")
    if not _finite(payload.get("arm_mass")) or payload["arm_mass"] < 0:
        errors.append("metadata arm_mass must be non-negative and finite")
    if not isinstance(payload.get("kp"), int) or not 1 <= payload["kp"] <= 255:
        errors.append("metadata kp must be an integer in 1..255")
    result = {
        "status": "passed" if not errors else "failed",
        "samples": len(entries),
        "duration_s": round(entries[-1]["timestamp"], 3) if entries and _finite(entries[-1].get("timestamp")) else None,
        "motor": payload.get("motor"),
        "trajectory": payload.get("trajectory"),
        "errors": errors,
    }
    return result


def self_test() -> None:
    payload = {
        "mass": 0.05,
        "arm_mass": 0.01,
        "length": 0.1,
        "kp": 16,
        "vin": 12.0,
        "motor": "hl2915",
        "trajectory": "scaled_sin_time_square",
        "entries": [
            {
                "timestamp": 0.0,
                "goal_position": 0.0,
                "torque_enable": True,
                "position": 0.0,
                "speed": 0.0,
                "input_volts": 12.0,
                "temp": 30,
                "current_ma": 100.0,
                "status": 0,
                "moving": 0,
            },
            {
                "timestamp": 0.01,
                "goal_position": 0.01,
                "torque_enable": True,
                "position": 0.001,
                "speed": 0.1,
                "input_volts": 12.0,
                "temp": 30,
                "current_ma": 100.0,
                "status": 0,
                "moving": 1,
            },
        ],
    }
    assert validate(payload)["status"] == "passed"
    payload["motor"] = "xl330"
    assert validate(payload)["status"] == "failed"
    payload["motor"] = "hl2915"
    payload["entries"][1]["status"] = 4
    assert validate(payload)["status"] == "failed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", type=Path)
    parser.add_argument("--motor", default="hl2915", help="expected BAM motor metadata (default: hl2915)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("self-test passed")
        return 0
    if args.json is None:
        parser.error("JSON path is required unless --self-test is used")
    with args.json.open(encoding="utf-8") as handle:
        result = validate(json.load(handle), expected_motor=args.motor)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
