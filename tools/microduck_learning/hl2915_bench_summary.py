#!/usr/bin/env python3
"""Validate and summarize a read-only HL-2915 CSV recording."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Iterable


REQUIRED = {
    "unix_ms",
    "elapsed_ms",
    "sample",
    "id",
    "position_raw",
    "speed_raw",
    "load_raw",
    "status",
    "moving",
    "current_raw",
    "current_ma",
    "voltage_v",
    "temperature_c",
}


def summarize(rows: Iterable[dict[str, str]], expected_hz: float = 50.0) -> dict:
    by_id: dict[int, list[dict[str, float]]] = defaultdict(list)
    previous_elapsed = None
    malformed = []
    faults = []
    total = 0

    for line, row in enumerate(rows, start=2):
        if not REQUIRED.issubset(row):
            malformed.append(f"line {line}: missing required column")
            continue
        try:
            parsed = {
                "unix_ms": float(row["unix_ms"]),
                "elapsed_ms": float(row["elapsed_ms"]),
                "sample": float(row["sample"]),
                "id": int(row["id"]),
                "position_raw": float(row["position_raw"]),
                "speed_raw": float(row["speed_raw"]),
                "load_raw": float(row["load_raw"]),
                "status": float(row["status"]),
                "moving": float(row["moving"]),
                "current_raw": float(row["current_raw"]),
                "current_ma": float(row["current_ma"]),
                "voltage_v": float(row["voltage_v"]),
                "temperature_c": float(row["temperature_c"]),
            }
        except (TypeError, ValueError) as exc:
            malformed.append(f"line {line}: {exc}")
            continue
        if not all(math.isfinite(value) for key, value in parsed.items() if key != "id"):
            malformed.append(f"line {line}: non-finite numeric value")
            continue
        if previous_elapsed is not None and parsed["elapsed_ms"] < previous_elapsed:
            malformed.append(f"line {line}: elapsed_ms moved backwards")
        previous_elapsed = parsed["elapsed_ms"]
        if not 0 <= parsed["position_raw"] <= 4095:
            malformed.append(f"line {line}: position_raw outside 0..4095")
        by_id[parsed["id"]].append(parsed)
        total += 1

    duration_s = (previous_elapsed or 0.0) / 1000.0
    summaries = {}
    warnings = []
    for servo_id, values in sorted(by_id.items()):
        samples = len(values)
        hz = (samples - 1) / duration_s if duration_s > 0 and samples > 1 else 0.0
        summaries[str(servo_id)] = {
            "rows": samples,
            "estimated_hz": round(hz, 3),
            "position_raw": [
                min(item["position_raw"] for item in values),
                max(item["position_raw"] for item in values),
            ],
            # Feetech magnetic-servo feedback uses bit 15 for speed direction and bit 10 for
            # load direction. Keep the CSV raw, but report magnitudes without counting flags.
            "speed_raw_magnitude_max": max(int(item["speed_raw"]) & 0x7FFF for item in values),
            "load_raw_magnitude_max": max(int(item["load_raw"]) & 0x03FF for item in values),
            "current_ma_max": max(item["current_ma"] for item in values),
            "voltage_v": [
                min(item["voltage_v"] for item in values),
                max(item["voltage_v"] for item in values),
            ],
            "temperature_c_max": max(item["temperature_c"] for item in values),
            "status_values": sorted({int(item["status"]) for item in values}),
            "moving_samples": sum(1 for item in values if item["moving"] != 0),
        }
        if any(int(item["status"]) != 0 for item in values):
            faults.append(
                f"ID {servo_id}: status contains non-zero fault values "
                f"{summaries[str(servo_id)]['status_values']}"
            )
        if expected_hz > 0 and hz < expected_hz * 0.8:
            warnings.append(f"ID {servo_id}: estimated sampling rate is only {hz:.2f} Hz")

    if not by_id:
        malformed.append("recording has no valid rows")
    return {
        "status": "passed" if not malformed and not faults else "failed",
        "rows": total,
        "ids": sorted(by_id),
        "duration_s": round(duration_s, 3),
        "expected_hz": expected_hz,
        "servos": summaries,
        "warnings": warnings,
        "faults": faults,
        "errors": malformed,
    }


def self_test() -> None:
    data = io.StringIO(
        "unix_ms,elapsed_ms,sample,id,position_raw,speed_raw,load_raw,status,moving,current_raw,current_ma,voltage_v,temperature_c\n"
        "1000,0,1,1,2048,32768,1027,0,0,10,65,12.0,30\n"
        "1020,20,2,1,2050,32770,1028,0,1,11,71.5,11.9,31\n"
    )
    result = summarize(csv.DictReader(data))
    assert result["status"] == "passed"
    assert result["ids"] == [1]
    assert result["servos"]["1"]["rows"] == 2
    assert result["servos"]["1"]["speed_raw_magnitude_max"] == 2
    assert result["servos"]["1"]["load_raw_magnitude_max"] == 4
    assert result["servos"]["1"]["current_ma_max"] == 71.5
    assert result["servos"]["1"]["temperature_c_max"] == 31
    assert result["servos"]["1"]["status_values"] == [0]
    assert result["servos"]["1"]["moving_samples"] == 1

    fault = summarize(
        csv.DictReader(
            io.StringIO(
                "unix_ms,elapsed_ms,sample,id,position_raw,speed_raw,load_raw,status,moving,current_raw,current_ma,voltage_v,temperature_c\n"
                "1000,0,1,1,2048,0,0,4,0,0,0,12.0,30\n"
            )
        )
    )
    assert fault["status"] == "failed"
    assert fault["faults"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, help="write JSON summary")
    parser.add_argument("--expected-hz", type=float, default=50.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("self-test passed")
        return 0
    if args.csv is None:
        parser.error("CSV path is required unless --self-test is used")
    with args.csv.open(newline="", encoding="utf-8") as handle:
        result = summarize(csv.DictReader(handle), args.expected_hz)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
