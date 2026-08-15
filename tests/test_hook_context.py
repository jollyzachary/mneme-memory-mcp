from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mneme_memory_mcp.hook_context import build_context, prompt_keywords
from mneme_memory_mcp.store import SharedMemoryStore


class HookContextTest(unittest.TestCase):
    def make_store(self) -> SharedMemoryStore:
        return SharedMemoryStore(home=Path(tempfile.mkdtemp()))

    def test_prompt_keywords_drop_stopwords_and_dupes(self) -> None:
        words = prompt_keywords("Please check the DuckDB catalog data venv, DuckDB again")
        self.assertIn("duckdb", words)
        self.assertIn("catalog", words)
        self.assertNotIn("please", words)
        self.assertEqual(words.count("duckdb"), 1)

    def test_relevant_facts_matched_to_prompt(self) -> None:
        store = self.make_store()
        store.add("Catalog data lives in Parquet, query via DuckDB venv.", category="project")
        store.add("Dashboard accent colors are blue and yellow.", category="project")

        context = build_context(store=store, prompt="How do I query the DuckDB catalog data?")

        self.assertIn("## Memories Matched To This Prompt", context)
        self.assertIn("DuckDB venv", context)
        self.assertNotIn("Dashboard accent colors", context.split("## Memories Matched")[1])

    def test_falls_back_to_recent_without_prompt_match(self) -> None:
        store = self.make_store()
        store.add("Dashboard accent colors are blue and yellow.", category="project")

        context = build_context(store=store, prompt="zzz qqqq xxxxx")
        self.assertIn("## Recent Searchable Facts", context)

    def test_capture_and_session_summary_noise_excluded(self) -> None:
        store = self.make_store()
        store.add_fact(
            "[codex session summary] session=abc: 10 archived turns.",
            tags="capture,codex,session-summary",
            source="capture",
        )
        store.add("Durable fact about the staging environment.", category="project")

        for prompt in ("", "session summary archived turns"):
            context = build_context(store=store, prompt=prompt)
            self.assertNotIn("archived turns", context.split("# MEMORY.md")[-1])


if __name__ == "__main__":
    unittest.main()
