#!/usr/bin/env python3
"""Small regression tests for the board report's read-only evidence rules."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from board_readonly_report import collect_report  # noqa: E402


class BoardReportTests(unittest.TestCase):
    def test_missing_hardware_is_not_reported_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = collect_report(Path(directory), machine="aarch64", command_runner=lambda *_: None)

        self.assertEqual(report["status"], "incomplete")
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["serial" ]["status"], "missing")
        self.assertEqual(checks["imu"]["status"], "unknown")
        self.assertEqual(checks["camera" ]["status"], "missing")
        self.assertEqual(checks["mpp" ]["status"], "missing")

    def test_fixture_nodes_and_tools_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("dev/ttyS2", "dev/i2c-pihat", "dev/video0", "dev/mpp_service", "dev/rga"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            name = root / "sys/class/video4linux/video0/name"
            name.parent.mkdir(parents=True, exist_ok=True)
            name.write_text("rkisp_mainpath\n", encoding="utf-8")

            def runner(command: list[str]) -> str | None:
                if command[:2] == ["gst-inspect-1.0", "--version"]:
                    return "gst-inspect-1.0 version 1.26.2"
                if command[0] == "gst-inspect-1.0":
                    return "element present"
                return None

            report = collect_report(root, machine="aarch64", command_runner=runner)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(report["status"], "ready")
        self.assertEqual(checks["serial"]["status"], "pass")
        self.assertEqual(checks["hat_i2c"]["status"], "pass")
        self.assertEqual(checks["camera"]["status"], "pass")
        self.assertEqual(checks["camera_mainpath"]["status"], "pass")
        self.assertEqual(checks["mpp"]["status"], "pass")
        self.assertEqual(checks["gstreamer"]["status"], "pass")

    def test_video_node_without_rkisp_mainpath_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("dev/ttyS2", "dev/i2c-pihat", "dev/video0", "dev/mpp_service"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            report = collect_report(root, machine="aarch64", command_runner=lambda *_: None)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["camera"]["status"], "pass")
        self.assertEqual(checks["camera_mainpath"]["status"], "missing")
        self.assertEqual(report["status"], "incomplete")

    def test_old_gstreamer_is_not_ready_even_when_elements_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("dev/ttyS2", "dev/i2c-pihat", "dev/video0", "dev/mpp_service", "dev/rga"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            name = root / "sys/class/video4linux/video0/name"
            name.parent.mkdir(parents=True, exist_ok=True)
            name.write_text("rkisp_mainpath\n", encoding="utf-8")

            def runner(command: list[str]) -> str | None:
                if command[:2] == ["gst-inspect-1.0", "--version"]:
                    return "gst-inspect-1.0 version 1.20.3"
                if command[0] == "gst-inspect-1.0":
                    return "element present"
                return None

            report = collect_report(root, machine="aarch64", command_runner=runner)

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["gstreamer"]["status"], "missing")
        self.assertEqual(report["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
