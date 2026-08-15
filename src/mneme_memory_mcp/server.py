from __future__ import annotations

import json
import os
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .bridge import bridge_status
from .bridge import delegate_to_claude as run_claude
from .bridge import delegate_to_codex as run_codex
from .store import SharedMemoryStore, format_facts

mcp = FastMCP("mneme-memory")


def store() -> SharedMemoryStore:
    return SharedMemoryStore()


@mcp.tool()
def memory_summary() -> str:
    """Return the always-on shared memory summary."""

    return store().summary()


@mcp.tool()
def memory_search(
    query: str,
    limit: int = 10,
    scope: Literal["global", "project", "agent-private", "handoff"] = "project",
) -> str:
    """Search the shared memory fact store."""

    return format_facts(store().search(query=query, limit=limit, scope=scope))


@mcp.tool()
def memory_briefing(
    query: str = "",
    limit: int = 12,
    scope: Literal["global", "project", "agent-private", "handoff"] = "project",
) -> str:
    """Return a bounded trusted-memory briefing, optionally matched to a query."""

    return store().briefing(query=query, limit=limit, scope=scope)


@mcp.tool()
def memory_health() -> str:
    """Return database, retrieval, embedding, and integrity health."""

    return json.dumps(store().health(), sort_keys=True)


@mcp.tool()
def memory_list(
    limit: int = 25,
    scope: Literal["global", "project", "agent-private", "handoff"] = "project",
) -> str:
    """List recent facts from the shared memory fact store."""

    return format_facts(store().list(limit=limit, scope=scope))


@mcp.tool()
def memory_add(
    content: str,
    target: Literal["user", "memory"] = "memory",
    category: Literal[
        "user_pref", "project", "tool", "general", "conversation"
    ] = "general",
    tags: str = "",
    memory_type: Literal[
        "semantic", "episodic", "procedural", "resource", "handoff"
    ] = "semantic",
    scope: Literal["global", "project", "agent-private", "handoff"] | None = None,
    key: str = "",
    version: str = "",
    importance: float | None = None,
) -> str:
    """Add a durable fact to shared memory.

    Use target='user' for identity, preferences, and working style.
    Use target='memory' for projects, tools, paths, decisions, and setup notes.
    """

    try:
        memory_store = store()
        fact_id = memory_store.add(
            content=content,
            target=target,
            category=category,
            tags=tags,
            memory_type=memory_type,
            scope=scope,
            key=key,
            version=version,
            importance=importance,
            source="agent:mcp",
        )
        fact = memory_store.get_fact(fact_id)
    except ValueError as exc:
        return f"error: {exc}"
    state = fact.state if fact else "candidate"
    return f"saved {state} fact {fact_id} to {target} memory"


@mcp.tool()
def memory_current(
    key: str,
    scope: Literal["global", "project", "agent-private", "handoff"] = "project",
) -> str:
    """Resolve the current value for a supersession key."""

    fact = store().current(key, scope=scope)
    return fact.format() if fact else "(no current fact)"


@mcp.tool()
def memory_consolidate() -> str:
    """Regenerate compact USER.md and MEMORY.md working-set views."""

    store().consolidate()
    return "regenerated USER.md and MEMORY.md"


@mcp.tool()
def memory_update(
    fact_id: int,
    content: str | None = None,
    category: Literal["user_pref", "project", "tool", "general", "conversation"]
    | None = None,
    tags: str | None = None,
    trust_score: float | None = None,
    importance: float | None = None,
) -> str:
    """Update a fact by id."""

    try:
        ok = store().update(
            fact_id=fact_id,
            content=content,
            category=category,
            tags=tags,
            trust_score=trust_score,
            importance=importance,
        )
    except ValueError as exc:
        return f"error: {exc}"
    return "updated" if ok else f"fact {fact_id} not found"


@mcp.tool()
def memory_remove(fact_id: int) -> str:
    """Remove a fact by id and remove the matching Markdown bullet if present."""

    ok = store().remove(fact_id=fact_id)
    return "removed" if ok else f"fact {fact_id} not found"


@mcp.tool()
def memory_link(
    src_fact_id: int,
    dst_fact_id: int,
    relation_type: str,
    weight: float = 1.0,
    evidence: str = "",
    source: str = "agent:mcp",
) -> str:
    """Create a typed same-scope relationship between two durable facts."""

    try:
        relation_id = store().link(
            src_fact_id,
            dst_fact_id,
            relation_type=relation_type,
            weight=weight,
            evidence=evidence,
            source=source,
        )
    except ValueError as exc:
        return f"error: {exc}"
    return f"saved relation {relation_id}"


@mcp.tool()
def memory_links(
    fact_id: int | None = None,
    scope: Literal["global", "project", "agent-private", "handoff"] = "project",
    limit: int = 50,
) -> str:
    """List typed memory relationships, optionally for one fact."""

    return json.dumps(
        store().list_links(fact_id=fact_id, scope=scope, limit=limit),
        sort_keys=True,
    )


@mcp.tool()
def memory_unlink(relation_id: int) -> str:
    """Remove one explicit relationship without removing either fact."""

    return "removed" if store().unlink(relation_id) else f"relation {relation_id} not found"


@mcp.tool()
def memory_feedback(fact_id: int, helpful: bool, source: str = "agent") -> str:
    """Record whether a recalled fact helped with the current task."""

    fact = store().feedback(fact_id, helpful=helpful, source=source)
    return fact.format() if fact else f"fact {fact_id} is unavailable for feedback"


@mcp.tool()
def memory_review_list(limit: int = 25) -> str:
    """List automated candidate memories awaiting validation."""

    return format_facts(store().review_candidates(limit=limit))


@mcp.tool()
def memory_review_decide(
    fact_id: int,
    action: Literal["promote", "reject"],
    source: str = "human-review",
) -> str:
    """Promote a candidate to trusted memory or reject it without deleting audit history."""

    state: Literal["trusted", "rejected"] = (
        "trusted" if action == "promote" else "rejected"
    )
    try:
        fact = store().set_state(fact_id, state=state, source=source)
    except ValueError as exc:
        return f"error: {exc}"
    return fact.format() if fact else f"fact {fact_id} not found"


@mcp.tool()
def memory_maintain(
    max_episodic: int = 1000,
    max_age_days: int = 30,
    keep_events: int = 20000,
    keep_candidates: int = 3000,
    vacuum: bool = True,
) -> str:
    """Run bounded idempotent maintenance and return an integrity report."""

    report = store().maintain(
        max_episodic=max_episodic,
        max_age_days=max_age_days,
        keep_events=keep_events,
        keep_candidates=keep_candidates,
        vacuum=vacuum,
    )
    return json.dumps(report, sort_keys=True)


@mcp.tool()
def memory_embeddings_backfill(
    batch_size: int = 32,
    limit: int | None = None,
    force: bool = False,
) -> str:
    """Backfill missing local embeddings without changing memory content."""

    return json.dumps(
        store().backfill_embeddings(batch_size=batch_size, limit=limit, force=force),
        sort_keys=True,
    )


@mcp.tool()
def memory_embeddings_prepare() -> str:
    """Explicitly download/cache the pinned local embedding model."""

    return json.dumps(store().prepare_embeddings(), sort_keys=True)


@mcp.tool()
def memory_handoff_write(
    goal: str,
    scope: str = "global",
    repo_state: str = "",
    files_touched: str = "",
    decisions: str = "",
    blockers: str = "",
    assumptions: str = "",
    validation: str = "",
    next_steps: str = "",
    evidence: str = "",
) -> str:
    """Write a structured handoff for another agent/session."""

    handoff_id = store().write_handoff(
        scope=scope,
        goal=goal,
        repo_state=repo_state,
        files_touched=files_touched,
        decisions=decisions,
        blockers=blockers,
        assumptions=assumptions,
        validation=validation,
        next_steps=next_steps,
        evidence=evidence,
    )
    return f"saved handoff {handoff_id}"


@mcp.tool()
def memory_handoff_latest(scope: str = "global") -> str:
    """Return the latest structured handoff for a scope."""

    handoff = store().latest_handoff(scope)
    return handoff.format() if handoff else "(no handoff)"


if os.environ.get("MNEME_ENABLE_AGENT_BRIDGE", "0") == "1":

    @mcp.tool()
    def agent_bridge_status() -> str:
        """Show whether local Claude, Codex, and Node bridge dependencies are available."""

        return bridge_status()

    @mcp.tool()
    def delegate_to_claude(
        prompt: str,
        cwd: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 600,
    ) -> str:
        """Ask Claude Code to handle a one-shot task inside the configured bridge root."""

        try:
            return run_claude(
                prompt=prompt,
                cwd=cwd,
                model=model,
                timeout_seconds=timeout_seconds,
            ).format()
        except (RuntimeError, ValueError) as exc:
            return f"error: {exc}"

    @mcp.tool()
    def delegate_to_codex(
        prompt: str,
        cwd: str | None = None,
        model: str | None = None,
        sandbox: Literal["read-only", "workspace-write"] = "workspace-write",
        timeout_seconds: int = 600,
    ) -> str:
        """Ask Codex to handle a one-shot task inside the configured bridge root."""

        try:
            return run_codex(
                prompt=prompt,
                cwd=cwd,
                model=model,
                sandbox=sandbox,
                timeout_seconds=timeout_seconds,
            ).format()
        except (RuntimeError, ValueError) as exc:
            return f"error: {exc}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
