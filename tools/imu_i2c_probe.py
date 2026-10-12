#!/usr/bin/env python3
"""Standalone LSM6DSV16X I2C/SFLP bench probe for a Linux Radxa board.

This configures only the selected I2C device. It does not talk to robotd, the
servo UART, or ID=200. Requires Python 3.11+ and no third-party packages.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import statistics
import struct
import sys
import time
from pathlib import Path


I2C_RDWR = 0x0707
I2C_M_RD = 0x0001
WHO_AM_I = 0x0F
EXPECTED_ID = 0x70
GYRO_DPS_PER_LSB = 0.0175  # CTRL6=0x02, +/-500 dps
ACC_G_PER_LSB = 0.000122  # CTRL8=0x01, +/-4 g
FIFO_GAME_TAG = 0x13
FIFO_DRAIN_LIMIT = 32
SFLP_SETTLE_SECONDS = 1.5


class I2CMsg(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("len", ctypes.c_uint16),
        ("buf", ctypes.POINTER(ctypes.c_uint8)),
    ]


class I2CRdwr(ctypes.Structure):
    _fields_ = [("msgs", ctypes.POINTER(I2CMsg)), ("nmsgs", ctypes.c_uint32)]


class LinuxI2C:
    """I2C_RDWR combined transactions; keeps register-select and read together."""

    def __init__(self, device: str, address: int):
        if not 0x08 <= address <= 0x77:
            raise ValueError("I2C address must be a 7-bit device address")
        self.address = address
        self.fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.ioctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p)
        self.libc.ioctl.restype = ctypes.c_int

    def close(self) -> None:
        os.close(self.fd)

    def __enter__(self) -> LinuxI2C:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _transfer(self, payload: bytes, read_len: int = 0) -> bytes:
        if not payload or read_len < 0 or read_len > 512:
            raise ValueError("invalid I2C transfer length")
        write_buf = (ctypes.c_uint8 * len(payload))(*payload)
        read_buf = (ctypes.c_uint8 * read_len)()
        messages = [
            I2CMsg(self.address, 0, len(payload), write_buf),
        ]
        if read_len:
            messages.append(I2CMsg(self.address, I2C_M_RD, read_len, read_buf))
        array = (I2CMsg * len(messages))(*messages)
        request = I2CRdwr(array, len(messages))
        if self.libc.ioctl(self.fd, I2C_RDWR, ctypes.byref(request)) < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return bytes(read_buf)

    def read(self, register: int, length: int = 1) -> bytes:
        return self._transfer(bytes([register]), length)

    def write(self, register: int, value: int) -> None:
        self._transfer(bytes([register, value]))


def read_u8(bus: LinuxI2C, register: int) -> int:
    return bus.read(register)[0]


def write_checked(bus: LinuxI2C, register: int, value: int, mask: int = 0xFF) -> None:
    bus.write(register, value)
    actual = read_u8(bus, register)
    if actual & mask != value & mask:
        raise RuntimeError(
            f"register 0x{register:02x}: wrote 0x{value:02x}, read 0x{actual:02x}"
        )


def embedded_page(bus: LinuxI2C, enabled: bool) -> None:
    value = 0x80 if enabled else 0x00
    write_checked(bus, 0x01, value, 0x80)


def configure_sensor(bus: LinuxI2C, enable_sflp: bool = True) -> None:
    """Configure 120 Hz high-performance raw sensors and optionally SFLP FIFO.

    ST DS13510 Rev 4: main-page register tables 24, 50-55 and 216-218;
    embedded-page tables 262, 265, 295 and 323. The 0x06 ODR values are
    intentional: 0x36 selects ODR-triggered mode, not high-performance mode.
    """
    embedded_page(bus, False)
    identity = read_u8(bus, WHO_AM_I)
    if identity != EXPECTED_ID:
        raise RuntimeError(f"WHO_AM_I=0x{identity:02x}, expected 0x70; configuration stopped")

    write_checked(bus, 0x12, 0x44)  # BDU + IF_INC
    write_checked(bus, 0x15, 0x02)  # gyro +/-500 dps
    write_checked(bus, 0x17, 0x01)  # accelerometer +/-4 g
    write_checked(bus, 0x0A, 0x00)  # FIFO bypass clears old words
    if not enable_sflp:
        write_checked(bus, 0x10, 0x06)
        write_checked(bus, 0x11, 0x06)
        return

    write_checked(bus, 0x07, 0x0C)  # 12-word watermark
    write_checked(bus, 0x08, 0x00)
    write_checked(bus, 0x09, 0x00)  # only embedded-function words in FIFO

    embedded_page(bus, True)
    try:
        write_checked(bus, 0x5E, 0x5B)  # SFLP game vector at 120 Hz
        write_checked(bus, 0x04, read_u8(bus, 0x04) | 0x02)  # SFLP game enable
        write_checked(bus, 0x44, read_u8(bus, 0x44) | 0x02)  # SFLP FIFO enable
    finally:
        embedded_page(bus, False)

    write_checked(bus, 0x0A, 0x06)  # continuous FIFO
    write_checked(bus, 0x10, 0x06)  # accel 120 Hz, high-performance mode
    write_checked(bus, 0x11, 0x06)  # gyro 120 Hz, high-performance mode

    # Restart an already-running fusion instance after configuring its inputs.
    embedded_page(bus, True)
    try:
        bus.write(0x66, read_u8(bus, 0x66) | 0x02)
    finally:
        embedded_page(bus, False)

    # The chip emits plausible-looking quaternions while SFLP is converging.
    time.sleep(SFLP_SETTLE_SECONDS)
    write_checked(bus, 0x0A, 0x00)
    write_checked(bus, 0x0A, 0x06)


def decode_raw(payload: bytes) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if len(payload) != 12:
        raise ValueError("expected 12 raw gyro/accel bytes")
    counts = struct.unpack("<6h", payload)
    gyro = tuple(value * GYRO_DPS_PER_LSB for value in counts[:3])
    accel = tuple(value * ACC_G_PER_LSB for value in counts[3:])
    return gyro, accel


def decode_fifo_game(word: bytes) -> tuple[float, float, float, float] | None:
    if len(word) != 7:
        raise ValueError("expected one 7-byte FIFO word")
    if word[0] >> 3 != FIFO_GAME_TAG or word[1:] == bytes(6):
        return None
    x, y, z = struct.unpack("<3e", word[1:])
    squared = x * x + y * y + z * z
    if not all(math.isfinite(value) for value in (x, y, z)) or squared > 1.02:
        return None
    w = math.sqrt(max(0.0, 1.0 - squared))
    magnitude = math.sqrt(w * w + squared)
    return (w / magnitude, x / magnitude, y / magnitude, z / magnitude)


def read_fifo(bus: LinuxI2C) -> tuple[tuple[float, ...] | None, int, bool, int, int, int]:
    status = bus.read(0x1B, 2)
    level = status[0] | ((status[1] & 0x01) << 8)
    overrun = bool(status[1] & 0x08)
    newest = None
    unknown_tags = 0
    invalid_vectors = 0
    valid_vectors = 0
    for _ in range(min(level, FIFO_DRAIN_LIMIT)):
        word = bus.read(0x78, 7)
        if word[0] >> 3 == FIFO_GAME_TAG:
            quat = decode_fifo_game(word)
            if quat is None:
                invalid_vectors += 1
            else:
                newest = quat
                valid_vectors += 1
        else:
            unknown_tags += 1
    return newest, level, overrun, unknown_tags, invalid_vectors, valid_vectors


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def skip_missed_slots(due: float, now: float, period: float, remaining: int) -> tuple[float, int]:
    """Advance to a future slot after a pause instead of rapidly rereading old data."""
    if now - due <= period / 4 or remaining <= 0:
        return due, 0
    skipped = min(remaining, math.floor((now - due) / period) + 1)
    return due + skipped * period, skipped


def observe(
    bus: LinuxI2C, seconds: float, hz: int, output: Path | None,
    enable_sflp: bool = True,
) -> dict:
    period = 1.0 / hz
    target = max(1, round(seconds * hz))
    due = time.monotonic()
    start = due
    previous_at = None
    previous_raw = None
    stale_run = 0
    max_stale_run = 0
    stale_total = 0
    errors = 0
    fifo_overruns = 0
    fifo_backlog_ticks = 0
    unexpected_tags = 0
    invalid_sflp_vectors = 0
    sflp_words = 0
    fused_ticks = 0
    max_fifo_level = 0
    max_quat_step_deg = 0.0
    intervals = []
    wake_lateness = []
    io_durations = []
    gyro_values = [[], [], []]
    accel_magnitudes = []
    latest_quat = None
    output_file = output.open("x", encoding="utf-8") if output else None
    samples = 0
    missed_deadlines = 0
    interrupted = False
    try:
        index = 0
        while index < target:
            now = time.monotonic()
            if index:
                due, skipped = skip_missed_slots(due, now, period, target - index)
                index += skipped
                missed_deadlines += skipped
                if index >= target:
                    break
            remaining = due - now
            if remaining > 0:
                time.sleep(remaining)
            tick_at = time.monotonic()
            wake_lateness.append(max(0.0, tick_at - due))
            tick_number = index + 1
            index += 1
            if previous_at is not None:
                intervals.append(tick_at - previous_at)
            previous_at = tick_at
            due += period

            io_started = time.monotonic()
            try:
                if enable_sflp:
                    fused, fifo_level, overrun, bad_tags, invalid, valid = read_fifo(bus)
                else:
                    fused, fifo_level, overrun, bad_tags, invalid, valid = (
                        None, 0, False, 0, 0, 0
                    )
                raw = bus.read(0x22, 12)
            except OSError as exc:
                io_durations.append(time.monotonic() - io_started)
                errors += 1
                if errors <= 5:
                    print(f"I2C read error at tick {tick_number}: {exc}", file=sys.stderr)
                continue
            io_duration = time.monotonic() - io_started
            io_durations.append(io_duration)

            samples += 1
            max_fifo_level = max(max_fifo_level, fifo_level)
            fifo_backlog_ticks += int(fifo_level > FIFO_DRAIN_LIMIT)
            fifo_overruns += int(overrun)
            unexpected_tags += bad_tags
            invalid_sflp_vectors += invalid
            sflp_words += valid
            if fused is not None:
                if latest_quat is not None:
                    dot = sum(a * b for a, b in zip(latest_quat, fused))
                    step_deg = math.degrees(2.0 * math.acos(min(1.0, abs(dot))))
                    max_quat_step_deg = max(max_quat_step_deg, step_deg)
                latest_quat = fused
                fused_ticks += 1
            if raw == previous_raw:
                stale_run += 1
                stale_total += 1
            else:
                stale_run = 0
            max_stale_run = max(max_stale_run, stale_run)
            previous_raw = raw
            gyro, accel = decode_raw(raw)
            for axis in range(3):
                gyro_values[axis].append(gyro[axis])
            accel_magnitudes.append(math.sqrt(sum(value * value for value in accel)))

            if output_file:
                record = {
                    "tick": tick_number,
                    "elapsed_s": round(tick_at - start, 6),
                    "wake_late_ms": round(wake_lateness[-1] * 1000, 3),
                    "io_ms": round(io_duration * 1000, 3),
                    "gyro_dps": gyro,
                    "acc_g": accel,
                    "quat_wxyz_sensor": latest_quat,
                    "new_sflp": fused is not None,
                    "fifo_level": fifo_level,
                    "fifo_overrun": overrun,
                    "stale_raw": stale_run > 0,
                    "missed_deadlines_before_tick": missed_deadlines,
                }
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            if tick_number == 1 or tick_number % hz == 0:
                q_text = (
                    "waiting"
                    if latest_quat is None
                    else "[" + ", ".join(f"{v:+.3f}" for v in latest_quat) + "]"
                )
                print(
                    f"t={tick_at - start:6.1f}s raw={samples}/{tick_number} "
                    f"gyro={[round(v, 2) for v in gyro]} dps "
                    f"acc={[round(v, 3) for v in accel]} g "
                    f"|a|={accel_magnitudes[-1]:.3f}g q(wxyz)={q_text} "
                    f"fifo={fifo_level} missed={missed_deadlines} errors={errors}",
                    flush=True,
                )
    except KeyboardInterrupt:
        interrupted = True
        print("stopped by user; reporting partial run", file=sys.stderr)
    finally:
        if output_file:
            output_file.close()

    elapsed = max(time.monotonic() - start, 1e-9)
    gyro_summary = [
        {
            "mean_dps": statistics.mean(axis),
            "max_abs_dps": max(map(abs, axis)),
        }
        for axis in gyro_values
    ] if samples else []
    summary = {
        "scope": "standalone_i2c_bench_probe_not_robotd",
        "mode": "raw_and_sflp" if enable_sflp else "raw_only",
        "requested_hz": hz,
        "requested_seconds": seconds,
        "ticks": target,
        "samples": samples,
        "missed_deadlines": missed_deadlines,
        "interrupted": interrupted,
        "elapsed_seconds": round(elapsed, 3),
        "observed_hz": round((len(intervals) / sum(intervals)), 3) if intervals else 0.0,
        "interval_ms_p95": round(percentile(intervals, 0.95) * 1000, 3),
        "interval_ms_max": round(max(intervals, default=0.0) * 1000, 3),
        "interval_over_40ms": sum(value > 0.040 for value in intervals),
        "wake_late_ms_p95": round(percentile(wake_lateness, 0.95) * 1000, 3),
        "wake_late_ms_max": round(max(wake_lateness, default=0.0) * 1000, 3),
        "io_ms_p95": round(percentile(io_durations, 0.95) * 1000, 3),
        "io_ms_max": round(max(io_durations, default=0.0) * 1000, 3),
        "read_errors": errors,
        "raw_stale_total": stale_total,
        "raw_stale_max_run": max_stale_run,
        "sflp_ticks_with_new_vector": fused_ticks,
        "sflp_valid_fifo_words": sflp_words,
        "sflp_invalid_fifo_words": invalid_sflp_vectors,
        "max_quat_step_deg": round(max_quat_step_deg, 3),
        "fifo_overruns": fifo_overruns,
        "fifo_backlog_ticks": fifo_backlog_ticks,
        "fifo_max_level": max_fifo_level,
        "unexpected_fifo_tags": unexpected_tags,
        "last_quat_wxyz_sensor": latest_quat,
        "gyro_axes": gyro_summary,
        "acc_magnitude_g_mean": statistics.mean(accel_magnitudes) if samples else None,
        "output_jsonl": str(output) if output else None,
    }
    summary["probe_ok"] = (
        not interrupted
        and samples == target
        and missed_deadlines == 0
        and errors == 0
        and (not enable_sflp or fused_ticks >= min(25, target))
        and max_stale_run <= 3
        and fifo_overruns == 0
        and fifo_backlog_ticks == 0
        and summary["interval_over_40ms"] == 0
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", default="/dev/i2c-pihat", help="Linux I2C device path")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x6B)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--hz", type=int, default=50)
    parser.add_argument("--raw-only", action="store_true", help="read six axes without SFLP")
    parser.add_argument("--output", type=Path, help="optional per-tick JSONL file")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds <= 0 or args.seconds > 3600:
        parser.error("--seconds must be in (0, 3600]")
    if not 1 <= args.hz <= 100:
        parser.error("--hz must be in [1, 100]")
    if args.address not in (0x6A, 0x6B):
        parser.error("LSM6DSV16X address must be 0x6a or 0x6b")
    if args.output and args.output.exists():
        parser.error(f"--output already exists: {args.output}; choose a new filename")
    if sys.platform != "linux":
        parser.error("the live probe requires Linux; unit tests run without hardware")

    try:
        with LinuxI2C(args.bus, args.address) as bus:
            configure_sensor(bus, enable_sflp=not args.raw_only)
            print(
                f"LSM6DSV16X 0x{args.address:02x} on {args.bus}; "
                + (
                    "raw sensors configured"
                    if args.raw_only
                    else "SFLP configured, 1.5 s convergence elapsed"
                ),
                flush=True,
            )
            summary = observe(
                bus, args.seconds, args.hz, args.output,
                enable_sflp=not args.raw_only,
            )
    except (OSError, RuntimeError) as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 2
    print("summary: " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["probe_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
