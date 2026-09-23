import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_harness.foundry import ENDPOINT_ENV, load_endpoint, save_local_endpoint, validate_endpoint


class FoundryConfigurationTests(unittest.TestCase):
    def test_endpoint_is_saved_outside_project_and_loaded_again(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "user-settings.json"
            with (
                patch("doc_harness.foundry.CONFIG_PATH", config),
                patch.dict("os.environ", {ENDPOINT_ENV: ""}),
            ):
                save_local_endpoint("https://example.invalid/openai/v1/chat/completions")
                self.assertEqual(load_endpoint(), "https://example.invalid/openai/v1/")
                self.assertTrue(config.is_file())

    def test_environment_override_and_invalid_endpoint_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("doc_harness.foundry.CONFIG_PATH", Path(directory) / "missing.json"),
                patch.dict("os.environ", {ENDPOINT_ENV: "https://example.invalid/openai/v1/"}),
            ):
                self.assertEqual(load_endpoint(), "https://example.invalid/openai/v1/")
            with self.assertRaisesRegex(ValueError, "HTTPS Foundry"):
                validate_endpoint("http://example.invalid/openai/v1/")
