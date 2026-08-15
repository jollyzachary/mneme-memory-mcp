from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .store import SharedMemoryStore, resolve_home

MAX_SNIPPET_CHARS = 3200
MIN_SNIPPET_CHARS = 8

SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
            re.IGNORECASE | re.DOTALL,
        ),
        "[private key redacted]",
    ),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[^\s'\",]+"), r"\1[redacted]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"), "Bearer [redacted]"),
    (re.compile(r"\bsk-proj-[A-Za-z0-9_-]{16,}"), "sk-proj-[redacted]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "sk-[redacted]"),
    (re.compile(r"\bghp_[A-Za-z0-9_]{20,}"), "ghp_[redacted]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "github_pat_[redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA[redacted]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "AIza[redacted]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "xox-[redacted]"),
    (
        re.compile(r"\b(?:eyJ[A-Za-z0-9_-]+)\.(?:[A-Za-z0-9_-]+)\.(?:[A-Za-z0-9_-]+)\b"),
        "[JWT redacted]",
    ),
    (
        re.compile(
            r"(?i)\b(api[_ -]?key|token|secret|password|passwd|"
            r"aws[_ -]?secret[_ -]?access[_ -]?key|client[_ -]?secret|"
            r"service[_ -]?role[_ -]?key)\b['\"]?\s*[:=]\s*['\"]?[^'\"\s,}]+"
        ),
        r"\1=[redacted]",
    ),
    (
        re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]{80,}"),
        "[image data redacted]",
    ),
    (re.compile(r"\b[A-Za-z0-9+/]{600,}={0,2}\b"), "[large encoded blob redacted]"),
)


@dataclass(frozen=True)
class ConversationSnippet:
    source: str
    session_id: str
    role: str
    text: str

    def fact_content(self) -> str:
        return (
            f"[{self.source} conversation capture] "
            f"session={self.session_id or 'unknown'} role={self.role or 'unknown'}: "
            f"{self.text}"
        )

    def tags(self) -> str:
        parts = ["capture", self.source]
        if self.role:
            parts.append(f"role:{self.role}")
        if self.session_id:
            parts.append(f"session:{self.session_id}")
        return ",".join(parts)


@dataclass(frozen=True)
class CaptureStats:
    source: str
    files_scanned: int
    snippets_indexed: int

    def format(self) -> str:
        return (
            f"{self.source}: archived {self.snippets_indexed} snippets "
            f"from {self.files_scanned} files"
        )


@dataclass
class JsonlCursor:
    offset: int = 0


def capture_conversations(
    source: str = "all",
    *,
    home: Path | None = None,
    since_minutes: int | None = 1440,
    limit_files: int = 25,
    include_archived: bool = False,
) -> list[CaptureStats]:
    memory_home = home or resolve_home()
    store = SharedMemoryStore(home=memory_home)
    selected = ("claude", "codex") if source == "all" else (source,)
    stats: list[CaptureStats] = []
    for item in selected:
        if item == "claude":
            stats.append(
                _capture_source(
                    source="claude",
                    files=_claude_files(
                        since_minutes=since_minutes, limit_files=limit_files
                    ),
                    parser=parse_claude_jsonl,
                    store=store,
                )
            )
        elif item == "codex":
            stats.append(
                _capture_source(
                    source="codex",
                    files=_codex_files(
                        since_minutes=since_minutes,
                        limit_files=limit_files,
                        include_archived=include_archived,
                    ),
                    parser=parse_codex_jsonl,
                    store=store,
                )
            )
            stats.append(_capture_codex_prompt_history(store))
        else:
            raise ValueError(f"unknown source: {source}")
    return stats


def parse_claude_jsonl(
    path: Path,
    *,
    start_offset: int = 0,
    cursor: JsonlCursor | None = None,
) -> list[ConversationSnippet]:
    snippets: list[ConversationSnippet] = []
    for record in _iter_jsonl(path, start_offset=start_offset, cursor=cursor):
        session_id = str(
            record.get("sessionId") or record.get("session_id") or path.stem
        )
        record_type = str(record.get("type") or "")

        if record_type == "queue-operation" and record.get("operation") == "enqueue":
            text = _sanitize_text(record.get("content"))
            if _should_keep(text):
                snippets.append(ConversationSnippet("claude", session_id, "user", text))
            continue

        message = record.get("message")
        if isinstance(message, dict):
            role = str(message.get("role") or record.get("role") or "unknown")
            text = _sanitize_text(_content_to_text(message.get("content")))
            if _should_keep(text):
                snippets.append(ConversationSnippet("claude", session_id, role, text))
            continue

        role = str(record.get("role") or "")
        text = _sanitize_text(_content_to_text(record.get("content")))
        if role and _should_keep(text):
            snippets.append(ConversationSnippet("claude", session_id, role, text))
    return snippets


def parse_codex_jsonl(
    path: Path,
    *,
    start_offset: int = 0,
    cursor: JsonlCursor | None = None,
) -> list[ConversationSnippet]:
    snippets: list[ConversationSnippet] = []
    session_id = _codex_session_id(path)
    for record in _iter_jsonl(path, start_offset=start_offset, cursor=cursor):
        if record.get("type") == "session_meta":
            payload = record.get("payload")
            if isinstance(payload, dict):
                session_id = str(payload.get("id") or session_id)
            continue

        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue

        payload_type = str(payload.get("type") or "")
        if record.get("type") == "event_msg":
            if payload_type == "user_message":
                text = _sanitize_text(payload.get("message"))
                if _should_keep(text):
                    snippets.append(
                        ConversationSnippet("codex", session_id, "user", text)
                    )
            elif payload_type == "agent_message":
                text = _sanitize_text(payload.get("message"))
                if _should_keep(text):
                    snippets.append(
                        ConversationSnippet("codex", session_id, "assistant", text)
                    )
            continue

        if record.get("type") == "response_item" and payload_type == "message":
            role = str(payload.get("role") or "assistant")
            text = _sanitize_text(_content_to_text(payload.get("content")))
            if _should_keep(text):
                snippets.append(ConversationSnippet("codex", session_id, role, text))
    return snippets


def _capture_source(
    *,
    source: str,
    files: list[Path],
    parser: Callable[..., list[ConversationSnippet]],
    store: SharedMemoryStore,
) -> CaptureStats:
    indexed = 0
    sessions: set[str] = set()
    for path in files:
        try:
            start_offset = store.capture_offset(source=source, path=path)
            cursor = JsonlCursor(offset=start_offset)
            snippets = parser(path, start_offset=start_offset, cursor=cursor)
        except OSError:
            continue
        for snippet in snippets:
            store.add_episodic(
                source=snippet.source,
                session_id=snippet.session_id,
                role=snippet.role,
                text=snippet.text,
                tags=snippet.tags(),
                trust_score=0.35,
            )
            sessions.add(snippet.session_id)
            indexed += 1
        store.update_capture_offset(
            source=source,
            path=path,
            byte_offset=cursor.offset,
        )
    for session_id in sessions:
        store.consolidate_session(source=source, session_id=session_id)
    store.prune_episodic()
    store.prune_events()
    store.maybe_vacuum()
    return CaptureStats(
        source=source, files_scanned=len(files), snippets_indexed=indexed
    )


def _capture_codex_prompt_history(store: SharedMemoryStore) -> CaptureStats:
    state_path = Path.home() / ".codex" / ".codex-global-state.json"
    if not state_path.exists():
        return CaptureStats(
            source="codex-prompt-history", files_scanned=0, snippets_indexed=0
        )
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CaptureStats(
            source="codex-prompt-history", files_scanned=1, snippets_indexed=0
        )

    indexed = 0
    for item in _walk_prompt_history(data):
        text = _sanitize_text(item)
        if not _should_keep(text):
            continue
        snippet = ConversationSnippet("codex", "prompt-history", "user", text)
        store.add_episodic(
            source=snippet.source,
            session_id=snippet.session_id,
            role=snippet.role,
            text=snippet.text,
            tags="capture,codex,prompt-history,role:user",
            trust_score=0.30,
        )
        indexed += 1
    if indexed:
        store.consolidate_session(source="codex", session_id="prompt-history")
        store.prune_episodic()
    return CaptureStats(
        source="codex-prompt-history", files_scanned=1, snippets_indexed=indexed
    )


def _walk_prompt_history(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z]", "", str(key).lower())
            if normalized in {"prompthistory", "prompts"}:
                yield from _extract_prompt_items(child)
            elif isinstance(child, dict):
                yield from _walk_prompt_history(child)


def _extract_prompt_items(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        text = value.get("prompt") or value.get("text") or value.get("message")
        if isinstance(text, str):
            yield text
        else:
            yield from _walk_prompt_history(value)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, str):
                yield child
            elif isinstance(child, dict):
                text = child.get("prompt") or child.get("text") or child.get("message")
                if isinstance(text, str):
                    yield text
                else:
                    yield from _extract_prompt_items(child)


def _claude_files(*, since_minutes: int | None, limit_files: int) -> list[Path]:
    return _recent_files(
        [Path.home() / ".claude" / "projects", Path.home() / ".claude" / "sessions"],
        since_minutes=since_minutes,
        limit_files=limit_files,
    )


def _codex_files(
    *,
    since_minutes: int | None,
    limit_files: int,
    include_archived: bool,
) -> list[Path]:
    roots = [Path.home() / ".codex" / "sessions"]
    if include_archived:
        roots.append(Path.home() / ".codex" / "archived_sessions")
    return _recent_files(roots, since_minutes=since_minutes, limit_files=limit_files)


def _recent_files(
    roots: list[Path],
    *,
    since_minutes: int | None,
    limit_files: int,
) -> list[Path]:
    cutoff = None if since_minutes is None else time.time() - max(0, since_minutes) * 60
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(path for path in root.rglob("*.jsonl") if path.is_file())
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if cutoff is not None:
        files = [path for path in files if path.stat().st_mtime >= cutoff]
    return files[: max(1, limit_files)]


def _iter_jsonl(
    path: Path,
    *,
    start_offset: int = 0,
    cursor: JsonlCursor | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield complete JSONL records and retain an append-safe byte checkpoint."""

    state = cursor or JsonlCursor()
    with path.open("rb") as handle:
        size = path.stat().st_size
        safe_start = max(0, min(int(start_offset), size))
        handle.seek(safe_start)
        state.offset = safe_start
        while True:
            line_start = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            if not raw.endswith(b"\n"):
                # The writer may still be appending this record. Retry it next run.
                state.offset = line_start
                break
            state.offset = handle.tell()
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(record, dict):
                yield record


def _codex_session_id(path: Path) -> str:
    """Read only the leading metadata so incremental tail parsing keeps identity."""

    try:
        with path.open("rb") as handle:
            for _index in range(50):
                raw = handle.readline()
                if not raw:
                    break
                try:
                    record = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if record.get("type") != "session_meta":
                    continue
                payload = record.get("payload")
                if isinstance(payload, dict) and payload.get("id"):
                    return str(payload["id"])
    except OSError:
        pass
    return path.stem


def _content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _content_to_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        item_type = value.get("type")
        if item_type in {"text", "input_text", "output_text"} and isinstance(
            value.get("text"), str
        ):
            return str(value["text"])
        if item_type == "tool_result":
            return _content_to_text(value.get("content"))
        if item_type == "tool_use":
            name = value.get("name") or "tool"
            input_text = _safe_json(value.get("input"))
            return (
                f"tool_use {name}: {input_text}" if input_text else f"tool_use {name}"
            )
        for key in ("text", "message", "content"):
            if key in value:
                return _content_to_text(value[key])
    return ""


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return str(value)


def _sanitize_text(value: Any) -> str:
    text = _content_to_text(value) if not isinstance(value, str) else value
    if not text:
        return ""
    text = text.replace("\x00", "")
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_SNIPPET_CHARS:
        text = text[:MAX_SNIPPET_CHARS].rstrip() + " ... [truncated]"
    return text


# Tool-call / hook markup that intermittently leaked into memory. Store-side
# stripping only knows a few shapes and truncation can split tags mid-pattern,
# so reject markup-bearing snippets outright — capture is low-trust episodic
# material and a dropped snippet costs nothing.
_MARKUP_SIGNATURES = (
    "<parameter",
    "</parameter",
    "<function",
    "</function",
    "antml:",
    "hookspecificoutput",
    "<system-reminder",
    "<local-command",
    "tool_use_id",
)


def _should_keep(text: str) -> bool:
    if len(text.strip()) < MIN_SNIPPET_CHARS:
        return False
    if text.startswith("gAAAAAB"):
        return False
    lowered = text.lower()
    return not any(signature in lowered for signature in _MARKUP_SIGNATURES)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mneme-memory-capture",
        description="Archive local Claude/Codex transcripts and distill compact Mneme summaries.",
    )
    parser.add_argument(
        "source", nargs="?", choices=("all", "claude", "codex"), default="all"
    )
    parser.add_argument("--memory-home", type=Path, default=None)
    parser.add_argument("--since-minutes", type=int, default=1440)
    parser.add_argument(
        "--all-history",
        action="store_true",
        help="Scan without a modified-time cutoff.",
    )
    parser.add_argument("--limit-files", type=int, default=25)
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    stats = capture_conversations(
        source=args.source,
        home=args.memory_home,
        since_minutes=None if args.all_history else args.since_minutes,
        limit_files=args.limit_files,
        include_archived=args.include_archived,
    )
    if not args.quiet:
        print("\n".join(item.format() for item in stats))


if __name__ == "__main__":
    main()
