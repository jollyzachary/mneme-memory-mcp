#!/usr/bin/env python3
"""Backfill local fact embeddings for hybrid retrieval.

The command accepts a scratch database by default. Writing to the configured
Mneme store requires ``--allow-live``.

Examples
--------
# Run against a scratch copy:
cp ~/.hermes/memory_store.db /tmp/mneme-embed-scratch.db
python scripts/backfill_embeddings.py --db /tmp/mneme-embed-scratch.db

# Force re-embed everything on a copy:
python scripts/backfill_embeddings.py --db /tmp/mneme-embed-scratch.db --force
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _live_db_candidates() -> list[Path]:
    import os

    candidates: list[Path] = []
    raw = os.environ.get("MNEME_DB_PATH")
    if raw:
        candidates.append(Path(raw).expanduser().resolve())
    home_raw = (
        os.environ.get("MNEME_HOME")
        or os.environ.get("HERMES_HOME")
        or "~/.hermes"
    )
    candidates.append((Path(home_raw).expanduser() / "memory_store.db").resolve())
    candidates.append(Path("~/.hermes/memory_store.db").expanduser().resolve())
    # Deduplicate while preserving order.
    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Mneme fact embeddings (scratch DB only by default)."
    )
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to a SQLite memory_store.db (prefer a copy of the live DB).",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max facts to embed (for timing samples).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed facts even if a vector already exists for the model.",
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Permit writing the live ~/.hermes (or MNEME_DB_PATH) database.",
    )
    args = parser.parse_args(argv)

    db_path = args.db.expanduser().resolve()
    if not db_path.exists():
        print(f"error: database not found: {db_path}", file=sys.stderr)
        return 2

    live_paths = _live_db_candidates()
    if db_path in live_paths and not args.allow_live:
        print(
            "REFUSED: refusing to write the live Mneme memory database.\n"
            f"  target: {db_path}\n"
            "  Copy it first, e.g.:\n"
            f"    cp {db_path} /tmp/mneme-embed-scratch.db\n"
            "    python scripts/backfill_embeddings.py --db /tmp/mneme-embed-scratch.db\n"
            "  Or pass --allow-live if you intentionally want the live store.",
            file=sys.stderr,
        )
        return 3

    # Import after path checks so dependency errors retain a clear target message.
    from mneme_memory_mcp.store import SharedMemoryStore, embeddings_available

    if not embeddings_available():
        print(
            "error: no embedder available. Install optional deps:\n"
            "  pip install 'mneme-memory-mcp[embeddings]'\n"
            "  # or: pip install sentence-transformers numpy",
            file=sys.stderr,
        )
        return 4

    store = SharedMemoryStore(db_path=db_path, home=db_path.parent)
    print(f"backfill target: {db_path}")
    print(f"batch_size={args.batch_size} limit={args.limit} force={args.force}")
    wall0 = time.perf_counter()
    result = store.backfill_embeddings(
        batch_size=args.batch_size,
        limit=args.limit,
        force=args.force,
    )
    wall = time.perf_counter() - wall0
    print(
        f"status={result['status']} model={result['model']} "
        f"embedded={result['embedded']} errors={result['errors']} "
        f"embed_seconds={result['seconds']:.3f} wall_seconds={wall:.3f}"
    )
    if result["status"] != "ok":
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
