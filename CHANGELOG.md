# Changelog

## 0.10.2 - 2026-08-16

- Moves PostgreSQL mirror repair out of memory-search requests and into one
  elected background worker with adaptive retry timing.
- Preserves newer mirror work when an older retry completes.
- Gives pgGraph expansion its own timeout and circuit breaker so graph faults do
  not discard direct lexical or vector matches.
- Falls back to SQLite recall when the local PostgreSQL retrieval service is
  unavailable.
- Creates one verified SQLite backup per day and retains the latest 30 automatic
  snapshots.
- Reports mirror retries, repair leadership, graph state, and PostgreSQL
  availability through Mneme health output.
