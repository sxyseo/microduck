from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_servo_candidate import evaluate_candidate


class CandidateGateTests(unittest.TestCase):
    def test_missing_datasheet_fields_stays_insufficient(self) -> None:
        result = evaluate_candidate({"model": "unknown"})
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn("voltage_min_v", result["missing_fields"])

    def test_same_bus_candidate_is_only_ready_for_bench(self) -> None:
        result = evaluate_candidate(
            {
                "model": "candidate-v1",
                "voltage_min_v": 9,
                "voltage_max_v": 14,
                "protocol": "feetech_v1",
                "signal": "ttl_half_duplex",
                "position_counts": 4096,
                "position_range_deg": 360,
                "spline_teeth": 25,
                "torque_kgcm": 10,
                "datasheet_confirmed": True,
            }
        )
        self.assertEqual(result["status"], "profile_candidate")
        self.assertFalse(result["hardware_passed"])
        self.assertIn("bench", result["next_steps"][0].lower())

    def test_six_volt_low_torque_candidate_is_not_a_leg_replacement(self) -> None:
        result = evaluate_candidate(
            {
                "model": "low-load-v1",
                "voltage_min_v": 4.8,
                "voltage_max_v": 6.0,
                "protocol": "feetech_v1",
                "signal": "ttl_half_duplex",
                "position_counts": 4096,
                "position_range_deg": 360,
                "spline_teeth": 25,
                "torque_kgcm": 4.5,
                "datasheet_confirmed": True,
            }
        )
        self.assertEqual(result["status"], "low_load_power_variant")
        self.assertIn("separate_power", result["blockers"])
        self.assertIn("low_load_only", result["blockers"])

    def test_different_bus_requires_new_driver(self) -> None:
        result = evaluate_candidate(
            {
                "model": "rs485-v1",
                "voltage_min_v": 9,
                "voltage_max_v": 14,
                "protocol": "modbus_rtu",
                "signal": "rs485",
                "position_counts": 4096,
                "position_range_deg": 360,
                "spline_teeth": 25,
                "torque_kgcm": 14,
                "datasheet_confirmed": True,
            }
        )
        self.assertEqual(result["status"], "new_bus_driver")
        self.assertIn("new_driver", result["blockers"])

    def test_nonphysical_ranges_are_insufficient_data(self) -> None:
        result = evaluate_candidate(
            {
                "model": "bad-v1",
                "voltage_min_v": 14,
                "voltage_max_v": 6,
                "protocol": "feetech_v1",
                "signal": "ttl_half_duplex",
                "position_counts": 0,
                "position_range_deg": 360,
                "spline_teeth": 25,
                "torque_kgcm": -1,
                "datasheet_confirmed": True,
            }
        )
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn("voltage_min_v", result["missing_fields"])
        self.assertIn("position_counts", result["missing_fields"])
        self.assertIn("torque_kgcm", result["missing_fields"])

    def test_cli_writes_machine_readable_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidate.json"
            output = root / "report.json"
            source.write_text(json.dumps({"model": "unknown"}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("check_servo_candidate.py")),
                    str(source),
                    "--json-out",
                    str(output),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
