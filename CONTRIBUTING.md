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
- Preserve explicit setup-profile selection in the guided installers.
- Document new configuration variables and keep project configuration
  allowlisted.
- Call out changes that expand filesystem, subprocess, network, or client-config
  authority.

## Fixture hygiene

Use synthetic fixtures and examples. Do not include credentials, personal
memory, transcripts, identifiable machine paths, or private host information in
source, tests, screenshots, or issue reports.

Local stores, generated working sets, configuration containing credentials,
logs, caches, database secrets, and scratch output must remain untracked.

## Security reports

Do not open a public issue for a suspected vulnerability. Follow
[SECURITY.md](SECURITY.md).
