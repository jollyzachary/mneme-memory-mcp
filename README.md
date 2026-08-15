# Mneme Memory MCP

Local-first memory infrastructure for AI agents.

![Mneme Memory MCP](assets/mneme-hero.png)

[![CI](https://github.com/jollyzachary/mneme-memory-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/jollyzachary/mneme-memory-mcp/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-111111.svg)](LICENSE)

Mneme is pronounced NEE-mee. Its name comes from the Greek word μνήμη
(*mnḗmē*), meaning “memory” or “remembrance.”

Mneme gives trusted local AI clients a shared, durable memory layer through the
[Model Context Protocol](https://modelcontextprotocol.io/). It preserves useful
context across sessions without making a cloud service the source of truth.

The system combines a governed SQLite journal, compact Markdown working sets,
hybrid retrieval, structured handoffs, optional conversation capture, and an
optional PostgreSQL retrieval plane built with pgContext and pgGraph.

> **Project status:** active, early-stage software. The storage model and public
> tool surface are usable today, but installation and extension interfaces may
> evolve before a stable 1.0 release.

## Why Mneme

Agent context is usually trapped inside one chat, one client, or one vendor.
Mneme separates durable memory from the agent using it:

- one local source of truth for facts, preferences, decisions, and handoffs;
- durable recall for one agent, or shared recall across multiple trusted
  MCP-compatible agents;
- explicit trust states for manual, automated, quarantined, and rejected memory;
- human-readable generated views without treating Markdown as the database;
- lexical, semantic, and relationship-aware retrieval with a local fallback;
- no required hosted database, telemetry service, or cloud synchronization.

## Architecture

```text
Agent 1 ─┐
Agent 2 ─┼── MCP / CLI / local hooks ── Mneme
Agent 3 ─┘                              │
                                         ├── SQLite journal (authoritative)
                                         ├── USER.md / MEMORY.md (generated)
                                         └── PostgreSQL retrieval plane (optional)
                                              ├── pgContext vectors
                                              └── pgGraph relationships
```

A single agent can use Mneme for continuity across sessions. Multiple agents
can use different clients or models, or separate instances of the same client.
Each connects to Mneme directly; no agent has to coordinate the others.

SQLite remains authoritative for facts, lifecycle state, review decisions,
supersession, audit events, handoffs, and episodic archives. PostgreSQL is a
rebuildable retrieval layer; Mneme can fall back to SQLite if that derived
service is unavailable.

## Core capabilities

- **Durable memory:** semantic, procedural, resource, episodic, and handoff
  records with provenance, importance, trust, and lifecycle state.
- **Governed writes:** automated content enters as a candidate; suspected prompt
  injection is quarantined; secret-like fact content is rejected.
- **Hybrid recall:** SQLite FTS5 and exact matching, optional local MiniLM
  embeddings, Reciprocal Rank Fusion, and bounded quality priors.
- **Structured relationships:** typed same-scope links between facts, with
  inspectable evidence and reversible unlinking.
- **Versioned facts:** stable keys and versions preserve supersession history
  while resolving the current value deterministically.
- **Compact context:** generated `USER.md` and `MEMORY.md` views contain trusted
  global/project material only; private and handoff-only scopes stay out.
- **Cross-agent handoffs:** structured goals, state, decisions, blockers,
  evidence, and next steps let one agent or session hand work to another
  without passing the full chat history.
- **Optional capture:** local Claude and Codex transcripts can be archived as
  bounded episodic data and distilled into reviewable candidates.
- **Portable access:** MCP tools and local CLI commands use the same store.

## Security and trust model

Mneme is designed for a **single user operating trusted local clients**. The
default server uses local stdio transport; it does not expose an HTTP listener.
Scope labels organize retrieval context, but they are not a replacement for
multi-user authentication or tenant isolation.

Important defaults:

- agent delegation tools are **disabled** unless explicitly enabled;
- project `.env` loading accepts documented Mneme settings only;
- generated memory files and local stores are hardened to owner-only POSIX
  permissions when the filesystem supports them;
- real `.env` files, SQLite databases, PostgreSQL secrets, logs, caches, and
  generated memory are excluded from Git;
- installers require an explicit `global`, `project`, or `server` profile;
- external agent runtimes are never installed by Mneme; optional client plugins
  require an explicit user flag.

Only connect MCP clients you trust with the selected memory home. See
[SECURITY.md](SECURITY.md) for reporting and deployment guidance.

## Quick start

Clone the repository and create an isolated environment:

```bash
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Windows PowerShell:

```powershell
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Start the MCP server:

```bash
.venv/bin/mneme-memory-mcp
```

The default memory home is `~/.hermes`. Set `MNEME_HOME` to use a different
location.

### Configure Codex

```toml
[mcp_servers.mneme_memory]
command = "/absolute/path/to/mneme-memory-mcp/.venv/bin/mneme-memory-mcp"
args = []
startup_timeout_sec = 120

[mcp_servers.mneme_memory.env]
MNEME_HOME = "/absolute/path/to/your/mneme-home"
```

### Configure Claude Code

```json
{
  "mcpServers": {
    "mneme-memory": {
      "type": "stdio",
      "command": "/absolute/path/to/mneme-memory-mcp/.venv/bin/mneme-memory-mcp",
      "args": [],
      "env": {
        "MNEME_HOME": "/absolute/path/to/your/mneme-home"
      }
    }
  }
}
```

Windows examples are available in [`examples/`](examples/).

## Guided installer

The installer supports three explicit profiles:

| Profile | Intended use | Global client instructions |
| --- | --- | --- |
| `global` | One trusted personal machine sharing `~/.hermes` | Yes |
| `project` | An isolated repository or workspace memory home | No |
| `server` | Server installation with manual client wiring | No |

After choosing a profile:

```bash
./scripts/install.sh --profile server --profile-confirmed
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile server -ProfileConfirmed
```

The installer refuses non-interactive setup until a profile has been selected
and confirmed. Optional external client plugins require a separate flag:

```bash
./scripts/install.sh --profile global --profile-confirmed --agent-plugins
```

For memory-only setup without client, plugin, or continuity changes:

```bash
./scripts/install.sh --profile global --profile-confirmed --memory-only
```

## MCP tools

The default server exposes tools for:

- summary, briefing, search, list, and current-value resolution;
- add, update, remove, feedback, and lifecycle review;
- typed relationship creation, inspection, and removal;
- structured handoff write/read;
- health, maintenance, consolidation, and embedding backfill.

Representative tools include `memory_summary`, `memory_search`, `memory_add`,
`memory_current`, `memory_link`, `memory_review_decide`,
`memory_handoff_write`, and `memory_health`.

## Local CLI

The package installs:

- `mneme-memory` — read, search, add, review, link, consolidate, and manage
  handoffs;
- `mneme-memory-mcp` — run the MCP server;
- `mneme-memory-capture` — archive configured local conversations;
- `mneme-memory-continuity` — install or inspect local continuity hooks;
- `mneme-memory-env-mcp` — start the server from an allowlisted project config;
- `mneme-memory-doctor` — inspect storage and retrieval health.

Run `mneme-memory --help` for the full command surface.

## Storage model

Default global layout:

```text
~/.hermes/
├── memory_store.db
└── memories/
    ├── USER.md
    └── MEMORY.md
```

The Markdown files are generated working sets, not the database. Raw episodic
capture remains bounded and separate from the main fact table. Automatic
capture creates candidate memory; it does not silently promote content to the
trusted working set.

## Optional PostgreSQL retrieval plane

Install the client dependency:

```bash
python -m pip install -e '.[embeddings,postgres]'
```

Prepare the local secret files and start the loopback-only service:

```bash
bash infra/postgres/scripts/mneme-postgres.sh prepare
bash infra/postgres/scripts/mneme-postgres.sh start
```

Stage a dry-run migration before applying it:

```bash
python scripts/migrate_sqlite_to_postgres.py
python scripts/migrate_sqlite_to_postgres.py --apply --skip-graph-rebuild
```

Start with `MNEME_RETRIEVAL_BACKEND=dual`. Move to `postgres` only after
checking mirror counts and recall quality. Full setup, rollback, and relationship
details are in [docs/postgres-retrieval.md](docs/postgres-retrieval.md).

## Optional agent bridge

The memory server does not register local agent-execution tools by default. To
enable the bridge, set both an explicit capability flag and a contained working
root:

```bash
export MNEME_ENABLE_AGENT_BRIDGE=1
export MNEME_BRIDGE_ROOT=/absolute/path/to/a/trusted/workspace
mneme-memory-mcp
```

Delegated working directories must remain inside `MNEME_BRIDGE_ROOT`. The
public MCP surface does not expose Claude's permission bypass or Codex's
`danger-full-access` mode, child environments omit credentials, diagnostic
commands are redacted, and returned output is bounded.

## Configuration

Start with [`.env.example`](.env.example). Project config accepts only documented
Mneme keys; unrelated process variables are ignored.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MNEME_HOME` | unset | Primary memory-home override |
| `HERMES_HOME` | `~/.hermes` | Hermes-compatible fallback home |
| `MNEME_MEMORY_DIR` | `<home>/memories` | Generated Markdown directory |
| `MNEME_DB_PATH` | `<home>/memory_store.db` | SQLite authority path |
| `MNEME_RETRIEVAL_BACKEND` | `sqlite` | `sqlite`, `dual`, or `postgres` |
| `MNEME_POSTGRES_HOST` | `127.0.0.1` | PostgreSQL retrieval host |
| `MNEME_POSTGRES_PORT` | `55433` | PostgreSQL retrieval port |
| `MNEME_POSTGRES_PASSWORD_FILE` | local secret file | App-role password path |
| `MNEME_POSTGRES_REQUIRED` | `0` | Fail instead of using SQLite fallback |
| `MNEME_ENABLE_AGENT_BRIDGE` | `0` | Register local delegation tools |
| `MNEME_BRIDGE_ROOT` | unset | Allowed delegation workspace root |

## Documentation

- [Global memory architecture](docs/global-memory-architecture.md)
- [Always-on memory](docs/always-on-memory.md)
- [PostgreSQL retrieval plane](docs/postgres-retrieval.md)
- [Agent mesh](docs/agent-mesh.md)
- [Hermes pairing](docs/hermes.md)

## Development

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m build
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Never use
real memory, credentials, transcripts, local usernames, or private filesystem
paths as fixtures.

## Privacy

Mneme does not transmit memory by itself. Data leaves the machine only when a
connected agent or optional delegated CLI sends context to its configured model
provider. Conversation capture and the agent bridge are optional; enable them
only when their data flow matches your threat model.

## License

Mneme Memory MCP is released under the [MIT License](LICENSE). Optional runtime
dependencies and container components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
