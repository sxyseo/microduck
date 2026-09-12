#!/usr/bin/env python3
"""Validate saved read-only ``hl2915_probe`` output without touching hardware."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


_RESPONSE = re.compile(r"响应=\[([^\]]*)\]")
_STATE = re.compile(
    r"ID\s+(?P<id>\d+):.*?status=(?P<status>\d+|n/a).*?"
    r"current=(?P<current>[0-9]+(?:\.[0-9]+)?mA|n/a),\s+"
    r"voltage=(?P<voltage>[0-9]+(?:\.[0-9]+)?)V,\s+"
    r"temp=(?P<temperature>\d+)°C"
)


def _ids(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip()]


def _read_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def validate_text(text: str, expected_ids: list[int]) -> dict[str, Any]:
    failures: dict[str, str] = {}
    missing: list[int] = []
    response_match = _RESPONSE.search(text)
    responded_ids = _ids(response_match.group(1)) if response_match else []
    if responded_ids != expected_ids:
        failures["response_ids"] = f"expected={expected_ids}, got={responded_ids}"

    states: dict[int, dict[str, Any]] = {}
    for match in _STATE.finditer(text):
        servo_id = int(match.group("id"))
        current = match.group("current")
        states[servo_id] = {
            "status": None if match.group("status") == "n/a" else int(match.group("status")),
            "current_ma": None if current == "n/a" else float(current.removesuffix("mA")),
            "voltage_v": float(match.group("voltage")),
            "temperature_c": int(match.group("temperature")),
        }

    for servo_id in expected_ids:
        state = states.get(servo_id)
        if state is None:
            missing.append(servo_id)
            continue
        if state["status"] not in (None, 0):
            failures["status"] = f"ID={servo_id} status={state['status']}"
        if not 9.0 <= state["voltage_v"] <= 14.0:
            failures["voltage"] = f"ID={servo_id} voltage={state['voltage_v']}V"
        if state["temperature_c"] >= 55:
            failures["temperature"] = f"ID={servo_id} temperature={state['temperature_c']}C"
        if state["current_ma"] is not None and state["current_ma"] >= 1400.0:
            failures["current"] = f"ID={servo_id} current={state['current_ma']}mA"

    status = "failed" if failures else "insufficient_data" if missing or not response_match else "passed"
    return {
        "status": status,
        "expected_ids": expected_ids,
        "responded_ids": responded_ids,
        "states": states,
        "missing_ids": missing,
        "failures": failures,
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="saved stdout from hl2915_probe")
    parser.add_argument("--ids", nargs="+", type=int, required=True, help="expected servo IDs")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        result = validate_text(_read_log(args.log), args.ids)
    except OSError as exc:
        print(f"probe log validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
