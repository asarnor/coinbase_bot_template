#!/usr/bin/env python3
"""Regression tests for hosted deployment execution safety."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import app_entrypoint


class AppEntrypointSafetyTests(unittest.TestCase):
    @patch("app_entrypoint.subprocess.run")
    def test_bot_defaults_to_simulation(self, run):
        run.return_value.returncode = 0

        with patch.dict(os.environ, {"APP_ROLE": "bot"}, clear=True):
            self.assertEqual(app_entrypoint.main(), 0)

        command = run.call_args.args[0]
        self.assertEqual(command[-1], "main_multi_symbol.py")
        self.assertNotIn("--execute", command)

    @patch("app_entrypoint.subprocess.run")
    def test_bot_execute_must_be_explicitly_enabled(self, run):
        run.return_value.returncode = 0

        with patch.dict(
            os.environ,
            {"APP_ROLE": "bot", "BOT_EXECUTE": "true"},
            clear=True,
        ):
            self.assertEqual(app_entrypoint.main(), 0)

        self.assertEqual(
            run.call_args.args[0],
            [app_entrypoint.sys.executable, "main_multi_symbol.py", "--execute"],
        )

    def test_render_routes_through_safe_entrypoint(self):
        manifest = Path(__file__).with_name("render.yaml").read_text()

        self.assertIn("startCommand: python app_entrypoint.py", manifest)
        self.assertIn("key: BOT_EXECUTE", manifest)
        self.assertNotIn("startCommand: python main.py --execute", manifest)


if __name__ == "__main__":
    unittest.main()
