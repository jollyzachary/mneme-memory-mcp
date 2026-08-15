from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mneme_memory_mcp.postgres_retrieval import (
    PostgresSettings,
    _structured_entities,
    _unique_prefix,
    _vector_literal,
    _weighted_rrf,
    postgres_required,
    postgres_retrieval_enabled,
    retrieval_backend,
)
from mneme_memory_mcp.store import SharedMemoryStore


class PostgresConfigurationTest(unittest.TestCase):
    def test_backend_defaults_to_sqlite_and_rejects_unknown_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(retrieval_backend(), "sqlite")
            self.assertFalse(postgres_retrieval_enabled())
            self.assertFalse(postgres_required())
        with patch.dict(
            os.environ, {"MNEME_RETRIEVAL_BACKEND": "not-a-backend"}, clear=True
        ):
            self.assertEqual(retrieval_backend(), "sqlite")

    def test_environment_builds_local_password_file_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            password_file = Path(tmp) / "password"
            with patch.dict(
                os.environ,
                {
                    "MNEME_POSTGRES_HOST": "127.0.0.1",
                    "MNEME_POSTGRES_PORT": "55433",
                    "MNEME_POSTGRES_DATABASE": "mneme_test",
                    "MNEME_POSTGRES_USER": "mneme_test_app",
                    "MNEME_POSTGRES_PASSWORD_FILE": str(password_file),
                    "MNEME_POSTGRES_CONNECT_TIMEOUT": "4",
                    "MNEME_POSTGRES_STATEMENT_TIMEOUT_MS": "7000",
                },
                clear=True,
            ):
                settings = PostgresSettings.from_environment()

        self.assertEqual(settings.port, 55433)
        self.assertEqual(settings.database, "mneme_test")
        self.assertEqual(settings.user, "mneme_test_app")
        self.assertEqual(settings.password_file, password_file)
        self.assertEqual(settings.connect_timeout, 4)
        self.assertEqual(settings.statement_timeout_ms, 7000)

    def test_global_store_loads_machine_runtime_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / "mneme.env"
            env_file.write_text(
                "MNEME_RETRIEVAL_BACKEND=postgres\n"
                "MNEME_POSTGRES_PASSWORD_FILE=secret\n",
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {"MNEME_GLOBAL_ENV_FILE": str(env_file)},
                    clear=True,
                ),
                patch("mneme_memory_mcp.store.Path.home", return_value=root),
            ):
                SharedMemoryStore(home=root / ".hermes")
                self.assertEqual(retrieval_backend(), "postgres")
                self.assertEqual(
                    os.environ["MNEME_POSTGRES_PASSWORD_FILE"],
                    str(root / "secret"),
                )

    def test_postgres_mode_falls_back_to_sqlite_when_service_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            with patch.dict(
                os.environ, {"MNEME_RETRIEVAL_BACKEND": "sqlite"}, clear=True
            ):
                store.add("SQLite-only sentinel fact", scope="global")
            with (
                patch.dict(
                    os.environ,
                    {"MNEME_RETRIEVAL_BACKEND": "postgres"},
                    clear=True,
                ),
                patch.object(
                    store, "_postgres_search_scores", return_value=({}, False)
                ),
            ):
                self.assertEqual(
                    store.search("sentinel", scope="global")[0].content,
                    "SQLite-only sentinel fact",
                )

    def test_postgres_mode_returns_empty_after_successful_empty_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            with (
                patch.dict(
                    os.environ,
                    {"MNEME_RETRIEVAL_BACKEND": "postgres"},
                    clear=True,
                ),
                patch.object(
                    store, "_postgres_search_scores", return_value=({}, True)
                ),
            ):
                self.assertEqual(store.search("sentinel", scope="global"), [])


class PostgresRankingTest(unittest.TestCase):
    def test_structured_entities_use_only_stable_keys_and_tags(self) -> None:
        entities = _structured_entities(
            {
                "key": "ExampleProject/Build",
                "tags": "memory, graph:v1, noisy tag with spaces, memory",
            }
        )
        self.assertEqual(
            entities,
            [
                ("key", "exampleproject/build"),
                ("tag", "graph:v1"),
                ("tag", "memory"),
            ],
        )

    def test_weighted_rrf_rewards_cross_branch_agreement(self) -> None:
        scores = _weighted_rrf([([1, 2], 1.0), ([2, 3], 1.0)])
        self.assertGreater(scores[2], scores[1])
        self.assertGreater(scores[2], scores[3])
        self.assertEqual(_unique_prefix([2, 2, 1, 3], 3), [2, 1, 3])
        self.assertEqual(_vector_literal([1.0, 0.25]), "[1,0.25]")


class TypedRelationTest(unittest.TestCase):
    def test_links_are_same_scope_inspectable_and_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            first = store.add("Mneme stores durable facts.", scope="global")
            second = store.add("pgGraph expands explicit relations.", scope="global")
            private = store.add("Private scratch note.", scope="agent-private")

            relation_id = store.link(
                first,
                second,
                relation_type="supports",
                weight=1.5,
                evidence="Explicit test edge",
            )

            links = store.list_links(fact_id=first, scope="global")
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["relation_type"], "supports")
            self.assertEqual(links[0]["weight"], 1.5)
            with self.assertRaisesRegex(ValueError, "cannot cross scopes"):
                store.link(first, private, relation_type="must-not-cross")
            self.assertTrue(store.unlink(relation_id))
            self.assertEqual(store.list_links(fact_id=first, scope="global"), [])


if __name__ == "__main__":
    unittest.main()
