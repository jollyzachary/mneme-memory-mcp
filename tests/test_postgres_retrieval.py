from __future__ import annotations

import os
import tempfile
import time
import unittest
from multiprocessing import Process
from pathlib import Path
from unittest.mock import patch

from mneme_memory_mcp.postgres_retrieval import (
    PostgresRetrievalPlane,
    PostgresSettings,
    _structured_entities,
    _unique_prefix,
    _vector_literal,
    _weighted_rrf,
    postgres_required,
    postgres_retrieval_enabled,
    retrieval_backend,
)
from mneme_memory_mcp.server import _repair_delay_seconds
from mneme_memory_mcp.store import (
    SharedMemoryStore,
    _postgres_circuit_snapshot,
    _record_postgres_failure,
    _record_postgres_success,
)


def _hold_repair_lock(home: str, marker: str) -> None:
    store = SharedMemoryStore(home=Path(home))
    handle = store.acquire_postgres_repair_lock()
    Path(marker).write_text("acquired", encoding="utf-8")
    try:
        while True:
            time.sleep(1)
    finally:
        store.release_postgres_repair_lock(handle)


class PostgresConfigurationTest(unittest.TestCase):
    def test_backend_defaults_to_sqlite_and_rejects_unknown_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(retrieval_backend(), "sqlite")
            self.assertFalse(postgres_retrieval_enabled())
            self.assertFalse(postgres_required())
            self.assertEqual(PostgresSettings.from_environment().connect_timeout, 1)
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
                    "MNEME_POSTGRES_GRAPH_STATEMENT_TIMEOUT_MS": "900",
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
        self.assertEqual(settings.graph_statement_timeout_ms, 900)

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

    def test_postgres_mode_falls_back_to_sqlite_when_service_is_unavailable(
        self,
    ) -> None:
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
                patch.object(store, "_postgres_search_scores", return_value=({}, True)),
            ):
                self.assertEqual(store.search("sentinel", scope="global"), [])

    def test_search_never_drains_mirror_retries_on_the_request_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            with (
                patch.dict(
                    os.environ,
                    {"MNEME_RETRIEVAL_BACKEND": "postgres"},
                    clear=True,
                ),
                patch("mneme_memory_mcp.store._embed_texts", return_value=[]),
                patch.object(PostgresRetrievalPlane, "search", return_value={}),
                patch.object(store, "_flush_postgres_sync_queue") as flush,
            ):
                store._postgres_search_scores(
                    query="fast chat request",
                    scopes=("global",),
                    candidate_limit=50,
                )
            flush.assert_not_called()

    def test_postgres_outage_circuit_skips_repeated_connection_waits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            _record_postgres_success()
            _record_postgres_failure(RuntimeError("local service stopped"))
            with (
                patch.dict(
                    os.environ,
                    {
                        "MNEME_RETRIEVAL_BACKEND": "postgres",
                        "MNEME_POSTGRES_REQUIRED": "0",
                    },
                    clear=True,
                ),
                patch.object(PostgresRetrievalPlane, "search") as search,
            ):
                scores, available = store._postgres_search_scores(
                    query="emergency recall",
                    scopes=("global",),
                    candidate_limit=50,
                )
            self.assertEqual(scores, {})
            self.assertFalse(available)
            search.assert_not_called()
            self.assertTrue(_postgres_circuit_snapshot()["open"])
            _record_postgres_success()

    def test_failed_derived_mirror_never_invalidates_durable_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            with (
                patch.dict(
                    os.environ,
                    {
                        "MNEME_RETRIEVAL_BACKEND": "postgres",
                        "MNEME_POSTGRES_REQUIRED": "1",
                    },
                    clear=True,
                ),
                patch("mneme_memory_mcp.store._embed_texts", return_value=[]),
                patch.object(
                    PostgresRetrievalPlane,
                    "upsert_facts",
                    side_effect=RuntimeError("derived service unavailable"),
                ),
            ):
                fact_id = store.add("Durable before derived retrieval", scope="global")

            self.assertEqual(
                store.get_fact(fact_id).content,
                "Durable before derived retrieval",
            )
            with store.connect() as conn:
                queued = conn.execute(
                    """
                    SELECT attempts, revision
                    FROM postgres_sync_queue
                    WHERE item_type = 'fact' AND item_id = ?
                    """,
                    (fact_id,),
                ).fetchone()
            self.assertIsNotNone(queued)
            self.assertEqual(int(queued["attempts"]), 0)
            self.assertEqual(int(queued["revision"]), 1)


class PostgresRankingTest(unittest.TestCase):
    def test_structured_entities_use_only_stable_keys_and_tags(self) -> None:
        entities = _structured_entities(
            {
                "key": "DraftZero/Build",
                "tags": "memory, graph:v1, noisy tag with spaces, memory",
            }
        )
        self.assertEqual(
            entities,
            [
                ("key", "draftzero/build"),
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


class AdaptiveRepairTest(unittest.TestCase):
    def test_only_one_process_owns_the_repair_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            first = SharedMemoryStore(home=home)
            second = SharedMemoryStore(home=home)

            self.assertTrue(
                first.claim_maintenance_lease(
                    name="postgres-repair", owner_id="first", ttl_seconds=30
                )
            )
            self.assertFalse(
                second.claim_maintenance_lease(
                    name="postgres-repair", owner_id="second", ttl_seconds=30
                )
            )
            with first.connect() as conn:
                conn.execute(
                    "UPDATE maintenance_leases SET expires_at = 0 WHERE name = ?",
                    ("postgres-repair",),
                )
                conn.commit()
            self.assertTrue(
                second.claim_maintenance_lease(
                    name="postgres-repair", owner_id="second", ttl_seconds=30
                )
            )

    def test_revision_acknowledgement_preserves_newer_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SharedMemoryStore(home=Path(tmp))
            store.ensure()
            with store.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO postgres_sync_queue
                        (item_type, item_id, operation, revision)
                    VALUES ('fact', 41, 'upsert', 1)
                    """
                )
                conn.commit()
                revisions = store._postgres_sync_revisions(conn, "fact", [41])
                conn.execute(
                    "UPDATE postgres_sync_queue SET revision = 2 WHERE item_id = 41"
                )
                conn.commit()

            store._clear_postgres_sync_items("fact", revisions)
            with store.connect() as conn:
                row = conn.execute(
                    "SELECT revision FROM postgres_sync_queue WHERE item_id = 41"
                ).fetchone()
            self.assertEqual(int(row["revision"]), 2)

    def test_scheduler_is_fast_only_when_work_is_due(self) -> None:
        self.assertEqual(
            _repair_delay_seconds(
                {"total": 1, "due": 1, "next_due_seconds": 0, "max_attempts": 0},
                repaired=1,
            ),
            0.1,
        )
        self.assertEqual(
            _repair_delay_seconds(
                {"total": 1, "due": 0, "next_due_seconds": 8, "max_attempts": 2},
                repaired=0,
            ),
            8.0,
        )
        self.assertEqual(
            _repair_delay_seconds(
                {"total": 0, "due": 0, "next_due_seconds": 0, "max_attempts": 0},
                repaired=0,
            ),
            15.0,
        )

    @unittest.skipIf(os.name == "nt", "POSIX kernel lock test")
    def test_kernel_lock_has_zero_polling_and_immediate_crash_takeover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_marker = root / "first"
            second_marker = root / "second"
            first = Process(target=_hold_repair_lock, args=(tmp, str(first_marker)))
            second = Process(target=_hold_repair_lock, args=(tmp, str(second_marker)))
            first.start()
            deadline = time.time() + 5
            while time.time() < deadline and not first_marker.exists():
                time.sleep(0.02)
            self.assertTrue(first_marker.exists())
            second.start()
            time.sleep(0.25)
            self.assertFalse(second_marker.exists())
            takeover_started = time.perf_counter()
            first.terminate()
            first.join(timeout=5)
            deadline = time.time() + 5
            while time.time() < deadline and not second_marker.exists():
                time.sleep(0.02)
            takeover_seconds = time.perf_counter() - takeover_started
            try:
                self.assertTrue(second_marker.exists())
                self.assertLess(takeover_seconds, 1.0)
            finally:
                second.terminate()
                second.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
