#!/usr/bin/env python3
"""Run or validate a bounded Pollen Robot HAT I2C/audio smoke report."""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any


CODEC_ADDRESS = 0x18


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("source") != "radxa":
        errors.append("source must be radxa")
    if payload.get("machine") != "aarch64":
        errors.append("machine must be aarch64")
    if payload.get("data_provenance") != "measured":
        errors.append("data_provenance must be measured")
    if payload.get("hardware") != "pollen-rpi-robot-hat":
        errors.append("hardware must be pollen-rpi-robot-hat")

    codec = payload.get("codec")
    if not isinstance(codec, dict) or codec.get("status") != "passed" or codec.get("address") != "0x18":
        errors.append("codec must pass at address 0x18")

    capture = payload.get("capture")
    if (
        not isinstance(capture, dict)
        or capture.get("status") != "passed"
        or not isinstance(capture.get("bytes"), int)
        or isinstance(capture.get("bytes"), bool)
        or capture["bytes"] <= 44
    ):
        errors.append("capture must pass and contain PCM data")

    playback = payload.get("playback")
    if not isinstance(playback, dict) or playback.get("status") != "passed":
        errors.append("playback must pass")
    if payload.get("audible_confirmed") is not True:
        errors.append("audible_confirmed must be true")

    return {"status": "passed" if not errors else "failed", "errors": errors}


def i2c_address_present(scan: str, address: int) -> bool:
    row_base = address & 0xF0
    column = address & 0x0F
    for line in scan.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]{2}):\s+(.*)$", line)
        if match is None or int(match.group(1), 16) != row_base:
            continue
        cells = match.group(2).split()
        if len(cells) != 16:
            return False
        return cells[column].lower() == f"{address:02x}" or cells[column] == "UU"
    return False


def _run(command: list[str], timeout: float = 15.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "failed",
            "returncode": None,
            "error": str(exc),
            "seconds": round(time.monotonic() - started, 3),
        }
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
        "seconds": round(time.monotonic() - started, 3),
    }


def _write_quiet_tone(path: Path) -> None:
    sample_rate = 48_000
    duration = 0.25
    amplitude = int(0.02 * 32767)
    frames = b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * sample / sample_rate)))
        for sample in range(int(sample_rate * duration))
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def run_smoke(
    *,
    bus: int = 3,
    device: str = "plughw:aic3104",
    duration_seconds: int = 2,
    audible_confirmed: bool = False,
) -> dict[str, Any]:
    if not 0 <= bus <= 255:
        raise ValueError("bus must be between 0 and 255")
    if not 1 <= duration_seconds <= 5:
        raise ValueError("duration_seconds must be between 1 and 5")

    scan_command = ["i2cdetect", "-y", "-r", str(bus)]
    scan_result = _run(scan_command)
    codec_found = scan_result.get("status") == "passed" and i2c_address_present(
        str(scan_result.get("stdout_tail", "")), CODEC_ADDRESS
    )

    with tempfile.TemporaryDirectory(prefix="microduck-hat-") as directory:
        root = Path(directory)
        capture_path = root / "capture.wav"
        tone_path = root / "quiet-tone.wav"
        capture_command = [
            "arecord",
            "-q",
            "-D",
            f"{device},0",
            "-t",
            "wav",
            "-f",
            "S16_LE",
            "-r",
            "48000",
            "-c",
            "2",
            "-d",
            str(duration_seconds),
            str(capture_path),
        ]
        capture_result = _run(capture_command, timeout=duration_seconds + 10)
        capture_bytes = capture_path.stat().st_size if capture_path.is_file() else 0

        _write_quiet_tone(tone_path)
        playback_command = ["aplay", "-q", "-D", device, str(tone_path)]
        playback_result = _run(playback_command)

        payload = {
            "schema_version": 1,
            "source": "radxa",
            "machine": platform.machine(),
            "data_provenance": "measured",
            "hardware": "pollen-rpi-robot-hat",
            "codec": {
                "status": "passed" if codec_found else "failed",
                "address": "0x18",
                "command": scan_command,
                "result": scan_result,
            },
            "capture": {
                "status": "passed"
                if capture_result.get("status") == "passed" and capture_bytes > 44
                else "failed",
                "bytes": capture_bytes,
                "seconds": duration_seconds,
                "command": capture_command,
                "result": capture_result,
            },
            "playback": {
                "status": playback_result.get("status"),
                "command": playback_command,
                "result": playback_result,
            },
            "audible_confirmed": audible_confirmed,
            "temporary_audio_deleted": True,
        }
        payload.update(validate(payload))
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json", nargs="?", type=Path, help="existing HAT smoke JSON to validate")
    parser.add_argument("--run", action="store_true", help="run bounded I2C, capture and playback checks")
    parser.add_argument("--bus", type=int, default=3)
    parser.add_argument("--device", default="plughw:aic3104")
    parser.add_argument("--duration-seconds", type=int, default=2)
    parser.add_argument("--confirm-official-hat", action="store_true")
    parser.add_argument("--confirm-audible", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        sample = {
            "schema_version": 1,
            "source": "radxa",
            "machine": "aarch64",
            "data_provenance": "measured",
            "hardware": "pollen-rpi-robot-hat",
            "codec": {"status": "passed", "address": "0x18"},
            "capture": {"status": "passed", "bytes": 45},
            "playback": {"status": "passed"},
            "audible_confirmed": True,
        }
        assert validate(sample)["status"] == "passed"
        print("self-test passed")
        return 0

    if args.run:
        if not args.confirm_official_hat:
            parser.error("--run requires --confirm-official-hat; do not scan an unknown I2C board")
        try:
            report = run_smoke(
                bus=args.bus,
                device=args.device,
                duration_seconds=args.duration_seconds,
                audible_confirmed=args.confirm_audible,
            )
        except ValueError as exc:
            parser.error(str(exc))
    elif args.json:
        try:
            report = json.loads(args.json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"HAT smoke JSON failed: {exc}")
            return 1
        if not isinstance(report, dict):
            print("HAT smoke JSON root must be an object")
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
