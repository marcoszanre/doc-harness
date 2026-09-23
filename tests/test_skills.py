import subprocess
import sys
import unittest
from pathlib import Path


class SkillPackagingTests(unittest.TestCase):
    def test_guides_load_when_started_from_repository_parent(self):
        parent = Path(__file__).resolve().parents[2]
        script = "from doc_harness.skills import read_skill; assert 'Begin with' in read_skill('guide')"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=parent,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
