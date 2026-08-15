from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mneme_memory_mcp.continuity import (
    MANAGED_START,
    MNEME_CAPTURE_HOOK_NAME,
    MNEME_CODEX_NOTIFY_NAME,
    MNEME_HOOK_NAME,
    MNEME_PROMPT_HOOK_NAME,
    ContinuityPaths,
    _read_notify_values,
    continuity_status,
    default_paths,
    install_continuity,
)


class ContinuityTest(unittest.TestCase):
    def make_paths(self, root: Path) -> ContinuityPaths:
        home = root / "home"
        return ContinuityPaths(
            memory_home=root / "memory",
            bin_dir=root / "repo" / ".venv" / ("Scripts" if os.name == "nt" else "bin"),
            codex_agents=home / ".codex" / "AGENTS.md",
            codex_config=home / ".codex" / "config.toml",
            codex_notify_wrapper=home / ".codex" / MNEME_CODEX_NOTIFY_NAME,
            claude_md=home / ".claude" / "CLAUDE.md",
            claude_settings=home / ".claude" / "settings.json",
            claude_user_config=home / ".claude.json",
            claude_hook=home / ".claude" / "hooks" / MNEME_HOOK_NAME,
            claude_prompt_hook=home / ".claude" / "hooks" / MNEME_PROMPT_HOOK_NAME,
            claude_capture_hook=home / ".claude" / "hooks" / MNEME_CAPTURE_HOOK_NAME,
        )

    def test_default_bin_dir_preserves_virtualenv_entrypoint(self) -> None:
        with patch(
            "mneme_memory_mcp.continuity.sys.executable",
            "/tmp/mneme-managed-venv/bin/python",
        ):
            paths = default_paths()
        self.assertEqual(paths.bin_dir, Path("/tmp/mneme-managed-venv/bin"))

    def test_install_continuity_preserves_existing_files_and_is_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_paths(root)
            paths.codex_agents.parent.mkdir(parents=True)
            paths.claude_md.parent.mkdir(parents=True)
            paths.codex_agents.write_text("# Existing Codex Notes\n", encoding="utf-8")
            paths.claude_md.write_text("# Existing Claude Notes\n", encoding="utf-8")
            paths.claude_settings.write_text(
                json.dumps({"enabledPlugins": {"codex@openai-codex": True}}),
                encoding="utf-8",
            )
            paths.codex_config.parent.mkdir(parents=True, exist_ok=True)
            paths.codex_config.write_text(
                'notify = ["/usr/local/bin/existing-notify", "turn-ended"]\n',
                encoding="utf-8",
            )

            first = install_continuity(paths)
            second = install_continuity(paths)

            codex_text = paths.codex_agents.read_text(encoding="utf-8")
            claude_text = paths.claude_md.read_text(encoding="utf-8")
            settings = json.loads(paths.claude_settings.read_text(encoding="utf-8"))
            claude_user_config = json.loads(
                paths.claude_user_config.read_text(encoding="utf-8")
            )
            codex_config = paths.codex_config.read_text(encoding="utf-8")
            notify_wrapper = paths.codex_notify_wrapper.read_text(encoding="utf-8")
            capture_script = paths.claude_capture_hook.read_text(encoding="utf-8")
            notify_values = _read_notify_values(codex_config)
            hook_executable = os.access(paths.claude_hook, os.X_OK)
            prompt_hook_executable = os.access(paths.claude_prompt_hook, os.X_OK)
            capture_hook_executable = os.access(paths.claude_capture_hook, os.X_OK)
            notify_executable = os.access(paths.codex_notify_wrapper, os.X_OK)

        self.assertTrue(first.codex_instructions)
        self.assertTrue(second.claude_sessionstart_hook)
        self.assertTrue(second.claude_userprompt_hook)
        self.assertTrue(second.claude_stop_capture_hook)
        self.assertTrue(second.claude_sessionend_capture_hook)
        self.assertTrue(second.claude_mcp_config)
        self.assertTrue(second.codex_notify_capture)
        self.assertIn("# Existing Codex Notes", codex_text)
        self.assertIn("# Existing Claude Notes", claude_text)
        self.assertEqual(codex_text.count(MANAGED_START), 1)
        self.assertEqual(claude_text.count(MANAGED_START), 1)
        self.assertTrue(hook_executable)
        self.assertTrue(prompt_hook_executable)
        self.assertTrue(capture_hook_executable)
        self.assertTrue(notify_executable)
        self.assertEqual(settings["enabledPlugins"]["codex@openai-codex"], True)
        self.assertIn("SessionStart", settings["hooks"])
        self.assertIn("UserPromptSubmit", settings["hooks"])
        self.assertIn("Stop", settings["hooks"])
        self.assertIn("SessionEnd", settings["hooks"])
        self.assertIn("mneme-memory", claude_user_config["mcpServers"])
        self.assertEqual(
            claude_user_config["mcpServers"]["mneme-memory"]["args"],
            ["-m", "mneme_memory_mcp"],
        )
        self.assertEqual(
            settings["hooks"]["Stop"][0]["hooks"][0]["command"],
            str(paths.claude_capture_hook),
        )
        self.assertIn("export MNEME_EMBED_ON_WRITE=0", capture_script)
        self.assertEqual(notify_values, [str(paths.codex_notify_wrapper)])
        self.assertIn("/usr/local/bin/existing-notify", notify_wrapper)
        self.assertIn("turn-ended", notify_wrapper)
        self.assertEqual(codex_config.count("notify ="), 1)

    def test_existing_hermes_session_hook_counts_as_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_paths(root)
            paths.claude_settings.parent.mkdir(parents=True)
            paths.claude_settings.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "/Users/me/.claude/hooks/hermes-memory.sh",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            install_continuity(paths)
            status = continuity_status(paths)
            settings_text = paths.claude_settings.read_text(encoding="utf-8")

        self.assertTrue(status.claude_sessionstart_hook)
        self.assertTrue(status.claude_stop_capture_hook)
        self.assertIn("hermes-memory.sh", settings_text)
        self.assertNotIn(MNEME_HOOK_NAME, settings_text)
        self.assertIn(MNEME_CAPTURE_HOOK_NAME, settings_text)

    def test_claude_cli_managed_mcp_config_counts_as_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self.make_paths(root)

            install_continuity(paths)
            paths.claude_user_config.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "mneme-memory": {
                                "type": "stdio",
                                "command": str(paths.bin_dir / "mneme-memory-mcp"),
                                "args": [],
                                "env": {"HERMES_HOME": str(paths.memory_home)},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            status = continuity_status(paths)

        self.assertTrue(status.claude_mcp_config)

    def test_install_rejects_paths_that_can_inject_generated_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            paths = ContinuityPaths(
                **{
                    **paths.__dict__,
                    "memory_home": Path(str(paths.memory_home) + "\nmalicious"),
                }
            )

            with self.assertRaises(ValueError):
                install_continuity(paths)


if __name__ == "__main__":
    unittest.main()
