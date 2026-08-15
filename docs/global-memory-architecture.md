# Mneme architecture

## Purpose

Mneme is a local memory service for trusted agents. Any
configured MCP-compatible client can use the same durable context. Applications
and individual projects can keep separate, app-owned memory stores when their
data should not enter the machine-wide context.

The default memory home is:

- database: `~/.hermes/memory_store.db`
- generated working sets: `~/.hermes/memories/USER.md` and
  `~/.hermes/memories/MEMORY.md`

No application process, bundle identifier, or application data directory is a
dependency of global Mneme.

## System boundary

```text
Agent 1 ─┐
Agent 2 ─┼── MCP / CLI / hooks ── Global Mneme ── ~/.hermes
Agent 3 ─┘

Local app ────── app-owned memory engine ── application data/<app id>
```

Each agent connects directly to Mneme. No separate agent runtime is required.

## Memory model

Global Mneme stores:

- semantic facts;
- procedural strategies and runbooks;
- resource pointers;
- structured handoffs;
- bounded episodic conversation archives;
- candidate facts distilled from automated capture.

Every durable fact carries:

- scope and type;
- provenance and source;
- trust and importance;
- lifecycle state (`trusted`, `candidate`, `quarantined`, or `rejected`);
- reinforcement, retrieval, helpful, and unhelpful counters;
- supersession lineage;
- timestamps and optional embedding.

Manual and handoff writes are trusted. Automated capture writes are
candidates. Suspected prompt injection is quarantined. Rejected and
quarantined memories never enter normal retrieval or generated working sets.

## Retrieval

Recall is local and hybrid:

1. FTS5 and exact substring matching preserve identifiers, commands, paths,
   and names.
2. Optional local embeddings retrieve paraphrases.
3. Reciprocal Rank Fusion combines lexical and semantic rankings.
4. A bounded quality prior uses trust, importance, reinforcement, helpfulness,
   source quality, and recency.
5. Retrievals are accounted for so frequently useful memories become easier
   to retain during maintenance.

Lexical search remains fully functional if the embedding backend is
unavailable.

## Context policy

`USER.md` and `MEMORY.md` are generated views, not the source of truth.

- Working sets contain trusted, curated facts only.
- Automated capture remains search-only until promoted.
- Transcript capture stores complete-line byte offsets in SQLite, so repeat hooks
  process appended JSONL records instead of rescanning entire sessions.
- Prompt hooks inject a small working set plus relevance-gated facts.
- Context is explicitly labeled as untrusted data, never instructions.
- Token and character budgets bound all injected context.

## Safety and governance

- Storage is local-only.
- SQLite uses WAL, a busy timeout, and restrictive local file permissions.
- Secret-like material is rejected before persistence.
- Prompt-injection-like material is quarantined.
- Automated memories can be reviewed, promoted, or rejected without deleting
  their audit trail.
- Superseded facts remain recoverable and are hidden from current recall.
- Event and episodic tables are bounded by maintenance policy.
- Maintenance is idempotent and reports integrity status.

## MCP contract

The global MCP server exposes:

- summary, briefing, search, list, and current-value resolution;
- remember, update, feedback, review, and lifecycle controls;
- handoff read/write;
- health, maintenance, consolidation, and embedding backfill;
- optional local agent delegation.

Configured agents connect to the same server command and memory home.

## Migration invariants

Upgrades must:

- preserve every existing fact, event, handoff, and episodic entry;
- preserve fact identifiers and supersession links;
- default existing manual facts to `trusted`;
- default existing capture-derived facts to `candidate`;
- leave the pre-upgrade database recoverable;
- never require another application to be running;
- pass integrity, migration-idempotence, retrieval, capture, concurrency, and
  continuity checks before client cutover.
