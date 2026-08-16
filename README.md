# Mneme Memory MCP

Local-first, durable memory for AI agents.

![Mneme Memory MCP](assets/mneme-hero.png)

[![CI](https://github.com/jollyzachary/mneme-memory-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jollyzachary/mneme-memory-mcp/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-111111.svg)](LICENSE)

Mneme gives MCP-compatible agents a shared memory layer that remains under the
user's control. It preserves facts, decisions, preferences, relationships, and
handoffs across sessions without making a hosted service the source of truth.

Mneme is pronounced **NEE-mee**. The name comes from the Greek word μνήμη
(*mnēmē*), meaning memory or remembrance.

> Mneme is early-stage software. The storage model and MCP interface are usable,
> but installation and extension interfaces may change before 1.0.

## What it does

- Stores durable facts with scope, provenance, trust, importance, and lifecycle
  state.
- Resolves versioned facts while retaining supersession history.
- Combines SQLite full-text search, exact matching, and optional local
  embeddings.
- Supports typed relationships and bounded graph-aware recall.
- Produces compact Markdown working sets for low-cost context injection.
- Carries structured handoffs between agents and sessions.
- Quarantines suspicious automated content and rejects secret-like fact writes.
- Exposes the same memory through MCP tools and a local CLI.

## Architecture

```text
Agent 1 ─┐
Agent 2 ─┼── MCP / CLI ── Mneme ── SQLite journal (authoritative)
Agent 3 ─┘                   │
                            ├── Generated working sets
                            └── PostgreSQL retrieval plane (optional)
                                 ├── pgContext vectors
                                 └── pgGraph relationships
```

A single agent can use Mneme for continuity across sessions. Multiple trusted
agents can connect to the same store without routing through one another.

SQLite owns durable state, governance decisions, audit events, handoffs, and
episodic archives. The optional PostgreSQL service is a rebuildable retrieval
index. If it is unavailable, Mneme can continue from SQLite.

## Design

### Governed memory

Manual writes enter the trusted working set. Automated capture enters as a
candidate and must be promoted before it appears in generated context. Content
that resembles prompt injection is quarantined. Secret-like durable writes are
rejected, while conversation capture applies credential redaction before
storing episodic text. Default search and list operations return trusted memory
only; candidate review is an explicit operation.

### Hybrid retrieval

Mneme preserves exact identifiers and commands through lexical search while
optional local embeddings recover paraphrases. Reciprocal Rank Fusion combines
the candidate sets, then bounded quality signals account for trust, importance,
source quality, feedback, and recency.

### Inspectable relationships

Relationships are explicit, typed, same-scope edges. Mneme does not convert
embedding similarity into an asserted relationship. Links can be inspected,
used during bounded retrieval, and removed without changing either fact.

### Structured handoffs

Handoffs record the goal, current state, decisions, blockers, evidence, and next
steps. They provide continuity without copying an entire transcript into the
next session.

## Quick start

### Give this to your AI agent

Paste this into a local AI coding agent with terminal access:

```text
Set up Mneme Memory MCP on my computer so I can start using it with my local AI
agents.

Repository: https://github.com/jollyzachary/mneme-memory-mcp

1. Check that Git, Python 3.10 or newer, and at least one MCP-compatible AI
   client are installed.
2. Clone the repository into a suitable local folder.
3. Read README.md and docs/continuity.md, then run the included installer for my
   operating system with the global profile. Use the repository's documented
   installer rather than creating a custom installation process.
4. Connect Mneme to each supported AI client already installed on my computer.
   Preserve unrelated client settings and any existing Mneme memory.
5. Run mneme-memory-doctor and mneme-memory-continuity status. Resolve any setup
   errors, report the memory home and connected clients, and tell me which
   applications to restart.
6. After the restart, help me save one harmless preference and recall it in a
   new session so we can confirm Mneme is working.

Keep Mneme's durable store local. Do not enable optional PostgreSQL retrieval
or agent delegation unless I request it.
```

### Install it yourself

macOS or Linux:

```bash
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
./scripts/install.sh --profile global
```

Windows PowerShell:

```powershell
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile global
```

The global profile creates a managed Python environment, initializes the default
memory home at `~/.hermes`, and configures supported clients that are already
installed. Restart those clients after installation so they reload their MCP
configuration. See [Client continuity](docs/continuity.md) for isolated project
memory and server-only profiles.

## Connect an MCP client

Codex configuration:

```toml
[mcp_servers.mneme_memory]
command = "/absolute/path/to/mneme-memory-mcp/.venv/bin/mneme-memory-mcp"
args = []
startup_timeout_sec = 120

[mcp_servers.mneme_memory.env]
MNEME_HOME = "/absolute/path/to/mneme-home"
```

Claude Code configuration:

```json
{
  "mcpServers": {
    "mneme-memory": {
      "type": "stdio",
      "command": "/absolute/path/to/mneme-memory-mcp/.venv/bin/mneme-memory-mcp",
      "args": [],
      "env": {
        "MNEME_HOME": "/absolute/path/to/mneme-home"
      }
    }
  }
}
```

Additional macOS, Linux, and Windows examples are in [`examples/`](examples/).

## MCP interface

The server provides tools for four core workflows:

| Workflow | Representative tools |
| --- | --- |
| Recall | `memory_summary`, `memory_search`, `memory_briefing`, `memory_current` |
| Write and govern | `memory_add`, `memory_update`, `memory_review_decide`, `memory_feedback` |
| Relate and transfer | `memory_link`, `memory_links`, `memory_handoff_write`, `memory_handoff_latest` |
| Operate | `memory_health`, `memory_maintain`, `memory_consolidate`, `memory_embeddings_backfill` |

Run `mneme-memory --help` for the CLI command surface.

## Storage layout

```text
~/.hermes/
├── backups/
│   └── mneme-auto-*.db
├── memory_store.db
└── memories/
    ├── USER.md
    └── MEMORY.md
```

The SQLite journal is the source of truth. `USER.md` and `MEMORY.md` are
generated views containing compact, trusted context. Raw episodic capture stays
separate from the main fact table.

## Optional retrieval plane

Mneme can mirror retrieval data to a loopback-only PostgreSQL 17 service using
pgContext and pgGraph:

```bash
python -m pip install -e '.[embeddings,postgres]'
bash infra/postgres/scripts/mneme-postgres.sh prepare
bash infra/postgres/scripts/mneme-postgres.sh start
python scripts/migrate_sqlite_to_postgres.py
```

The migration command is a dry run until `--apply` is supplied. Start in `dual`
mode, compare recall and mirror counts, and move to `postgres` only after the
derived index is healthy. See [PostgreSQL retrieval](docs/postgres-retrieval.md)
for the full design and rollback procedure.

SQLite remains authoritative throughout. Mneme repairs failed mirror writes in
the background with adaptive backoff, bounds pgGraph expansion behind a short
fail-soft timeout and circuit breaker, and falls back to SQLite recall when the
derived PostgreSQL service is unavailable. One elected local worker performs
repair and creates a verified SQLite snapshot daily, retaining the latest 30
automatic backups.

## Security boundary

Mneme's default server uses local stdio transport and assumes one user with
trusted local clients. Scope labels control recall context; they are not
multi-user authentication or tenant isolation.

The optional conversation-capture and subprocess-delegation features expand the
data and execution boundary. They are disabled unless configured. Use separate
memory homes when clients should not share authority, and review
[SECURITY.md](SECURITY.md) before enabling optional integrations.

Mneme does not transmit stored memory by itself. Data can leave the machine when
a connected client sends retrieved context to its configured model provider.

## Documentation

- [System architecture](docs/architecture.md)
- [Client continuity](docs/continuity.md)
- [Shared memory and optional delegation](docs/shared-memory.md)
- [PostgreSQL retrieval](docs/postgres-retrieval.md)

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m build
```

Contribution and disclosure guidance is available in
[CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

Mneme Memory MCP is released under the [MIT License](LICENSE). Third-party
components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
