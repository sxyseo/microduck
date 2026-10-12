"""Offline checks for the Radxa I2C IMU probe; no sensor is required."""

import ctypes
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imu_i2c_probe as probe  # noqa: E402


class FakeBus:
    def __init__(self, identity=0x70):
        self.page = False
        self.main = {0x0F: identity, 0x01: 0x00}
        self.embedded = {0x04: 0x00, 0x44: 0x00, 0x5E: 0x5B, 0x66: 0x00}
        self.writes = []

    def read(self, register, length=1):
        if register == 0x01:
            return bytes([0x80 if self.page else 0x00])
        registers = self.embedded if self.page else self.main
        return bytes(registers.get(register + offset, 0) for offset in range(length))

    def write(self, register, value):
        self.writes.append((self.page, register, value))
        if register == 0x01:
            self.page = bool(value & 0x80)
        else:
            (self.embedded if self.page else self.main)[register] = value


class ProbeTests(unittest.TestCase):
    def test_linux_i2c_read_uses_combined_register_and_read_messages(self):
        case = self

        class FakeLibc:
            def ioctl(self, fd, command, pointer):
                request = ctypes.cast(pointer, ctypes.POINTER(probe.I2CRdwr)).contents
                messages = request.msgs
                case.assertEqual((fd, command), (7, probe.I2C_RDWR))
                case.assertEqual(request.nmsgs, 2)
                case.assertEqual(bytes(messages[0].buf[: messages[0].len]), b"\x0f")
                case.assertEqual((messages[0].addr, messages[1].addr), (0x6B, 0x6B))
                case.assertEqual(messages[1].flags, probe.I2C_M_RD)
                messages[1].buf[0] = 0x70
                return 0

        bus = probe.LinuxI2C.__new__(probe.LinuxI2C)
        bus.fd = 7
        bus.address = 0x6B
        bus.libc = FakeLibc()
        self.assertEqual(bus.read(0x0F), b"\x70")

    def test_raw_counts_are_little_endian_and_use_selected_full_scales(self):
        gyro, accel = probe.decode_raw(
            bytes.fromhex("e9 ff ca ff 28 00 80 ff be 00 3d 20")
        )
        self.assertAlmostEqual(gyro[0], -0.4025)
        self.assertAlmostEqual(gyro[1], -0.945)
        self.assertAlmostEqual(accel[2], 1.006866)

    def test_fifo_tag_and_half_precision_quaternion(self):
        word = bytes([0x13 << 3]) + struct.pack("<3e", 0.5, 0.0, 0.0)
        quat = probe.decode_fifo_game(word)
        self.assertIsNotNone(quat)
        self.assertAlmostEqual(quat[0], 0.8660254, places=5)
        self.assertAlmostEqual(quat[1], 0.5)
        self.assertIsNone(probe.decode_fifo_game(bytes([0x12 << 3]) + word[1:]))
        self.assertIsNone(probe.decode_fifo_game(bytes([0x13 << 3]) + bytes(6)))

    def test_fifo_reports_latest_valid_vector_and_bad_words(self):
        class FifoBus:
            def __init__(self):
                self.words = [
                    bytes([0x12 << 3]) + struct.pack("<3e", 0.1, 0.0, 0.0),
                    bytes([0x13 << 3]) + bytes(6),
                    bytes([0x13 << 3]) + struct.pack("<3e", 0.5, 0.0, 0.0),
                ]

            def read(self, register, length=1):
                if register == 0x1B:
                    return b"\x03\x08"
                if register == 0x78:
                    return self.words.pop(0)
                raise AssertionError(f"unexpected register 0x{register:02x}")

        quat, level, overrun, unknown, invalid, valid = probe.read_fifo(FifoBus())
        self.assertEqual((level, overrun, unknown, invalid, valid), (3, True, 1, 1, 1))
        self.assertAlmostEqual(quat[1], 0.5)

    def test_configuration_uses_high_performance_and_restores_main_page(self):
        bus = FakeBus()
        with patch.object(probe.time, "sleep"):
            probe.configure_sensor(bus)
        self.assertFalse(bus.page)
        self.assertEqual(bus.main[0x10], 0x06)
        self.assertEqual(bus.main[0x11], 0x06)
        self.assertEqual(bus.main[0x0A], 0x06)
        self.assertEqual(bus.embedded[0x04] & 0x02, 0x02)
        self.assertEqual(bus.embedded[0x44] & 0x02, 0x02)
        self.assertIn((True, 0x5E, 0x5B), bus.writes)
        self.assertNotIn((False, 0x10, 0x36), bus.writes)

    def test_raw_only_configuration_does_not_touch_sflp_page(self):
        bus = FakeBus()
        with patch.object(probe.time, "sleep") as sleep:
            probe.configure_sensor(bus, enable_sflp=False)
        self.assertFalse(bus.page)
        self.assertEqual(bus.main[0x10], 0x06)
        self.assertEqual(bus.main[0x11], 0x06)
        self.assertEqual(bus.main[0x0A], 0x00)
        self.assertFalse(any(page for page, _, _ in bus.writes))
        sleep.assert_not_called()

    def test_raw_only_observation_produces_a_summary_without_fifo_reads(self):
        class RawBus:
            def read(self, register, length=1):
                if (register, length) != (0x22, 12):
                    raise AssertionError(f"unexpected read: {(register, length)}")
                return struct.pack("<6h", 0, 0, 0, 0, 0, 8197)

        with patch("builtins.print"):
            summary = probe.observe(RawBus(), 0.02, 50, None, enable_sflp=False)
        self.assertEqual(summary["mode"], "raw_only")
        self.assertEqual(summary["samples"], 1)
        self.assertEqual(summary["sflp_valid_fifo_words"], 0)
        self.assertTrue(summary["probe_ok"])

    def test_late_wakeup_skips_slots_instead_of_burst_reading(self):
        class Clock:
            now = 0.0
            sleeps = 0
            read_times = []

            def monotonic(self):
                return self.now

            def sleep(self, duration):
                self.sleeps += 1
                self.now += duration + (0.104 if self.sleeps == 2 else 0.0)

        class RawBus:
            def __init__(self, clock):
                self.clock = clock
                self.count = 0

            def read(self, register, length=1):
                self.clock.read_times.append(self.clock.now)
                self.count += 1
                return struct.pack("<6h", self.count, 0, 0, 0, 0, 8197)

        clock = Clock()
        with patch.object(probe.time, "monotonic", clock.monotonic), \
             patch.object(probe.time, "sleep", clock.sleep), \
             patch("builtins.print"):
            summary = probe.observe(RawBus(clock), 0.2, 50, None, enable_sflp=False)
        self.assertEqual(summary["missed_deadlines"], 5)
        self.assertEqual(summary["samples"], 5)
        self.assertAlmostEqual(summary["wake_late_ms_max"], 104.0)
        self.assertEqual(summary["io_ms_max"], 0.0)
        self.assertGreaterEqual(min(
            b - a for a, b in zip(clock.read_times, clock.read_times[1:])
        ), 0.015)
        self.assertFalse(summary["probe_ok"])

    def test_wrong_identity_aborts_before_configuring_sensor(self):
        bus = FakeBus(identity=0x00)
        with self.assertRaisesRegex(RuntimeError, "WHO_AM_I=0x00"):
            probe.configure_sensor(bus)
        self.assertEqual(bus.writes, [(False, 0x01, 0x00)])


if __name__ == "__main__":
    unittest.main()
