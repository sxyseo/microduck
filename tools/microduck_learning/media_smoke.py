#!/usr/bin/env python3
"""Run or validate a Radxa camera/MPP/WebRTC smoke report.

The optional ``--run`` mode opens the camera and runs short, bounded commands on the Radxa.
Without ``--run`` this module only validates a previously saved JSON artifact.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("source") != "radxa":
        errors.append("source must be radxa")
    if payload.get("data_provenance") != "measured":
        errors.append("data_provenance must be measured")

    capture = payload.get("camera_capture")
    if not isinstance(capture, dict) or capture.get("status") != "passed":
        errors.append("camera_capture.status must be passed")
    else:
        if not isinstance(capture.get("frames"), int) or capture["frames"] < 30:
            errors.append("camera_capture.frames must be at least 30")
        if not _positive_number(capture.get("bytes")):
            errors.append("camera_capture.bytes must be positive")

    encoded = payload.get("hardware_encode")
    if not isinstance(encoded, dict) or encoded.get("status") != "passed":
        errors.append("hardware_encode.status must be passed")
    elif not _positive_number(encoded.get("bytes")):
        errors.append("hardware_encode.bytes must be positive")

    decoded = payload.get("decode")
    if not isinstance(decoded, dict) or decoded.get("status") != "passed":
        errors.append("decode.status must be passed")

    webrtc = payload.get("webrtc_elements")
    if not isinstance(webrtc, dict) or webrtc.get("status") != "passed":
        errors.append("webrtc_elements.status must be passed")

    return {
        "status": "passed" if not errors else "failed",
        "camera_frames": capture.get("frames") if isinstance(capture, dict) else None,
        "errors": errors,
    }


def _run(command: list[str], *, timeout: float = 45.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "returncode": None, "error": str(exc), "seconds": round(time.monotonic() - started, 3)}
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
        "seconds": round(time.monotonic() - started, 3),
    }


def _find_camera(root: Path = Path("/sys/class/video4linux")) -> str | None:
    if not root.exists():
        return None
    for name_path in sorted(root.glob("video*/name")):
        try:
            name = name_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if "rkisp_mainpath" in name:
            return "/dev/" + name_path.parent.name
    return None


def _inspect(element: str) -> bool:
    if shutil.which("gst-inspect-1.0") is None:
        return False
    return _run(["gst-inspect-1.0", element], timeout=10)["status"] == "passed"


def run_smoke(camera: str | None = None, frames: int = 60) -> dict[str, Any]:
    if frames < 30:
        raise ValueError("frames must be at least 30")
    camera = camera or _find_camera()
    with tempfile.TemporaryDirectory(prefix="microduck-media-") as directory:
        root = Path(directory)
        raw = root / "camera.raw"
        h264 = root / "test.h264"
        capture_command = None
        capture_result: dict[str, Any]
        if camera and shutil.which("v4l2-ctl"):
            capture_command = [
                "v4l2-ctl",
                "--device=" + camera,
                "--stream-mmap=3",
                f"--stream-count={frames}",
                "--stream-to=" + str(raw),
            ]
            capture_result = _run(capture_command)
        else:
            capture_result = {"status": "failed", "error": "找不到 rkisp_mainpath 或 v4l2-ctl"}
        captured_bytes = raw.stat().st_size if raw.exists() else 0
        capture = {
            "status": "passed" if capture_result.get("status") == "passed" and captured_bytes > 0 else "failed",
            "device": camera,
            "frames": frames,
            "bytes": captured_bytes,
            "command": capture_command,
            "result": capture_result,
        }

        encode_command = [
            "gst-launch-1.0",
            "-q",
            "-e",
            "videotestsrc",
            f"num-buffers={frames}",
            "!",
            "video/x-raw,format=NV12,width=1280,height=720,framerate=30/1",
            "!",
            "mpph264enc",
            "profile=baseline",
            "header-mode=each-idr",
            "bps=2000000",
            "!",
            "h264parse",
            "!",
            "filesink",
            "location=" + str(h264),
        ]
        encode_result = _run(encode_command)
        encoded_bytes = h264.stat().st_size if h264.exists() else 0
        encoded = {
            "status": "passed" if encode_result.get("status") == "passed" and encoded_bytes > 0 else "failed",
            "bytes": encoded_bytes,
            "command": encode_command,
            "result": encode_result,
        }

        decode_command = [
            "gst-launch-1.0",
            "-q",
            "filesrc",
            "location=" + str(h264),
            "!",
            "h264parse",
            "!",
            "avdec_h264",
            "!",
            "fakesink",
        ]
        decode_result = _run(decode_command) if encoded["status"] == "passed" else {"status": "failed", "error": "encode failed"}
        decoded = {"status": decode_result.get("status"), "command": decode_command, "result": decode_result}

        elements = [element for element in ("webrtcbin", "webrtcsink") if _inspect(element)]
        webrtc = {"status": "passed" if len(elements) == 2 else "failed", "elements": elements}

        payload = {
            "schema_version": 1,
            "source": "radxa",
            "data_provenance": "measured",
            "camera_capture": capture,
            "hardware_encode": encoded,
            "decode": decoded,
            "webrtc_elements": webrtc,
        }
        payload.update(validate(payload))
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", type=Path, help="existing smoke JSON to validate")
    parser.add_argument("--run", action="store_true", help="run the bounded camera/MPP smoke on Radxa")
    parser.add_argument("--camera", help="rkisp_mainpath device, for example /dev/video0")
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        sample = {
            "source": "radxa",
            "data_provenance": "measured",
            "camera_capture": {"status": "passed", "frames": 60, "bytes": 1},
            "hardware_encode": {"status": "passed", "bytes": 1},
            "decode": {"status": "passed"},
            "webrtc_elements": {"status": "passed"},
        }
        assert validate(sample)["status"] == "passed"
        print("self-test passed")
        return 0
    if args.run:
        report = run_smoke(args.camera, args.frames)
    elif args.json:
        try:
            report = json.loads(args.json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"media smoke JSON failed: {exc}")
            return 1
        if not isinstance(report, dict):
            print("media smoke JSON root must be an object")
            return 1
        report.update(validate(report))
    else:
        parser.error("give a JSON path, --run, or --self-test")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"json: {args.json_out}")
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
