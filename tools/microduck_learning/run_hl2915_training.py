#!/usr/bin/env python3
"""Register the HL-2915 BAM adapter, then launch the normal mjlab train CLI."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from hl2915_bam_adapter import register_from_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bam-json", required=True, type=Path)
    parser.add_argument("--self-test", action="store_true")
    args, train_args = parser.parse_known_args()
    try:
        payload, _ = register_from_model(args.bam_json)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.self_test:
        from bam.model import load_model

        model = load_model(str(args.bam_json))
        actuator = model.actuator
        if not math.isclose(float(model.kt.value), float(payload["kt"]), rel_tol=1e-12):
            raise SystemExit("HL-2915 fitted parameters were reset while loading")
        control = float(actuator.compute_control(0.1, 0.0, 0.0, 0.02))
        if not math.isfinite(control):
            raise SystemExit("HL-2915 training adapter produced non-finite control")
        print(f"hl2915 training adapter: ready, control={control:.6f}V")
        return 0

    if not train_args:
        parser.error("missing mjlab task and train arguments")
    from mjlab.scripts.train import main as train_main

    sys.argv = ["train", *train_args]
    result = train_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
