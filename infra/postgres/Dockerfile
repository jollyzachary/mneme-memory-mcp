FROM ghcr.io/evokoa/pggraph@sha256:5b7cab9dbbbea72682d4a283bc43328e6ff7a51c3746840380fd021805517e5d AS pggraph

FROM ghcr.io/evokoa/pgcontext@sha256:197150bff2ffcad721f37760654ac20796d26b64a12ee5bbeca41951ab252f9d

ARG PG_MAJOR=17

LABEL org.opencontainers.image.title="Mneme PostgreSQL retrieval plane" \
      org.opencontainers.image.description="PostgreSQL 17 with pgContext 0.2.0 and pgGraph 1.0.0" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0"

RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        postgresql-${PG_MAJOR}-cron \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pggraph \
    /usr/share/postgresql/${PG_MAJOR}/extension/graph* \
    /usr/share/postgresql/${PG_MAJOR}/extension/
COPY --from=pggraph \
    /usr/lib/postgresql/${PG_MAJOR}/lib/graph.so \
    /usr/lib/postgresql/${PG_MAJOR}/lib/graph.so

COPY initdb/ /docker-entrypoint-initdb.d/

CMD ["postgres", "-c", "shared_preload_libraries=pg_cron,graph", "-c", "cron.database_name=mneme", "-c", "pgcontext.hnsw_ef_search=64", "-c", "pgcontext.hnsw_candidate_budget=128", "-c", "pgcontext.hnsw_recall_threshold=0.95", "-c", "graph.allow_rls_tables=on", "-c", "graph.tenant_setting=mneme.graph_scope", "-c", "graph.default_max_depth=4", "-c", "graph.max_nodes=2000", "-c", "graph.max_frontier=1000"]
