# Hermes Pairing

Mneme uses a Hermes-compatible default memory home, but Hermes Agent is not
required to run the MCP server.

```text
Claude Code ─┐
Codex ───────┼── mneme-memory-mcp ── ~/.hermes
Hermes ──────┘                         memories/ + memory_store.db
```

## Install Mneme

```bash
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
./scripts/install.sh --profile global --profile-confirmed
```

Windows:

```powershell
git clone https://github.com/jollyzachary/mneme-memory-mcp.git
cd mneme-memory-mcp
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile global -ProfileConfirmed
```

The global profile uses `~/.hermes` unless `MNEME_HOME` or `HERMES_HOME` is
set. If Hermes Agent is already installed, it can use the same directory.

## Install Hermes separately

Mneme never fetches or executes external agent-installation code. If you want
Hermes Agent, review its current upstream documentation, release artifacts, and
trust model, then install it separately. Mneme will detect an existing `hermes`
command but does not require one.

## Verify paths

```bash
~/.local/share/mneme-memory-mcp/venv/bin/mneme-memory-doctor
```

The doctor reports the resolved home, generated Markdown files, SQLite store,
and MCP server command.

## Component boundary

Hermes is an agent runtime. Mneme is a shared memory service. They can share a
home without becoming the same component, and Mneme remains usable while the
Hermes runtime is not running.
