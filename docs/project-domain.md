# Project Domain Knowledge — eb1

## What eb1 Is

A Python-only research offshoot of the eb1 pipeline, used to produce academic artifacts:

- EB-1A visa evidence packets (USCIS 8 CFR 204.5(h)(3))
- Conference / workshop papers describing the eb1 method
- Internal technical reports

The underlying pipeline is a frozen snapshot of eb1. Code in `pipeline/`, `db/`, `config/`, `tests/` is evidence — it gets read, described, cited; it does not get actively re-developed here. Active pipeline development happens in the parallel `eb1` repo (not accessible from eb1).

## Tech Stack

| Component | Path | Tech |
|---|---|---|
| Pipeline | `pipeline/` | Python 3.13+, openai, pymongo, psycopg3, sentence-transformers, hdbscan, umap |
| Persistence | `db/` | psycopg3 pool (PG writes), pymongo (PROD reads) |
| Config | `config/settings.py` | Pydantic BaseSettings, reads `.env` |
| Tests | `tests/` | pytest, no DB/LLM required for unit tests |

## Directory Layout

```
pipeline/
  __main__.py                  Entry point: uv run python -m pipeline
  main.py                      CLI parsing, step orchestration, benchmark adapter
  config/
    loader.py                  TOML → typed dataclasses; taxonomy management
    analyzer.toml              LLM model, concurrency, routing knobs
    benchmark.toml             Multi-LLM comparison runs
    clustering.toml            Offline HDBSCAN clustering
  segmentation/
    segmenter.py               Orchestrator: LLM calls + segment building
    preprocessing.py           Message cleaning, slug normalization
    windowing.py               Pre-segmentation chunking, flat-history build
    bot_processor.py           Bot-only segment handling, template matching
    deterministic_rules.py     P1 (first-segment skip) + P4 (scheduling rules)
    subtopic_validator.py      P2 (hallucinated subtopic remapping)
    pool_taxonomy.py           P3 (pool-specific taxonomy filtering)
  templates/classifier.py      LLM-classify PROD message templates
  graders/segmentation_graders.py    8 deterministic graders (G0.3–G0.11, G1.2, G1.4)
  sampling/signal_extractor.py  TP/FP signal extraction from matchings
  evaluation/
    evaluator.py               Quality metrics
    benchmark_eval.py          Benchmark vs GT (Hungarian + F1 + Unified Score)
  quality/offline.py           Embed → UMAP → HDBSCAN
  prompts/analyzer/            Versioned LLM prompts (eb1_prompt_user_v3.md, eb1_prompt_bot_v1.md)

db/
  client.py                    MongoDB client (PROD read-only)
  pg.py                        PostgreSQL connection pool
  repositories/                Typed repos — one per PG table
    base.py                    BaseRepository (fetch, execute, count)
    segments.py                sms_chat_segments
    benchmark.py               eb1_benchmark_raw
    benchmark_groups.py        eb1_benchmark_groups
    benchmark_runs.py          eb1_benchmark_runs (with unified score persistence)
    benchmark_matches.py       eb1_benchmark_matches
    benchmark_taxonomy.py      Per-benchmark taxonomy
    pipeline_config.py         eb1_pipeline_configs
    pipeline_logs.py           eb1_pipeline_logs
    taxonomy.py                sms_chat_taxonomy (user + bot types)
    signals.py                 matching_signals
    templates.py               eb1_template_mappings
  schema/                      SQL migrations (idempotent ALTER TABLE scripts)

tests/                         ~300 unit tests (no DB/LLM required)
config/settings.py             Pydantic Settings (loads .env)
docs/                          Architecture docs, ERD, benchmark reports, EB-1 source material
  papers/                        Academic outputs (drafts, EB-1 exhibits, refs.bib) — academic agents only
  notion/                        Notion-exported working docs
  architecture/                  Pipeline flowcharts
  erd.md                         PROD schema ERD
  GRADERS.md                     Grader specifications
  user_taxonomy.md               Taxonomy reference
  eb1_BENEFITS.md                Seed material for papers/EB-1 exhibits
reports/                        Benchmark evaluation logs (>30 historical runs)
bro/                            Workflow files (GOALS, DISCUSSION, BLUEPRINT, EXECUTION, tasks, ACADEMIC)
```

## Pipeline Architecture

Four-step flow, driven by `pipeline/__main__.py`:

```
signal → segment → validate → evaluate
```

### `segment` — Analyzer (core of eb1)

Single-node LLM orchestration in `pipeline/segmentation/segmenter.py`. One LLM call per user-window does segmentation + summarization + topic/subtopic classification. v6 deterministic bypasses reduce LLM calls and hallucinations:

- **P1** (first-segment skip): first automated chunk → `onboarding/welcome`, no LLM.
- **P2** (subtopic validation): post-LLM; remaps hallucinated subtopics to closest existing via string similarity + variant detection.
- **P3** (pool-specific taxonomy): filters taxonomy before prompt assembly based on user's pool (wednesday, yik-yak).
- **P4** (scheduling rules): bot-only chunks with scheduling keywords → first = `availability_request`, rest = `availability_reminder`, no LLM.

Expected combined impact: subtopic weighted F1 **0.62 → 0.97**, **−55% LLM calls** on backfill.

### `validate` — Graders

`pipeline/graders/segmentation_graders.py` defines deterministic checks:
G0.3 coverage, G0.7 pre-seg completeness, G0.8 non-user uniqueness, G0.9 reviewed integrity, G0.10 topic completeness, G0.11 confidence range, G1.2 single-message segments, G1.4 temporal contiguity.

### `evaluate` — Benchmark Evaluation

`pipeline/evaluation/benchmark_eval.py` compares model runs against human GT:

- **Matching** — Hungarian algorithm over `combined = 0.7×message_jaccard + 0.3×temporal_iou`, threshold 0.3.
- **F1** — per-class TP/FP/FN → precision, recall, F1. Unmatched GT count as FN.
- **Unified Score** — single 0–1 metric: `q = jaccard × topic × (0.5 + 0.5 × sub)`, `score = Σq / max(GT, model)`. Symmetrically penalises under- and over-segmentation.

## Database (PostgreSQL)

Output tables (pipeline writes):

| Table | Purpose |
|---|---|
| `sms_chat_segments` | Primary pipeline output — segmented + classified messages |
| `sms_chat_taxonomy` → `eb1_taxonomy_topics` + `eb1_taxonomy_subtopics` | Topic definitions (user + bot types) |
| `eb1_template_mappings` | LLM-classified PROD templates |
| `eb1_pipeline_configs` | Model + prompt config per run |
| `eb1_pipeline_logs` | Remap logs and operational logs |
| `eb1_benchmark_groups` | Benchmark group metadata |
| `eb1_benchmark_runs` | Aggregated benchmark scores + leaderboard with rank |
| `eb1_benchmark_raw` | Per-segment benchmark output |
| `eb1_benchmark_matches` | GT ↔ model Jaccard match rows |
| `matching_signals` | TP/FP signals per matching (read-only for pipeline) |

PROD tables (MongoDB, read-only): `sms_chats`, `sms_chat_messages`, `matchings`, `message_templates`, `users`, `user_profiles`.

## Project Invariants

1. **`uv` only for Python** — never `pip`.
2. **Parameterized SQL** — `%s` placeholders with psycopg; never f-string interpolation.
3. **Connection pool** — `with pool.connection() as conn:` for writes.
4. **JSONB values** — wrap dicts in `psycopg.types.json.Json()` for `%s` placeholders.
5. **Config over code** — pipeline behavior driven by TOML files in `pipeline/config/`.
6. **Idempotent steps** — sentinel fields (`classified_at`, `reviewed_by`) let steps re-run safely.
7. **Fail fast at boundaries** — validate connections, config, schema at startup.
8. **Separate read and write** — `get_input_db()` (PROD) vs `get_db()` (local).
9. **PROD MongoDB is read-only** — every write goes to PostgreSQL.
10. **`sms_chat_segments` is the single source of truth** — every other artifact derives from it.
11. **No silent error swallowing** — every `except` logs diagnostics (input length, first 500 chars, error message).

## CLI Commands

```bash
# Full pipeline
uv run python -m pipeline

# Individual steps
uv run python -m pipeline --step signal
uv run python -m pipeline --step segment
uv run python -m pipeline --step validate
uv run python -m pipeline --step evaluate

# Benchmark
uv run python -m pipeline --benchmark <name>
uv run python -m pipeline --benchmark-eval --group-id <group>
uv run python -m pipeline --classify-templates
uv run python -m pipeline --offline-quality
```

## Verification Commands

```bash
uv run ruff check pipeline/ db/ tests/
uv run pytest tests/ -v
```

## Environment Variables (`.env`)

| Var | Required | Purpose |
|---|---|---|
| `POSTGRES_DSN` | Yes | PostgreSQL connection for pipeline writes |
| `AI_GATEWAY_API_KEY` | Yes | Vercel AI Gateway — all LLM providers behind one key |
| `MONGODB_PROD_ANALYTICS_URI` | Yes | PROD MongoDB Atlas (read-only) |
| `MONGODB_PROD_ANALYTICS_DB_NAME` | Yes | PROD database name |
| `MONGODB_OUTPUT_URI` | No | Legacy MongoDB output (signal extraction only) |
| `MONGODB_OUTPUT_DB_NAME` | No | Legacy output database |

## Configuration Hotspots

| File | Key settings |
|---|---|
| `pipeline/config/analyzer.toml` | LLM model, temperature, concurrency, bot_gap_seconds, user_window_days, template_match_threshold |
| `pipeline/config/benchmark.toml` | Multi-model runs (model, prompt, temperature, base_url) |
| `pipeline/config/clustering.toml` | Embedder, UMAP, HDBSCAN params |
