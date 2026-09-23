import json
import tempfile
import unittest
from pathlib import Path

from textual._ansi_sequences import ANSI_SEQUENCES_KEYS
from textual._xterm_parser import XTermParser
from textual.keys import Keys

from doc_harness.terminal_keys import _install_binding


class TerminalKeyTests(unittest.TestCase):
    def test_existing_shift_enter_binding_is_decoded_without_editing_terminal_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = json.dumps({
                "keybindings": [{"keys": "shift+enter", "id": "User.shift.newline"}],
                "actions": [{
                    "id": "User.shift.newline",
                    "command": {"action": "sendInput", "input": "\x1b\r"},
                }],
            })
            path.write_text(original, encoding="utf-8")
            previous = ANSI_SEQUENCES_KEYS.get("\x1b\r")
            try:
                self.assertTrue(_install_binding(path))
                events = list(XTermParser().feed("\x1b\r"))
                self.assertEqual([event.key for event in events], ["ctrl+j"])
                self.assertEqual(ANSI_SEQUENCES_KEYS["\x1b\r"], (Keys.ControlJ,))
                self.assertEqual(path.read_text(encoding="utf-8"), original)
            finally:
                if previous is None:
                    ANSI_SEQUENCES_KEYS.pop("\x1b\r", None)
                else:
                    ANSI_SEQUENCES_KEYS["\x1b\r"] = previous

    def test_no_binding_leaves_terminal_behavior_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"actions": [], "keybindings": []}), encoding="utf-8")
            previous = ANSI_SEQUENCES_KEYS.get("\x1b\r")
            self.assertFalse(_install_binding(path))
            self.assertEqual(ANSI_SEQUENCES_KEYS.get("\x1b\r"), previous)
