from __future__ import annotations

import argparse
import json

from .store import (
    MemoryCategory,
    MemoryScope,
    MemoryTarget,
    MemoryType,
    SharedMemoryStore,
    format_facts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mneme-memory",
        description="Read and write the shared Mneme/Hermes memory layer.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary", help="Print USER.md and MEMORY.md.")

    briefing = subparsers.add_parser(
        "briefing", help="Print a bounded trusted-memory briefing."
    )
    briefing.add_argument(
        "query", nargs="?", default="", help="Optional task/query text."
    )
    briefing.add_argument(
        "--limit", type=int, default=12, help="Maximum relevant facts."
    )
    briefing.add_argument(
        "--scope",
        choices=("global", "project", "agent-private", "handoff"),
        default="project",
    )

    subparsers.add_parser("health", help="Print database and retrieval health.")

    search = subparsers.add_parser("search", help="Search durable facts.")
    search.add_argument("query", help="Search terms.")
    search.add_argument("--limit", type=int, default=10, help="Maximum results.")
    search.add_argument(
        "--scope",
        choices=("global", "project", "agent-private", "handoff"),
        default="project",
        help="Read visibility scope.",
    )

    recent = subparsers.add_parser("list", help="List recent durable facts.")
    recent.add_argument("--limit", type=int, default=25, help="Maximum results.")
    recent.add_argument(
        "--scope",
        choices=("global", "project", "agent-private", "handoff"),
        default="project",
        help="Read visibility scope.",
    )

    add = subparsers.add_parser("add", help="Add a durable fact.")
    add.add_argument("content", nargs="+", help="Fact content to remember.")
    add.add_argument(
        "--target",
        choices=("user", "memory"),
        default="memory",
        help="Memory target file to append to.",
    )
    add.add_argument(
        "--category",
        choices=("user_pref", "project", "tool", "general", "conversation"),
        default="general",
        help="Fact category.",
    )
    add.add_argument("--tags", default="", help="Comma-separated tags.")
    add.add_argument(
        "--memory-type",
        choices=("semantic", "episodic", "procedural", "resource", "handoff"),
        default="semantic",
        help="Typed memory layer.",
    )
    add.add_argument(
        "--scope",
        choices=("global", "project", "agent-private", "handoff"),
        default=None,
        help="Memory visibility scope.",
    )
    add.add_argument(
        "--key", default="", help="Stable supersession key for mutable facts."
    )
    add.add_argument(
        "--version", default="", help="Optional version or freshness signal."
    )
    add.add_argument(
        "--importance",
        type=float,
        default=None,
        help="Importance from 0 through 1.",
    )

    current = subparsers.add_parser(
        "current", help="Resolve the current fact for a supersession key."
    )
    current.add_argument("key")
    current.add_argument(
        "--scope",
        choices=("global", "project", "agent-private", "handoff"),
        default="project",
        help="Read visibility scope.",
    )

    link = subparsers.add_parser(
        "link", help="Create a typed relationship between two durable facts."
    )
    link.add_argument("src_fact_id", type=int)
    link.add_argument("dst_fact_id", type=int)
    link.add_argument("relation_type")
    link.add_argument("--weight", type=float, default=1.0)
    link.add_argument("--evidence", default="")
    link.add_argument("--source", default="cli")

    links = subparsers.add_parser("links", help="List typed memory relationships.")
    links.add_argument("--fact-id", type=int, default=None)
    links.add_argument("--limit", type=int, default=50)
    links.add_argument(
        "--scope",
        choices=("global", "project", "agent-private", "handoff"),
        default="project",
    )

    unlink = subparsers.add_parser("unlink", help="Remove a typed relationship.")
    unlink.add_argument("relation_id", type=int)

    subparsers.add_parser(
        "consolidate", help="Regenerate compact USER.md and MEMORY.md views."
    )

    feedback = subparsers.add_parser(
        "feedback", help="Record usefulness feedback for a fact."
    )
    feedback.add_argument("fact_id", type=int)
    feedback.add_argument(
        "rating",
        choices=("helpful", "not-helpful"),
    )
    feedback.add_argument("--source", default="cli")

    review = subparsers.add_parser("review", help="Review automated memory candidates.")
    review_sub = review.add_subparsers(dest="review_command", required=True)
    review_list = review_sub.add_parser("list", help="List candidate memories.")
    review_list.add_argument("--limit", type=int, default=25)
    for command in ("promote", "reject"):
        decision = review_sub.add_parser(
            command, help=f"{command.title()} a candidate."
        )
        decision.add_argument("fact_id", type=int)

    maintain = subparsers.add_parser("maintain", help="Run bounded memory maintenance.")
    maintain.add_argument("--max-episodic", type=int, default=1000)
    maintain.add_argument("--max-age-days", type=int, default=30)
    maintain.add_argument("--keep-events", type=int, default=20000)
    maintain.add_argument("--keep-candidates", type=int, default=3000)
    maintain.add_argument("--no-vacuum", action="store_true")

    embeddings = subparsers.add_parser(
        "embeddings", help="Manage local semantic embeddings."
    )
    embedding_sub = embeddings.add_subparsers(dest="embedding_command", required=True)
    embedding_sub.add_parser("prepare", help="Download/cache the pinned local model.")
    backfill = embedding_sub.add_parser("backfill", help="Backfill missing embeddings.")
    backfill.add_argument("--batch-size", type=int, default=32)
    backfill.add_argument("--limit", type=int, default=None)
    backfill.add_argument("--force", action="store_true")

    handoff = subparsers.add_parser(
        "handoff", help="Read or write structured handoffs."
    )
    handoff_sub = handoff.add_subparsers(dest="handoff_command", required=True)
    handoff_latest = handoff_sub.add_parser(
        "latest", help="Print the latest handoff for a scope."
    )
    handoff_latest.add_argument("--scope", default="global")
    handoff_write = handoff_sub.add_parser("write", help="Write a structured handoff.")
    handoff_write.add_argument("--scope", default="global")
    handoff_write.add_argument("--goal", required=True)
    handoff_write.add_argument("--repo-state", default="")
    handoff_write.add_argument("--files-touched", default="")
    handoff_write.add_argument("--decisions", default="")
    handoff_write.add_argument("--blockers", default="")
    handoff_write.add_argument("--assumptions", default="")
    handoff_write.add_argument("--validation", default="")
    handoff_write.add_argument("--next-steps", default="")
    handoff_write.add_argument("--evidence", default="")

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    store = SharedMemoryStore()

    if args.command == "summary":
        print(store.summary())
    elif args.command == "briefing":
        print(store.briefing(query=args.query, limit=args.limit, scope=args.scope))
    elif args.command == "health":
        print(json.dumps(store.health(), indent=2, sort_keys=True))
    elif args.command == "search":
        print(
            format_facts(
                store.search(query=args.query, limit=args.limit, scope=args.scope)
            )
        )
    elif args.command == "list":
        print(format_facts(store.list(limit=args.limit, scope=args.scope)))
    elif args.command == "add":
        content = " ".join(args.content)
        fact_id = store.add(
            content=content,
            target=args.target,
            category=args.category,
            tags=args.tags,
            memory_type=args.memory_type,
            scope=args.scope,
            key=args.key,
            version=args.version,
            importance=args.importance,
        )
        print(f"saved fact {fact_id} to {args.target} memory")
    elif args.command == "current":
        fact = store.current(args.key, scope=args.scope)
        print(fact.format() if fact else "(no current fact)")
    elif args.command == "link":
        try:
            relation_id = store.link(
                args.src_fact_id,
                args.dst_fact_id,
                relation_type=args.relation_type,
                weight=args.weight,
                evidence=args.evidence,
                source=args.source,
            )
        except ValueError as exc:
            print(f"error: {exc}")
        else:
            print(f"saved relation {relation_id}")
    elif args.command == "links":
        print(
            json.dumps(
                store.list_links(
                    fact_id=args.fact_id, scope=args.scope, limit=args.limit
                ),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "unlink":
        print(
            "removed"
            if store.unlink(args.relation_id)
            else f"relation {args.relation_id} not found"
        )
    elif args.command == "consolidate":
        store.consolidate()
        print("regenerated USER.md and MEMORY.md")
    elif args.command == "feedback":
        fact = store.feedback(
            args.fact_id,
            helpful=args.rating == "helpful",
            source=args.source,
        )
        print(
            fact.format()
            if fact
            else f"fact {args.fact_id} is unavailable for feedback"
        )
    elif args.command == "review":
        if args.review_command == "list":
            print(format_facts(store.review_candidates(limit=args.limit)))
        else:
            state = "trusted" if args.review_command == "promote" else "rejected"
            try:
                fact = store.set_state(args.fact_id, state=state, source="cli-review")
            except ValueError as exc:
                print(f"error: {exc}")
            else:
                print(fact.format() if fact else f"fact {args.fact_id} not found")
    elif args.command == "maintain":
        print(
            json.dumps(
                store.maintain(
                    max_episodic=args.max_episodic,
                    max_age_days=args.max_age_days,
                    keep_events=args.keep_events,
                    keep_candidates=args.keep_candidates,
                    vacuum=not args.no_vacuum,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    elif args.command == "embeddings":
        if args.embedding_command == "prepare":
            print(json.dumps(store.prepare_embeddings(), indent=2, sort_keys=True))
        elif args.embedding_command == "backfill":
            print(
                json.dumps(
                    store.backfill_embeddings(
                        batch_size=args.batch_size,
                        limit=args.limit,
                        force=args.force,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
    elif args.command == "handoff":
        if args.handoff_command == "latest":
            handoff = store.latest_handoff(args.scope)
            print(handoff.format() if handoff else "(no handoff)")
        elif args.handoff_command == "write":
            handoff_id = store.write_handoff(
                scope=args.scope,
                goal=args.goal,
                repo_state=args.repo_state,
                files_touched=args.files_touched,
                decisions=args.decisions,
                blockers=args.blockers,
                assumptions=args.assumptions,
                validation=args.validation,
                next_steps=args.next_steps,
                evidence=args.evidence,
            )
            print(f"saved handoff {handoff_id}")


__all__ = [
    "MemoryCategory",
    "MemoryScope",
    "MemoryTarget",
    "MemoryType",
    "build_parser",
    "main",
]


if __name__ == "__main__":
    main()
