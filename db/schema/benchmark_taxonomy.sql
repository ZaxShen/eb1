-- Benchmark-only taxonomy tables — stores ONLY benchmark-discovered entries.
-- Reads use UNION ALL with prod tables (eb1_taxonomy_*) to get the full
-- superset. No FK to benchmark topics — parent topic may live in prod.

CREATE TABLE IF NOT EXISTS eb1_benchmark_taxonomy_topics (
  slug             TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  type             TEXT NOT NULL CHECK (type IN ('user', 'bot')),
  confirmed_by     TEXT,
  confirmed_at     TIMESTAMPTZ,
  created_by       TEXT,
  updated_by       TEXT,
  group_id         INTEGER REFERENCES eb1_benchmark_groups(id),
  benchmark_run_id INTEGER REFERENCES eb1_benchmark_runs(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_benchmark_topics_type
  ON eb1_benchmark_taxonomy_topics(type);

CREATE INDEX IF NOT EXISTS idx_benchmark_topics_run
  ON eb1_benchmark_taxonomy_topics(benchmark_run_id)
  WHERE benchmark_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS eb1_benchmark_taxonomy_subtopics (
  slug             TEXT NOT NULL,
  topic_slug       TEXT NOT NULL,
  name             TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  confirmed_by     TEXT,
  confirmed_at     TIMESTAMPTZ,
  created_by       TEXT,
  updated_by       TEXT,
  group_id         INTEGER REFERENCES eb1_benchmark_groups(id),
  benchmark_run_id INTEGER REFERENCES eb1_benchmark_runs(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (topic_slug, slug),
  UNIQUE (slug)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_subtopics_run
  ON eb1_benchmark_taxonomy_subtopics(benchmark_run_id)
  WHERE benchmark_run_id IS NOT NULL;
