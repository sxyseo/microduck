#!/usr/bin/env python3
"""Bind one HL-2915 BAM model, training checkout, and exported ONNX into one report."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from check_onnx_contract import file_identity


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _verified_file(contract: dict[str, Any], base: Path, label: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    raw_path = contract.get("path")
    path = Path(raw_path) if isinstance(raw_path, str) else Path()
    if not path.is_absolute():
        path = base / path
    expected_sha = contract.get("sha256")
    expected_size = contract.get("size_bytes")
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(f"{label} contract has no path")
    if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        errors.append(f"{label} contract has no valid SHA-256")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size <= 0:
        errors.append(f"{label} contract has no valid size_bytes")
    actual: dict[str, object] = {}
    if path.is_file():
        actual = file_identity(path)
        if expected_sha != actual["sha256"] or expected_size != actual["size_bytes"]:
            errors.append(f"{label} file identity does not match its contract")
    else:
        errors.append(f"{label} file does not exist: {path}")
    return {"path": str(path.resolve()), **actual}, errors


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def build_report(
    bam_contract_path: Path,
    onnx_contract_path: Path,
    training_repo: Path,
    purpose: str,
) -> dict[str, Any]:
    bam_contract = _load(bam_contract_path)
    onnx_contract = _load(onnx_contract_path)
    repo = training_repo.resolve()
    errors: list[str] = []

    bam_file, file_errors = _verified_file(bam_contract, repo, "BAM model")
    errors.extend(file_errors)
    if bam_contract.get("status") != "passed":
        errors.append("BAM model contract did not pass")
    if bam_contract.get("actuator") != "hl2915" or bam_contract.get("model") != "m6":
        errors.append("BAM model must be actuator=hl2915 and model=m6")
    provenance = bam_contract.get("data_provenance")
    if provenance not in {"measured", "synthetic"}:
        errors.append("BAM model data_provenance must be measured or synthetic")

    onnx_file, file_errors = _verified_file(onnx_contract, repo, "ONNX")
    errors.extend(file_errors)
    input_spec = onnx_contract.get("input")
    output_spec = onnx_contract.get("output")
    if (
        not isinstance(input_spec, dict)
        or input_spec.get("shape") != [1, 61]
        or not isinstance(output_spec, dict)
        or output_spec.get("shape") != [1, 14]
        or onnx_contract.get("finite_zero_observation") is not True
    ):
        errors.append("ONNX contract must pass obs[1,61] -> actions[1,14] CPU inference")

    commit = ""
    clean = False
    try:
        commit = _git(repo, "rev-parse", "HEAD")
        clean = not _git(repo, "status", "--porcelain")
    except ValueError as exc:
        errors.append(f"training repo: {exc}")
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        errors.append("training repo has no valid commit")
    if not clean:
        errors.append("training repo is not clean")

    return {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "purpose": purpose,
        "training_repo": {"path": str(repo), "commit": commit, "clean": clean},
        "bam_model": {
            **bam_file,
            "contract_path": str(bam_contract_path.resolve()),
            "actuator": bam_contract.get("actuator"),
            "model": bam_contract.get("model"),
            "data_provenance": provenance,
        },
        "onnx": {**onnx_file, "contract_path": str(onnx_contract_path.resolve())},
        "errors": errors,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bam-contract", type=Path, required=True)
    parser.add_argument("--onnx-contract", type=Path, required=True)
    parser.add_argument("--training-repo", type=Path, required=True)
    parser.add_argument("--purpose", choices=("smoke", "candidate"), required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(
            args.bam_contract,
            args.onnx_contract,
            args.training_repo,
            args.purpose,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"training lineage failed: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
