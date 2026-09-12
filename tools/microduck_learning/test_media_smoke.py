from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from media_smoke import validate


def _payload() -> dict:
    return {
        "schema_version": 1,
        "source": "radxa",
        "data_provenance": "measured",
        "camera_capture": {"status": "passed", "frames": 60, "bytes": 13824000},
        "hardware_encode": {"status": "passed", "bytes": 476000},
        "decode": {"status": "passed"},
        "webrtc_elements": {"status": "passed", "elements": ["webrtcbin", "webrtcsink"]},
    }


class MediaSmokeTests(unittest.TestCase):
    def test_measured_capture_encode_decode_is_passed(self) -> None:
        result = validate(_payload())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["camera_frames"], 60)

    def test_synthetic_or_empty_media_is_rejected(self) -> None:
        payload = _payload()
        payload["data_provenance"] = "synthetic"
        result = validate(payload)
        self.assertEqual(result["status"], "failed")
        self.assertIn("data_provenance must be measured", result["errors"])

    def test_missing_capture_evidence_is_rejected(self) -> None:
        payload = _payload()
        payload["camera_capture"]["bytes"] = 0
        result = validate(payload)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("camera_capture" in error for error in result["errors"]))

    def test_cli_reads_json_and_returns_failure_for_bad_contract(self) -> None:
        payload = _payload()
        payload["hardware_encode"]["status"] = "failed"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "media.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(validate(json.loads(path.read_text(encoding="utf-8")))["status"], "failed")


if __name__ == "__main__":
    unittest.main()
