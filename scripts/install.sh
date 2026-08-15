#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_SLUG="$(basename "$ROOT" | sed 's/[^A-Za-z0-9._-]/-/g')"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
MNEME_DATA_DIR="${MNEME_DATA_DIR:-$DATA_HOME/mneme-memory-mcp}"
INSTALL_DIR="${MNEME_INSTALL_DIR:-$MNEME_DATA_DIR}"
VENV_DIR="${MNEME_VENV_DIR:-$INSTALL_DIR/venv}"
GLOBAL_MEMORY_HOME="${MNEME_HOME:-${HERMES_HOME:-$HOME/.hermes}}"
MEMORY_HOME="$GLOBAL_MEMORY_HOME"
ENV_FILE="${MNEME_ENV_FILE:-$ROOT/.env}"
PROJECT_MEMORY_HOME="${MNEME_PROJECT_HOME:-$MNEME_DATA_DIR/projects/$PROJECT_SLUG}"
SETUP_PROFILE="${MNEME_SETUP_PROFILE:-}"
MCP_COMMAND="$VENV_DIR/bin/mneme-memory-mcp"
MCP_ARGS=()
MCP_STATIC_ENV=1
CONFIGURE_CLIENTS=1
INSTALL_CONTINUITY=1
EDITABLE_INSTALL="${MNEME_EDITABLE:-0}"
INSTALL_EMBEDDINGS="${MNEME_INSTALL_EMBEDDINGS:-1}"
INSTALL_POSTGRES="${MNEME_INSTALL_POSTGRES:-0}"
PYTHON_BIN="${PYTHON_BIN:-}"

usage() {
  cat <<'EOF'
Mneme Memory MCP installer

Usage:
  ./scripts/install.sh [--profile global|project|server] [options]

Mneme installs into a managed user-data directory. Choose a setup profile to
set the memory scope and client configuration. Client configuration is
best-effort.

Setup profiles:
  global   Shared persistent memory in ~/.hermes, with supported client
           configuration, startup context, and local conversation capture.
  project  Project/env-scoped memory from .env, defaulting to a project folder
           under ~/.local/share/mneme-memory-mcp/projects. This configures MCP
           clients without installing global memory instructions.
  server   Install the local Mneme server only; print manual config.

Options:
  --profile VALUE      Select global, project, or server setup.
  --global-memory      Alias for --profile global.
  --project-memory     Alias for --profile project.
  --server-only        Alias for --profile server.
  --env-file PATH      .env file for project/env-scoped memory.
  --install-dir PATH   Managed install directory. Default: ~/.local/share/mneme-memory-mcp.
  --venv-dir PATH      Python virtualenv directory. Default: <install-dir>/venv.
  --editable           Install Mneme in editable mode for local development.
  --no-embeddings      Skip the local semantic-retrieval dependencies.
  --postgres-retrieval Install the PostgreSQL retrieval client dependency.
  --no-client-config   Do not modify Codex or Claude MCP configuration.
  --no-continuity      Do not install global Claude/Codex memory instructions.
  --memory-only        Skip client configuration and continuity changes.

Environment:
  MNEME_HOME    Memory home to use. Defaults to HERMES_HOME or ~/.hermes.
  HERMES_HOME   Hermes-compatible memory home.
  MNEME_SETUP_PROFILE  global, project, or server.
  MNEME_INSTALL_DIR    Managed install directory.
  MNEME_VENV_DIR       Python virtualenv directory.
  MNEME_DATA_DIR       Mneme data directory. Defaults to ~/.local/share/mneme-memory-mcp.
  MNEME_ENV_FILE       .env file for the project profile.
  MNEME_PROJECT_HOME   Default memory home for the project profile.
  MNEME_EDITABLE       Set to 1 for editable local development installs.
  MNEME_INSTALL_EMBEDDINGS  Set to 0 to skip semantic-retrieval dependencies.
  MNEME_INSTALL_POSTGRES    Set to 1 to install the PostgreSQL retrieval client.
  PYTHON_BIN    Python 3.10+ binary to use. Auto-detected when unset.
EOF
}

find_python() {
  if [ -n "$PYTHON_BIN" ]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
      then
        command -v "$candidate"
        return 0
      fi
    fi
  done

  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--profile requires a value: global, project, or server" >&2
        exit 2
      fi
      SETUP_PROFILE="$1"
      ;;
    --profile=*)
      SETUP_PROFILE="${1#*=}"
      ;;
    --global-memory)
      SETUP_PROFILE="global"
      ;;
    --project-memory|--env-memory)
      SETUP_PROFILE="project"
      ;;
    --server-only)
      SETUP_PROFILE="server"
      ;;
    --env-file)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--env-file requires a path" >&2
        exit 2
      fi
      ENV_FILE="$1"
      ;;
    --env-file=*)
      ENV_FILE="${1#*=}"
      ;;
    --install-dir)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--install-dir requires a path" >&2
        exit 2
      fi
      INSTALL_DIR="$1"
      VENV_DIR="$INSTALL_DIR/venv"
      ;;
    --install-dir=*)
      INSTALL_DIR="${1#*=}"
      VENV_DIR="$INSTALL_DIR/venv"
      ;;
    --venv-dir)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--venv-dir requires a path" >&2
        exit 2
      fi
      VENV_DIR="$1"
      ;;
    --venv-dir=*)
      VENV_DIR="${1#*=}"
      ;;
    --editable)
      EDITABLE_INSTALL=1
      ;;
    --no-embeddings)
      INSTALL_EMBEDDINGS=0
      ;;
    --postgres-retrieval)
      INSTALL_POSTGRES=1
      ;;
    --no-client-config)
      CONFIGURE_CLIENTS=0
      ;;
    --no-continuity)
      INSTALL_CONTINUITY=0
      ;;
    --memory-only)
      CONFIGURE_CLIENTS=0
      INSTALL_CONTINUITY=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

run_optional() {
  local label="$1"
  shift
  echo "==> $label"
  if "$@"; then
    return 0
  fi
  local code=$?
  echo "warning: $label failed with exit $code; continuing." >&2
  return 0
}

run_optional_mcp_command() {
  local label="$1"
  shift
  if [ "${#MCP_ARGS[@]}" -gt 0 ]; then
    run_optional "$label" "$@" "$MCP_COMMAND" "${MCP_ARGS[@]}"
  else
    run_optional "$label" "$@" "$MCP_COMMAND"
  fi
}

abspath_under_root() {
  case "$1" in
    "~")
      printf '%s\n' "$HOME"
      ;;
    "~/"*)
      printf '%s/%s\n' "$HOME" "${1#~/}"
      ;;
    /*)
      printf '%s\n' "$1"
      ;;
    *)
      printf '%s\n' "$ROOT/$1"
      ;;
  esac
}

choose_profile() {
  if [ -z "$SETUP_PROFILE" ] && [ -t 0 ] && [ "${MNEME_INSTALL_NONINTERACTIVE:-0}" != "1" ]; then
    cat <<'EOF'

Choose a Mneme setup profile:

  1) Global persistent memory
     Shared memory and continuity hooks for supported clients.

  2) Project/env-scoped memory
     An isolated memory home for this workspace. Memory comes from .env and
     defaults to ~/.local/share/mneme-memory-mcp/projects/<repo>.

  3) Server only / manual wiring
     Installs Mneme locally and prints config without client configuration or
     continuity hooks.

EOF
    printf 'Select 1, 2, or 3: '
    read -r choice
    case "$choice" in
      1|global|g)
        SETUP_PROFILE="global"
        ;;
      2|project|p|env)
        SETUP_PROFILE="project"
        ;;
      3|server|s|manual)
        SETUP_PROFILE="server"
        ;;
      *)
        echo "Unknown selection: $choice" >&2
        exit 2
        ;;
    esac
  elif [ -z "$SETUP_PROFILE" ]; then
    cat >&2 <<'EOF'
No Mneme setup profile was selected.

Pass one of these profiles explicitly:
  global   shared memory with supported client continuity
  project  project/env-scoped memory from .env
  server   server install only; manual wiring

Example:
  ./scripts/install.sh --profile project
EOF
    exit 2
  fi

  case "$SETUP_PROFILE" in
    global|project|server)
      ;;
    *)
      echo "Unknown profile: $SETUP_PROFILE" >&2
      echo "Use --profile global, --profile project, or --profile server." >&2
      exit 2
      ;;
  esac

}

read_env_memory_home() {
  "$PYTHON_BIN" - "$ENV_FILE" <<'PY'
import os
import re
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.exists():
    raise SystemExit(1)

pattern = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
values = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    match = pattern.match(line)
    if not match:
        continue
    key, value = match.groups()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values[key] = value

value = values.get("MNEME_HOME") or values.get("HERMES_HOME")
if not value:
    raise SystemExit(1)

expanded = Path(os.path.expandvars(os.path.expanduser(value)))
if not expanded.is_absolute():
    expanded = path.parent / expanded
print(expanded)
PY
}

ensure_project_env() {
  ENV_FILE="$(abspath_under_root "$ENV_FILE")"
  PROJECT_MEMORY_HOME="$(abspath_under_root "$PROJECT_MEMORY_HOME")"
  mkdir -p "$(dirname "$ENV_FILE")"

  if [ ! -f "$ENV_FILE" ]; then
    printf '# Mneme project-scoped memory\nMNEME_HOME=%s\n' "$PROJECT_MEMORY_HOME" > "$ENV_FILE"
    return 0
  fi

  if ! read_env_memory_home >/dev/null 2>&1; then
    {
      printf '\n# Mneme project-scoped memory\n'
      printf 'MNEME_HOME=%s\n' "$PROJECT_MEMORY_HOME"
    } >> "$ENV_FILE"
  fi
}

apply_profile() {
  INSTALL_DIR="$(abspath_under_root "$INSTALL_DIR")"
  VENV_DIR="$(abspath_under_root "$VENV_DIR")"

  case "$SETUP_PROFILE" in
    global)
      MEMORY_HOME="$GLOBAL_MEMORY_HOME"
      MCP_COMMAND="$VENV_DIR/bin/mneme-memory-mcp"
      MCP_ARGS=()
      MCP_STATIC_ENV=1
      ;;
    project)
      ensure_project_env
      MEMORY_HOME="$(read_env_memory_home)"
      INSTALL_CONTINUITY=0
      MCP_COMMAND="$VENV_DIR/bin/mneme-memory-env-mcp"
      MCP_ARGS=(--env-file "$ENV_FILE" --default-home "$PROJECT_MEMORY_HOME")
      MCP_STATIC_ENV=0
      ;;
    server)
      MEMORY_HOME="$GLOBAL_MEMORY_HOME"
      CONFIGURE_CLIENTS=0
      INSTALL_CONTINUITY=0
      MCP_COMMAND="$VENV_DIR/bin/mneme-memory-mcp"
      MCP_ARGS=()
      MCP_STATIC_ENV=1
      ;;
    *)
      echo "Unknown profile: $SETUP_PROFILE" >&2
      echo "Use --profile global, --profile project, or --profile server." >&2
      exit 2
      ;;
  esac

  export MNEME_HOME="$MEMORY_HOME"
  export HERMES_HOME="$MEMORY_HOME"
}

validate_venv_dir() {
  INSTALL_DIR="$("$PYTHON_BIN" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$INSTALL_DIR")"
  VENV_DIR="$("$PYTHON_BIN" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$VENV_DIR")"
  case "$VENV_DIR" in
    "$INSTALL_DIR"/*) ;;
    *)
      echo "Refusing venv outside the managed install directory: $VENV_DIR" >&2
      exit 2
      ;;
  esac
  if [ "$VENV_DIR" = "$INSTALL_DIR" ]; then
    echo "The venv directory must be a child of the managed install directory." >&2
    exit 2
  fi
  if [ -d "$VENV_DIR" ] && [ ! -f "$VENV_DIR/pyvenv.cfg" ]; then
    if find "$VENV_DIR" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
      echo "Refusing to clear a non-venv directory: $VENV_DIR" >&2
      exit 2
    fi
  fi
}

configure_clients() {
  if [ "$CONFIGURE_CLIENTS" -ne 1 ]; then
    echo "==> Skipping Codex/Claude MCP configuration."
    return 0
  fi

  if command -v codex >/dev/null 2>&1; then
    codex mcp remove mneme_memory >/dev/null 2>&1 || true
    if [ "$MCP_STATIC_ENV" -eq 1 ]; then
      run_optional_mcp_command \
        "Configuring Codex MCP server: mneme_memory" \
        codex mcp add --env "MNEME_HOME=$MNEME_HOME" mneme_memory --
    else
      run_optional_mcp_command \
        "Configuring Codex MCP server: mneme_memory" \
        codex mcp add mneme_memory --
    fi
  else
    echo "==> Codex CLI not found; skipping Codex MCP configuration."
  fi

  if command -v claude >/dev/null 2>&1; then
    claude mcp remove mneme-memory >/dev/null 2>&1 || true
    if [ "$MCP_STATIC_ENV" -eq 1 ]; then
      run_optional_mcp_command \
        "Configuring Claude Code MCP server: mneme-memory" \
        claude mcp add -s user mneme-memory -e "MNEME_HOME=$MNEME_HOME" --
    else
      run_optional_mcp_command \
        "Configuring Claude Code MCP server: mneme-memory" \
        claude mcp add -s user mneme-memory --
    fi
  else
    echo "==> Claude CLI not found; skipping Claude MCP configuration."
  fi
}

install_continuity() {
  if [ "$INSTALL_CONTINUITY" -ne 1 ]; then
    echo "==> Skipping client continuity installation."
    return 0
  fi

  run_optional \
    "Installing Mneme client continuity for Codex and Claude" \
    "$VENV_DIR/bin/mneme-memory-continuity" install --memory-home "$MNEME_HOME" --bin-dir "$VENV_DIR/bin"
}

print_manual_config() {
  cat <<EOF

==> Mneme configuration

Selected profile: $SETUP_PROFILE

The installer attempted to configure:

EOF

  if [ "$CONFIGURE_CLIENTS" -eq 1 ]; then
    cat <<'EOF'
- Mneme MCP in Codex and Claude Code
EOF
  else
    cat <<'EOF'
- Client MCP configuration skipped for this profile or flag set
EOF
  fi

  if [ "$INSTALL_CONTINUITY" -eq 1 ]; then
    cat <<'EOF'
- Shared memory instructions for new Codex and Claude sessions
- Claude SessionStart memory injection
- Claude UserPromptSubmit per-prompt memory injection
- Claude/Codex searchable conversation capture hooks
EOF
  else
    cat <<'EOF'
- No global Claude/Codex memory instructions for this profile
EOF
  fi

  cat <<'EOF'

If automatic client configuration was skipped or failed, add Mneme manually.
EOF

  if [ "$MCP_STATIC_ENV" -eq 1 ]; then
    cat <<EOF

Codex:

[mcp_servers.mneme_memory]
command = "$MCP_COMMAND"
args = []
startup_timeout_sec = 120

[mcp_servers.mneme_memory.env]
MNEME_HOME = "$MNEME_HOME"

Claude Code:

{
  "mcpServers": {
    "mneme-memory": {
      "type": "stdio",
      "command": "$MCP_COMMAND",
      "args": [],
      "env": {
        "MNEME_HOME": "$MNEME_HOME"
      }
    }
  }
}
EOF
  else
    cat <<EOF

Codex:

[mcp_servers.mneme_memory]
command = "$MCP_COMMAND"
args = ["--env-file", "$ENV_FILE", "--default-home", "$PROJECT_MEMORY_HOME"]
startup_timeout_sec = 120

Claude Code:

{
  "mcpServers": {
    "mneme-memory": {
      "type": "stdio",
      "command": "$MCP_COMMAND",
      "args": ["--env-file", "$ENV_FILE", "--default-home", "$PROJECT_MEMORY_HOME"]
    }
  }
}
EOF
  fi

  cat <<'EOF'

Restart Codex and Claude Code after install so MCP configuration reloads.
EOF
}

echo "==> Mneme Memory MCP"
echo "repo: $ROOT"
choose_profile

if ! PYTHON_BIN="$(find_python)"; then
  echo "Python 3.10 or newer is required." >&2
  echo "Install Python 3.10+ or set PYTHON_BIN=/path/to/python3.10." >&2
  exit 1
fi

apply_profile
validate_venv_dir

echo "profile: $SETUP_PROFILE"
echo "install dir: $INSTALL_DIR"
echo "venv dir: $VENV_DIR"
echo "memory home: $MEMORY_HOME"
if [ "$SETUP_PROFILE" = "project" ]; then
  echo "env file: $ENV_FILE"
fi
echo "python: $PYTHON_BIN"
echo "semantic embeddings: $([ "$INSTALL_EMBEDDINGS" = "1" ] && echo enabled || echo disabled)"
echo "PostgreSQL retrieval client: $([ "$INSTALL_POSTGRES" = "1" ] && echo enabled || echo disabled)"

mkdir -p "$INSTALL_DIR"
"$PYTHON_BIN" -m venv --clear "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
EXTRAS=()
[ "$INSTALL_EMBEDDINGS" = "1" ] && EXTRAS+=(embeddings)
[ "$INSTALL_POSTGRES" = "1" ] && EXTRAS+=(postgres)
PACKAGE_SPEC="$ROOT"
if [ "${#EXTRAS[@]}" -gt 0 ]; then
  PACKAGE_SPEC="$ROOT[$(IFS=,; echo "${EXTRAS[*]}")]"
fi
if [ "$EDITABLE_INSTALL" = "1" ]; then
  "$VENV_DIR/bin/python" -m pip install -e "$PACKAGE_SPEC"
else
  "$VENV_DIR/bin/python" -m pip install "$PACKAGE_SPEC"
fi
if [ "$INSTALL_EMBEDDINGS" = "1" ]; then
  run_optional \
    "Preparing pinned local embedding model" \
    "$VENV_DIR/bin/mneme-memory" embeddings prepare
fi

mkdir -p "$MEMORY_HOME/memories"
[ -f "$MEMORY_HOME/memories/USER.md" ] || printf '# USER.md\n\n' > "$MEMORY_HOME/memories/USER.md"
[ -f "$MEMORY_HOME/memories/MEMORY.md" ] || printf '# MEMORY.md\n\n' > "$MEMORY_HOME/memories/MEMORY.md"
chmod 700 "$MEMORY_HOME" "$MEMORY_HOME/memories"
chmod 600 "$MEMORY_HOME/memories/USER.md" "$MEMORY_HOME/memories/MEMORY.md"

echo
install_continuity
echo
configure_clients
echo
"$VENV_DIR/bin/mneme-memory-doctor"

print_manual_config
