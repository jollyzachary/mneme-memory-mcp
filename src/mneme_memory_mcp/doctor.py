from __future__ import annotations

import shutil

from .continuity import continuity_status
from .store import SharedMemoryStore, resolve_db_path, resolve_home, resolve_memory_dir


def _which(command: str) -> str:
    return shutil.which(command) or "missing"


def status_lines() -> list[str]:
    home = resolve_home()
    memory_dir = resolve_memory_dir(home)
    db_path = resolve_db_path(home)
    health = SharedMemoryStore(
        home=home, memory_dir=memory_dir, db_path=db_path
    ).health()

    lines = [
        "Mneme Memory MCP doctor",
        "",
        f"memory home: {home}",
        f"markdown memories: {memory_dir}",
        f"fact store: {db_path}",
        f"USER.md: {'ok' if (memory_dir / 'USER.md').exists() else 'missing'}",
        f"MEMORY.md: {'ok' if (memory_dir / 'MEMORY.md').exists() else 'missing'}",
        f"SQLite store: {'ok' if db_path.exists() else 'will be created on first write'}",
        f"SQLite integrity: {health['integrity']}",
        f"schema version: {health['schema_version']}",
        f"current facts: {health['current_facts']}",
        f"candidate facts: {health['candidates']}",
        f"embedding backend: {health['embedding_backend']}",
        f"embedding coverage: {health['embedded_facts']}/{health['embedding_eligible_facts']}",
        f"retrieval backend: {health['retrieval_backend']}",
        f"pending PostgreSQL sync: {health['pending_postgres_sync']}",
        f"Claude CLI: {_which('claude')}",
        f"Codex CLI: {_which('codex')}",
        f"Node: {_which('node')}",
    ]

    postgres = health.get("postgres")
    if isinstance(postgres, dict):
        lines.append(f"PostgreSQL retrieval: {postgres.get('status', 'unknown')}")
        if postgres.get("status") == "ok":
            lines.append(
                f"PostgreSQL mirror: {postgres.get('facts', 0)} facts, "
                f"{postgres.get('edges', 0)} edges"
            )

    lines.extend(["", "Client continuity:"])
    lines.extend(f"  {line}" for line in continuity_status().lines())

    lines.extend(
        [
            "",
            "MCP server command:",
            "  mneme-memory-mcp",
        ]
    )
    return lines


def main() -> None:
    print("\n".join(status_lines()))


if __name__ == "__main__":
    main()
