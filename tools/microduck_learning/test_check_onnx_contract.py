from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from check_onnx_contract import file_identity


class OnnxContractTests(unittest.TestCase):
    def test_file_identity_contains_size_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "policy.onnx"
            model.write_bytes(b"policy")

            identity = file_identity(model)

        self.assertEqual(identity["sha256"], hashlib.sha256(b"policy").hexdigest())
        self.assertEqual(identity["size_bytes"], 6)


if __name__ == "__main__":
    unittest.main()
