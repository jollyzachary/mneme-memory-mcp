from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

COLLECTION = "mneme_facts"
RRF_K = 60
DEFAULT_PORT = 55433
DEFAULT_DATABASE = "mneme"
DEFAULT_USER = "mneme_app"
_ENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}$")
_LOGGER = logging.getLogger(__name__)
_GRAPH_RUNTIME_LOCK = threading.Lock()
_GRAPH_RUNTIME: dict[str, Any] = {
    "attempts": 0,
    "successes": 0,
    "failures": 0,
    "consecutive_failures": 0,
    "circuit_open_until": 0.0,
    "last_latency_ms": 0.0,
    "ewma_latency_ms": 0.0,
    "last_error": "",
}


def _graph_runtime_snapshot() -> dict[str, Any]:
    with _GRAPH_RUNTIME_LOCK:
        snapshot = dict(_GRAPH_RUNTIME)
    remaining = max(0.0, float(snapshot.pop("circuit_open_until")) - time.monotonic())
    snapshot["circuit_open"] = remaining > 0
    snapshot["circuit_retry_seconds"] = round(remaining, 3)
    snapshot["last_latency_ms"] = round(float(snapshot["last_latency_ms"]), 3)
    snapshot["ewma_latency_ms"] = round(float(snapshot["ewma_latency_ms"]), 3)
    return snapshot


def _record_graph_success(latency_ms: float) -> None:
    with _GRAPH_RUNTIME_LOCK:
        previous = float(_GRAPH_RUNTIME["ewma_latency_ms"])
        _GRAPH_RUNTIME["attempts"] += 1
        _GRAPH_RUNTIME["successes"] += 1
        _GRAPH_RUNTIME["consecutive_failures"] = 0
        _GRAPH_RUNTIME["circuit_open_until"] = 0.0
        _GRAPH_RUNTIME["last_latency_ms"] = latency_ms
        _GRAPH_RUNTIME["ewma_latency_ms"] = (
            latency_ms if previous <= 0 else (0.2 * latency_ms) + (0.8 * previous)
        )
        _GRAPH_RUNTIME["last_error"] = ""


def _record_graph_failure(exc: Exception, latency_ms: float) -> None:
    with _GRAPH_RUNTIME_LOCK:
        previous = float(_GRAPH_RUNTIME["ewma_latency_ms"])
        _GRAPH_RUNTIME["attempts"] += 1
        _GRAPH_RUNTIME["failures"] += 1
        _GRAPH_RUNTIME["consecutive_failures"] += 1
        _GRAPH_RUNTIME["last_latency_ms"] = latency_ms
        _GRAPH_RUNTIME["ewma_latency_ms"] = (
            latency_ms if previous <= 0 else (0.2 * latency_ms) + (0.8 * previous)
        )
        _GRAPH_RUNTIME["last_error"] = str(exc)[:300]
        if int(_GRAPH_RUNTIME["consecutive_failures"]) >= 3:
            _GRAPH_RUNTIME["circuit_open_until"] = time.monotonic() + 30.0


class PostgresRetrievalError(RuntimeError):
    """A local PostgreSQL retrieval-plane operation failed."""


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    port: int
    database: str
    user: str
    password_file: Path
    connect_timeout: int = 3
    statement_timeout_ms: int = 5_000
    graph_statement_timeout_ms: int = 750

    @classmethod
    def from_environment(cls) -> PostgresSettings:
        default_secret = (
            Path.home()
            / ".local"
            / "share"
            / "mneme-memory-mcp"
            / "postgres"
            / "secrets"
            / "app_password"
        )
        return cls(
            host=os.environ.get("MNEME_POSTGRES_HOST", "127.0.0.1"),
            port=int(os.environ.get("MNEME_POSTGRES_PORT", str(DEFAULT_PORT))),
            database=os.environ.get("MNEME_POSTGRES_DATABASE", DEFAULT_DATABASE),
            user=os.environ.get("MNEME_POSTGRES_USER", DEFAULT_USER),
            password_file=Path(
                os.environ.get("MNEME_POSTGRES_PASSWORD_FILE", str(default_secret))
            ).expanduser(),
            connect_timeout=max(
                1, int(os.environ.get("MNEME_POSTGRES_CONNECT_TIMEOUT", "1"))
            ),
            statement_timeout_ms=max(
                500, int(os.environ.get("MNEME_POSTGRES_STATEMENT_TIMEOUT_MS", "5000"))
            ),
            graph_statement_timeout_ms=max(
                100,
                int(os.environ.get("MNEME_POSTGRES_GRAPH_STATEMENT_TIMEOUT_MS", "750")),
            ),
        )


def retrieval_backend() -> str:
    backend = os.environ.get("MNEME_RETRIEVAL_BACKEND", "sqlite").strip().lower()
    return backend if backend in {"sqlite", "dual", "postgres"} else "sqlite"


def postgres_retrieval_enabled() -> bool:
    return retrieval_backend() in {
        "postgres",
        "dual",
    }


def postgres_required() -> bool:
    return os.environ.get("MNEME_POSTGRES_REQUIRED", "0") == "1"


class PostgresRetrievalPlane:
    """Derived pgContext + pgGraph retrieval plane for Mneme.

    SQLite remains the governed journal during the first cutover stage. This
    class mirrors facts into PostgreSQL, retrieves candidate ids, and returns
    those ids to the existing SQLite trust/supersession ranker.
    """

    def __init__(self, settings: PostgresSettings | None = None) -> None:
        self.settings = settings or PostgresSettings.from_environment()

    def _connect(self):
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise PostgresRetrievalError(
                "PostgreSQL retrieval requires the 'postgres' optional dependency"
            ) from exc

        try:
            password = self.settings.password_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PostgresRetrievalError(
                f"cannot read PostgreSQL password file: {self.settings.password_file}"
            ) from exc
        if not password:
            raise PostgresRetrievalError("PostgreSQL password file is empty")

        try:
            return psycopg.connect(
                host=self.settings.host,
                port=self.settings.port,
                dbname=self.settings.database,
                user=self.settings.user,
                password=password,
                connect_timeout=self.settings.connect_timeout,
                options=f"-c statement_timeout={self.settings.statement_timeout_ms}",
            )
        except Exception as exc:  # noqa: BLE001 - psycopg exposes provider errors
            raise PostgresRetrievalError("local PostgreSQL is unavailable") from exc

    @staticmethod
    def _set_scopes(cur: Any, scopes: Sequence[str]) -> None:
        cur.execute(
            "SELECT set_config('mneme.visible_scopes', %s, true)", (",".join(scopes),)
        )

    def search(
        self,
        query: str,
        scopes: Sequence[str],
        limit: int,
        query_vector: Sequence[float] | None,
    ) -> dict[int, float]:
        candidate_limit = max(50, min(500, int(limit)))
        rankings: list[tuple[list[int], float]] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, scopes)
                lexical = self._lexical_ids(cur, query, scopes, candidate_limit)
                exact = self._exact_ids(cur, query, scopes, candidate_limit)
                if exact:
                    rankings.append((exact, 1.25))
                if lexical:
                    rankings.append((lexical, 1.0))
                if query_vector:
                    dense = self._dense_ids(cur, query_vector, scopes, candidate_limit)
                    if dense:
                        rankings.append((dense, 1.0))

                seed_ids = _unique_prefix(
                    [fact_id for ranked, _weight in rankings for fact_id in ranked],
                    3,
                )
                if seed_ids:
                    graph = self._graph_ids_best_effort(
                        cur, seed_ids, scopes, candidate_limit
                    )
                    if graph:
                        rankings.append((graph, 0.55))

        return _weighted_rrf(rankings)

    def _graph_ids_best_effort(
        self,
        cur: Any,
        seed_ids: Sequence[int],
        scopes: Sequence[str],
        limit: int,
    ) -> list[int]:
        """Bound graph enrichment without sacrificing direct PostgreSQL recall.

        pgGraph is a derived ranking lane. Lexical, exact, and pgContext hits
        remain valid when its index is rebuilding, compacting, or temporarily
        unhealthy. A savepoint is required because a PostgreSQL statement
        timeout otherwise aborts the entire search transaction.
        """

        runtime = _graph_runtime_snapshot()
        if bool(runtime["circuit_open"]):
            return []

        savepoint = "mneme_graph_expansion"
        started = time.perf_counter()
        cur.execute(f"SAVEPOINT {savepoint}")
        try:
            cur.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (str(self.settings.graph_statement_timeout_ms),),
            )
            graph = self._graph_ids(cur, seed_ids, scopes, limit)
        except Exception as exc:  # noqa: BLE001 - derived lane must fail soft
            cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            cur.execute(f"RELEASE SAVEPOINT {savepoint}")
            latency_ms = (time.perf_counter() - started) * 1_000
            _record_graph_failure(exc, latency_ms)
            _LOGGER.warning("pgGraph enrichment skipped: %s", exc)
            return []

        cur.execute(f"RELEASE SAVEPOINT {savepoint}")
        cur.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(self.settings.statement_timeout_ms),),
        )
        _record_graph_success((time.perf_counter() - started) * 1_000)
        return graph

    @staticmethod
    def _lexical_ids(
        cur: Any, query: str, scopes: Sequence[str], limit: int
    ) -> list[int]:
        cur.execute(
            """
            SELECT fact_id
            FROM mneme.facts
            WHERE is_current
              AND state IN ('trusted', 'candidate')
              AND memory_type != 'episodic'
              AND scope = ANY(%s)
              AND search_document @@ websearch_to_tsquery('english', %s)
            ORDER BY ts_rank_cd(
                         search_document,
                         websearch_to_tsquery('english', %s),
                         32
                     ) DESC,
                     updated_at DESC,
                     fact_id DESC
            LIMIT %s
            """,
            (list(scopes), query, query, limit),
        )
        return [int(row[0]) for row in cur.fetchall()]

    @staticmethod
    def _exact_ids(
        cur: Any, query: str, scopes: Sequence[str], limit: int
    ) -> list[int]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        needle = f"%{escaped}%"
        cur.execute(
            """
            SELECT fact_id
            FROM mneme.facts
            WHERE is_current
              AND state IN ('trusted', 'candidate')
              AND memory_type != 'episodic'
              AND scope = ANY(%s)
              AND (
                    content ILIKE %s ESCAPE '\\' OR tags ILIKE %s ESCAPE '\\'
                    OR key ILIKE %s ESCAPE '\\' OR category ILIKE %s ESCAPE '\\'
              )
            ORDER BY CASE WHEN key ILIKE %s ESCAPE '\\' THEN 0 ELSE 1 END,
                     trust_score DESC,
                     updated_at DESC,
                     fact_id DESC
            LIMIT %s
            """,
            (list(scopes), needle, needle, needle, needle, needle, limit),
        )
        return [int(row[0]) for row in cur.fetchall()]

    @staticmethod
    def _dense_ids(
        cur: Any,
        query_vector: Sequence[float],
        scopes: Sequence[str],
        limit: int,
    ) -> list[int]:
        vector = _vector_literal(query_vector)
        ranked: list[tuple[float, int]] = []
        for scope in scopes:
            filter_json = json.dumps(
                {"must": [{"key": "scope", "match": scope}]},
                separators=(",", ":"),
            )
            cur.execute(
                """
                SELECT s.source_key::bigint AS fact_id, s.score
                FROM pgcontext.search(
                    %s,
                    %s::pgcontext.vector,
                    %s,
                    %s
                ) AS s
                JOIN mneme.facts f ON f.fact_id = s.source_key::bigint
                WHERE f.is_current
                  AND f.state IN ('trusted', 'candidate')
                  AND f.memory_type != 'episodic'
                  AND f.scope = %s
                ORDER BY s.score ASC, f.fact_id ASC
                LIMIT %s
                """,
                (COLLECTION, vector, filter_json, limit * 2, scope, limit),
            )
            ranked.extend((float(row[1]), int(row[0])) for row in cur.fetchall())
        ranked.sort(key=lambda item: (item[0], item[1]))
        return _unique_prefix([fact_id for _score, fact_id in ranked], limit)

    @staticmethod
    def _graph_ids(
        cur: Any,
        seed_ids: Sequence[int],
        scopes: Sequence[str],
        limit: int,
    ) -> list[int]:
        cur.execute(
            "SELECT fact_id, scope FROM mneme.facts WHERE fact_id = ANY(%s)",
            (list(seed_ids),),
        )
        by_scope: dict[str, list[int]] = {scope: [] for scope in scopes}
        for fact_id, scope in cur.fetchall():
            if str(scope) in by_scope:
                by_scope[str(scope)].append(int(fact_id))

        ranked: list[tuple[int, int]] = []
        for scope, scoped_ids in by_scope.items():
            if not scoped_ids:
                continue
            cur.execute(
                """
                SELECT set_config('graph.tenant_setting', 'mneme.graph_scope', true),
                       set_config('mneme.graph_scope', %s, true)
                """,
                (scope,),
            )
            cur.execute(
                """
                SELECT f.fact_id, MIN(t.depth) AS depth
                FROM unnest(%s::bigint[]) AS seed
                CROSS JOIN LATERAL graph.traverse(
                    'mneme.facts'::regclass::oid,
                    seed::text,
                    max_depth => 2,
                    direction => 'any',
                    include_start => false,
                    hydrate => false,
                    max_rows => %s,
                    max_nodes => 500,
                    max_frontier => 250
                ) AS t
                JOIN mneme.facts f ON f.fact_id = CASE
                    WHEN t.node_table = 'mneme.facts'::regclass::oid
                         AND t.node_id ~ '^[0-9]+$'
                    THEN t.node_id::bigint
                    ELSE NULL
                END
                WHERE t.node_table = 'mneme.facts'::regclass::oid
                  AND f.is_current
                  AND f.state IN ('trusted', 'candidate')
                  AND f.scope = %s
                GROUP BY f.fact_id
                ORDER BY MIN(t.depth), f.fact_id
                LIMIT %s
                """,
                (list(scoped_ids), min(100, max(10, limit)), scope, limit),
            )
            ranked.extend((int(row[1]), int(row[0])) for row in cur.fetchall())
        ranked.sort(key=lambda item: (item[0], item[1]))
        return _unique_prefix([fact_id for _depth, fact_id in ranked], limit)

    def upsert_facts(
        self,
        facts: Sequence[Mapping[str, Any]],
        embeddings: Mapping[int, Sequence[float]],
    ) -> int:
        if not facts:
            return 0
        source_keys: list[str] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, ("global", "project", "agent-private", "handoff"))
                for fact in facts:
                    fact_id = int(fact["fact_id"])
                    vector = embeddings.get(fact_id)
                    cur.execute(
                        """
                        INSERT INTO mneme.facts (
                            fact_id, id, content, category, tags, trust_score,
                            importance, reinforcement_count, retrieval_count,
                            helpful_count, unhelpful_count, last_retrieved_at,
                            state, created_at, updated_at, memory_type, scope,
                            key, version, supersedes_id, superseded_by, source,
                            provenance, embedding, embedding_model, is_current
                        ) VALUES (
                            %(fact_id)s, %(fact_id)s, %(content)s, %(category)s, %(tags)s,
                            %(trust_score)s, %(importance)s,
                            %(reinforcement_count)s, %(retrieval_count)s,
                            %(helpful_count)s, %(unhelpful_count)s,
                            %(last_retrieved_at)s, %(state)s, %(created_at)s,
                            %(updated_at)s, %(memory_type)s, %(scope)s, %(key)s,
                            %(version)s, %(supersedes_id)s, %(superseded_by)s,
                            %(source)s, %(provenance)s,
                            %(embedding)s::pgcontext.vector,
                            %(embedding_model)s, %(is_current)s
                        )
                        ON CONFLICT (fact_id) DO UPDATE SET
                            content = EXCLUDED.content,
                            category = EXCLUDED.category,
                            tags = EXCLUDED.tags,
                            trust_score = EXCLUDED.trust_score,
                            importance = EXCLUDED.importance,
                            reinforcement_count = EXCLUDED.reinforcement_count,
                            retrieval_count = EXCLUDED.retrieval_count,
                            helpful_count = EXCLUDED.helpful_count,
                            unhelpful_count = EXCLUDED.unhelpful_count,
                            last_retrieved_at = EXCLUDED.last_retrieved_at,
                            state = EXCLUDED.state,
                            created_at = EXCLUDED.created_at,
                            updated_at = EXCLUDED.updated_at,
                            memory_type = EXCLUDED.memory_type,
                            scope = EXCLUDED.scope,
                            key = EXCLUDED.key,
                            version = EXCLUDED.version,
                            supersedes_id = EXCLUDED.supersedes_id,
                            superseded_by = EXCLUDED.superseded_by,
                            source = EXCLUDED.source,
                            provenance = EXCLUDED.provenance,
                            embedding = COALESCE(EXCLUDED.embedding, mneme.facts.embedding),
                            embedding_model = COALESCE(
                                EXCLUDED.embedding_model,
                                mneme.facts.embedding_model
                            ),
                            is_current = EXCLUDED.is_current
                        WHERE (
                            mneme.facts.content,
                            mneme.facts.category,
                            mneme.facts.tags,
                            mneme.facts.trust_score,
                            mneme.facts.importance,
                            mneme.facts.reinforcement_count,
                            mneme.facts.retrieval_count,
                            mneme.facts.helpful_count,
                            mneme.facts.unhelpful_count,
                            mneme.facts.last_retrieved_at,
                            mneme.facts.state,
                            mneme.facts.created_at,
                            mneme.facts.updated_at,
                            mneme.facts.memory_type,
                            mneme.facts.scope,
                            mneme.facts.key,
                            mneme.facts.version,
                            mneme.facts.supersedes_id,
                            mneme.facts.superseded_by,
                            mneme.facts.source,
                            mneme.facts.provenance,
                            mneme.facts.embedding_model,
                            mneme.facts.is_current
                        ) IS DISTINCT FROM (
                            EXCLUDED.content,
                            EXCLUDED.category,
                            EXCLUDED.tags,
                            EXCLUDED.trust_score,
                            EXCLUDED.importance,
                            EXCLUDED.reinforcement_count,
                            EXCLUDED.retrieval_count,
                            EXCLUDED.helpful_count,
                            EXCLUDED.unhelpful_count,
                            EXCLUDED.last_retrieved_at,
                            EXCLUDED.state,
                            EXCLUDED.created_at,
                            EXCLUDED.updated_at,
                            EXCLUDED.memory_type,
                            EXCLUDED.scope,
                            EXCLUDED.key,
                            EXCLUDED.version,
                            EXCLUDED.supersedes_id,
                            EXCLUDED.superseded_by,
                            EXCLUDED.source,
                            EXCLUDED.provenance,
                            COALESCE(
                                EXCLUDED.embedding_model,
                                mneme.facts.embedding_model
                            ),
                            EXCLUDED.is_current
                        )
                        OR (
                            EXCLUDED.embedding IS NOT NULL
                            AND (
                                mneme.facts.embedding IS NULL
                                OR mneme.facts.embedding::text
                                   IS DISTINCT FROM EXCLUDED.embedding::text
                            )
                        )
                        """,
                        {
                            **dict(fact),
                            "embedding": _vector_literal(vector) if vector else None,
                            "embedding_model": fact.get("embedding_model")
                            if vector
                            else None,
                            "is_current": fact.get("superseded_by") is None,
                        },
                    )
                    self._replace_fact_entities(cur, fact)
                    self._replace_supersession_edge(cur, fact)
                    if vector:
                        source_keys.append(str(fact_id))
                if source_keys:
                    cur.execute(
                        "SELECT pgcontext.upsert_points(%s, %s)",
                        (COLLECTION, source_keys),
                    )
            conn.commit()
        self._apply_graph_sync()
        return len(facts)

    @staticmethod
    def _replace_fact_entities(cur: Any, fact: Mapping[str, Any]) -> None:
        fact_id = int(fact["fact_id"])
        scope = str(fact.get("scope") or "global")
        entities = _structured_entities(fact)
        desired_bridge_ids: list[str] = []
        for kind, canonical in entities:
            cur.execute(
                """
                INSERT INTO mneme.entities (scope, kind, canonical)
                VALUES (%s, %s, %s)
                ON CONFLICT (scope, kind, canonical) DO NOTHING
                RETURNING entity_id
                """,
                (scope, kind, canonical),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute(
                    """
                    SELECT entity_id
                    FROM mneme.entities
                    WHERE scope = %s AND kind = %s AND canonical = %s
                    """,
                    (scope, kind, canonical),
                )
                inserted = cur.fetchone()
            entity_id = int(inserted[0])
            bridge_id = f"{fact_id}:{kind}:{canonical}"
            desired_bridge_ids.append(bridge_id)
            cur.execute(
                """
                INSERT INTO mneme.fact_entities
                    (bridge_id, fact_id, entity_id, scope, relation_type, weight)
                VALUES (%s, %s, %s, %s, %s, 1.0)
                ON CONFLICT (bridge_id) DO UPDATE SET
                    fact_id = EXCLUDED.fact_id,
                    entity_id = EXCLUDED.entity_id,
                    scope = EXCLUDED.scope,
                    relation_type = EXCLUDED.relation_type,
                    weight = EXCLUDED.weight
                WHERE (
                    mneme.fact_entities.fact_id,
                    mneme.fact_entities.entity_id,
                    mneme.fact_entities.scope,
                    mneme.fact_entities.relation_type,
                    mneme.fact_entities.weight
                ) IS DISTINCT FROM (
                    EXCLUDED.fact_id,
                    EXCLUDED.entity_id,
                    EXCLUDED.scope,
                    EXCLUDED.relation_type,
                    EXCLUDED.weight
                )
                """,
                (bridge_id, fact_id, entity_id, scope, kind),
            )
        cur.execute(
            """
            DELETE FROM mneme.fact_entities
            WHERE fact_id = %s
              AND NOT (bridge_id = ANY(%s))
            """,
            (fact_id, desired_bridge_ids),
        )

    @staticmethod
    def _replace_supersession_edge(cur: Any, fact: Mapping[str, Any]) -> None:
        fact_id = int(fact["fact_id"])
        edge_id = f"supersedes:{fact_id}"
        supersedes_id = fact.get("supersedes_id")
        if supersedes_id is None:
            cur.execute("DELETE FROM mneme.memory_edges WHERE edge_id = %s", (edge_id,))
            return
        cur.execute(
            """
            INSERT INTO mneme.memory_edges
                (edge_id, src_fact_id, dst_fact_id, scope, relation_type,
                 weight, source, evidence)
            SELECT %s, %s, target.fact_id, %s, 'supersedes', 1.0, 'mneme', ''
            FROM mneme.facts AS target
            WHERE target.fact_id = %s
              AND target.scope = %s
            ON CONFLICT (edge_id) DO UPDATE SET
                src_fact_id = EXCLUDED.src_fact_id,
                dst_fact_id = EXCLUDED.dst_fact_id,
                scope = EXCLUDED.scope,
                relation_type = EXCLUDED.relation_type,
                weight = EXCLUDED.weight
            WHERE (
                mneme.memory_edges.src_fact_id,
                mneme.memory_edges.dst_fact_id,
                mneme.memory_edges.scope,
                mneme.memory_edges.relation_type,
                mneme.memory_edges.weight
            ) IS DISTINCT FROM (
                EXCLUDED.src_fact_id,
                EXCLUDED.dst_fact_id,
                EXCLUDED.scope,
                EXCLUDED.relation_type,
                EXCLUDED.weight
            )
            """,
            (
                edge_id,
                fact_id,
                str(fact.get("scope") or "global"),
                int(supersedes_id),
                str(fact.get("scope") or "global"),
            ),
        )

    def upsert_relations(self, relations: Sequence[Mapping[str, Any]]) -> int:
        if not relations:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, ("global", "project", "agent-private", "handoff"))
                for relation in relations:
                    cur.execute(
                        """
                        INSERT INTO mneme.memory_edges
                            (edge_id, src_fact_id, dst_fact_id, scope,
                             relation_type, weight, source, evidence,
                             created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (edge_id) DO UPDATE SET
                            src_fact_id = EXCLUDED.src_fact_id,
                            dst_fact_id = EXCLUDED.dst_fact_id,
                            scope = EXCLUDED.scope,
                            relation_type = EXCLUDED.relation_type,
                            weight = EXCLUDED.weight,
                            source = EXCLUDED.source,
                            evidence = EXCLUDED.evidence,
                            updated_at = EXCLUDED.updated_at
                        WHERE (
                            mneme.memory_edges.src_fact_id,
                            mneme.memory_edges.dst_fact_id,
                            mneme.memory_edges.scope,
                            mneme.memory_edges.relation_type,
                            mneme.memory_edges.weight,
                            mneme.memory_edges.source,
                            mneme.memory_edges.evidence,
                            mneme.memory_edges.updated_at
                        ) IS DISTINCT FROM (
                            EXCLUDED.src_fact_id,
                            EXCLUDED.dst_fact_id,
                            EXCLUDED.scope,
                            EXCLUDED.relation_type,
                            EXCLUDED.weight,
                            EXCLUDED.source,
                            EXCLUDED.evidence,
                            EXCLUDED.updated_at
                        )
                        """,
                        (
                            f"explicit:{int(relation['relation_id'])}",
                            int(relation["src_fact_id"]),
                            int(relation["dst_fact_id"]),
                            str(relation["scope"]),
                            str(relation["relation_type"]),
                            float(relation["weight"]),
                            str(relation["source"]),
                            str(relation["evidence"]),
                            relation["created_at"],
                            relation["updated_at"],
                        ),
                    )
            conn.commit()
        self._apply_graph_sync()
        return len(relations)

    def delete_fact(self, fact_id: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, ("global", "project", "agent-private", "handoff"))
                cur.execute(
                    "SELECT pgcontext.delete_points(%s, %s)",
                    (COLLECTION, [str(int(fact_id))]),
                )
                cur.execute("DELETE FROM mneme.facts WHERE fact_id = %s", (fact_id,))
            conn.commit()
        self._apply_graph_sync()

    def delete_relation(self, relation_id: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, ("global", "project", "agent-private", "handoff"))
                cur.execute(
                    "DELETE FROM mneme.memory_edges WHERE edge_id = %s",
                    (f"explicit:{int(relation_id)}",),
                )
            conn.commit()
        self._apply_graph_sync()

    def rebuild_graph(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, ("global", "project", "agent-private", "handoff"))
                cur.execute("SELECT * FROM graph.build()")
            conn.commit()

    def _apply_graph_sync(self) -> None:
        if os.environ.get("MNEME_GRAPH_SYNC_ON_WRITE", "0") == "0":
            return
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    self._set_scopes(
                        cur, ("global", "project", "agent-private", "handoff")
                    )
                    cur.execute("SELECT * FROM graph.apply_sync()")
                conn.commit()
        except PostgresRetrievalError:
            raise
        except Exception as exc:  # noqa: BLE001 - derived index may lag safely
            raise PostgresRetrievalError("pgGraph synchronization failed") from exc

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                self._set_scopes(cur, ("global", "project", "agent-private", "handoff"))
                cur.execute(
                    """
                    SELECT extname, extversion
                    FROM pg_extension
                    WHERE extname IN ('pgcontext', 'graph', 'pg_cron')
                    ORDER BY extname
                    """
                )
                extensions = {
                    str(name): str(version) for name, version in cur.fetchall()
                }
                cur.execute("SELECT COUNT(*) FROM mneme.facts")
                fact_count = int(cur.fetchone()[0])
                cur.execute("SELECT COUNT(*) FROM mneme.memory_edges")
                edge_count = int(cur.fetchone()[0])
                try:
                    cur.execute("SELECT * FROM mneme.graph_health()")
                    graph_row = cur.fetchone()
                    graph_health = {
                        "status": "ok"
                        if bool(graph_row[2])
                        and str(graph_row[3]) in {"healthy", "succeeded", "running"}
                        else "degraded",
                        "projection_watermark": int(graph_row[0]),
                        "pending_sync_rows": int(graph_row[1]),
                        "projection_valid": bool(graph_row[2]),
                        "maintenance_status": str(graph_row[3]),
                        "maintenance_message": str(graph_row[4] or ""),
                    }
                except Exception as exc:  # noqa: BLE001 - expose health gap
                    graph_health = {"status": "unavailable", "error": str(exc)}
        extensions_ok = {"pgcontext", "graph", "pg_cron"}.issubset(extensions)
        graph_runtime = _graph_runtime_snapshot()
        graph_health["runtime"] = graph_runtime
        graph_ok = graph_health["status"] == "ok" and not bool(
            graph_runtime["circuit_open"]
        )
        return {
            "status": "ok" if extensions_ok and graph_ok else "degraded",
            "host": self.settings.host,
            "port": self.settings.port,
            "database": self.settings.database,
            "facts": fact_count,
            "edges": edge_count,
            "extensions": extensions,
            "graph": graph_health,
        }


def _structured_entities(fact: Mapping[str, Any]) -> list[tuple[str, str]]:
    entities: set[tuple[str, str]] = set()
    key = str(fact.get("key") or "").strip()
    if key and _ENTITY_RE.fullmatch(key):
        entities.add(("key", key.lower()))
    for raw_tag in str(fact.get("tags") or "").split(","):
        tag = raw_tag.strip()
        if tag and _ENTITY_RE.fullmatch(tag):
            entities.add(("tag", tag.lower()))
    return sorted(entities)


def _vector_literal(values: Sequence[float] | None) -> str | None:
    if values is None:
        return None
    return "[" + ",".join(format(float(value), ".9g") for value in values) + "]"


def _weighted_rrf(
    ranked_lists: Sequence[tuple[Sequence[int], float]], *, k: int = RRF_K
) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked, weight in ranked_lists:
        for rank, fact_id in enumerate(ranked, start=1):
            scores[int(fact_id)] = scores.get(int(fact_id), 0.0) + float(weight) / (
                k + rank
            )
    return scores


def _unique_prefix(values: Sequence[int], limit: int) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        value = int(value)
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


__all__ = [
    "PostgresRetrievalError",
    "PostgresRetrievalPlane",
    "PostgresSettings",
    "postgres_required",
    "postgres_retrieval_enabled",
    "retrieval_backend",
]
