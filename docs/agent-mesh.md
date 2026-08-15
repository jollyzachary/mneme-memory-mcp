# Agent Mesh

![Mneme agent bridge](../assets/docs/agent-bridge.png)

Mneme's primary job is shared memory. Trusted MCP-compatible agents can read
and write the same local store without routing through one another.

```text
Agent 1 ─┐
Agent 2 ─┼── mneme-memory-mcp ── local memory home
Agent 3 ─┘
```

The agents may use different clients or models, or they may be separate
instances of the same client. Mneme gives each one direct access to the same
governed memory layer.

## Shared memory

All connected clients use the same MCP server command and `MNEME_HOME` or
`HERMES_HOME`. The default global home contains:

```text
~/.hermes/memory_store.db
~/.hermes/memories/USER.md
~/.hermes/memories/MEMORY.md
```

The SQLite database is authoritative. Markdown files are generated working
sets for compact continuity.

## Optional local delegation

Mneme includes an optional bridge for one-shot Claude Code and Codex tasks. It
is deliberately absent from the default MCP tool surface because a local
subprocess executor has a larger trust boundary than a memory service.

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

Working directories must remain inside `MNEME_BRIDGE_ROOT`. Codex is limited to
`read-only` or `workspace-write`; the MCP tool does not expose
`danger-full-access`. Claude uses its default permission mode. Child processes
receive a minimal environment, diagnostic command arguments are redacted, and
returned output is bounded.

## External integrations

OpenAI's Claude-to-Codex plugin and Ponytail are optional upstream projects.
Mneme does not vendor them. The guided installer will attempt to add them only
when the user supplies the explicit agent-plugin flag.

## Safety boundary

The default stdio server assumes one user and trusted local clients. Scope
labels organize recall; they are not multi-user authentication. Use separate
memory homes and server registrations when clients should not share authority.
