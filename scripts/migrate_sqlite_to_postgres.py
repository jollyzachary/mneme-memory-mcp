#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterator, Sequence

from mneme_memory_mcp.postgres_retrieval import PostgresRetrievalPlane
from mneme_memory_mcp.store import resolve_db_path, resolve_home


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or apply a non-destructive copy from Mneme SQLite into its "
            "PostgreSQL retrieval plane. SQLite is never deleted or rewritten."
        )
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=resolve_db_path(resolve_home()),
        help="Source Mneme SQLite database.",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the copy. Without this flag, only print a read-only plan.",
    )
    parser.add_argument(
        "--skip-graph-rebuild",
        action="store_true",
        help="Do not rebuild pgGraph after an applied copy.",
    )
    return parser


def connect_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def _chunks(rows: Sequence[sqlite3.Row], size: int) -> Iterator[Sequence[sqlite3.Row]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _unpack(blob: bytes) -> list[float]:
    count = len(blob) // 4
    if count == 0:
        return []
    return list(struct.unpack(f"{count}f", blob))


def _load_facts(
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], dict[int, Sequence[float]]]:
    if _has_table(conn, "fact_embeddings"):
        rows = conn.execute(
            """
            SELECT f.*, e.model AS embedding_model, e.embedding AS embedding_blob
            FROM facts f
            LEFT JOIN fact_embeddings e ON e.fact_id = f.fact_id
            ORDER BY f.fact_id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT f.*, NULL AS embedding_model, NULL AS embedding_blob
            FROM facts f
            ORDER BY f.fact_id
            """
        ).fetchall()
    facts: list[dict[str, Any]] = []
    embeddings: dict[int, Sequence[float]] = {}
    for row in rows:
        fact = dict(row)
        blob = fact.pop("embedding_blob", None)
        fact_id = int(fact["fact_id"])
        if blob:
            embeddings[fact_id] = _unpack(blob)
        facts.append(fact)
    return facts, embeddings


def _load_relations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _has_table(conn, "fact_relations"):
        return []
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM fact_relations ORDER BY relation_id"
        ).fetchall()
    ]


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    source = args.sqlite.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"SQLite source does not exist: {source}")
    batch_size = max(1, min(5_000, int(args.batch_size)))

    with connect_read_only(source) as conn:
        facts, embeddings = _load_facts(conn)
        relations = _load_relations(conn)

    plan = {
        "mode": "apply" if args.apply else "dry-run",
        "source": str(source),
        "facts": len(facts),
        "embeddings": len(embeddings),
        "relations": len(relations),
        "batch_size": batch_size,
        "sqlite_preserved": True,
    }
    print(json.dumps(plan, indent=2, sort_keys=True))
    if not args.apply:
        print("Dry run only. Re-run with --apply after reviewing the plan.")
        return

    plane = PostgresRetrievalPlane()
    copied = 0
    for batch in _chunks(facts, batch_size):
        batch_embeddings = {
            int(row["fact_id"]): embeddings[int(row["fact_id"])]
            for row in batch
            if int(row["fact_id"]) in embeddings
        }
        copied += plane.upsert_facts(batch, batch_embeddings)

    relation_count = 0
    for batch in _chunks(relations, batch_size):
        relation_count += plane.upsert_relations(batch)

    if not args.skip_graph_rebuild:
        plane.rebuild_graph()

    result = plane.health()
    result.update(
        {
            "copied_facts": copied,
            "copied_relations": relation_count,
            "source_preserved": str(source),
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
