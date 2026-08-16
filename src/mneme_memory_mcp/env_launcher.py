from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import MutableMapping

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALLOWED_ENV_KEYS = frozenset(
    {
        "MNEME_HOME",
        "HERMES_HOME",
        "MNEME_MEMORY_DIR",
        "MNEME_DB_PATH",
        "MNEME_RETRIEVAL_BACKEND",
        "MNEME_MIN_COSINE",
        "MNEME_EMBED_MODEL",
        "MNEME_EMBED_MODEL_REVISION",
        "MNEME_EMBED_LOCAL_ONLY",
        "MNEME_EMBED_ON_WRITE",
        "MNEME_POSTGRES_HOST",
        "MNEME_POSTGRES_PORT",
        "MNEME_POSTGRES_DATABASE",
        "MNEME_POSTGRES_USER",
        "MNEME_POSTGRES_PASSWORD_FILE",
        "MNEME_POSTGRES_CONNECT_TIMEOUT",
        "MNEME_POSTGRES_STATEMENT_TIMEOUT_MS",
        "MNEME_POSTGRES_GRAPH_STATEMENT_TIMEOUT_MS",
        "MNEME_POSTGRES_REQUIRED",
        "MNEME_GRAPH_SYNC_ON_WRITE",
    }
)


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep != "=" or not _KEY_RE.match(key):
            continue
        if key in ALLOWED_ENV_KEYS:
            values[key] = _clean_value(value.strip())
    return values


def configure_environment(
    env_file: Path,
    default_home: Path,
    environ: MutableMapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    env = environ if environ is not None else os.environ
    for key, value in parse_env_file(env_file).items():
        if key in {
            "MNEME_HOME",
            "HERMES_HOME",
            "MNEME_MEMORY_DIR",
            "MNEME_DB_PATH",
            "MNEME_POSTGRES_PASSWORD_FILE",
        }:
            value = _resolve_path_value(value, env_file.parent)
        env.setdefault(key, value)

    if "MNEME_HOME" not in env and "HERMES_HOME" not in env:
        env["MNEME_HOME"] = str(default_home)
        env["HERMES_HOME"] = str(default_home)
    elif "MNEME_HOME" in env and "HERMES_HOME" not in env:
        env["HERMES_HOME"] = env["MNEME_HOME"]
    elif "HERMES_HOME" in env and "MNEME_HOME" not in env:
        env["MNEME_HOME"] = env["HERMES_HOME"]

    return env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mneme-memory-env-mcp",
        description="Run Mneme MCP after loading memory settings from a .env file.",
    )
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--default-home", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    configure_environment(
        env_file=args.env_file.expanduser(),
        default_home=args.default_home.expanduser(),
    )
    from .server import main as server_main

    server_main()


def _clean_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _resolve_path_value(value: str, base_dir: Path) -> str:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = base_dir / expanded
    return str(expanded)


if __name__ == "__main__":
    main()
