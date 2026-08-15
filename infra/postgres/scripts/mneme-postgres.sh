#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd "$script_dir/.." && pwd)"
compose_file="$infra_dir/compose.yaml"
command="${1:-status}"

case "$command" in
  prepare)
    bash "$script_dir/prepare-secrets.sh"
    ;;
  start)
    bash "$script_dir/prepare-secrets.sh"
    docker compose -f "$compose_file" up -d --build
    ;;
  stop)
    docker compose -f "$compose_file" stop
    ;;
  status)
    docker compose -f "$compose_file" ps
    ;;
  logs)
    docker compose -f "$compose_file" logs --tail=200 postgres
    ;;
  *)
    echo "usage: $0 prepare|start|stop|status|logs" >&2
    exit 2
    ;;
esac
