# PostgreSQL retrieval plane

Mneme can add a local PostgreSQL 17 retrieval service beside its SQLite memory journal. The service combines pgContext 0.2.0 for filtered vector search with pgGraph 1.0.0 for bounded relationship traversal. Both extensions come from Evokoa's open-source releases.

SQLite remains authoritative for fact review, trust state, supersession, audit events, and the generated Markdown working set. PostgreSQL stores a rebuildable mirror. A failed container cannot corrupt or strand the original memory.

## Retrieval path

A PostgreSQL search runs four candidate branches:

1. PostgreSQL full-text search over content, keys, tags, categories, and memory types.
2. Exact substring and symbol matching.
3. Filtered pgContext HNSW search with the existing pinned MiniLM embeddings.
4. Bounded two-hop pgGraph expansion from the best direct matches. This
   enrichment lane has its own short timeout and savepoint; an unhealthy or
   rebuilding graph cannot discard valid lexical, exact, or pgContext results.
   Three consecutive failures open a 30-second process-local circuit breaker
   so repeated chat requests stay fast while database maintenance recovers.
   `memory_health` exposes graph attempts, successes, failures, recent and
   moving-average latency, the last error, and circuit state.

Weighted Reciprocal Rank Fusion combines the branches. Mneme then loads the selected facts from SQLite and applies its existing trust, importance, feedback, source, recency, and supersession rules. Project searches can see global and project facts; the adapter searches each vector tenant separately and passes the same tenant to pgGraph.

Graph traversal uses explicit relationships, supersession links, stable keys, and tags. Mneme does not infer open-ended relationships from prose during writes. That choice keeps the graph small enough to inspect and avoids turning embedding similarity into a false claim that two facts are related.

## Local service

The Compose service binds only to `127.0.0.1:55433`. It uses a named Docker volume and reads separate admin and application passwords from owner-only files under:

```text
~/.local/share/mneme-memory-mcp/postgres/secrets
```

The image is built from pinned multi-architecture release digests:

- `ghcr.io/evokoa/pgcontext:pg17-v0.2.0`
- `ghcr.io/evokoa/pggraph:1.0.0`

The wrapper does not include a command that deletes the Docker volume.

## Install and stage

For a managed global install, include the PostgreSQL retrieval client:

```bash
./scripts/install.sh --profile global --profile-confirmed --postgres-retrieval
```

For development installs, install both local retrieval extras:

```bash
python -m pip install '.[embeddings,postgres]'
```

Prepare secrets and start the service:

```bash
bash infra/postgres/scripts/mneme-postgres.sh prepare
bash infra/postgres/scripts/mneme-postgres.sh start
```

The setup creates the database, app role, pgContext collection, graph registration, indexes, scope policies, and scheduled pgGraph maintenance.

Inspect the SQLite copy plan without writing to PostgreSQL:

```bash
python scripts/migrate_sqlite_to_postgres.py
```

Apply the copy after reviewing the counts:

```bash
python scripts/migrate_sqlite_to_postgres.py --apply --skip-graph-rebuild
```

The Docker service runs pgGraph's adaptive scheduled maintenance every minute
as the internal database administrator. That single non-overlapping job decides
whether to apply sync, compact, vacuum, or repair; a second unconditional sync
job must not run beside it. The MCP application role never receives
graph-administrator privileges.

After a bulk migration, rebuild the derived graph once from the container's
administrator session. Do not leave a full-corpus migration behind
`--skip-graph-rebuild`: its trigger log can exceed the bounded incremental
mutation buffer.

```bash
docker exec mneme-postgres psql -U mneme_admin -d mneme \
  -c "SELECT * FROM graph.build();"
```

The migration opens SQLite in read-only mode and copies facts, embeddings, and
explicit relationships. It does not modify or delete the SQLite file.

## Cutover modes

Set these variables in the environment used to launch the Mneme MCP server:

```env
MNEME_RETRIEVAL_BACKEND=postgres
MNEME_POSTGRES_HOST=127.0.0.1
MNEME_POSTGRES_PORT=55433
MNEME_POSTGRES_DATABASE=mneme
MNEME_POSTGRES_USER=mneme_app
MNEME_POSTGRES_PASSWORD_FILE=~/.local/share/mneme-memory-mcp/postgres/secrets/app_password
MNEME_POSTGRES_CONNECT_TIMEOUT=1
MNEME_POSTGRES_REQUIRED=0
MNEME_GRAPH_SYNC_ON_WRITE=0
```

The available modes are:

| Mode | Behavior |
| --- | --- |
| `sqlite` | Existing FTS5, exact, and local vector retrieval. PostgreSQL receives no live writes. |
| `dual` | PostgreSQL and SQLite both retrieve candidates. Mneme fuses the scores and mirrors new writes to PostgreSQL. |
| `postgres` | PostgreSQL retrieves candidates. SQLite still applies governance and ranking. |

Start with `dual`. Move to `postgres` after comparing result quality and confirming that mirror counts stay aligned. Keep `MNEME_POSTGRES_REQUIRED=0` for normal interactive use so SQLite provides emergency recall if the derived service stops. Set it to `1` only for diagnostics that intentionally require a hard PostgreSQL failure.

For a machine-global installation, put these variables in the owner-only file
`~/.config/mneme-memory/env`. Every process opening the canonical `~/.hermes`
store loads that file, including capture hooks and direct CLI commands. Project
stores do not inherit it.

The global Farynth installation uses `postgres`: normal retrieval comes only
from PostgreSQL, pgContext, and pgGraph. SQLite remains the write journal,
governance layer, synchronization source, and emergency fallback.
An unavailable local PostgreSQL service is detected within one second; the
process then opens a 15-second availability circuit so subsequent chat recall
uses the emergency path immediately instead of repeating connection waits.

## Relationships

Agents and users can add a typed relationship through MCP:

```text
memory_link(src_fact_id, dst_fact_id, relation_type, weight, evidence)
```

The CLI exposes the same operation:

```bash
mneme-memory link 41 57 depends-on --evidence "Decision 57 assumes tool setup 41"
```

Mneme stores the relationship in SQLite first and mirrors it to PostgreSQL. Both facts must share a scope. pgGraph traversal has depth, row, node, and frontier limits.

The facts table uses forced PostgreSQL RLS. pgGraph is explicitly allowed to
index its topology coordinates, while every returned fact is still joined and
hydrated through the RLS-protected facts table and then rechecked by SQLite's
scope and governance filters. Cross-scope edges are rejected.

Use `memory_links` to inspect relationships and `memory_unlink` to remove one without changing either fact.

## Interrupted writes

Mneme records PostgreSQL mirror work in a SQLite outbox before it attempts the
derived write. On macOS and Linux, long-lived MCP processes elect one repair
leader with a blocking kernel file lock: non-leaders consume no polling CPU and
the operating system releases leadership immediately after a crash. A
crash-expiring SQLite lease provides health visibility and the cross-platform
fallback. The leader wakes immediately for same-process work, follows queued
retry deadlines, and sleeps up to 15 seconds while idle; exponential retry
backoff is capped at five minutes.
Search never waits for mirror repair, and a failed mirror cannot turn an
already-durable SQLite write into a user-visible write error. `memory_health`
and `mneme-memory-doctor` report pending and retrying counts. Revision-checked
outbox acknowledgements preserve a newer update when multiple agents write the
same fact while an older mirror attempt is in flight. This covers short
Docker restarts without blocking a durable write or requiring an immediate
full copy.

The elected worker also creates one verified online SQLite snapshot per day
under `~/.hermes/backups/mneme-auto-*.db`. It publishes a snapshot only after
`PRAGMA integrity_check` succeeds and retains the newest 30 automatic
snapshots. Retention applies only to the `mneme-auto-` namespace; existing
manual and migration backups are never touched.

## Rollback

Before a migration, make a consistent point-in-time backup and verify it:

```bash
mkdir -p ~/.local/share/mneme-memory-mcp/backups
chmod 700 ~/.local/share/mneme-memory-mcp/backups
sqlite3 ~/.hermes/memory_store.db \
  ".backup '$HOME/.local/share/mneme-memory-mcp/backups/memory_store.db'"
chmod 600 ~/.local/share/mneme-memory-mcp/backups/memory_store.db
sqlite3 ~/.local/share/mneme-memory-mcp/backups/memory_store.db \
  'PRAGMA integrity_check;'
```

Set `MNEME_RETRIEVAL_BACKEND=sqlite` and restart the MCP server. The existing SQLite store remains complete throughout staging and cutover. Stopping the container also leaves its named volume intact:

```bash
bash infra/postgres/scripts/mneme-postgres.sh stop
```

Do not use `docker compose down -v` unless you intend to delete the derived PostgreSQL copy.
