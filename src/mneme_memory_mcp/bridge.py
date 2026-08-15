from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from .store import SharedMemoryStore, resolve_home

AgentName = Literal["claude", "codex"]

DEFAULT_TIMEOUT_SECONDS = 600
MAX_CONTEXT_CHARS = 12000
MAX_OUTPUT_CHARS = 64_000


@dataclass(frozen=True)
class AgentRun:
    agent: str
    command: list[str]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str

    def format(self) -> str:
        pieces = [
            f"agent: {self.agent}",
            f"cwd: {self.cwd}",
            f"exit: {self.returncode}",
            "command: [redacted]",
            "",
            (self.stdout or "").strip() or "(no stdout)",
        ]
        stderr = (self.stderr or "").strip()
        if stderr:
            pieces.extend(["", "stderr:", stderr])
        return "\n".join(pieces).strip()


def bridge_status() -> str:
    """Return local agent bridge readiness."""

    lines = [
        "Mneme agent bridge status",
        f"memory home: {resolve_home()}",
        f"claude: {_binary_status('claude')}",
        f"codex: {_binary_status('codex')}",
        f"node: {_binary_status('node')}",
    ]
    return "\n".join(lines)


def delegate_to_claude(
    prompt: str,
    cwd: str | None = None,
    model: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> AgentRun:
    """Run a one-shot Claude Code task with Mneme memory injected.

    Uses Claude Code's default permission mode."""

    prompt = _require_prompt(prompt)
    workdir = _resolve_cwd(cwd)
    claude = _require_binary("claude")
    command = [
        claude,
        "-p",
        "--permission-mode",
        "default",
        "--append-system-prompt",
        _mneme_system_prompt("Claude Code"),
    ]
    if model:
        command.extend(["--model", model])
    command.append(prompt)
    return _run("claude", command, workdir, timeout_seconds, env=_claude_env())


def delegate_to_codex(
    prompt: str,
    cwd: str | None = None,
    model: str | None = None,
    sandbox: Literal["read-only", "workspace-write"] = "workspace-write",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> AgentRun:
    """Run a one-shot Codex task with Mneme memory injected.

    Defaults to Codex's workspace-write sandbox. Mneme's memory home is added as
    a writable root so the delegated agent can use the shared memory service.
    The MCP bridge never exposes Codex's danger-full-access mode."""

    prompt = _require_prompt(prompt)
    workdir = _resolve_cwd(cwd)
    codex = _require_binary("codex")
    command = [
        codex,
        "exec",
        "-C",
        str(workdir),
        "--sandbox",
        sandbox,
        "--skip-git-repo-check",
        "--color",
        "never",
    ]
    if sandbox == "workspace-write":
        # The shared Mneme store lives at ~/.hermes, outside the workspace. Make its home a
        # writable root so the delegate's nested memory MCP writes — and even reads, which
        # run migrate-on-open — don't hit a readonly database.
        writable_roots = json.dumps([str(resolve_home())])
        command.extend(["-c", f"sandbox_workspace_write.writable_roots={writable_roots}"])
    if model:
        command.extend(["--model", model])
    command.append(_with_memory_prompt(prompt, "Codex"))
    return _run("codex", command, workdir, timeout_seconds)


def _binary_status(name: str) -> str:
    path = shutil.which(name)
    return path if path else "missing"


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} CLI was not found on PATH")
    if os.name == "nt" and Path(path).suffix.lower() in {".bat", ".cmd"}:
        raise RuntimeError(
            f"{name} resolved to a Windows batch launcher; the Mneme bridge "
            "requires a native executable to preserve argument boundaries"
        )
    return path


def _require_prompt(prompt: str) -> str:
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("prompt must not be empty")
    return prompt


def _resolve_cwd(cwd: str | None) -> Path:
    configured_root = os.environ.get("MNEME_BRIDGE_ROOT", "").strip()
    if not configured_root:
        raise ValueError(
            "MNEME_BRIDGE_ROOT must be set before agent delegation is enabled"
        )
    root = Path(configured_root).expanduser().resolve()
    path = Path(cwd).expanduser().resolve() if cwd else root
    if not path.exists():
        raise ValueError(f"cwd does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"cwd is not a directory: {path}")
    if path != root and not path.is_relative_to(root):
        raise ValueError(f"cwd must stay within MNEME_BRIDGE_ROOT: {root}")
    return path


def _bounded_timeout(timeout_seconds: int) -> int:
    try:
        value = int(timeout_seconds)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_SECONDS
    return max(5, min(value, 3600))


def _mneme_system_prompt(agent_label: str) -> str:
    summary = SharedMemoryStore().summary()
    if len(summary) > MAX_CONTEXT_CHARS:
        summary = summary[:MAX_CONTEXT_CHARS] + "\n\n[Mneme memory summary truncated]"
    return (
        "You are being invoked through Mneme Memory MCP as "
        f"{agent_label}. Treat this as a peer-agent delegation.\n\n"
        "Use the shared Mneme/Hermes memory below for continuity. "
        "If durable facts are discovered, ask the caller to store them through Mneme memory tools.\n\n"
        f"{summary}"
    )


def _with_memory_prompt(prompt: str, agent_label: str) -> str:
    return f"{_mneme_system_prompt(agent_label)}\n\nDelegated task:\n{prompt}"


def _claude_env() -> dict[str, str]:
    """Return the caller's environment for the headless `claude` CLI.

    Authentication remains the responsibility of the installed Claude CLI. Mneme
    never searches the filesystem for credential files or copies credentials into
    a child process environment.
    """
    return _delegate_env()


def _delegate_env() -> dict[str, str]:
    """Build a minimal child environment without inheriting credentials."""

    allowed = {
        "HOME",
        "USER",
        "USERPROFILE",
        "LOGNAME",
        "PATH",
        "PATHEXT",
        "SHELL",
        "SYSTEMROOT",
        "COMSPEC",
        "APPDATA",
        "LOCALAPPDATA",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "TERM",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def _run(
    agent: str,
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> AgentRun:
    command = _windows_batch_safe_command(command)
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr_file:
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=_bounded_timeout(timeout_seconds),
                check=False,
                env=env or _delegate_env(),
            )
            returncode = result.returncode
            timeout_message = ""
        except subprocess.TimeoutExpired:
            returncode = 124
            timeout_message = (
                f"timed out after {_bounded_timeout(timeout_seconds)} seconds"
            )

        stdout = _read_bounded_output(stdout_file)
        stderr = _read_bounded_output(stderr_file)
        if timeout_message:
            stderr = f"{stderr}\n{timeout_message}".strip()
        return AgentRun(
            agent=agent,
            command=command,
            cwd=cwd,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )


def _read_bounded_output(stream: TextIO) -> str:
    stream.seek(0)
    text = stream.read(MAX_OUTPUT_CHARS + 1)
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n[output truncated]"
    return text


def _windows_batch_safe_command(command: list[str]) -> list[str]:
    if os.name != "nt" or not command:
        return command
    if Path(command[0]).suffix.lower() not in {".bat", ".cmd"}:
        return command
    return [command[0], *[_line_safe_arg(arg) for arg in command[1:]]]


def _line_safe_arg(arg: str) -> str:
    return str(arg).replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
