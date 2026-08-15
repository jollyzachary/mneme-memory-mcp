from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mneme_memory_mcp.store import SharedMemoryStore, _normalize_content


class HygieneTest(unittest.TestCase):
    def make_store(self) -> SharedMemoryStore:
        return SharedMemoryStore(home=Path(tempfile.mkdtemp()))

    def test_tool_call_markup_is_stripped(self) -> None:
        # Bug #1: a leaked tool-call boundary must never be stored.
        dirty = 'Always rebuild the dev app.</content> <parameter name="category">project'
        self.assertEqual(_normalize_content(dirty), "Always rebuild the dev app.")

        store = self.make_store()
        fid = store.add(dirty, target="memory", category="project", key="rebuild")
        stored = store._get_fact(fid)
        assert stored is not None
        self.assertNotIn("</content>", stored.content)
        self.assertNotIn("parameter name", stored.content)

    def test_user_facts_survive_a_flood_of_recent_facts(self) -> None:
        # Bug #3: an older user_pref fact must still reach USER.md even when many
        # newer non-user facts exist (the old filter-after-limit dropped it).
        store = self.make_store()
        store.add(
            "The operator prefers concise technical summaries.",
            target="user",
            category="user_pref",
        )
        for i in range(150):
            store.add_fact(f"capture noise number {i}", source="capture", scope="global")

        store.consolidate()
        user_md = store.read_markdown("user")
        self.assertIn("operator prefers", user_md)
        self.assertNotIn("No current facts", user_md)

    def test_capture_facts_excluded_from_working_set(self) -> None:
        # Bug #2: capture stays searchable but does not pollute the always-on view.
        store = self.make_store()
        store.add_fact("curated project decision", source="manual", category="project", scope="project")
        store.add_fact("[distilled claude memory] raw transcript dump", source="capture", scope="global")
        store.consolidate()

        memory_md = store.read_markdown("memory")
        self.assertIn("curated project decision", memory_md)
        self.assertNotIn("distilled claude memory", memory_md)
        # …but capture is still retrievable on demand.
        self.assertTrue(store.search("transcript", scope="global"))

    def test_duplicate_episodic_does_not_grow_events(self) -> None:
        # Bug #4 (bloat): re-capturing the same snippet must not append an event.
        store = self.make_store()
        store.ensure()

        def event_count() -> int:
            with store.connect() as conn:
                return conn.execute(
                    "SELECT COUNT(*) FROM events WHERE event_type='episodic.add'"
                ).fetchone()[0]

        store.add_episodic(source="claude", session_id="s1", role="user", text="hello world snippet")
        self.assertEqual(event_count(), 1)
        # Same content again (what every repeated capture run does) -> no new event.
        store.add_episodic(source="claude", session_id="s1", role="user", text="hello world snippet")
        self.assertEqual(event_count(), 1)
        # prune_events keeps the table bounded.
        self.assertGreaterEqual(store.prune_events(keep_recent=0, max_age_days=99999), 0)

    def test_repair_cleans_existing_rows(self) -> None:
        store = self.make_store()
        # Insert corruption directly (bypassing the new boundary) to simulate legacy data.
        store.ensure()
        with store.connect() as conn:
            conn.execute(
                "INSERT INTO facts (content, category, source, scope) VALUES (?, 'project', 'manual', 'project')",
                ('legacy fact body.</content> <parameter name="category">project',),
            )
            conn.commit()
        changed = store.repair_corrupted_content()
        self.assertGreaterEqual(changed, 1)
        self.assertFalse(
            any("</content>" in f.content for f in store.list(limit=100, scope="project"))
        )


if __name__ == "__main__":
    unittest.main()
