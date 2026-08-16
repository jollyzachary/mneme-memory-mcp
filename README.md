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

## Give this to your AI agent

Paste the prompt below into a local coding agent with terminal access. It tells
the agent to use Mneme's installer, preserve existing data, and verify the
connection when setup is complete.

```text
Install and configure Mneme Memory MCP from
https://github.com/jollyzachary/mneme-memory-mcp on this computer.

1. Read README.md, docs/continuity.md, and the installer help for this operating
   system before changing anything.
2. Inspect any existing Mneme installation, MNEME_HOME value, and MCP client
   configuration. Preserve existing memory and unrelated configuration. Do not
   print memory contents, credentials, or secrets.
3. Use the global profile unless I request isolated project memory or a
   server-only installation. If an existing setup makes that choice unsafe,
   stop and explain the conflict.
4. Clone the repository and use its provided installer:
   - macOS or Linux: ./scripts/install.sh --profile global
   - Windows PowerShell: powershell -ExecutionPolicy Bypass -File
     .\scripts\install.ps1 -Profile global
   Change only the profile argument when a different profile is required. Do
   not replace the installer with a custom setup unless the installer fails.
5. Configure the supported MCP clients already installed on this computer. Do
   not install unrelated agent runtimes or enable PostgreSQL retrieval or agent
   delegation unless I ask.
6. Run the installed mneme-memory-doctor and mneme-memory-continuity status
   commands. Confirm the selected profile, memory home, server command, and each
   configured client. Tell me which applications must restart, then give me one
   harmless store-and-recall check I can use after the restart.

Stop before overwriting an existing installation, moving a memory home that
contains data, or replacing client configuration you cannot preserve.
```

## Quick start

```bash
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/mneme-memory-mcp
```

Windows PowerShell:

```powershell
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m mneme_memory_mcp
```

The default memory home is `~/.hermes`. Set `MNEME_HOME` in the MCP client's
process environment to choose another location.

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
