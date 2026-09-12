#!/usr/bin/env python3
"""Check the policy ONNX contract before copying it to Radxa.

The deployment contract is deliberately small: one float input [1, 61], one float output
[1, 14], and a successful CPU inference with finite values.  onnxruntime is the only runtime
dependency; the script does not import torch or start the robot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_INPUT = [1, 61]
EXPECTED_OUTPUT = [1, 14]


def file_identity(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _shape(value: object) -> list[int | None]:
    result: list[int | None] = []
    for dim in value:  # type: ignore[union-attr]
        result.append(dim if isinstance(dim, int) else None)
    return result


def check(path: Path) -> dict[str, object]:
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        raise SystemExit("需要 onnxruntime 和 numpy：请在训练仓库的 uv 环境中运行") from exc

    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError(f"必须是 1 个输入和 1 个输出，实际 {len(inputs)} / {len(outputs)}")
    input_shape = _shape(inputs[0].shape)
    output_shape = _shape(outputs[0].shape)
    if input_shape != EXPECTED_INPUT:
        raise ValueError(f"输入形状错误：{input_shape}，期望 {EXPECTED_INPUT}")
    if output_shape != EXPECTED_OUTPUT:
        raise ValueError(f"输出形状错误：{output_shape}，期望 {EXPECTED_OUTPUT}")
    result = session.run(None, {inputs[0].name: np.zeros((1, 61), dtype=np.float32)})
    values = result[0]
    if list(values.shape) != EXPECTED_OUTPUT:
        raise ValueError(f"CPU 推理输出形状错误：{list(values.shape)}")
    if not np.isfinite(values).all():
        raise ValueError("CPU 推理输出包含 NaN 或无穷大")
    return {
        "path": str(path),
        "input": {"name": inputs[0].name, "shape": input_shape},
        "output": {"name": outputs[0].name, "shape": output_shape},
        "runtime": "onnxruntime/CPUExecutionProvider",
        "finite_zero_observation": bool(np.isfinite(values).all()),
        **file_identity(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("onnx", type=Path, nargs="?")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert _shape([1, 61]) == [1, 61]
        assert _shape(["batch", 14]) == [None, 14]
        print("self-test: ok")
        return 0
    if args.onnx is None:
        parser.error("必须提供 ONNX 文件，或使用 --self-test")
    if not args.onnx.is_file():
        raise SystemExit(f"找不到 ONNX 文件：{args.onnx}")
    try:
        report = check(args.onnx)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"ONNX 合同失败：{exc}") from exc
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
