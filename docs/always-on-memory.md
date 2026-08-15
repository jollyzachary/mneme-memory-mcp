# Always-On Memory

Mneme can run in global mode or project/env-scoped mode.

Global mode is meant to make every configured agent answer from the same remembered ground. Project/env mode is meant to keep memory isolated to a repo or environment file.

The installer gives Claude Code and Codex a persistent memory habit in six layers:

1. Shared local memory files in `~/.hermes/memories`
2. Shared typed facts, events, handoffs, and episodic archive in `~/.hermes/memory_store.db`
3. Mneme MCP tools in Claude and Codex
4. Global client instructions that tell new chats to consult Mneme before substantive answers
5. A Claude `UserPromptSubmit` hook that adds shared memory context before every future prompt
6. Local capture hooks that archive recent Claude/Codex transcript snippets and distill compact searchable summaries

Automated distilled memories enter the candidate state. They remain available
for explicit recall at a ranking penalty, but they do not enter the always-on
working set until promoted. Suspected prompt injection is quarantined, and
secret-like content is rejected before persistence.

For Claude Code, Mneme also adds a `SessionStart` hook that prints the Markdown memory summary into every fresh Claude session and a `UserPromptSubmit` hook that injects the current memory summary plus recent durable facts before future prompts.

## What Gets Installed

Running:

```bash
./scripts/install.sh --profile global --profile-confirmed
```

or on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile global -ProfileConfirmed
```

installs or updates managed Mneme blocks in:

```text
~/.codex/AGENTS.md
~/.claude/CLAUDE.md
```

On Windows these are `%USERPROFILE%\.codex\AGENTS.md` and `%USERPROFILE%\.claude\CLAUDE.md`.

The blocks tell each client to start from shared memory, prefer the Mneme MCP tools, and use the `mneme-memory` CLI fallback if MCP tools are unavailable.

Claude also gets:

```text
~/.claude/hooks/mneme-memory-sessionstart.sh
~/.claude/hooks/mneme-memory-userprompt.sh
~/.claude/hooks/mneme-memory-capture.sh
```

On Windows:

```text
%USERPROFILE%\.claude\hooks\mneme-memory-sessionstart.cmd
%USERPROFILE%\.claude\hooks\mneme-memory-userprompt.cmd
%USERPROFILE%\.claude\hooks\mneme-memory-capture.cmd
```

and `SessionStart` plus `UserPromptSubmit` hook entries in:

```text
~/.claude/settings.json
```

The capture hook is also installed into Claude Code `Stop` and `SessionEnd` hooks. Codex gets a small notify wrapper at:

```text
~/.codex/mneme-memory-notify.sh
```

On Windows this wrapper is `%USERPROFILE%\.codex\mneme-memory-notify.cmd`.

The wrapper archives recent Codex transcript snippets, distills compact searchable summaries, then forwards to the previously configured notify command when one existed. In `~/.codex/config.toml`, Mneme should be the first and only configured `notify` command; the previous notify chain is stored inside the wrapper:

```toml
notify = ["/Users/you/.codex/mneme-memory-notify.sh"]
```

If an existing compatible Hermes/Mneme memory hook is already present, Mneme keeps it and avoids adding a duplicate.

Automatic captures go into SQLite's separate `episodic_entries` archive with `capture`, client, role, and session tags. SQLite-backed byte-offset checkpoints ensure repeated hooks parse only complete records appended since the prior run. Raw turns are capped and age-pruned, and they are not appended to `USER.md`, `MEMORY.md`, or the main fact table. Mneme consolidates each session into one compact summary plus a few high-value distilled facts that are searchable through `memory_search` and `mneme-memory search`. Hooks skip per-write embedding work to stay responsive; `mneme-memory embeddings backfill` fills missing vectors in batches.

When an older 0.6.x database is opened, legacy raw `category='conversation'` facts are migrated into `episodic_entries`, removed from `facts`, and the FTS index is rebuilt. Real semantic/project/tool facts stay in `facts`.

`USER.md` and `MEMORY.md` are generated working-set views. Regenerate them at any time:

```bash
mneme-memory consolidate
```

For mutable facts, write a stable key and resolve the current value deterministically:

```bash
mneme-memory add --key test-command --version 2026-06-25 "The test command is python -m unittest discover -s tests"
mneme-memory current test-command
```

Reads are scope-gated:

```bash
mneme-memory search "test command" --scope project
mneme-memory search "handoff" --scope handoff
```

Project scope sees global + project facts. Agent-private and handoff facts require their matching scope.

For cross-agent continuation, write and read structured handoffs:

```bash
mneme-memory handoff write --scope project --goal "Finish the memory overhaul" --next-steps "run checks and commit locally"
mneme-memory handoff latest --scope project
```

## Project/Env-Scoped Memory

Use this when you want Mneme available to Claude and Codex, but you do not want global memory instructions or a machine-wide startup hook:

```bash
./scripts/install.sh --profile project --profile-confirmed
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile project -ProfileConfirmed
```

This profile reads memory settings from:

```text
.env
```

If the file does not contain `MNEME_HOME` or `HERMES_HOME`, the installer adds a project-local default:

```env
MNEME_HOME=/Users/YOU/.local/share/mneme-memory-mcp/projects/mneme-memory-mcp
```

Claude and Codex are configured to run:

```bash
mneme-memory-env-mcp --env-file /path/to/.env --default-home /Users/YOU/.local/share/mneme-memory-mcp/projects/mneme-memory-mcp
```

That launcher loads the `.env` memory settings when the MCP server starts. It does not write to `~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`, or Claude `SessionStart` hooks.

Project/env-scoped mode intentionally does not install global capture hooks. Use it when a repo should have shared memory only while clients are configured to that repo's `.env`.

## The Memory-First Rule

Fresh Claude and Codex chats should follow this order:

1. Read `memory_summary` for USER.md and MEMORY.md context.
2. Use `memory_search` when prior work, preferences, repo state, tools, people, or decisions may matter.
3. Add durable facts with `memory_add` when the user would reasonably expect future agents to remember them.
4. Use `memory_feedback` when a recalled fact materially helped or misled the task.
5. Review automated candidates with `memory_review_list` and `memory_review_decide`.
6. Fall back to the local CLI when MCP tools are not available:

```bash
mneme-memory summary
mneme-memory search "query terms"
mneme-memory add --target memory "durable fact"
mneme-memory consolidate
mneme-memory-capture all
```

## Doctor Check

Check the continuity layer with:

```bash
~/.local/share/mneme-memory-mcp/venv/bin/mneme-memory-doctor
```

Windows:

```powershell
& "$env:LOCALAPPDATA\mneme-memory-mcp\venv\Scripts\python.exe" -m mneme_memory_mcp.doctor
```

or directly:

```bash
~/.local/share/mneme-memory-mcp/venv/bin/mneme-memory-continuity status
```

Windows:

```powershell
& "$env:LOCALAPPDATA\mneme-memory-mcp\venv\Scripts\python.exe" -m mneme_memory_mcp.continuity status
```

Expected healthy output includes:

```text
Codex always-on memory instructions: ok
Codex automatic memory capture: ok
Claude always-on memory instructions: ok
Claude SessionStart memory hook file: ok
Claude SessionStart memory hook configured: ok
Claude per-prompt memory hook file: ok
Claude UserPromptSubmit memory hook configured: ok
Claude automatic memory capture hook file: ok
Claude Stop memory capture configured: ok
Claude SessionEnd memory capture configured: ok
Claude user-scope MCP config: ok
```

## Practical Guarantee

Mneme can make the memory layer the default for configured Claude Code and Codex clients by installing global instructions, MCP servers, a CLI fallback, startup/per-prompt memory injection, and local capture hooks.

No package can force an unconfigured client, a client that ignores its global instructions, or a disconnected remote chat to read local files. But once the installer has run successfully on a machine, new local Claude Code and Codex chats have the shared memory layer wired in by default.

## Opt Out

Skip the continuity layer while keeping MCP client setup:

```bash
./scripts/install.sh --profile global --profile-confirmed --no-continuity
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile global -ProfileConfirmed -NoContinuity
```

Install only the memory server without client or plugin changes:

```bash
./scripts/install.sh --profile global --profile-confirmed --memory-only
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile global -ProfileConfirmed -MemoryOnly
```

Install with project/env-scoped memory instead of global memory:

```bash
./scripts/install.sh --profile project --profile-confirmed
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile project -ProfileConfirmed
```
