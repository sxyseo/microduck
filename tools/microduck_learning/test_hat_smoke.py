from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from hat_smoke import i2c_address_present, validate


def _payload() -> dict:
    return {
        "schema_version": 1,
        "source": "radxa",
        "machine": "aarch64",
        "data_provenance": "measured",
        "hardware": "pollen-rpi-robot-hat",
        "codec": {"status": "passed", "address": "0x18"},
        "capture": {"status": "passed", "bytes": 192044},
        "playback": {"status": "passed"},
        "audible_confirmed": True,
    }


class HatSmokeTests(unittest.TestCase):
    def test_measured_codec_capture_and_playback_pass(self) -> None:
        self.assertEqual(validate(_payload())["status"], "passed")

    def test_synthetic_or_unconfirmed_audio_is_rejected(self) -> None:
        payload = _payload()
        payload["data_provenance"] = "synthetic"
        payload["audible_confirmed"] = False

        result = validate(payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("data_provenance must be measured", result["errors"])
        self.assertIn("audible_confirmed must be true", result["errors"])

    def test_wrong_codec_or_empty_capture_is_rejected(self) -> None:
        payload = _payload()
        payload["codec"]["address"] = "0x19"
        payload["capture"]["bytes"] = 44

        result = validate(payload)

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("codec" in error for error in result["errors"]))
        self.assertTrue(any("capture" in error for error in result["errors"]))

    def test_unknown_schema_is_rejected(self) -> None:
        payload = _payload()
        payload["schema_version"] = 2

        result = validate(payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("schema_version must be 1", result["errors"])

    def test_i2c_parser_accepts_exact_address_or_bound_driver(self) -> None:
        scan = """     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
10: -- -- -- -- -- -- -- -- UU -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
"""
        self.assertTrue(i2c_address_present(scan, 0x18))
        self.assertFalse(i2c_address_present(scan, 0x19))

    def test_cli_refuses_to_scan_an_unconfirmed_hat(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("hat_smoke.py")), "--run"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--confirm-official-hat", completed.stderr)

    def test_cli_self_test_matches_the_current_schema(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("hat_smoke.py")), "--self-test"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("self-test passed", completed.stdout)


if __name__ == "__main__":
    unittest.main()
