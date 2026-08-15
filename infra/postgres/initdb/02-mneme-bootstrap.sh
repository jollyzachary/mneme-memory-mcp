#!/usr/bin/env bash
set -euo pipefail

app_user="${MNEME_APP_USER:-mneme_app}"
app_password_file="${MNEME_APP_PASSWORD_FILE:-/run/secrets/app_password}"

if [ ! -s "$app_password_file" ]; then
  echo "Mneme app password file is missing or empty" >&2
  exit 1
fi

app_password="$(tr -d '\r\n' < "$app_password_file")"

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=mneme_app_user="$app_user" \
  --set=mneme_app_password="$app_password" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS graph;
CREATE EXTENSION IF NOT EXISTS pgcontext;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mneme_runtime') THEN
        CREATE ROLE mneme_runtime NOLOGIN;
    END IF;
END
$roles$;

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'mneme_app_user', :'mneme_app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'mneme_app_user')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'mneme_app_user', :'mneme_app_password')
\gexec
SELECT format('GRANT mneme_runtime TO %I', :'mneme_app_user')
\gexec

CREATE SCHEMA IF NOT EXISTS mneme;

CREATE TABLE IF NOT EXISTS mneme.facts (
    fact_id BIGINT PRIMARY KEY,
    id BIGINT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    tags TEXT NOT NULL DEFAULT '',
    trust_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    importance DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    retrieval_count INTEGER NOT NULL DEFAULT 0,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    unhelpful_count INTEGER NOT NULL DEFAULT 0,
    last_retrieved_at TIMESTAMPTZ,
    state TEXT NOT NULL DEFAULT 'trusted'
        CHECK (state IN ('trusted', 'candidate', 'quarantined', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    memory_type TEXT NOT NULL DEFAULT 'semantic',
    scope TEXT NOT NULL DEFAULT 'global'
        CHECK (scope IN ('global', 'project', 'agent-private', 'handoff')),
    key TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    supersedes_id BIGINT,
    superseded_by BIGINT,
    source TEXT NOT NULL DEFAULT 'manual',
    provenance TEXT NOT NULL DEFAULT '',
    embedding pgcontext.vector(384),
    embedding_model TEXT,
    is_current BOOLEAN NOT NULL DEFAULT true,
    search_document TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(content, '')), 'A') ||
        setweight(
            to_tsvector(
                'simple',
                coalesce(key, '') || ' ' || coalesce(tags, '') || ' ' ||
                coalesce(category, '') || ' ' || coalesce(memory_type, '')
            ),
            'B'
        )
    ) STORED,
    CHECK (id = fact_id)
);

CREATE TABLE IF NOT EXISTS mneme.entities (
    entity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope TEXT NOT NULL,
    kind TEXT NOT NULL,
    canonical TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope, kind, canonical)
);

CREATE TABLE IF NOT EXISTS mneme.fact_entities (
    bridge_id TEXT PRIMARY KEY,
    fact_id BIGINT NOT NULL REFERENCES mneme.facts(fact_id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL REFERENCES mneme.entities(entity_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0 CHECK (weight > 0),
    UNIQUE (fact_id, entity_id, relation_type)
);

CREATE TABLE IF NOT EXISTS mneme.memory_edges (
    edge_id TEXT PRIMARY KEY,
    src_fact_id BIGINT NOT NULL REFERENCES mneme.facts(fact_id) ON DELETE CASCADE,
    dst_fact_id BIGINT NOT NULL REFERENCES mneme.facts(fact_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0 CHECK (weight > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    evidence TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (src_fact_id <> dst_fact_id),
    UNIQUE (src_fact_id, dst_fact_id, relation_type)
);

CREATE OR REPLACE FUNCTION mneme.enforce_edge_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    src_scope TEXT;
    dst_scope TEXT;
BEGIN
    SELECT scope INTO src_scope FROM mneme.facts WHERE fact_id = NEW.src_fact_id;
    SELECT scope INTO dst_scope FROM mneme.facts WHERE fact_id = NEW.dst_fact_id;
    IF src_scope IS NULL OR dst_scope IS NULL THEN
        RAISE EXCEPTION 'memory edge references a missing fact';
    END IF;
    IF src_scope <> dst_scope OR NEW.scope <> src_scope THEN
        RAISE EXCEPTION 'memory edges cannot cross Mneme scopes';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS memory_edges_scope_guard ON mneme.memory_edges;
CREATE TRIGGER memory_edges_scope_guard
BEFORE INSERT OR UPDATE ON mneme.memory_edges
FOR EACH ROW EXECUTE FUNCTION mneme.enforce_edge_scope();

CREATE INDEX IF NOT EXISTS facts_scope_current_state_idx
    ON mneme.facts(scope, is_current, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS facts_key_idx ON mneme.facts(scope, key)
    WHERE key <> '';
CREATE INDEX IF NOT EXISTS facts_search_document_idx
    ON mneme.facts USING GIN(search_document);
CREATE INDEX IF NOT EXISTS entities_scope_kind_idx
    ON mneme.entities(scope, kind, canonical);
CREATE INDEX IF NOT EXISTS fact_entities_fact_idx
    ON mneme.fact_entities(fact_id);
CREATE INDEX IF NOT EXISTS fact_entities_entity_idx
    ON mneme.fact_entities(entity_id);
CREATE INDEX IF NOT EXISTS memory_edges_src_idx
    ON mneme.memory_edges(src_fact_id, relation_type);
CREATE INDEX IF NOT EXISTS memory_edges_dst_idx
    ON mneme.memory_edges(dst_fact_id, relation_type);

CREATE INDEX facts_embedding_hnsw
ON mneme.facts USING pgcontext_hnsw (
    embedding pgcontext.vector_hnsw_cosine_ops
)
WHERE embedding IS NOT NULL;

SELECT graph.add_table(
    'mneme.facts'::regclass, 'fact_id',
    ARRAY['category', 'state', 'key', 'memory_type'], 'scope'
);
SELECT graph.add_table(
    'mneme.entities'::regclass, 'entity_id', ARRAY['kind', 'canonical'], 'scope'
);
SELECT graph.add_table(
    'mneme.fact_entities'::regclass, 'bridge_id', ARRAY['relation_type', 'weight'], 'scope'
);
SELECT graph.add_table(
    'mneme.memory_edges'::regclass, 'edge_id',
    ARRAY['relation_type', 'weight', 'source'], 'scope'
);
SELECT graph.add_edge(
    'mneme.facts'::regclass, 'supersedes_id',
    'mneme.facts'::regclass, 'fact_id', 'supersedes', true
);
SELECT graph.add_edge(
    'mneme.fact_entities'::regclass, 'fact_id',
    'mneme.facts'::regclass, 'fact_id', 'describes_fact', true
);
SELECT graph.add_edge(
    'mneme.fact_entities'::regclass, 'entity_id',
    'mneme.entities'::regclass, 'entity_id', 'uses_entity', true
);
SELECT graph.add_edge(
    'mneme.memory_edges'::regclass, 'src_fact_id',
    'mneme.facts'::regclass, 'fact_id', 'edge_source', true
);
SELECT graph.add_edge(
    'mneme.memory_edges'::regclass, 'dst_fact_id',
    'mneme.facts'::regclass, 'fact_id', 'edge_target', true
);

SELECT graph.enable_sync();
SELECT * FROM graph.build();

SELECT cron.schedule(
    'mneme-pggraph-maintenance',
    '*/5 * * * *',
    $$SELECT * FROM graph.run_scheduled_maintenance();$$
)
WHERE NOT EXISTS (
    SELECT 1 FROM cron.job WHERE jobname = 'mneme-pggraph-maintenance'
);

SELECT cron.schedule(
    'mneme-pggraph-sync',
    '* * * * *',
    $$SELECT * FROM graph.apply_sync();$$
)
WHERE NOT EXISTS (
    SELECT 1 FROM cron.job WHERE jobname = 'mneme-pggraph-sync'
);

GRANT CONNECT ON DATABASE mneme TO mneme_runtime;
GRANT USAGE ON SCHEMA mneme, pgcontext, graph TO mneme_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA mneme TO mneme_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA mneme TO mneme_runtime;
GRANT EXECUTE ON FUNCTION
    pgcontext.upsert_points(TEXT, TEXT[]),
    pgcontext.delete_points(TEXT, TEXT[]),
    pgcontext.search(TEXT, pgcontext.vector, TEXT, INTEGER)
TO mneme_runtime;
GRANT EXECUTE ON FUNCTION
    graph.traverse(
        OID, TEXT, INTEGER, TEXT[], TEXT, OID[], JSONB, TEXT, TEXT,
        TEXT, BOOLEAN, BOOLEAN, INTEGER, INTEGER, INTEGER, INTEGER
    )
TO mneme_runtime;

ALTER DEFAULT PRIVILEGES IN SCHEMA mneme
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mneme_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA mneme
    GRANT USAGE, SELECT ON SEQUENCES TO mneme_runtime;

ALTER TABLE mneme.facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE mneme.facts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS facts_visible_scopes ON mneme.facts;
CREATE POLICY facts_visible_scopes
ON mneme.facts FOR SELECT TO mneme_runtime
USING (
    scope = ANY(
        string_to_array(current_setting('mneme.visible_scopes', true), ',')
    )
);
DROP POLICY IF EXISTS facts_insert ON mneme.facts;
CREATE POLICY facts_insert ON mneme.facts
FOR INSERT TO mneme_runtime WITH CHECK (true);
DROP POLICY IF EXISTS facts_update ON mneme.facts;
CREATE POLICY facts_update ON mneme.facts
FOR UPDATE TO mneme_runtime USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS facts_delete ON mneme.facts;
CREATE POLICY facts_delete ON mneme.facts
FOR DELETE TO mneme_runtime USING (true);

-- pgContext authorizes a collection through role membership. Create the
-- collection as the NOLOGIN runtime role so the application can use only this
-- collection without inheriting the PostgreSQL administrator role.
SET SESSION AUTHORIZATION mneme_runtime;
SELECT pgcontext.create_collection('mneme_facts', 'mneme.facts');
SELECT pgcontext.register_vector(
    'mneme_facts', 'embedding', 'embedding', 384, 'cosine'
);
SELECT pgcontext.register_filter_column('mneme_facts', 'scope', 'scope');
SELECT pgcontext.register_filter_column('mneme_facts', 'state', 'state');
SELECT pgcontext.register_filter_column('mneme_facts', 'is_current', 'is_current');
SELECT pgcontext.register_filter_column('mneme_facts', 'memory_type', 'memory_type');
RESET SESSION AUTHORIZATION;
SQL

unset app_password
