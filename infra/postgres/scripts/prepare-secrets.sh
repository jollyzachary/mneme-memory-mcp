#!/usr/bin/env bash
set -euo pipefail

secret_dir="${MNEME_POSTGRES_SECRET_DIR:-$HOME/.local/share/mneme-memory-mcp/postgres/secrets}"
umask 077
mkdir -p "$secret_dir"

generate_secret() {
  local target="$1"
  if [ -s "$target" ]; then
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 36 | tr -d '\n' >"$target"
  else
    python3 -c 'import secrets; print(secrets.token_urlsafe(36), end="")' >"$target"
  fi
  chmod 600 "$target"
}

generate_secret "$secret_dir/admin_password"
generate_secret "$secret_dir/app_password"

printf 'Mneme PostgreSQL secrets are ready in %s\n' "$secret_dir"
