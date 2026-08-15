from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mneme_memory_mcp.capture import (
    _capture_source,
    parse_claude_jsonl,
    parse_codex_jsonl,
)
from mneme_memory_mcp.store import SharedMemoryStore


class CaptureTest(unittest.TestCase):
    def write_jsonl(self, records: list[dict]) -> Path:
        root = Path(tempfile.mkdtemp())
        path = root / "session.jsonl"
        path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8",
        )
        return path

    def test_parse_claude_queue_and_tool_result(self) -> None:
        path = self.write_jsonl(
            [
                {
                    "type": "queue-operation",
                    "operation": "enqueue",
                    "sessionId": "claude-1",
                    "content": "Please publish the sample card to ExampleQueue.",
                },
                {
                    "type": "message",
                    "sessionId": "claude-1",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "content": "ExampleBoard result: PublishSuccess id 123",
                            }
                        ],
                    },
                },
            ]
        )

        snippets = parse_claude_jsonl(path)

        self.assertEqual(len(snippets), 2)
        self.assertEqual(snippets[0].source, "claude")
        self.assertIn("ExampleQueue", snippets[0].text)
        self.assertIn("PublishSuccess", snippets[1].text)

    def test_parse_codex_messages_and_redacts_secret(self) -> None:
        path = self.write_jsonl(
            [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "codex-1",
                        "base_instructions": {"text": "skip me"},
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Use token=abc123 to inspect ExampleQueue work.",
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "I found the ExampleQueue draft.",
                            }
                        ],
                    },
                },
            ]
        )

        snippets = parse_codex_jsonl(path)

        self.assertEqual(len(snippets), 2)
        self.assertEqual(snippets[0].session_id, "codex-1")
        self.assertIn("token=[redacted]", snippets[0].text)
        self.assertIn("ExampleQueue draft", snippets[1].text)

    def test_parse_codex_redacts_quoted_json_secret(self) -> None:
        path = self.write_jsonl(
            [
                {"type": "session_meta", "payload": {"id": "codex-json"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": '{"api_key":"abcdefghijklmnop123456"}',
                    },
                },
            ]
        )

        snippets = parse_codex_jsonl(path)

        self.assertEqual(len(snippets), 1)
        self.assertNotIn("abcdefghijklmnop123456", snippets[0].text)
        self.assertIn("[redacted]", snippets[0].text)

    def test_capture_routes_raw_turns_to_episodic_and_distills_searchable_summary(
        self,
    ) -> None:
        path = self.write_jsonl(
            [
                {"type": "session_meta", "payload": {"id": "codex-1"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Please remember the deploy command is ./scripts/deploy.sh.",
                    },
                },
            ]
        )
        store = SharedMemoryStore(home=Path(tempfile.mkdtemp()))

        stats = _capture_source(
            source="codex",
            files=[path],
            parser=parse_codex_jsonl,
            store=store,
        )

        self.assertEqual(stats.snippets_indexed, 1)
        # Raw transcript must not live in facts; distilled/summary may surface via FTS
        # or hybrid paraphrase search. Never return the un-distilled "Please remember" form.
        framed = store.search("Please remember the deploy command")
        for hit in framed:
            self.assertNotIn("Please remember the deploy command is", hit.content)
            self.assertTrue(
                "distilled" in hit.content.lower()
                or "session summary" in hit.content.lower()
                or "deploy command" in hit.content.lower()
            )
        self.assertIn("deploy command", store.search("deploy command")[0].content)
        with store.connect() as conn:
            episodic_count = conn.execute(
                "SELECT COUNT(*) FROM episodic_entries"
            ).fetchone()[0]
            conversation_facts = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE category = 'conversation'"
            ).fetchone()[0]
            summaries = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE memory_type = 'resource'"
            ).fetchone()[0]
        self.assertEqual(episodic_count, 1)
        self.assertEqual(conversation_facts, 0)
        self.assertEqual(summaries, 1)

    def test_low_signal_chat_stays_episodic_instead_of_becoming_a_fact(self) -> None:
        path = self.write_jsonl(
            [
                {"type": "session_meta", "payload": {"id": "codex-low-signal"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Can you explain this paragraph to me?",
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Certainly. Here is a short explanation.",
                            }
                        ],
                    },
                },
            ]
        )
        store = SharedMemoryStore(home=Path(tempfile.mkdtemp()))

        _capture_source(
            source="codex",
            files=[path],
            parser=parse_codex_jsonl,
            store=store,
        )

        with store.connect() as conn:
            distilled = conn.execute(
                "SELECT COUNT(*) FROM facts WHERE tags LIKE '%distilled%'"
            ).fetchone()[0]
            episodic = conn.execute("SELECT COUNT(*) FROM episodic_entries").fetchone()[
                0
            ]
        self.assertEqual(distilled, 0)
        self.assertEqual(episodic, 2)

    def test_capture_uses_byte_checkpoint_and_only_processes_appended_records(
        self,
    ) -> None:
        path = self.write_jsonl(
            [
                {"type": "session_meta", "payload": {"id": "codex-incremental"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "The first durable transcript record.",
                    },
                },
            ]
        )
        store = SharedMemoryStore(home=Path(tempfile.mkdtemp()))

        first = _capture_source(
            source="codex",
            files=[path],
            parser=parse_codex_jsonl,
            store=store,
        )
        repeated = _capture_source(
            source="codex",
            files=[path],
            parser=parse_codex_jsonl,
            store=store,
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "The newly appended transcript record.",
                        },
                    }
                )
                + "\n"
            )
        appended = _capture_source(
            source="codex",
            files=[path],
            parser=parse_codex_jsonl,
            store=store,
        )

        self.assertEqual(first.snippets_indexed, 1)
        self.assertEqual(repeated.snippets_indexed, 0)
        self.assertEqual(appended.snippets_indexed, 1)
        with store.connect() as conn:
            episodic = conn.execute("SELECT COUNT(*) FROM episodic_entries").fetchone()[
                0
            ]
            checkpoint = conn.execute(
                "SELECT byte_offset FROM capture_checkpoints"
            ).fetchone()[0]
        self.assertEqual(episodic, 2)
        self.assertEqual(checkpoint, path.stat().st_size)


if __name__ == "__main__":
    unittest.main()
