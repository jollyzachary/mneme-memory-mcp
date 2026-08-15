from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import resolve_home, resolve_memory_dir

MANAGED_START = "<!-- mneme-memory-start -->"
MANAGED_END = "<!-- mneme-memory-end -->"
MNEME_HOOK_NAME = (
    "mneme-memory-sessionstart.cmd"
    if os.name == "nt"
    else "mneme-memory-sessionstart.sh"
)
MNEME_PROMPT_HOOK_NAME = (
    "mneme-memory-userprompt.cmd" if os.name == "nt" else "mneme-memory-userprompt.sh"
)
MNEME_CAPTURE_HOOK_NAME = (
    "mneme-memory-capture.cmd" if os.name == "nt" else "mneme-memory-capture.sh"
)
MNEME_CODEX_NOTIFY_NAME = (
    "mneme-memory-notify.cmd" if os.name == "nt" else "mneme-memory-notify.sh"
)
COMPATIBLE_HOOK_NAMES = (
    MNEME_HOOK_NAME,
    "mneme-memory-sessionstart.sh",
    "mneme-memory-sessionstart.cmd",
    "hermes-memory.sh",
    "sessionstart-hermes-memory.sh",
)


@dataclass(frozen=True)
class ContinuityPaths:
    memory_home: Path
    bin_dir: Path
    codex_agents: Path
    codex_config: Path
    codex_notify_wrapper: Path
    claude_md: Path
    claude_settings: Path
    claude_user_config: Path
    claude_hook: Path
    claude_prompt_hook: Path
    claude_capture_hook: Path


@dataclass(frozen=True)
class ContinuityStatus:
    codex_instructions: bool
    codex_notify_capture: bool
    claude_instructions: bool
    claude_hook_file: bool
    claude_sessionstart_hook: bool
    claude_prompt_hook_file: bool
    claude_userprompt_hook: bool
    claude_capture_hook_file: bool
    claude_stop_capture_hook: bool
    claude_sessionend_capture_hook: bool
    claude_mcp_config: bool
    codex_agents: Path
    codex_config: Path
    codex_notify_wrapper: Path
    claude_md: Path
    claude_settings: Path
    claude_user_config: Path
    claude_hook: Path
    claude_prompt_hook: Path
    claude_capture_hook: Path

    def lines(self) -> list[str]:
        return [
            f"Codex always-on memory instructions: {_ok(self.codex_instructions)} ({self.codex_agents})",
            f"Codex automatic memory capture: {_ok(self.codex_notify_capture)} ({self.codex_config})",
            f"Claude always-on memory instructions: {_ok(self.claude_instructions)} ({self.claude_md})",
            f"Claude SessionStart memory hook file: {_ok(self.claude_hook_file)} ({self.claude_hook})",
            f"Claude SessionStart memory hook configured: {_ok(self.claude_sessionstart_hook)} ({self.claude_settings})",
            f"Claude per-prompt memory hook file: {_ok(self.claude_prompt_hook_file)} ({self.claude_prompt_hook})",
            f"Claude UserPromptSubmit memory hook configured: {_ok(self.claude_userprompt_hook)} ({self.claude_settings})",
            f"Claude automatic memory capture hook file: {_ok(self.claude_capture_hook_file)} ({self.claude_capture_hook})",
            f"Claude Stop memory capture configured: {_ok(self.claude_stop_capture_hook)} ({self.claude_settings})",
            f"Claude SessionEnd memory capture configured: {_ok(self.claude_sessionend_capture_hook)} ({self.claude_settings})",
            f"Claude user-scope MCP config: {_ok(self.claude_mcp_config)} ({self.claude_user_config})",
        ]


def default_paths(
    memory_home: Path | None = None,
    bin_dir: Path | None = None,
) -> ContinuityPaths:
    home = Path.home()
    resolved_memory_home = memory_home or resolve_home()
    # Preserve the virtualenv entrypoint path. Resolving the interpreter symlink
    # can jump to a shared base Python and make healthy MCP wiring look missing.
    resolved_bin_dir = bin_dir or Path(sys.executable).parent
    return ContinuityPaths(
        memory_home=resolved_memory_home.expanduser(),
        bin_dir=resolved_bin_dir.expanduser(),
        codex_agents=home / ".codex" / "AGENTS.md",
        codex_config=home / ".codex" / "config.toml",
        codex_notify_wrapper=home / ".codex" / MNEME_CODEX_NOTIFY_NAME,
        claude_md=home / ".claude" / "CLAUDE.md",
        claude_settings=home / ".claude" / "settings.json",
        claude_user_config=home / ".claude.json",
        claude_hook=home / ".claude" / "hooks" / MNEME_HOOK_NAME,
        claude_prompt_hook=home / ".claude" / "hooks" / MNEME_PROMPT_HOOK_NAME,
        claude_capture_hook=home / ".claude" / "hooks" / MNEME_CAPTURE_HOOK_NAME,
    )


def install_continuity(paths: ContinuityPaths | None = None) -> ContinuityStatus:
    paths = paths or default_paths()
    _validate_generated_paths(paths)
    memory_dir = resolve_memory_dir(paths.memory_home)
    memory_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        paths.memory_home.chmod(0o700)
        memory_dir.chmod(0o700)
    _ensure_memory_file(memory_dir / "USER.md", "USER.md")
    _ensure_memory_file(memory_dir / "MEMORY.md", "MEMORY.md")

    upsert_managed_block(paths.codex_agents, codex_block(paths))
    upsert_managed_block(paths.claude_md, claude_block(paths))
    install_claude_hook(paths)
    install_claude_prompt_hook(paths)
    install_claude_capture_hook(paths)
    merge_claude_settings(
        paths.claude_settings,
        paths.claude_hook,
        paths.claude_capture_hook,
        paths.claude_prompt_hook,
    )
    install_claude_mcp_config(paths)
    install_codex_notify_wrapper(paths)
    return continuity_status(paths)


def continuity_status(paths: ContinuityPaths | None = None) -> ContinuityStatus:
    paths = paths or default_paths()
    return ContinuityStatus(
        codex_instructions=_path_contains(paths.codex_agents, MANAGED_START),
        codex_notify_capture=_codex_notify_capture_configured(paths),
        claude_instructions=_path_contains(paths.claude_md, MANAGED_START),
        claude_hook_file=_is_runnable(paths.claude_hook),
        claude_sessionstart_hook=_has_compatible_sessionstart_hook(
            paths.claude_settings
        ),
        claude_prompt_hook_file=_is_runnable(paths.claude_prompt_hook),
        claude_userprompt_hook=_has_hook_command(
            paths.claude_settings,
            "UserPromptSubmit",
            paths.claude_prompt_hook.name,
        ),
        claude_capture_hook_file=_is_runnable(paths.claude_capture_hook),
        claude_stop_capture_hook=_has_hook_command(
            paths.claude_settings,
            "Stop",
            paths.claude_capture_hook.name,
        ),
        claude_sessionend_capture_hook=_has_hook_command(
            paths.claude_settings,
            "SessionEnd",
            paths.claude_capture_hook.name,
        ),
        claude_mcp_config=_claude_mcp_configured(paths),
        codex_agents=paths.codex_agents,
        codex_config=paths.codex_config,
        codex_notify_wrapper=paths.codex_notify_wrapper,
        claude_md=paths.claude_md,
        claude_settings=paths.claude_settings,
        claude_user_config=paths.claude_user_config,
        claude_hook=paths.claude_hook,
        claude_prompt_hook=paths.claude_prompt_hook,
        claude_capture_hook=paths.claude_capture_hook,
    )


def codex_block(paths: ContinuityPaths) -> str:
    cli = _module_command(paths.bin_dir, "mneme_memory_mcp.cli")
    return f"""## Mneme Shared Memory
Treat Mneme as the continuity layer for every Codex chat in this environment.

Before a substantive answer, consult the shared memory layer so new chats inherit the same user preferences, project state, tool setup, and prior decisions. Prefer Mneme MCP tools when available:

- `memory_summary` for the current USER.md and MEMORY.md context.
- `memory_search` when the request may involve prior work, preferences, repo state, tools, people, or long-running projects.
- `memory_add` for durable facts the user would reasonably expect future Codex, Claude, and Hermes sessions to remember.

If MCP tools are unavailable, use the CLI fallback:

```bash
{cli} summary
{cli} search "query terms"
{cli} add --target memory "durable fact"
```

Memory home: `{paths.memory_home}`
Markdown memories: `{resolve_memory_dir(paths.memory_home)}`
"""


def claude_block(paths: ContinuityPaths) -> str:
    cli = _module_command(paths.bin_dir, "mneme_memory_mcp.cli")
    return f"""## Mneme Shared Memory
Treat Mneme as the continuity layer for every Claude Code session in this environment.

At the start of a new session, and before any substantive answer, consult the shared memory layer so new chats inherit the same user preferences, project state, tool setup, and prior decisions. Prefer the `mneme-memory` MCP server tools when available:

- `memory_summary` for the current USER.md and MEMORY.md context.
- `memory_search` when the request may involve prior work, preferences, repo state, tools, people, or long-running projects.
- `memory_add` for durable facts the user would reasonably expect future Claude, Codex, and Hermes sessions to remember.

If MCP tools are unavailable, use the CLI fallback:

```bash
{cli} summary
{cli} search "query terms"
{cli} add --target memory "durable fact"
```

Memory home: `{paths.memory_home}`
Markdown memories: `{resolve_memory_dir(paths.memory_home)}`
"""


def upsert_managed_block(path: Path, block: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    managed = f"{MANAGED_START}\n{block.rstrip()}\n{MANAGED_END}\n"
    pattern = re.compile(
        rf"{re.escape(MANAGED_START)}.*?{re.escape(MANAGED_END)}\n?",
        re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(lambda _match: managed, existing)
    else:
        prefix = existing.rstrip()
        updated = f"{prefix}\n\n{managed}" if prefix else managed

    if updated != existing:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def install_claude_hook(paths: ContinuityPaths) -> None:
    paths.claude_hook.parent.mkdir(parents=True, exist_ok=True)
    paths.claude_hook.write_text(claude_hook_script(paths), encoding="utf-8")
    _make_runnable(paths.claude_hook)


def install_claude_prompt_hook(paths: ContinuityPaths) -> None:
    paths.claude_prompt_hook.parent.mkdir(parents=True, exist_ok=True)
    paths.claude_prompt_hook.write_text(
        claude_prompt_hook_script(paths), encoding="utf-8"
    )
    _make_runnable(paths.claude_prompt_hook)


def install_claude_capture_hook(paths: ContinuityPaths) -> None:
    paths.claude_capture_hook.parent.mkdir(parents=True, exist_ok=True)
    paths.claude_capture_hook.write_text(
        claude_capture_hook_script(paths), encoding="utf-8"
    )
    _make_runnable(paths.claude_capture_hook)


def install_claude_mcp_config(paths: ContinuityPaths) -> bool:
    data = _read_json_object(paths.claude_user_config)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["mcpServers"] = servers

    server = {
        "type": "stdio",
        "command": str(_python_executable(paths.bin_dir)),
        "args": ["-m", "mneme_memory_mcp"],
        "env": {
            "HERMES_HOME": str(paths.memory_home),
            "MNEME_HOME": str(paths.memory_home),
        },
    }
    servers["mneme-memory"] = server

    serialized = json.dumps(data, indent=2, sort_keys=False) + "\n"
    existing = (
        paths.claude_user_config.read_text(encoding="utf-8")
        if paths.claude_user_config.exists()
        else ""
    )
    if serialized != existing:
        paths.claude_user_config.parent.mkdir(parents=True, exist_ok=True)
        paths.claude_user_config.write_text(serialized, encoding="utf-8")
        return True
    return False


def install_codex_notify_wrapper(paths: ContinuityPaths) -> None:
    if not paths.codex_config.exists():
        values: list[str] = []
        config_text = ""
    else:
        config_text = paths.codex_config.read_text(encoding="utf-8")
        values = _read_notify_values(config_text)
        if values and values[0] == str(paths.codex_notify_wrapper):
            if paths.codex_notify_wrapper.exists():
                return
            values = []

    paths.codex_notify_wrapper.parent.mkdir(parents=True, exist_ok=True)
    paths.codex_notify_wrapper.write_text(
        codex_notify_wrapper_script(paths, values),
        encoding="utf-8",
    )
    _make_runnable(paths.codex_notify_wrapper)

    updated_values = [str(paths.codex_notify_wrapper)]
    updated = _write_notify_values(config_text, updated_values)
    if updated != config_text:
        paths.codex_config.write_text(updated, encoding="utf-8")


def claude_hook_script(paths: ContinuityPaths) -> str:
    if os.name == "nt":
        return claude_hook_cmd_script(paths)
    default_home = shlex.quote(str(paths.memory_home))
    return f"""#!/usr/bin/env bash
set -euo pipefail

DEFAULT_MEMORY_HOME={default_home}
MEMORY_HOME="${{MNEME_HOME:-${{HERMES_HOME:-$DEFAULT_MEMORY_HOME}}}}"
MEMORY_DIR="${{MNEME_MEMORY_DIR:-$MEMORY_HOME/memories}}"
USER_FILE="$MEMORY_DIR/USER.md"
MEMORY_FILE="$MEMORY_DIR/MEMORY.md"

echo "## Mneme shared persistent memory"
echo
echo "Claude Code should use this shared memory before substantive answers. Search or write durable facts through the mneme-memory MCP server when available."
echo

if [ -f "$USER_FILE" ]; then
  echo "### USER.md"
  cat "$USER_FILE"
  echo
fi

if [ -f "$MEMORY_FILE" ]; then
  echo "### MEMORY.md"
  cat "$MEMORY_FILE"
  echo
fi
"""


def claude_capture_hook_script(paths: ContinuityPaths) -> str:
    if os.name == "nt":
        return claude_capture_hook_cmd_script(paths)
    capture_cli = _console_script(paths.bin_dir, "mneme-memory-capture")
    default_home = shlex.quote(str(paths.memory_home))
    return f"""#!/usr/bin/env bash
set +e

DEFAULT_MEMORY_HOME={default_home}
MEMORY_HOME="${{MNEME_HOME:-${{HERMES_HOME:-$DEFAULT_MEMORY_HOME}}}}"
export MNEME_HOME="$MEMORY_HOME"
export HERMES_HOME="$MEMORY_HOME"
export MNEME_EMBED_ON_WRITE=0

{shlex.quote(str(capture_cli))} claude --memory-home "$MEMORY_HOME" --since-minutes 360 --limit-files 12 --quiet >/dev/null 2>&1
exit 0
"""


def claude_prompt_hook_script(paths: ContinuityPaths) -> str:
    if os.name == "nt":
        return claude_prompt_hook_cmd_script(paths)
    context_module = _module_command(paths.bin_dir, "mneme_memory_mcp.hook_context")
    default_home = shlex.quote(str(paths.memory_home))
    return f"""#!/usr/bin/env bash
set +e

DEFAULT_MEMORY_HOME={default_home}
MEMORY_HOME="${{MNEME_HOME:-${{HERMES_HOME:-$DEFAULT_MEMORY_HOME}}}}"
export MNEME_HOME="$MEMORY_HOME"
export HERMES_HOME="$MEMORY_HOME"

{context_module} --memory-home "$MEMORY_HOME" --event UserPromptSubmit
exit 0
"""


def codex_notify_wrapper_script(
    paths: ContinuityPaths, original_command: list[str]
) -> str:
    if os.name == "nt":
        return codex_notify_wrapper_cmd_script(paths, original_command)
    capture_cli = _console_script(paths.bin_dir, "mneme-memory-capture")
    original = " ".join(shlex.quote(part) for part in original_command)
    default_home = shlex.quote(str(paths.memory_home))
    return f"""#!/usr/bin/env bash
set +e

DEFAULT_MEMORY_HOME={default_home}
MEMORY_HOME="${{MNEME_HOME:-${{HERMES_HOME:-$DEFAULT_MEMORY_HOME}}}}"
export MNEME_HOME="$MEMORY_HOME"
export HERMES_HOME="$MEMORY_HOME"
export MNEME_EMBED_ON_WRITE=0

{shlex.quote(str(capture_cli))} codex --memory-home "$MEMORY_HOME" --since-minutes 360 --limit-files 12 --quiet >/dev/null 2>&1

ORIGINAL_NOTIFY=({original})
if [ "${{#ORIGINAL_NOTIFY[@]}}" -gt 0 ] && [ -x "${{ORIGINAL_NOTIFY[0]}}" ]; then
  exec "${{ORIGINAL_NOTIFY[@]}}" "$@"
fi

exit 0
"""


def claude_hook_cmd_script(paths: ContinuityPaths) -> str:
    python = _cmd_literal(str(_python_executable(paths.bin_dir)))
    memory_home = _cmd_literal(str(paths.memory_home))
    return f"""@echo off
setlocal

if "%MNEME_HOME%"=="" (
  if "%HERMES_HOME%"=="" (
    set "MEMORY_HOME={memory_home}"
  ) else (
    set "MEMORY_HOME=%HERMES_HOME%"
  )
) else (
  set "MEMORY_HOME=%MNEME_HOME%"
)
set "MNEME_HOME=%MEMORY_HOME%"
set "HERMES_HOME=%MEMORY_HOME%"

echo ## Mneme shared persistent memory
echo.
echo Claude Code should use this shared memory before substantive answers. Search or write durable facts through the mneme-memory MCP server when available.
echo.
"{python}" -m mneme_memory_mcp.cli summary 2>nul
exit /b 0
"""


def claude_prompt_hook_cmd_script(paths: ContinuityPaths) -> str:
    python = _cmd_literal(str(_python_executable(paths.bin_dir)))
    memory_home = _cmd_literal(str(paths.memory_home))
    return f"""@echo off
setlocal

if "%MNEME_HOME%"=="" (
  if "%HERMES_HOME%"=="" (
    set "MEMORY_HOME={memory_home}"
  ) else (
    set "MEMORY_HOME=%HERMES_HOME%"
  )
) else (
  set "MEMORY_HOME=%MNEME_HOME%"
)
set "MNEME_HOME=%MEMORY_HOME%"
set "HERMES_HOME=%MEMORY_HOME%"

"{python}" -m mneme_memory_mcp.hook_context --memory-home "%MEMORY_HOME%" --event UserPromptSubmit
exit /b 0
"""


def claude_capture_hook_cmd_script(paths: ContinuityPaths) -> str:
    python = _cmd_literal(str(_python_executable(paths.bin_dir)))
    memory_home = _cmd_literal(str(paths.memory_home))
    return f"""@echo off
setlocal

if "%MNEME_HOME%"=="" (
  if "%HERMES_HOME%"=="" (
    set "MEMORY_HOME={memory_home}"
  ) else (
    set "MEMORY_HOME=%HERMES_HOME%"
  )
) else (
  set "MEMORY_HOME=%MNEME_HOME%"
)
set "MNEME_HOME=%MEMORY_HOME%"
set "HERMES_HOME=%MEMORY_HOME%"

"{python}" -m mneme_memory_mcp.capture claude --memory-home "%MEMORY_HOME%" --since-minutes 360 --limit-files 12 --quiet >nul 2>nul
exit /b 0
"""


def codex_notify_wrapper_cmd_script(
    paths: ContinuityPaths, original_command: list[str]
) -> str:
    python = _cmd_literal(str(_python_executable(paths.bin_dir)))
    memory_home = _cmd_literal(str(paths.memory_home))
    original = " ".join(f'"{_cmd_literal(part)}"' for part in original_command)
    return f"""@echo off
setlocal

if "%MNEME_HOME%"=="" (
  if "%HERMES_HOME%"=="" (
    set "MEMORY_HOME={memory_home}"
  ) else (
    set "MEMORY_HOME=%HERMES_HOME%"
  )
) else (
  set "MEMORY_HOME=%MNEME_HOME%"
)
set "MNEME_HOME=%MEMORY_HOME%"
set "HERMES_HOME=%MEMORY_HOME%"

"{python}" -m mneme_memory_mcp.capture codex --memory-home "%MEMORY_HOME%" --since-minutes 360 --limit-files 12 --quiet >nul 2>nul

set ORIGINAL_NOTIFY={original}
if not "%ORIGINAL_NOTIFY%"=="" (
  for %%A in (%ORIGINAL_NOTIFY%) do (
    if exist "%%~A" (
      %ORIGINAL_NOTIFY% %*
    )
    goto :done_notify
  )
)
:done_notify
exit /b 0
"""


def merge_claude_settings(
    settings_path: Path,
    hook_path: Path,
    capture_hook_path: Path | None = None,
    prompt_hook_path: Path | None = None,
) -> bool:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json_object(settings_path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks

    session_start = hooks.setdefault("SessionStart", [])
    if not isinstance(session_start, list):
        session_start = []
        hooks["SessionStart"] = session_start

    if not _sessionstart_has_compatible_hook(session_start):
        session_start.append(
            {"hooks": [{"type": "command", "command": str(hook_path)}]}
        )

    if prompt_hook_path is not None:
        _ensure_hook_command(hooks, "UserPromptSubmit", str(prompt_hook_path))

    if capture_hook_path is not None:
        _ensure_hook_command(hooks, "Stop", str(capture_hook_path))
        _ensure_hook_command(hooks, "SessionEnd", str(capture_hook_path))

    serialized = json.dumps(data, indent=2, sort_keys=False) + "\n"
    existing = (
        settings_path.read_text(encoding="utf-8") if settings_path.exists() else ""
    )
    if serialized != existing:
        settings_path.write_text(serialized, encoding="utf-8")
        return True
    return False


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = path.with_suffix(path.suffix + ".mneme-bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ensure_hook_command(hooks: dict[str, Any], event: str, command: str) -> None:
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        entries = []
        hooks[event] = entries
    if _hook_entries_have_command(entries, command):
        return
    entries.append({"hooks": [{"type": "command", "command": command}]})


def _has_compatible_sessionstart_hook(settings_path: Path) -> bool:
    if not settings_path.exists():
        return False
    data = _read_json_object(settings_path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        return False
    return _sessionstart_has_compatible_hook(session_start)


def _has_hook_command(settings_path: Path, event: str, command_part: str) -> bool:
    if not settings_path.exists():
        return False
    data = _read_json_object(settings_path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get(event)
    if not isinstance(entries, list):
        return False
    return _hook_entries_have_command(entries, command_part)


def _sessionstart_has_compatible_hook(session_start: list[Any]) -> bool:
    for entry in session_start:
        for command in _iter_hook_commands(entry):
            if any(name in command for name in COMPATIBLE_HOOK_NAMES):
                return True
    return False


def _hook_entries_have_command(entries: list[Any], command_part: str) -> bool:
    return any(
        command_part in command
        for entry in entries
        for command in _iter_hook_commands(entry)
    )


def _iter_hook_commands(entry: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(entry, dict):
        command = entry.get("command")
        if isinstance(command, str):
            commands.append(command)
        hooks = entry.get("hooks")
        if isinstance(hooks, list):
            for hook in hooks:
                commands.extend(_iter_hook_commands(hook))
    return commands


def _ensure_memory_file(path: Path, title: str) -> None:
    if not path.exists():
        path.write_text(f"# {title}\n\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def _path_contains(path: Path, text: str) -> bool:
    return path.exists() and text in path.read_text(encoding="utf-8")


def _read_notify_values(config_text: str) -> list[str]:
    match = re.search(r"(?m)^notify\s*=\s*(\[[^\n]*\])", config_text)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _write_notify_values(config_text: str, values: list[str]) -> str:
    line = f"notify = {json.dumps(values, ensure_ascii=False)}"
    if re.search(r"(?m)^notify\s*=\s*\[[^\n]*\]", config_text):
        return re.sub(
            r"(?m)^notify\s*=\s*\[[^\n]*\]", lambda _match: line, config_text, count=1
        )
    return f"{line}\n{config_text}" if config_text else f"{line}\n"


def _codex_notify_capture_configured(paths: ContinuityPaths) -> bool:
    if not _is_runnable(paths.codex_notify_wrapper):
        return False
    if not paths.codex_config.exists():
        return False
    values = _read_notify_values(paths.codex_config.read_text(encoding="utf-8"))
    return bool(values and values[0] == str(paths.codex_notify_wrapper))


def _claude_mcp_configured(paths: ContinuityPaths) -> bool:
    data = _read_json_object(paths.claude_user_config)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    server = servers.get("mneme-memory")
    if not isinstance(server, dict):
        return False
    command = str(server.get("command") or "")
    args = [str(arg) for arg in server.get("args", [])]
    command_name = Path(command).name.lower()
    if command == str(_python_executable(paths.bin_dir)):
        return "mneme_memory_mcp" in args
    return command_name in {"mneme-memory-mcp", "mneme-memory-mcp.exe"}


def _console_script(bin_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return bin_dir / f"{name}{suffix}"


def _python_executable(bin_dir: Path) -> Path:
    return bin_dir / ("python.exe" if os.name == "nt" else "python")


def _module_command(bin_dir: Path, module: str) -> str:
    if os.name != "nt":
        script_name = {
            "mneme_memory_mcp.cli": "mneme-memory",
            "mneme_memory_mcp.capture": "mneme-memory-capture",
            "mneme_memory_mcp.continuity": "mneme-memory-continuity",
        }.get(module)
        if script_name:
            return shlex.quote(str(_console_script(bin_dir, script_name)))
    return f'"{_python_executable(bin_dir)}" -m {module}'


def _make_runnable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _is_runnable(path: Path) -> bool:
    if os.name == "nt":
        return path.exists() and path.is_file()
    return path.exists() and os.access(path, os.X_OK)


def _cmd_literal(value: str) -> str:
    return value.replace("%", "%%").replace('"', '""')


def _validate_generated_paths(paths: ContinuityPaths) -> None:
    """Reject path text that could become hook source or global instructions."""

    forbidden = {"\x00", "\r", "\n", "`"}
    if os.name == "nt":
        forbidden.update({"&", "|", "<", ">", "^", "%", "!"})
    for path in paths.__dict__.values():
        value = str(path)
        if any(character in value for character in forbidden):
            raise ValueError(f"unsafe character in generated configuration path: {value!r}")


def _ok(value: bool) -> str:
    return "ok" if value else "missing"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mneme-memory-continuity",
        description="Install or inspect Mneme always-on memory continuity.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install", help="Install always-on client continuity."
    )
    install.add_argument("--memory-home", type=Path, default=None)
    install.add_argument("--bin-dir", type=Path, default=None)

    status = subparsers.add_parser("status", help="Show continuity status.")
    status.add_argument("--memory-home", type=Path, default=None)
    status.add_argument("--bin-dir", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    paths = default_paths(memory_home=args.memory_home, bin_dir=args.bin_dir)
    if args.command == "install":
        status = install_continuity(paths)
        print("Mneme always-on memory continuity installed.")
    else:
        status = continuity_status(paths)
        print("Mneme always-on memory continuity status")
    print("\n".join(status.lines()))


if __name__ == "__main__":
    main()
