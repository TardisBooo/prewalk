from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts import check_contracts


ROOT = Path(__file__).resolve().parents[1]


class NativeContractTests(unittest.TestCase):
    def test_repository_contracts(self) -> None:
        check_contracts.validate_repo(ROOT)

    def test_invalid_plain_frontmatter_scalar_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SKILL.md"
            path.write_text(
                "---\nname: broken\ndescription: Arm a run: then route it\n---\n",
                encoding="utf-8",
            )
            with self.assertRaises(check_contracts.ContractError):
                check_contracts.parse_frontmatter(path)


if __name__ == "__main__":
    unittest.main()
