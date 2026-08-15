from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .continuity import continuity_status
from .store import SharedMemoryStore, resolve_db_path, resolve_home, resolve_memory_dir


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def find_hermes() -> str | None:
    found = shutil.which("hermes")
    if found:
        return found

    candidates = [
        Path.home() / ".local" / "bin" / "hermes",
        Path.home() / ".hermes" / "bin" / "hermes",
        Path.home() / ".hermes" / "hermes-agent" / "hermes",
    ]
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        candidates.extend(
            [
                Path.home() / ".local" / "bin" / "hermes.exe",
                Path.home() / ".hermes" / "bin" / "hermes.exe",
                Path.home() / ".hermes" / "hermes-agent" / "hermes.exe",
            ]
        )
        if local_app_data:
            candidates.append(
                Path(local_app_data)
                / "hermes"
                / "hermes-agent"
                / "venv"
                / "Scripts"
                / "hermes.exe"
            )
    existing = _first_existing(candidates)
    return str(existing) if existing else None


def _which(command: str) -> str:
    return shutil.which(command) or "missing"


def _version(command: str) -> str:
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "version unavailable"

    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if text else "version unavailable"


def status_lines() -> list[str]:
    home = resolve_home()
    memory_dir = resolve_memory_dir(home)
    db_path = resolve_db_path(home)
    hermes = find_hermes()
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

    if hermes:
        lines.append(f"Hermes Agent: {hermes} ({_version(hermes)})")
    else:
        lines.append("Hermes Agent: missing")
        lines.append(
            "Mneme can run without Hermes; review the upstream Hermes documentation before installing it separately."
        )

    lines.extend(["", "Always-on memory continuity:"])
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
