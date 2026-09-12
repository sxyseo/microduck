#!/usr/bin/env python3
"""Run BAM fitting with an explicit HL-2915 Feetech adapter.

The adapter reuses BAM's Feetech voltage-controlled implementation. ``error_gain`` is
deliberately required: it must be measured for HL-2915, not copied from STS3215.
"""

from __future__ import annotations

import argparse
import json
import math
import runpy
import sys
from pathlib import Path

from hl2915_bam_adapter import AdapterConfig, METADATA_KEY, register

DATA_PROVENANCE_KEY = "data_provenance"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--error-gain",
        type=float,
        required=True,
        help="Measured duty/(firmware_kp*radian); do not copy the STS3215 value",
    )
    parser.add_argument("--max-velocity-rpm", type=float, default=110.0)
    parser.add_argument("--default-vin", type=float, default=12.0)
    parser.add_argument("--default-kp", type=float, default=16.0)
    parser.add_argument("--max-pwm", type=float, default=0.97)
    parser.add_argument("--max-current-a", type=float, default=1.5)
    parser.add_argument("--self-test", action="store_true", help="register the adapter and exit")
    return parser


def _exercise(registry) -> float:
    from bam.model import models

    model = models["m6"]()
    actuator = registry.actuators["hl2915"]()
    model.set_actuator(actuator)
    control = float(actuator.compute_control(0.1, 0.0, 0.0, 0.02))
    if not math.isfinite(control):
        raise SystemExit("hl2915 adapter self-test produced a non-finite control")
    return control


def main() -> int:
    parser = _parser()
    args, fit_args = parser.parse_known_args()
    if "--actuator" in fit_args:
        parser.error("do not pass --actuator; this wrapper registers hl2915")
    config = AdapterConfig(
        error_gain=args.error_gain,
        max_velocity_rpm=args.max_velocity_rpm,
        default_vin=args.default_vin,
        default_kp=args.default_kp,
        max_pwm=args.max_pwm,
        max_current_a=args.max_current_a,
    )
    try:
        registry = register(config)
    except ValueError as exc:
        parser.error(str(exc))
    if args.self_test:
        print(f"hl2915 adapter: registered, control={_exercise(registry):.6f}V")
        return 0

    sys.argv = ["bam.fit", *fit_args, "--actuator", "hl2915"]
    state = runpy.run_module("bam.fit", run_name="__main__")
    output = Path(state["params_json_filename"])
    payload = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("actuator") != "hl2915":
        raise SystemExit("bam.fit did not produce an hl2915 parameter object")
    payload[METADATA_KEY] = config.to_mapping()
    payload[DATA_PROVENANCE_KEY] = "measured"
    output.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")
    print(f"HL-2915 adapter metadata saved: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
