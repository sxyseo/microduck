from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from bringup_status import build_status


class BringupStatusTests(unittest.TestCase):
    def test_cli_output_is_utf8(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("bringup_status.py"))],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        output = completed.stdout.decode("utf-8")
        self.assertIn("下一步：", output)

    def test_empty_inputs_are_pending_not_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)
        self.assertEqual(report["status"], "pending")
        self.assertTrue(any(gate["status"] == "manual" for gate in report["gates"]))
        board_gate = next(gate for gate in report["gates"] if gate["gate"] == "S4 Radxa")
        self.assertEqual(
            board_gate["next"],
            "python tools/microduck_learning/board_readonly_report.py --json-out artifacts/board-readonly-report.json",
        )
        media_gate = next(gate for gate in report["gates"] if gate["gate"] == "S6 camera/HAT media")
        self.assertIn("没有板卡报告", media_gate["evidence"])
        self.assertIn("board_readonly_report.py", media_gate["next"])
        self.assertEqual(
            next(gate for gate in report["gates"] if gate["gate"] == "BAM model")["next"],
            "先运行 python tools/microduck_learning/check_bam_model.py",
        )
        self.assertEqual(
            next(gate for gate in report["gates"] if gate["gate"] == "S7 ONNX")["next"],
            "导出 ONNX 后运行 python tools/microduck_learning/check_onnx_contract.py",
        )
        self.assertEqual(
            next(gate for gate in report["gates"] if gate["gate"] == "S7 training lineage")["status"],
            "pending",
        )
        self.assertEqual(
            next(gate for gate in report["gates"] if gate["gate"] == "S3 bench CSV")["next"],
            "cargo +1.89.0 run -p duck-control --bin hl2915_record -- COMx 1 2 --seconds 600 --output artifacts/hl2915-bench.csv --hz 50",
        )
        self.assertEqual(
            next(gate for gate in report["gates"] if gate["gate"] == "S5 IMU/mixed")["next"],
            "cargo +1.89.0 run -p duck-control --bin hl2915_mixed_probe -- COMx 1 2 --watch-seconds 60",
        )
        self.assertEqual(
            next(gate for gate in report["gates"] if gate["gate"] == "BAM data")["next"],
            "先完成 S3，再用 hl2915_bam_record 做受限摆锤采样",
        )

    def test_valid_board_and_onnx_evidence_are_recognised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            board = {
                "checks": [
                    {"name": name, "status": "pass"}
                    for name in ("architecture", "serial", "hat_i2c", "hat_audio", "camera", "camera_mainpath", "mpp", "rga", "gstreamer")
                ]
            }
            bench = {"status": "passed", "ids": [1, 2]}
            contract = {
                "input": {"shape": [1, 61]},
                "output": {"shape": [1, 14]},
                "finite_zero_observation": True,
                "sha256": "a" * 64,
                "size_bytes": 123,
            }
            entry = {
                "timestamp": 0.0,
                "goal_position": 0.0,
                "torque_enable": True,
                "position": 0.0,
                "speed": 0.0,
                "input_volts": 12.0,
                "temp": 30,
                "current_ma": 100.0,
                "status": 0,
                "moving": 0,
            }
            bam = {
                "mass": 0.05,
                "arm_mass": 0.0,
                "length": 0.1,
                "kp": 16,
                "vin": 12.0,
                "motor": "hl2915",
                "trajectory": "test",
                "entries": [entry, {**entry, "timestamp": 0.01}],
            }
            (root / "board.json").write_text(json.dumps(board), encoding="utf-8")
            (root / "bench.json").write_text(json.dumps(bench), encoding="utf-8")
            (root / "onnx.json").write_text(json.dumps(contract), encoding="utf-8")
            (root / "lineage.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "purpose": "candidate",
                        "training_repo": {"commit": "b" * 40, "clean": True},
                        "bam_model": {
                            "actuator": "hl2915", "model": "m6",
                            "data_provenance": "measured", "sha256": "c" * 64,
                            "size_bytes": 123,
                        },
                        "onnx": {"sha256": "a" * 64, "size_bytes": 123},
                        "errors": [],
                    }
                ),
                encoding="utf-8",
            )
            (root / "bam.json").write_text(json.dumps(bam), encoding="utf-8")
            (root / "servo-a.json").write_text(
                json.dumps({"status": "passed", "expected_ids": [1], "responded_ids": [1]}),
                encoding="utf-8",
            )
            (root / "servo-b.json").write_text(
                json.dumps({"status": "passed", "expected_ids": [2], "responded_ids": [2]}),
                encoding="utf-8",
            )
            (root / "media.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": "radxa",
                        "data_provenance": "measured",
                        "camera_capture": {"status": "passed", "frames": 60, "bytes": 1000},
                        "hardware_encode": {"status": "passed", "bytes": 1000},
                        "decode": {"status": "passed"},
                        "webrtc_elements": {"status": "passed"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "hat.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": "radxa",
                        "machine": "aarch64",
                        "data_provenance": "measured",
                        "hardware": "pollen-rpi-robot-hat",
                        "codec": {"status": "passed", "address": "0x18"},
                        "capture": {"status": "passed", "bytes": 1000},
                        "playback": {"status": "passed"},
                        "audible_confirmed": True,
                    }
                ),
                encoding="utf-8",
            )
            (root / "mixed.txt").write_text(
                "watch complete: samples=100, errors=0, stale_imu=0, max_stale_run=0, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=root / "board.json",
                bench_summary=root / "bench.json",
                mixed_log=root / "mixed.txt",
                bam_log=root / "bam.json",
                bam_model_contract=root / "bam-model.json",
                onnx_contract=root / "onnx.json",
                training_lineage=root / "lineage.json",
                servo_a_validation=root / "servo-a.json",
                servo_b_validation=root / "servo-b.json",
                media_smoke=root / "media.json",
                hat_smoke=root / "hat.json",
                confirm_ids=True,
                confirm_s8=True,
            )
            (root / "bam-model.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "actuator": "hl2915",
                        "model": "m6",
                        "adapter_metadata": {"error_gain": 0.1},
                        "data_provenance": "measured",
                        "sha256": "c" * 64,
                        "size_bytes": 123,
                    }
                ),
                encoding="utf-8",
            )
            report = build_status(args)
        gates = {gate["gate"]: gate for gate in report["gates"]}
        self.assertEqual(gates["S3 bench CSV"]["status"], "passed")
        self.assertEqual(gates["S4 Radxa"]["status"], "passed")
        self.assertEqual(gates["S5 IMU/mixed"]["status"], "passed")
        self.assertEqual(gates["S6 camera/HAT media"]["status"], "passed")
        self.assertEqual(gates["S7 ONNX"]["status"], "passed")
        self.assertEqual(gates["S7 training lineage"]["status"], "passed")
        self.assertEqual(gates["BAM data"]["status"], "passed")
        self.assertEqual(gates["BAM model"]["status"], "passed")
        self.assertEqual(report["status"], "ready")

    def test_smoke_training_lineage_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lineage.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1, "status": "passed", "purpose": "smoke",
                        "training_repo": {"commit": "b" * 40, "clean": True},
                        "bam_model": {
                            "actuator": "hl2915", "model": "m6",
                            "data_provenance": "measured", "sha256": "c" * 64,
                            "size_bytes": 123,
                        },
                        "onnx": {"sha256": "a" * 64, "size_bytes": 123},
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None, bench_summary=None, mixed_log=None, bam_log=None,
                bam_model_contract=None, onnx_contract=None, training_lineage=path,
                confirm_ids=False, confirm_s8=False,
            )

            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S7 training lineage")
        self.assertEqual(gate["status"], "pending")
        self.assertIn("smoke", gate["evidence"])

    def test_failed_training_lineage_fails_bringup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lineage.json"
            path.write_text(
                json.dumps({"schema_version": 1, "status": "failed", "errors": ["training repo is not clean"]}),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None, bench_summary=None, mixed_log=None, bam_log=None,
                bam_model_contract=None, onnx_contract=None, training_lineage=path,
                confirm_ids=False, confirm_s8=False,
            )

            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S7 training lineage")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("not clean", gate["evidence"])

    def test_pc_with_a_serial_port_is_not_radxa_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.json"
            path.write_text(
                json.dumps(
                    {
                        "checks": [
                            {"name": "architecture", "status": "warn"},
                            {"name": "serial", "status": "pass"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=path,
                bench_summary=None,
                mixed_log=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)
        # A real report with a serial node but a non-aarch64 architecture must remain pending.
        self.assertEqual(next(g for g in report["gates"] if g["gate"] == "S4 Radxa")["status"], "pending")

    def test_onnx_contract_without_file_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "onnx.json"
            path.write_text(
                json.dumps(
                    {
                        "input": {"shape": [1, 61]},
                        "output": {"shape": [1, 14]},
                        "finite_zero_observation": True,
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=path,
                confirm_ids=False,
                confirm_s8=False,
            )

            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S7 ONNX")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("SHA-256", gate["evidence"])

    def test_media_gate_needs_hat_functional_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            board = {
                "checks": [
                    {"name": name, "status": "pass"}
                    for name in (
                        "architecture",
                        "serial",
                        "hat_i2c",
                        "hat_audio",
                        "camera",
                        "camera_mainpath",
                        "mpp",
                        "rga",
                        "gstreamer",
                    )
                ]
            }
            media = {
                "source": "radxa",
                "data_provenance": "measured",
                "camera_capture": {"status": "passed", "frames": 60, "bytes": 1000},
                "hardware_encode": {"status": "passed", "bytes": 1000},
                "decode": {"status": "passed"},
                "webrtc_elements": {"status": "passed"},
            }
            (root / "board.json").write_text(json.dumps(board), encoding="utf-8")
            (root / "media.json").write_text(json.dumps(media), encoding="utf-8")
            args = SimpleNamespace(
                board_report=root / "board.json",
                bench_summary=None,
                mixed_log=None,
                media_smoke=root / "media.json",
                hat_smoke=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )

            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S6 camera/HAT media")
        self.assertEqual(gate["status"], "pending")
        self.assertIn("HAT", gate["evidence"])

    def test_servo_validation_reports_feed_s1_s2_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "servo-a.json").write_text(
                json.dumps({"status": "passed", "expected_ids": [1], "responded_ids": [1]}),
                encoding="utf-8",
            )
            (root / "servo-b.json").write_text(
                json.dumps({"status": "passed", "expected_ids": [2], "responded_ids": [2]}),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                servo_a_validation=root / "servo-a.json",
                servo_b_validation=root / "servo-b.json",
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)
            gate = next(item for item in report["gates"] if item["gate"] == "S0/S1/S2 servo IDs")
            self.assertEqual(gate["status"], "manual")
            self.assertIn("ID=1/2 日志通过", gate["evidence"])

            args.confirm_ids = True
            report = build_status(args)
        gate = next(item for item in report["gates"] if item["gate"] == "S0/S1/S2 servo IDs")
        self.assertEqual(gate["status"], "passed")

    def test_failed_servo_validation_cannot_be_overridden_manually(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "servo-a.json").write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            (root / "servo-b.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                servo_a_validation=root / "servo-a.json",
                servo_b_validation=root / "servo-b.json",
                confirm_ids=True,
                confirm_s8=False,
            )
            report = build_status(args)
        gate = next(item for item in report["gates"] if item["gate"] == "S0/S1/S2 servo IDs")
        self.assertEqual(gate["status"], "failed")

    def test_one_servo_validation_is_pending_even_with_manual_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "servo-a.json"
            path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=None,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                servo_a_validation=path,
                servo_b_validation=None,
                confirm_ids=True,
                confirm_s8=False,
            )
            report = build_status(args)
        gate = next(item for item in report["gates"] if item["gate"] == "S0/S1/S2 servo IDs")
        self.assertEqual(gate["status"], "pending")

    def test_manual_confirmation_cannot_replace_missing_servo_validations(self) -> None:
        args = SimpleNamespace(
            board_report=None,
            bench_summary=None,
            mixed_log=None,
            bam_log=None,
            bam_model_contract=None,
            onnx_contract=None,
            servo_a_validation=None,
            servo_b_validation=None,
            confirm_ids=True,
            confirm_s8=False,
        )
        report = build_status(args)
        gate = next(item for item in report["gates"] if item["gate"] == "S0/S1/S2 servo IDs")
        self.assertEqual(gate["status"], "pending")

    def test_missing_servo_validations_are_pending_without_confirmation(self) -> None:
        args = SimpleNamespace(
            board_report=None,
            bench_summary=None,
            mixed_log=None,
            bam_log=None,
            bam_model_contract=None,
            onnx_contract=None,
            servo_a_validation=None,
            servo_b_validation=None,
            confirm_ids=False,
            confirm_s8=False,
        )

        report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S0/S1/S2 servo IDs")
        self.assertEqual(gate["status"], "pending")

    def test_mixed_log_parser_requires_zero_faults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.txt"
            path.write_text(
                "watch complete: samples=2, errors=0, stale_imu=0, max_stale_run=0, imu_ready=true, "
                "status_faults=0, voltage_faults=1, temperature_faults=0, current_faults=0\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=path,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)
        gate = next(item for item in report["gates"] if item["gate"] == "S5 IMU/mixed")
        self.assertEqual(gate["status"], "failed")

    def test_mixed_log_rejects_zero_samples_even_if_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.txt"
            path.write_text(
                "watch complete: samples=0, errors=0, stale_imu=0, max_stale_run=0, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=path,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S5 IMU/mixed")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("samples=0", gate["evidence"])

    def test_mixed_log_rejects_fully_frozen_imu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.txt"
            path.write_text(
                "watch complete: samples=100, errors=0, stale_imu=99, max_stale_run=99, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=path,
                bam_log=None,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S5 IMU/mixed")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("stale_imu=99", gate["evidence"])

    def test_mixed_log_rejects_a_25_sample_frozen_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.txt"
            path.write_text(
                "watch complete: samples=100, errors=0, stale_imu=25, max_stale_run=25, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None, bench_summary=None, mixed_log=path, bam_log=None,
                bam_model_contract=None, onnx_contract=None, confirm_ids=False, confirm_s8=False,
            )
            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S5 IMU/mixed")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("max_stale_run=25", gate["evidence"])

    def test_mixed_log_requires_current_max_stale_run_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mixed.txt"
            path.write_text(
                "watch complete: samples=100, errors=0, stale_imu=0, imu_ready=true, "
                "status_faults=0, voltage_faults=0, temperature_faults=0, current_faults=0\n",
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None, bench_summary=None, mixed_log=path, bam_log=None,
                bam_model_contract=None, onnx_contract=None, confirm_ids=False, confirm_s8=False,
            )
            report = build_status(args)

        gate = next(item for item in report["gates"] if item["gate"] == "S5 IMU/mixed")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("使用当前版本", gate["next"])

    def test_fitted_model_is_not_misreported_as_raw_bam_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(
                json.dumps({"actuator": "hl2915", "model": "m6", "kt": 1.0}),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                board_report=None,
                bench_summary=None,
                mixed_log=None,
                bam_log=path,
                bam_model_contract=None,
                onnx_contract=None,
                confirm_ids=False,
                confirm_s8=False,
            )
            report = build_status(args)
        gate = next(item for item in report["gates"] if item["gate"] == "BAM data")
        self.assertEqual(gate["status"], "failed")
        self.assertIn("拟合模型", gate["evidence"])


if __name__ == "__main__":
    unittest.main()
