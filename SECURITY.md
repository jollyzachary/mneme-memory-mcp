# Security Policy

Mneme stores private local context and can be connected to powerful AI clients.
Security reports are taken seriously.

## Supported version

Security fixes target the latest revision on `main`. This project is currently
pre-1.0; older revisions may not receive backports.

## Reporting a vulnerability

Do not disclose a suspected vulnerability in a public issue. Use GitHub's
private vulnerability-reporting flow when it is available for this repository,
or contact the repository owner privately through the linked GitHub profile.

Include:

- the affected commit or version;
- operating system and Python version;
- the relevant setup profile and retrieval backend;
- minimal reproduction steps;
- expected and observed behavior;
- potential confidentiality, integrity, or availability impact.

Never include real credentials, memory contents, transcripts, local database
files, or private filesystem paths. Use synthetic data in reproductions.

## Deployment boundary

The default MCP server uses local stdio transport and assumes a single user with
trusted local clients. Scope labels organize recall but are not a multi-user
authorization system. Use separate memory homes and server registrations when
clients should not share authority.

The optional conversation-capture and local agent-bridge features expand the
data and execution boundary. The bridge is disabled by default and should be
enabled only with an explicit contained workspace root.

## Sensitive local files

The following must never be committed or attached to an issue:

- `.env` files;
- `memory_store.db`, WAL, or backup files;
- generated `USER.md` or `MEMORY.md` files containing real memory;
- PostgreSQL password files or volumes;
- Claude, Codex, or Hermes transcripts;
- logs, crash dumps, or command output containing local context.
