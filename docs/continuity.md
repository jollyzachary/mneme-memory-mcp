# Client continuity

Mneme can provide durable context whenever a configured client starts a new
session. The memory service remains independent of any one model or client.

## Continuity layers

```text
Client session
    │
    ├── MCP tools for explicit recall and writes
    ├── Generated working set for compact startup context
    ├── Optional prompt hook for relevance-gated recall
    └── Optional capture hook for bounded episodic history
             │
             └── candidates require review before promotion
```

The SQLite journal stores facts, lifecycle state, feedback, relationships,
handoffs, and episodic records. Generated Markdown files are compact views of
trusted memory, not a second database.

## Setup profiles

The guided installers require an explicit profile:

| Profile | Use case | Client configuration |
| --- | --- | --- |
| `global` | Shared memory for trusted clients on one workstation | Installs supported client wiring and continuity hooks |
| `project` | An isolated memory home for one workspace | Configures the workspace without global continuity hooks |
| `server` | Memory server only | Leaves client wiring to the operator |

macOS and Linux:

```bash
./scripts/install.sh --profile server
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile server
```

The installer requires a profile so changes to client configuration and
continuity hooks are explicit.

## Global continuity

The `global` profile can install managed instruction blocks, client MCP
configuration, and local hooks for supported clients. Managed blocks are
idempotent so subsequent installs update Mneme's section without replacing
unrelated user content.

The continuity layer can:

- expose `memory_summary`, `memory_search`, and the rest of the MCP interface;
- inject a bounded startup working set;
- perform relevance-gated recall before a prompt;
- archive bounded local transcript records;
- distill episodic records into reviewable candidates;
- write structured handoffs for later sessions.

Automatic capture never promotes a fact directly into trusted context.
Suspected prompt injection is quarantined, secret-like content is redacted or
rejected, and automated capture remains review-only. Unreviewed candidates stay
out of default search, list, and prompt context.

Install the global profile:

```bash
./scripts/install.sh --profile global
```

Install the memory server and client connection without continuity hooks:

```bash
./scripts/install.sh --profile global --no-continuity
```

Install only the memory service:

```bash
./scripts/install.sh --profile global --memory-only
```

Equivalent PowerShell switches are `-NoContinuity` and `-MemoryOnly`.

## Manual operation

The core service does not require automatic hooks. Any MCP-compatible client can
use Mneme through the server command and a selected `MNEME_HOME`.

Useful CLI commands:

```bash
mneme-memory summary
mneme-memory search "query terms"
mneme-memory add --target memory "durable fact"
mneme-memory handoff latest --scope project
mneme-memory consolidate
```

## Health check

```bash
mneme-memory-doctor
mneme-memory-continuity status
```

The doctor reports the resolved storage paths, database health, generated
working sets, retrieval backend, and installed client integrations.

## Boundary

Continuity depends on the connected client using its configured MCP server or
hooks. It cannot make an unconfigured client, remote chat, or disconnected
runtime read local memory. Treat prompt injection and conversation capture as
untrusted inputs, and use separate memory homes when clients should not share
authority.
