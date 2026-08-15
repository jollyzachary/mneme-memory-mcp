from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mneme_memory_mcp.bridge import (
    AgentRun,
    bridge_status,
    delegate_to_claude,
    delegate_to_codex,
)
from mneme_memory_mcp.store import SharedMemoryStore


FAKE_AGENT = """#!/usr/bin/env python3
import os
import sys

print("FAKE_AGENT")
print("name=" + os.path.basename(sys.argv[0]))
print("cwd=" + os.getcwd())
print("args=" + repr(sys.argv[1:]))
"""


class AgentBridgeTest(unittest.TestCase):
    def make_fake_bin(self, root: Path, name: str) -> None:
        if os.name == "nt":
            script = root / f"{name}_fake.py"
            script.write_text(FAKE_AGENT, encoding="utf-8")
            path = root / f"{name}.cmd"
            path.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
            return

        path = root / name
        path.write_text(FAKE_AGENT, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_bridge_status_reports_available_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fake_bin(root, "claude")
            self.make_fake_bin(root, "codex")
            self.make_fake_bin(root, "node")
            path = f"{root}{os.pathsep}{os.environ.get('PATH', '')}"
            with patch.dict(os.environ, {"PATH": path}):
                status = bridge_status()

        self.assertIn("claude:", status)
        self.assertIn("codex:", status)
        self.assertIn("node:", status)
        self.assertNotIn("missing", status)

    def test_delegate_to_claude_injects_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fake_bin(bin_dir, "claude")
            store = SharedMemoryStore(home=root / "memory")
            store.add("Shared memory fact.", target="memory", tags="test")

            path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            with patch.dict(
                os.environ,
                {
                    "PATH": path,
                    "MNEME_HOME": str(root / "memory"),
                    "MNEME_BRIDGE_ROOT": str(root),
                },
            ):
                result = delegate_to_claude("say hello", cwd=str(root))

        self.assertEqual(result.returncode, 0)
        self.assertIn("FAKE_AGENT", result.stdout)
        self.assertIn("Shared memory fact.", result.stdout)

    def test_delegate_to_codex_injects_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self.make_fake_bin(bin_dir, "codex")
            store = SharedMemoryStore(home=root / "memory")
            store.add("Another shared fact.", target="memory", tags="test")

            path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            with patch.dict(
                os.environ,
                {
                    "PATH": path,
                    "MNEME_HOME": str(root / "memory"),
                    "MNEME_BRIDGE_ROOT": str(root),
                },
            ):
                result = delegate_to_codex("review this", cwd=str(root), sandbox="read-only")

        self.assertEqual(result.returncode, 0)
        self.assertIn("FAKE_AGENT", result.stdout)
        self.assertIn("Another shared fact.", result.stdout)
        self.assertIn("read-only", result.stdout)
        # `codex exec` rejects the interactive approval flag.
        self.assertNotIn("--ask-for-approval", result.stdout)
        self.assertIn("--skip-git-repo-check", result.stdout)

    def test_format_tolerates_missing_streams(self) -> None:
        # Formatting remains stable when a subprocess produces no captured stream.
        run = AgentRun(
            agent="codex",
            command=["codex", "exec"],
            cwd=Path("."),
            returncode=0,
            stdout=None,
            stderr=None,
        )
        text = run.format()
        self.assertIn("agent: codex", text)
        self.assertIn("(no stdout)", text)
        self.assertIn("command: [redacted]", text)


if __name__ == "__main__":
    unittest.main()
