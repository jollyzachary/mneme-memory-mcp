from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mneme_memory_mcp.cli import main
from mneme_memory_mcp.store import SharedMemoryStore


class CliTest(unittest.TestCase):
    def run_cli(self, argv: list[str], memory_home: Path) -> str:
        output = io.StringIO()
        with (
            patch.dict("os.environ", {"MNEME_HOME": str(memory_home)}, clear=False),
            contextlib.redirect_stdout(output),
        ):
            main(argv)
        return output.getvalue()

    def test_add_summary_and_search_use_same_memory_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_home = Path(tmp) / "memory"

            add_result = self.run_cli(
                [
                    "add",
                    "--target",
                    "memory",
                    "--tags",
                    "test",
                    "Codex and Claude share Mneme.",
                ],
                memory_home,
            )
            summary = self.run_cli(["summary"], memory_home)
            search = self.run_cli(["search", "Claude"], memory_home)

        self.assertIn("saved fact 1", add_result)
        self.assertIn("Codex and Claude share Mneme.", summary)
        self.assertIn("Codex and Claude share Mneme.", search)

    def test_current_and_handoff_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_home = Path(tmp) / "memory"

            self.run_cli(
                [
                    "add",
                    "--key",
                    "test-command",
                    "--version",
                    "1",
                    "Test command is pnpm test.",
                ],
                memory_home,
            )
            self.run_cli(
                [
                    "add",
                    "--key",
                    "test-command",
                    "--version",
                    "2",
                    "Test command is bun test.",
                ],
                memory_home,
            )
            current = self.run_cli(["current", "test-command"], memory_home)
            write = self.run_cli(
                [
                    "handoff",
                    "write",
                    "--scope",
                    "project",
                    "--goal",
                    "Document the release workflow",
                    "--next-steps",
                    "review the migration notes",
                ],
                memory_home,
            )
            latest = self.run_cli(
                ["handoff", "latest", "--scope", "project"], memory_home
            )

        self.assertIn("bun test", current)
        self.assertNotIn("pnpm test", current)
        self.assertIn("saved handoff 1", write)
        self.assertIn("Document the release workflow", latest)

    def test_health_briefing_feedback_review_and_maintenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_home = Path(tmp) / "memory"
            store = SharedMemoryStore(home=memory_home)
            trusted = store.add(
                "Global Mneme uses a local SQLite database.", scope="global"
            )
            candidate = store.add_fact(
                "Captured candidate says global recall is enabled.",
                source="capture",
                scope="global",
            )

            health = self.run_cli(["health"], memory_home)
            briefing = self.run_cli(
                ["briefing", "SQLite database", "--scope", "global"],
                memory_home,
            )
            feedback = self.run_cli(
                ["feedback", str(trusted), "helpful"],
                memory_home,
            )
            review = self.run_cli(["review", "list"], memory_home)
            promoted = self.run_cli(
                ["review", "promote", str(candidate)],
                memory_home,
            )
            maintenance = self.run_cli(
                ["maintain", "--no-vacuum"],
                memory_home,
            )

        self.assertIn('"integrity": "ok"', health)
        self.assertIn("local SQLite database", briefing)
        self.assertIn("importance=", feedback)
        self.assertIn("Captured candidate", review)
        self.assertIn("state=trusted", promoted)
        self.assertIn('"status": "ok"', maintenance)


if __name__ == "__main__":
    unittest.main()
