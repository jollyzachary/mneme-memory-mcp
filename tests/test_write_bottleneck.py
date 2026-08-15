from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mneme_memory_mcp.capture import _should_keep
from mneme_memory_mcp.store import SharedMemoryStore


class MarkupRejectionTest(unittest.TestCase):
    def test_capture_rejects_tool_markup(self) -> None:
        self.assertFalse(_should_keep('some text then <parameter name="file_path">/x</parameter>'))
        self.assertFalse(_should_keep("output with hookSpecificOutput payload inside it"))
        self.assertTrue(_should_keep("a normal remembered decision about the development build"))


class WriteBottleneckTest(unittest.TestCase):
    """Verbalizable-bottleneck behavior: writes are distilled and near-dups
    supersede instead of piling up."""

    def make_store(self) -> SharedMemoryStore:
        return SharedMemoryStore(home=Path(tempfile.mkdtemp()))

    def test_remember_preamble_stripped_on_write(self) -> None:
        store = self.make_store()
        store.add("Remember that the dev build script is build-dev-app.sh.")
        fact = store.list(limit=1)[0]
        self.assertTrue(fact.content.startswith("the dev build script"))

    def test_keyless_near_duplicate_supersedes(self) -> None:
        store = self.make_store()
        first = store.add("Review workflow uses four workers and one reviewer for boards.")
        second = store.add(
            "Review workflow uses four workers and one reviewer for boards, retry twice."
        )

        current = store.list(limit=10)
        self.assertEqual([fact.fact_id for fact in current], [second])
        self.assertNotEqual(first, second)

    def test_different_facts_do_not_supersede(self) -> None:
        store = self.make_store()
        store.add("Analytics data lives in Parquet under data/warehouse.")
        store.add("Dashboard panels route through PanelInteractionSurface.")
        self.assertEqual(len(store.list(limit=10)), 2)

    def test_maybe_vacuum_runs_only_when_free_pages(self) -> None:
        store = self.make_store()
        store.add("A fact so the DB exists.")
        self.assertFalse(store.maybe_vacuum())
        self.assertTrue(store.maybe_vacuum(min_free_fraction=0.0))


if __name__ == "__main__":
    unittest.main()
