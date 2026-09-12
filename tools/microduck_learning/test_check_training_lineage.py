from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def _identity(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


class TrainingLineageTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, Path | str]:
        repo = root / "microduck_rl"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "README.md").write_text("training\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git", "-C", str(repo), "-c", "user.name=Test", "-c",
                "user.email=test@example.invalid", "commit", "-qm", "fixture",
            ],
            check=True,
        )
        commit = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        bam = root / "hl2915-m6.json"
        bam.write_text('{"actuator":"hl2915"}\n', encoding="utf-8")
        bam_contract = root / "bam-contract.json"
        bam_contract.write_text(
            json.dumps(
                {
                    "status": "passed", "actuator": "hl2915", "model": "m6",
                    "data_provenance": "measured", "path": str(bam), **_identity(bam),
                }
            ),
            encoding="utf-8",
        )
        onnx = root / "policy.onnx"
        onnx.write_bytes(b"onnx-policy")
        onnx_contract = root / "onnx-contract.json"
        onnx_contract.write_text(
            json.dumps(
                {
                    "path": str(onnx), "input": {"shape": [1, 61]},
                    "output": {"shape": [1, 14]}, "finite_zero_observation": True,
                    **_identity(onnx),
                }
            ),
            encoding="utf-8",
        )
        return {
            "repo": repo, "commit": commit, "bam_contract": bam_contract,
            "onnx": onnx, "onnx_contract": onnx_contract,
        }

    def _run(self, fixture: dict[str, Path | str], output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("check_training_lineage.py")),
                "--bam-contract", str(fixture["bam_contract"]),
                "--onnx-contract", str(fixture["onnx_contract"]),
                "--training-repo", str(fixture["repo"]),
                "--purpose", "candidate",
                "--json-out", str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_measured_candidate_binds_files_and_clean_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            output = root / "lineage.json"
            completed = self._run(fixture, output)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["training_repo"]["commit"], fixture["commit"])
            self.assertTrue(report["training_repo"]["clean"])
            self.assertEqual(report["bam_model"]["data_provenance"], "measured")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)

    def test_changed_onnx_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            Path(fixture["onnx"]).write_bytes(b"different-policy")

            completed = self._run(fixture, root / "lineage.json")

            self.assertNotEqual(completed.returncode, 0)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "failed")
            self.assertIn("ONNX file identity does not match its contract", report["errors"])

    def test_dirty_training_repo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            (Path(fixture["repo"]) / "untracked.txt").write_text("dirty\n", encoding="utf-8")

            completed = self._run(fixture, root / "lineage.json")

            self.assertNotEqual(completed.returncode, 0)
            report = json.loads(completed.stdout)
            self.assertFalse(report["training_repo"]["clean"])
            self.assertIn("training repo is not clean", report["errors"])

    def test_malformed_onnx_contract_is_reported_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture(root)
            contract_path = Path(fixture["onnx_contract"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["input"] = []
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            completed = self._run(fixture, root / "lineage.json")

            self.assertNotEqual(completed.returncode, 0)
            self.assertNotIn("Traceback", completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["status"], "failed")
            self.assertIn(
                "ONNX contract must pass obs[1,61] -> actions[1,14] CPU inference",
                report["errors"],
            )


if __name__ == "__main__":
    unittest.main()
