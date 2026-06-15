# eb1 — Matchmaking Chat Analysis Pipeline

## Overview

Analysis pipeline for Acme's matchmaking chat data. Reads user conversations and match outcomes from PROD MongoDB Atlas, segments chat histories by topic via LLM, and stores structured results in PostgreSQL.

| Part | Directory | Description |
|------|-----------|-------------|
| 1 | `pipeline/` | Analyzer pipeline: signal extraction, LLM segmentation, grading, evaluation, benchmarking |
| 2 | `db/`       | PostgreSQL repositories + MongoDB read-only client |
| 3 | `config/`   | Global settings — loads `.env` for DB URIs and API keys |
| 4 | `docs/`     | Schema reference (ERD), graders, taxonomy docs, benchmark results |

### Data Flow

```
PROD MongoDB (read-only)  →  Pipeline (LLM + graders)  →  PostgreSQL (writes)
   sms_chats                    segmentation                 sms_chat_segments
   sms_chat_messages            classification               eb1_taxonomy_topics
   matchings                    signal extraction             eb1_taxonomy_subtopics
   message_templates            template classification       eb1_template_mappings
                                benchmarking                 eb1_pipeline_configs
                                                             eb1_benchmark_groups
                                                             eb1_benchmark_runs
                                                             eb1_benchmark_raw
                                                             eb1_benchmark_matches
```

---

## First-Time Setup

```bash
# 1. Copy environment template and fill in your keys
cp .env.example .env

# 2. Install dependencies (creates .venv/ automatically)
uv sync --dev

# 3. Configure .env with:
#    - POSTGRES_DSN (required — pipeline writes here)
#    - MongoDB Atlas URIs (PROD read-only)
#    - AI_GATEWAY_API_KEY (LLM access)
#    See .env.example for all required variables.
```

---

## How to Run

### Full pipeline (all steps)

```bash
uv run python -m pipeline
```

### Individual steps

```bash
uv run python -m pipeline --step signal     # Extract TP/FP signals from PROD matchings
uv run python -m pipeline --step segment    # LLM Analyzer: segment + classify chat histories
uv run python -m pipeline --step validate   # Deterministic graders (G0.3, G0.7–G0.11, G1.2, G1.4)
uv run python -m pipeline --step evaluate   # Quality metrics (read-only)
```

### Options

```bash
uv run python -m pipeline --limit 10        # Process only the first N users (fast testing)
uv run python -m pipeline --force            # Re-segment users already processed
uv run python -m pipeline --relabel          # Re-classify existing segments without re-segmenting
```

### Benchmark mode

Run the Analyzer across multiple LLMs for side-by-side comparison.
Configure models in `pipeline/config/benchmark.toml`.

```bash
uv run python -m pipeline --benchmark my_bench                          # Run all configured models
uv run python -m pipeline --benchmark my_bench --group-id experiment-v1  # Custom group ID
uv run python -m pipeline --benchmark my_bench --cluster                # Also run HDBSCAN after each model
uv run python -m pipeline --benchmark my_bench --rerun-user <user_id>   # Re-segment one user
```

`--group-id` overrides `group_id` in `benchmark.toml`. If omitted and the toml has no `group_id`, defaults to `bench-YYYY-MM-DD`.

### Benchmark evaluation

Compare benchmark runs against human-verified ground truth. Results are persisted to three PG tiers:

| Tier | Table | What |
|------|-------|------|
| 1 | `eb1_benchmark_raw` | Raw per-segment LLM output |
| 2 | `eb1_benchmark_matches` | Jaccard match results (GT vs model) |
| 3 | `eb1_benchmark_runs` | Aggregated scores + leaderboard with rank |

```bash
uv run python -m pipeline --benchmark-eval                              # Evaluate all run IDs
uv run python -m pipeline --benchmark-eval --group-id bench-2026-03-28  # Evaluate a specific group
```

### Template classification

Classify PROD message templates against the taxonomy. One-time setup — the segmenter uses these to enrich bot-only segments without an LLM call.

```bash
uv run python -m pipeline --classify-templates
```

### Offline quality layer

Periodic embedding + HDBSCAN pass — not part of the regular pipeline.

```bash
uv run python -m pipeline --offline-quality
```

---

## Message Coverage Guarantee

The pipeline enforces **zero tolerance for message loss** through a chain of hard invariants:

```
1. Fetch        — Deterministic MongoDB query (all user-facing + boundary messages)
2. Pre-segment  — Every message placed in exactly one chunk (algorithmic guarantee)
3. LLM parse    — LLM may skip messages, but...
4. Orphan rescue — All LLM-skipped messages appended to nearest segment
5. Dedup        — Non-user duplicates removed; messages kept in best-scored segment
6. HARD BLOCK   — Pre-write coverage check: raises ValueError if ANY message missing
7. Write        — Segments committed to PostgreSQL
8. Grader G0.3  — Post-hoc validation confirms coverage (soft check, <5% threshold)
```

The pre-write invariant (step 6) in `_process_one` compares all processed message IDs against the union of segment `chat_messages`. If any message is absent, the pipeline **aborts for that user** before writing — no silent data loss is possible.

---

## Architecture

### Storage

| Store | Role | Access |
|-------|------|--------|
| **PROD MongoDB** | Source data (chats, messages, matchings, templates) | Read-only |
| **PostgreSQL** | Pipeline output (segments, taxonomy, signals, template mappings, benchmarks) | Read-write |

PostgreSQL handles ACID guarantees, connection pooling (`psycopg_pool`), and transactional writes. The repository layer (`db/repositories/`) provides typed access with parameterized queries and column-name allowlists to prevent SQL injection.

### Segmenter Decomposition

The segmenter is split into focused modules:

| Module | Responsibility |
|--------|---------------|
| `segmenter.py` | Orchestration, LLM calls, segment building, taxonomy entry |
| `preprocessing.py` | Message cleaning, slug normalization, reaction detection |
| `windowing.py` | Message windowing, pre-segmentation into chunks, context building |
| `bot_processor.py` | Bot-only segment classification, template matching |

### Taxonomy System

Topic/subtopic definitions are stored in PostgreSQL (`sms_chat_taxonomy`) with two types:
- **User taxonomy** — for user-engaged segments (human conversations)
- **Bot taxonomy** — for bot-only segments (automated messages)

Module-level dicts (`INITIAL_TAXONOMY`, `KNOWN_SUBTOPICS`, etc.) are populated from PG at startup and refreshed between segmenter batches. New topics discovered by the LLM are auto-upserted with `confirmed_by: null`.

---

## Project Structure

```
eb1/
├── pyproject.toml                        # uv dependencies and tool config
├── .env.example                          # Environment variable template
│
├── config/
│   └── settings.py                       # Pydantic BaseSettings — loads .env
│
├── db/                                   # Persistence layer
│   ├── client.py                         # MongoDB client (PROD read-only)
│   ├── pg.py                             # PostgreSQL connection pool (psycopg3)
│   └── repositories/
│       ├── base.py                       # BaseRepository (fetch, execute, count)
│       ├── segments.py                   # SegmentRepository — sms_chat_segments
│       ├── benchmark.py                  # BenchmarkSegmentRepository — eb1_benchmark_raw
│       ├── benchmark_groups.py           # BenchmarkGroupRepository — eb1_benchmark_groups
│       ├── benchmark_runs.py             # BenchmarkRunRepository — eb1_benchmark_runs
│       ├── benchmark_matches.py          # BenchmarkMatchRepository — eb1_benchmark_matches
│       ├── benchmark_taxonomy.py         # BenchmarkTaxonomyRepository
│       ├── pipeline_config.py            # PipelineConfigRepository — eb1_pipeline_configs
│       ├── pipeline_logs.py              # PipelineLogRepository — eb1_pipeline_logs
│       ├── taxonomy.py                   # TaxonomyRepository — sms_chat_taxonomy
│       ├── signals.py                    # SignalRepository — matching_signals
│       └── templates.py                  # TemplateMappingRepository — eb1_template_mappings
│
├── pipeline/                             # Analyzer pipeline
│   ├── __main__.py                       # Entry point: uv run python -m pipeline
│   ├── main.py                           # CLI parsing, step orchestration, benchmark adapter
│   ├── config/
│   │   ├── loader.py                     # Reads *.toml → typed dataclasses; taxonomy management
│   │   ├── analyzer.toml                 # LLM model, concurrency, routing
│   │   ├── benchmark.toml               # Multi-LLM comparison runs
│   │   └── clustering.toml              # Offline quality (embedder, UMAP, HDBSCAN)
│   ├── segmentation/
│   │   ├── segmenter.py                 # Orchestration, LLM calls, segment building
│   │   ├── preprocessing.py             # Message cleaning, slug normalization
│   │   ├── windowing.py                 # Message windowing, pre-segmentation
│   │   └── bot_processor.py             # Bot-only segment handling, template matching
│   ├── templates/
│   │   └── classifier.py                # LLM-classify PROD message templates
│   ├── graders/
│   │   └── segmentation_graders.py      # 8 deterministic graders (G0.3–G0.11, G1.2, G1.4)
│   ├── sampling/
│   │   └── signal_extractor.py          # TP/FP signal extraction from matchings
│   ├── evaluation/
│   │   ├── evaluator.py                 # Quality metrics
│   │   └── benchmark_eval.py            # Benchmark comparison against ground truth
│   ├── quality/
│   │   └── offline.py                   # Embed → UMAP → HDBSCAN → cluster object
│   └── prompts/
│       └── analyzer/
│           ├── __init__.py              # PromptTemplate loader
│           ├── eb1_prompt_user_v3.md    # Active prompt (three-tier routing, few-shot)
│           └── eb1_prompt_bot_v1.md     # Bot-only prompt
│
├── tests/                               # Unit tests (no LLM, no DB required)
│
├── docs/
│   ├── erd.md                           # PROD schema ERD + field reference
│   ├── GRADERS.md                       # Grader specifications
│   ├── user_taxonomy.md                 # Topic taxonomy reference
│   └── architecture/                    # Phase flowcharts
```

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_DSN` | Yes | PostgreSQL connection string for pipeline writes |
| `AI_GATEWAY_API_KEY` | Yes | Vercel AI Gateway — single key for all LLM providers |
| `MONGODB_PROD_ANALYTICS_URI` | Yes | PROD MongoDB Atlas (read-only source data) |
| `MONGODB_PROD_ANALYTICS_DB_NAME` | Yes | PROD database name |
| `MONGODB_OUTPUT_URI` | No | Legacy MongoDB output (only for signal extraction) |
| `MONGODB_OUTPUT_DB_NAME` | No | Legacy output database name |

---

## Testing

```bash
uv run pytest tests/ -q          # All tests (290 tests, no DB/LLM required)
uv run ruff check pipeline/ db/  # Lint
```

---

## Reference

- [uv documentation](https://docs.astral.sh/uv/)
