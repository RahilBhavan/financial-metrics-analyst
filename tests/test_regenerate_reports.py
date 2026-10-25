import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
GUARD = "FINANCIAL_METRICS_REGENERATING"


def snapshot(directory):
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()}


class RegenerateReports(unittest.TestCase):
    def test_regenerating_leaves_committed_reports_unchanged(self):
        # regenerate_reports.py runs evaluate, which discovers this suite; the guard stops the recursion.
        if os.environ.get(GUARD):
            return
        before = snapshot(REPORTS)
        backup = Path(tempfile.mkdtemp())
        try:
            for name, data in before.items():
                (backup / name).write_bytes(data)
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "regenerate_reports.py")],
                                    cwd=str(ROOT), env=dict(os.environ, **{GUARD: "1"}),
                                    capture_output=True, text=True, timeout=300)
            after = snapshot(REPORTS)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(before), sorted(after))
            self.assertEqual([n for n in before if before[n] != after[n]], [])
        finally:
            for name in snapshot(backup):  # restore whatever a failed run rewrote
                (REPORTS / name).write_bytes((backup / name).read_bytes())
            shutil.rmtree(backup)


if __name__ == "__main__":
    unittest.main()
