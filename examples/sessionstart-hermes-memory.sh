#!/usr/bin/env bash
# Optional Claude Code SessionStart hook.
# It injects Markdown memory into the start of each Claude session.

set -euo pipefail

MEM_DIR="${HERMES_HOME:-$HOME/.hermes}/memories"
[ -d "$MEM_DIR" ] || exit 0

out=""
for f in MEMORY.md USER.md; do
  [ -s "$MEM_DIR/$f" ] || continue
  out="${out}"$'\n'"### ${f}"$'\n'"$(cat "$MEM_DIR/$f" 2>/dev/null)"$'\n'
done

[ -n "$out" ] || exit 0

printf '## Shared persistent memory\n'
printf '_Source: %s. For deeper recall, use the mneme-memory MCP tools._\n' "$MEM_DIR"
printf '%s\n' "$out"

