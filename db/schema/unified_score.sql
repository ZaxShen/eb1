-- Unified score columns for eb1_benchmark_runs
-- See pipeline/evaluation/benchmark_eval.py :: _compute_unified_score
-- q = jaccard × topic × (0.5 + 0.5 × sub); score = Σq / max(GT, model)

ALTER TABLE eb1_benchmark_runs
    ADD COLUMN IF NOT EXISTS unified_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS unified_topic_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS unified_sub_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ue_unified_score DOUBLE PRECISION;
