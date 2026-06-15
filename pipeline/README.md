# eb1 Pipeline (`pipeline/`)

> **Status:** Phase 2 (Semi-supervised) — Analyzer architecture.

This package implements the eb1 pipeline. It reads PROD `sms_chats` + `sms_chat_messages` data from MongoDB, segments chat histories by topic via LLM, and stores structured `sms_chat_segments` in PostgreSQL — the **single source of truth for user state** in downstream matchmaking and product intelligence workflows.

---

## How to Run

Make sure `.env` is configured with `POSTGRES_DSN`, MongoDB Atlas URIs, and AI Gateway key.

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

| Flag | Description |
|---|---|
| `--step <name>` | Run a single step instead of the full pipeline |
| `--limit N` | Process only N users (applies to `segment` step only) |
| `--force` | Re-segment users that were already processed |
| `--relabel` | Clear AI fields on unreviewed segments and re-run the Analyzer |
| `--benchmark NAME` | Multi-LLM comparison mode (writes to `eb1_benchmark_raw`) |
| `--benchmark-eval` | Evaluate benchmarks against ground truth → Tier 2 + 3 |
| `--group-id GROUP_ID` | Override group ID (default: `bench-YYYY-MM-DD`). Use with `--benchmark` or `--benchmark-eval` |
| `--classify-templates` | LLM-classify PROD message templates against taxonomy |
| `--offline-quality` | Embed → HDBSCAN → write cluster object (periodic, not part of regular pipeline) |

---

## Step Consequences

| Step | Writes to | What happens |
|---|---|---|
| `signal` | PG `matching_signals` | Extracts TP/FP signals from PROD matchings. Idempotent. |
| `segment` | PG `sms_chat_segments` | LLM segments + classifies each user's chat. Idempotent — skips already segmented users. |
| `validate` | Nothing | Deterministic graders check segmentation quality. Prints pass/fail per grader. |
| `evaluate` | Nothing | Quality metrics: labeled ratio, distinct topics, low-confidence review queue. Read-only, no local files. |

---

## Pipeline Flow

```
PROD MongoDB (read-only): sms_chats + sms_chat_messages + matchings
        │
        ▼
1. signal  ── Extract TP/FP signals → PG matching_signals
        │
        ▼
2. segment ── Analyzer LLM: segment + classify → PG sms_chat_segments
        │         ├── Pre-write invariant: zero message loss (hard block)
        │         └── Taxonomy auto-upsert → PG sms_chat_taxonomy
        │
        ▼
3. validate ─ Deterministic graders (read-only, checks PG + PROD)
        │
        ▼
4. evaluate ─ Quality metrics + run summary (read-only)
```

---

## Message Coverage Guarantee

The segmenter enforces **zero tolerance for message loss** through a chain of invariants:

| Phase | Mechanism | Type |
|-------|-----------|------|
| Fetch | Deterministic MongoDB query — all user-facing + boundary messages | Hard |
| Pre-segment | Every message placed in exactly one chunk (algorithmic) | Hard |
| LLM parse | LLM may underreference messages | Soft |
| Orphan rescue | All unreferenced messages appended to nearest segment | Hard |
| Dedup | Non-user duplicates removed; messages kept in best-scored segment | Hard |
| **Pre-write check** | `ValueError` raised if ANY message missing from segments | **Hard block** |
| Write | Segments committed to PostgreSQL in a single transaction | Hard |
| G0.3 grader | Post-hoc coverage validation (< 5% failure threshold) | Soft |

The pre-write invariant in `_process_one` compares all processed message IDs against the union of segment `chat_messages`. If any message is absent, the pipeline **aborts for that user** — no silent data loss.

---

## Segmenter Architecture

The segmenter is decomposed into focused modules:

```
segmenter.py          Orchestration, LLM calls, segment building, taxonomy entry
  ├── preprocessing.py    Message cleaning, slug normalization, reaction detection
  ├── windowing.py        Message windowing, pre-segmentation into chunks
  └── bot_processor.py    Bot-only classification, template matching
```

### Processing Flow (per user)

1. **Fetch** — `_build_flat_history`: query all user-facing messages, deduplicate bot content
2. **Incremental check** — skip if no new messages since last segment
3. **Pre-segment** — `_pre_segment`: split into bot-only and user-engaged chunks
4. **Bot chunks** — `_build_bot_only_segments`: classify via template matching or dedicated LLM prompt
5. **User chunks** — window into ≤200-message batches, send to LLM with taxonomy context
6. **Parse** — `_parse_llm_segments`: validate LLM JSON, clamp indices
7. **Build** — `_build_segments_from_llm`: construct segment dicts, rescue orphans
8. **Dedup** — `_dedup_non_user_across_segments`: remove non-user duplicates across segments
9. **Invariant** — verify zero message loss + no duplicate IDs
10. **Write** — `segment_repo.insert_many()` in a single PG transaction

---

## Directory Structure

```
pipeline/
├── __main__.py               # Entry point: python -m pipeline
├── main.py                   # CLI parsing, step orchestration, benchmark adapter
├── config/
│   ├── loader.py             # Reads *.toml → typed dataclasses; taxonomy management
│   ├── analyzer.toml         # LLM model, concurrency, routing
│   ├── benchmark.toml        # Multi-LLM comparison runs
│   └── clustering.toml       # Offline quality (embedder, UMAP, HDBSCAN)
├── segmentation/
│   ├── segmenter.py          # Orchestration, LLM calls, segment building
│   ├── preprocessing.py      # Message cleaning, slug normalization
│   ├── windowing.py          # Message windowing, pre-segmentation
│   └── bot_processor.py      # Bot-only segment handling, template matching
├── templates/
│   └── classifier.py         # LLM-classify PROD message templates
├── graders/
│   └── segmentation_graders.py  # 8 deterministic graders
├── sampling/
│   └── signal_extractor.py   # TP/FP signal extraction
├── evaluation/
│   ├── evaluator.py          # Quality metrics
│   └── benchmark_eval.py     # Benchmark comparison against ground truth
├── quality/
│   └── offline.py            # Embed → UMAP → HDBSCAN → cluster object
└── prompts/
    └── analyzer/
        ├── __init__.py              # PromptTemplate loader
        ├── eb1_prompt_user_v3.md    # Active prompt (three-tier routing)
        └── eb1_prompt_bot_v1.md     # Bot-only prompt
```

---

## Dependencies

```
psycopg[binary]      # PostgreSQL driver (psycopg3)
psycopg-pool         # Connection pooling
pymongo              # MongoDB driver (PROD read-only)
openai               # LLM calls via AI Gateway
pydantic-settings    # Config loading
sentence-transformers  # Offline quality layer (embeddings)
hdbscan               # Offline quality layer (clustering)
umap-learn            # Offline quality layer (dimensionality reduction)
```
