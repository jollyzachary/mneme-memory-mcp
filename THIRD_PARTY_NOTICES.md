# Third-Party Notices

Mneme Memory MCP is licensed under the MIT License. It interoperates with or can
optionally install software maintained by other projects. Each dependency
remains subject to its own license and terms.

## Python dependencies

- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk) — MIT
- [sentence-transformers](https://github.com/huggingface/sentence-transformers) — Apache-2.0
- [NumPy](https://github.com/numpy/numpy) — primarily BSD-3-Clause; source and binary distributions include additional third-party notices
- [Psycopg](https://github.com/psycopg/psycopg) — LGPL-3.0-or-later

Development and packaging dependencies are declared in `pyproject.toml` and
retain their upstream licenses.

## Optional PostgreSQL image components

- [PostgreSQL](https://www.postgresql.org/) — PostgreSQL License
- [pg_cron](https://github.com/citusdata/pg_cron) — PostgreSQL License
- [pgContext](https://github.com/evokoa/pgcontext) — Apache-2.0
- [pgGraph](https://github.com/evokoa/pggraph) — Apache-2.0

The repository references pinned container-image digests but does not vendor
the upstream source trees. Review the corresponding image and release notices
before redistributing a derived container image.

## Optional integrations

Hermes Agent, the OpenAI Claude-to-Codex plugin, Ponytail, Claude Code, and
Codex are separate projects. The Mneme installer can interact with some of them
only after explicit user selection. They are not relicensed or redistributed by
this repository.
