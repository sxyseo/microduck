from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REQUIRED_M6 = {
    "kt": 0.3,
    "R": 2.8,
    "armature": 0.001,
    "q_offset": 0.0,
    "friction_base": 0.004,
    "friction_stribeck": 0.004,
    "load_friction_motor": 0.2,
    "load_friction_external": 0.001,
    "load_friction_motor_stribeck": 0.00001,
    "load_friction_external_stribeck": 0.08,
    "load_friction_motor_quad": 0.01,
    "load_friction_external_quad": 0.005,
    "dtheta_stribeck": 2.8,
    "alpha": 8.0,
    "friction_viscous": 0.005,
    "data_provenance": "measured",
    "hl2915_adapter": {
        "error_gain": 0.1,
        "max_velocity_rpm": 110.0,
        "default_vin": 12.0,
        "default_kp": 16.0,
        "max_pwm": 0.97,
        "max_current_a": 1.5,
    },
}


class CheckBamModelTests(unittest.TestCase):
    def _run(self, payload: dict, *extra: str) -> subprocess.CompletedProcess[bytes]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("check_bam_model.py")),
                    str(path),
                    *extra,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def test_accepts_hl2915_m6_contract(self) -> None:
        payload = {**REQUIRED_M6, "model": "m6", "actuator": "hl2915"}
        result = self._run(payload)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        report = json.loads(result.stdout)
        raw = json.dumps(payload).encode()
        self.assertEqual(report["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["size_bytes"], len(raw))

    def test_rejects_wrong_actuator_name(self) -> None:
        result = self._run({**REQUIRED_M6, "model": "m6", "actuator": "xl330"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("actuator", result.stderr.decode().lower())

    def test_rejects_raw_log_without_model_fields(self) -> None:
        result = self._run({"mass": 0.05, "entries": []})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr.decode())

    def test_rejects_hl2915_model_without_adapter_metadata(self) -> None:
        payload = {**REQUIRED_M6, "model": "m6", "actuator": "hl2915"}
        payload.pop("hl2915_adapter")
        result = self._run(payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hl2915_adapter", result.stderr.decode())

    def test_rejects_hl2915_model_without_data_provenance(self) -> None:
        payload = {**REQUIRED_M6, "model": "m6", "actuator": "hl2915"}
        payload.pop("data_provenance")
        result = self._run(payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("data_provenance", result.stderr.decode())

    def test_allows_synthetic_contract_for_pipeline_smoke(self) -> None:
        payload = {**REQUIRED_M6, "model": "m6", "actuator": "hl2915", "data_provenance": "synthetic"}
        result = self._run(payload)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_self_test_does_not_require_a_json_path(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("check_bam_model.py")),
                "--self-test",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn("self-test", result.stdout.decode().lower())


if __name__ == "__main__":
    unittest.main()
