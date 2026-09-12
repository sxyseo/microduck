from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from validate_hl2915_probe_log import validate_text


VALID = """端口 COM3 @ 1Mbps；请求 ID=[1]；响应=[1]
ID 1: position=2048 (180.00°), speed_raw=0, load_raw=0, status=0, moving=0, current=65.0mA, voltage=12.0V, temp=30°C
"""


class ProbeLogTests(unittest.TestCase):
    def test_accepts_one_servo_with_healthy_state(self) -> None:
        result = validate_text(VALID, [1])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["responded_ids"], [1])

    def test_rejects_missing_or_duplicate_response_ids(self) -> None:
        result = validate_text(VALID.replace("响应=[1]", "响应=[1, 2]"), [1])
        self.assertEqual(result["status"], "failed")
        self.assertIn("response_ids", result["failures"])

    def test_rejects_fault_and_voltage(self) -> None:
        text = VALID.replace("status=0", "status=4").replace("voltage=12.0V", "voltage=8.5V")
        result = validate_text(text, [1])
        self.assertEqual(result["status"], "failed")
        self.assertIn("status", result["failures"])
        self.assertIn("voltage", result["failures"])

    def test_missing_state_is_insufficient(self) -> None:
        result = validate_text("端口 COM3 @ 1Mbps；请求 ID=[1]；响应=[1]\n", [1])
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn(1, result["missing_ids"])

    def test_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "probe.txt"
            output = root / "report.json"
            source.write_text(VALID, encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("validate_hl2915_probe_log.py")),
                    str(source),
                    "--ids",
                    "1",
                    "--json-out",
                    str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "passed")

    def test_cli_accepts_windows_powershell_utf16_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "probe-utf16.txt"
            source.write_bytes(VALID.encode("utf-16"))
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("validate_hl2915_probe_log.py")),
                    str(source),
                    "--ids",
                    "1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
