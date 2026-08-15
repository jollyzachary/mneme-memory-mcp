# Shared memory and optional delegation

Mneme gives trusted MCP-compatible agents direct access to one governed local
store.

```text
Agent 1 ─┐
Agent 2 ─┼── mneme-memory-mcp ── local memory home
Agent 3 ─┘
```

The agents may use different clients or models, or they may be separate
instances of the same client. Mneme gives each one direct access to the same
governed memory layer.

## Shared memory

Connected clients use the same MCP server command and `MNEME_HOME`. The default
shared home contains:

```text
~/.hermes/memory_store.db
~/.hermes/memories/USER.md
~/.hermes/memories/MEMORY.md
```

The SQLite database is authoritative. Markdown files are generated working
sets for compact continuity.

## Optional local delegation

Mneme includes an optional bridge for bounded, one-shot local agent tasks. It is
absent from the default MCP surface because subprocess execution has a larger
trust boundary than memory access.

Enable it only for a trusted workspace:

```bash
export MNEME_ENABLE_AGENT_BRIDGE=1
export MNEME_BRIDGE_ROOT=/absolute/path/to/a/trusted/workspace
mneme-memory-mcp
```

When enabled, the server registers:

| Tool | Purpose |
| --- | --- |
| `agent_bridge_status` | Report local Claude, Codex, and Node availability |
| `delegate_to_claude` | Run a bounded Claude Code task inside the bridge root |
| `delegate_to_codex` | Run a bounded Codex task inside the bridge root |

Working directories must remain inside `MNEME_BRIDGE_ROOT`. Codex delegation is
limited to the bridge's supported sandbox modes. Child processes receive an
allowlisted environment, diagnostic command arguments are redacted, and
returned output is bounded.

## Safety boundary

The default stdio server assumes one user and trusted local clients. Scope
labels organize recall; they are not multi-user authentication. Use separate
memory homes and server registrations when clients should not share authority.
