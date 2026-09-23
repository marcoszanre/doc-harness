import unittest
from unittest.mock import MagicMock, patch

from doc_harness.__main__ import main


class LauncherTests(unittest.TestCase):
    def test_restart_reopens_workspace_chooser_without_erasing_files(self):
        first = MagicMock()
        first.run.return_value = "restart"
        second = MagicMock()
        second.run.return_value = None
        with (
            patch("sys.argv", ["doc-harness"]),
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdout.isatty", return_value=True),
            patch("doc_harness.__main__.ReadingApp", side_effect=[first, second]) as apps,
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(apps.call_count, 2)
        self.assertIsNone(apps.call_args_list[0].args[0])
        self.assertIsNone(apps.call_args_list[1].args[0])
