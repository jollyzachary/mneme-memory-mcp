# Contributing

Contributions that improve local reliability, privacy, retrieval quality, and
clear documentation are welcome.

## Development setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Before opening a pull request:

```bash
python -m pytest
python -m build
```

## Pull requests

- Keep changes focused and explain the user-visible behavior.
- Add or update tests for storage, migration, scope, or installer changes.
- Preserve SQLite migration compatibility and idempotence.
- Keep the PostgreSQL plane rebuildable from SQLite.
- Preserve the explicit setup-profile confirmation rule in `AGENTS.md`.
- Document new environment variables and reject unrelated project `.env` keys.
- Call out changes that expand filesystem, subprocess, network, or client-config
  authority.

## Fixture hygiene

Use synthetic examples only. Do not copy real memory, transcripts, credentials,
usernames, hostnames, repository secrets, product codenames, or local filesystem
paths into source, tests, screenshots, or issue reports.

Local memory stores, `.env` files, generated working sets, agent briefs, logs,
caches, PostgreSQL secrets, and scratch output must remain untracked.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[SECURITY.md](SECURITY.md).
