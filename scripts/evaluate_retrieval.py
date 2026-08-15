#!/usr/bin/env python3
"""Offline smoke evaluation for Mneme's lexical + semantic recall.

The script creates a temporary store, never touches the configured memory home,
and exits non-zero when retrieval quality drops below the requested threshold.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from mneme_memory_mcp.store import SharedMemoryStore, embeddings_available


@dataclass(frozen=True)
class Case:
    query: str
    expected: str


FACTS = (
    "Agent peers exchange messages through the local bridge protocol.",
    "The canonical sample library is stored under /srv/media/samples.",
    "A human reviewer performs interactive interface testing.",
    "Publishing changes requires explicit maintainer approval.",
    "The development build is the default target for requested product changes.",
)

CASES = (
    Case("how do subagents communicate with one another", "local bridge protocol"),
    Case("where is the canonical sample folder", "/srv/media/samples"),
    Case(
        "who performs graphical interface testing", "human reviewer performs interactive"
    ),
    Case("what authorizes publishing changes", "explicit maintainer approval"),
    Case("which build should product changes target", "development build"),
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--k", type=int, default=3)
    result.add_argument("--min-recall", type=float, default=0.80)
    return result


def main() -> None:
    args = parser().parse_args()
    with tempfile.TemporaryDirectory(prefix="mneme-eval-") as temporary:
        store = SharedMemoryStore(home=Path(temporary))
        for content in FACTS:
            store.add_fact(
                content,
                source="manual",
                scope="global",
                importance=0.8,
            )

        latencies: list[float] = []
        reciprocal_ranks: list[float] = []
        passed = 0
        for case in CASES:
            started = time.perf_counter()
            hits = store.search(case.query, limit=args.k, scope="global", record=False)
            latencies.append((time.perf_counter() - started) * 1_000)
            rank = next(
                (
                    index
                    for index, fact in enumerate(hits, start=1)
                    if case.expected.lower() in fact.content.lower()
                ),
                None,
            )
            if rank is not None:
                passed += 1
                reciprocal_ranks.append(1.0 / rank)
            else:
                reciprocal_ranks.append(0.0)
            print(
                f"case={case.query!r} rank={rank if rank is not None else 'miss'} "
                f"top={[fact.content for fact in hits]}"
            )

        recall = passed / len(CASES)
        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
        print(
            f"embedding_backend={'available' if embeddings_available() else 'unavailable'}"
        )
        print(f"recall@{args.k}={recall:.3f}")
        print(f"mrr={mrr:.3f}")
        print(f"latency_ms_p50={p50:.2f}")
        print(f"latency_ms_p95={p95:.2f}")
        if recall < args.min_recall:
            raise SystemExit(
                f"retrieval recall {recall:.3f} is below required {args.min_recall:.3f}"
            )


if __name__ == "__main__":
    main()
