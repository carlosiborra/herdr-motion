"""Drift guard for the vendored helpers."""
import hashlib
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "herdr_motion"

VENDORED_SHA256 = {
    "theme.py": "8415c9f04ed162db44bee68753954b58b3229a1a307b26b3f0100d51db482c24",
    "terminal.py": "35fcaf6dd4e8581622e01b9bca0e67c221848d130c11c87e5f17831d65c7741d",
}


class VendoredTest(unittest.TestCase):
    def test_hashes(self):
        for name, expected in VENDORED_SHA256.items():
            actual = hashlib.sha256((SRC / name).read_bytes()).hexdigest()
            self.assertEqual(
                actual,
                expected,
                "%s is a vendored helper and must be changed deliberately. "
                "If the change is intended, update its hash in tests/test_vendored.py "
                "and note it in CHANGELOG.md. New hash: %s" % (name, actual),
            )


if __name__ == "__main__":
    unittest.main()
