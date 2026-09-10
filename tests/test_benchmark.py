from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark.py"


class BenchmarkTests(unittest.TestCase):
    def test_record_and_report_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "runs.jsonl"
            common = ["--task", "adapter change", "--duration-seconds", "20", "--passed"]
            subprocess.run(
                [sys.executable, str(SCRIPT), "record", str(data), "--mode", "baseline",
                 "--input-tokens", "900", "--output-tokens", "100", *common],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                [sys.executable, str(SCRIPT), "record", str(data), "--mode", "prewalk",
                 "--input-tokens", "600", "--output-tokens", "100", *common],
                check=True, capture_output=True, text=True,
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "report", str(data)],
                check=True, capture_output=True, text=True,
            )
            self.assertIn("baseline", result.stdout)
            self.assertIn("prewalk", result.stdout)
            self.assertIn("-30.0%", result.stdout)
