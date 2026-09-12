#!/usr/bin/env python3
"""Validate a fitted BAM actuator JSON before using it for HL-2915 training."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from check_onnx_contract import file_identity
from hl2915_bam_adapter import AdapterConfig, METADATA_KEY

DATA_PROVENANCE_KEY = "data_provenance"
ALLOWED_PROVENANCE = {"measured", "synthetic"}


M6_FIELDS = (
    "kt",
    "R",
    "armature",
    "q_offset",
    "friction_base",
    "friction_stribeck",
    "load_friction_motor",
    "load_friction_external",
    "load_friction_motor_stribeck",
    "load_friction_external_stribeck",
    "load_friction_motor_quad",
    "load_friction_external_quad",
    "dtheta_stribeck",
    "alpha",
    "friction_viscous",
)


def validate(payload: dict[str, Any], *, actuator: str, model: str) -> dict[str, Any]:
    if "actuator" not in payload or "model" not in payload:
        raise ValueError("missing fitted-model metadata: actuator and model")
    if payload.get("actuator") != actuator:
        raise ValueError(
            f"actuator mismatch: file={payload.get('actuator')!r}, expected={actuator!r}"
        )
    if payload.get("model") != model:
        raise ValueError(f"model mismatch: file={payload.get('model')!r}, expected={model!r}")
    required = M6_FIELDS if model == "m6" else ()
    missing = [name for name in required if name not in payload]
    if missing:
        raise ValueError(f"missing {model} fields: {', '.join(missing)}")
    bad = []
    for name in required:
        value = payload[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            bad.append(name)
    if bad:
        raise ValueError(f"fields must be finite numbers: {', '.join(bad)}")
    for name in ("kt", "R"):
        if payload[name] <= 0:
            raise ValueError(f"{name} must be greater than zero")
    if payload["armature"] < 0:
        raise ValueError("armature must not be negative")
    if actuator == "hl2915":
        AdapterConfig.from_mapping(payload.get(METADATA_KEY))
        provenance = payload.get(DATA_PROVENANCE_KEY)
        if provenance not in ALLOWED_PROVENANCE:
            raise ValueError(
                "HL-2915 model must declare data_provenance='measured' or 'synthetic'"
            )
    return {
        "status": "passed",
        "actuator": actuator,
        "model": model,
        "required_fields": list(required),
        "adapter_metadata": payload.get(METADATA_KEY) if actuator == "hl2915" else None,
        "data_provenance": payload.get(DATA_PROVENANCE_KEY),
    }


def _self_test() -> None:
    payload: dict[str, Any] = {
        "actuator": "hl2915",
        "model": "m6",
        **{name: 1.0 for name in M6_FIELDS},
        METADATA_KEY: AdapterConfig(error_gain=0.1).to_mapping(),
        DATA_PROVENANCE_KEY: "synthetic",
    }
    validate(payload, actuator="hl2915", model="m6")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", type=Path, nargs="?")
    parser.add_argument("--actuator", default="hl2915")
    parser.add_argument("--model", default="m6")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true", help="validate an in-memory synthetic contract")
    args = parser.parse_args()
    if args.self_test:
        try:
            _self_test()
        except ValueError as exc:
            print(f"BAM model self-test failed: {exc}", file=sys.stderr)
            return 1
        print("BAM model self-test: ok")
        return 0
    if args.json is None:
        parser.error("JSON path is required unless --self-test is used")
    try:
        payload = json.loads(args.json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be an object; raw BAM logs are not fitted models")
        report = validate(payload, actuator=args.actuator, model=args.model)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"BAM model contract failed: {exc}", file=sys.stderr)
        return 1
    report["path"] = str(args.json)
    report.update(file_identity(args.json))
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
