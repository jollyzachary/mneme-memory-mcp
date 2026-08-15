from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mneme_memory_mcp.env_launcher import configure_environment, parse_env_file


class EnvLauncherTest(unittest.TestCase):
    def test_parse_env_file_reads_basic_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                """
# comment
export MNEME_HOME="/tmp/mneme"
IGNORED LINE
HERMES_HOME=/tmp/hermes
NODE_OPTIONS=--require=./untrusted.js
""".strip(),
                encoding="utf-8",
            )

            values = parse_env_file(env_file)

        self.assertEqual(values["MNEME_HOME"], "/tmp/mneme")
        self.assertEqual(values["HERMES_HOME"], "/tmp/hermes")
        self.assertNotIn("IGNORED LINE", values)
        self.assertNotIn("NODE_OPTIONS", values)

    def test_configure_environment_uses_env_file_before_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            env_file.write_text("MNEME_HOME=.mneme\n", encoding="utf-8")
            environ: dict[str, str] = {}

            configure_environment(
                env_file=env_file,
                default_home=root / ".mneme",
                environ=environ,
            )

        self.assertEqual(environ["MNEME_HOME"], str(root / ".mneme"))
        self.assertEqual(environ["HERMES_HOME"], str(root / ".mneme"))

    def test_configure_environment_keeps_existing_process_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            env_file.write_text("MNEME_HOME=/tmp/project-memory\n", encoding="utf-8")
            environ = {"MNEME_HOME": "/tmp/process-memory"}

            configure_environment(
                env_file=env_file,
                default_home=root / ".mneme",
                environ=environ,
            )

        self.assertEqual(environ["MNEME_HOME"], "/tmp/process-memory")
        self.assertEqual(environ["HERMES_HOME"], "/tmp/process-memory")

    def test_configure_environment_defaults_to_project_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environ: dict[str, str] = {}

            configure_environment(
                env_file=root / ".env",
                default_home=root / ".mneme",
                environ=environ,
            )

        self.assertEqual(environ["MNEME_HOME"], str(root / ".mneme"))
        self.assertEqual(environ["HERMES_HOME"], str(root / ".mneme"))


if __name__ == "__main__":
    unittest.main()
