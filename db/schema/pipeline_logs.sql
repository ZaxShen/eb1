-- Pipeline event logs — structured audit trail for pipeline events.
-- Use event_type to filter (e.g. 'taxonomy_remap', 'llm_fallback').
-- Payload is JSONB for flexible, queryable event data.

-- Production logs
CREATE TABLE IF NOT EXISTS eb1_pipeline_logs (
    id              SERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    user_id         TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    config_id       INTEGER REFERENCES eb1_pipeline_configs(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_logs_event_type
    ON eb1_pipeline_logs(event_type);

CREATE INDEX IF NOT EXISTS idx_pipeline_logs_created
    ON eb1_pipeline_logs(created_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_logs_user
    ON eb1_pipeline_logs(user_id)
    WHERE user_id IS NOT NULL;

-- Benchmark logs — same schema plus provenance
CREATE TABLE IF NOT EXISTS eb1_benchmark_pipeline_logs (
    id              SERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    user_id         TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    config_id       INTEGER REFERENCES eb1_pipeline_configs(id),
    group_id        INTEGER REFERENCES eb1_benchmark_groups(id),
    benchmark_run_id INTEGER REFERENCES eb1_benchmark_runs(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_benchmark_logs_event_type
    ON eb1_benchmark_pipeline_logs(event_type);

CREATE INDEX IF NOT EXISTS idx_benchmark_logs_run
    ON eb1_benchmark_pipeline_logs(benchmark_run_id);

CREATE INDEX IF NOT EXISTS idx_benchmark_logs_created
    ON eb1_benchmark_pipeline_logs(created_at);
