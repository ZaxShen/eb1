# eb1 Schemas

**Last updated:** 2026-03-28. Full ERD with mermaid diagram: `docs/erd.md`

---

## Data Stores

| Store | Role | Tables |
|-------|------|--------|
| **MongoDB Atlas (PROD)** | Read-only source | `users`, `sms_chats`, `sms_chat_messages`, `matchings`, `message_templates`, `user_profiles` |
| **PostgreSQL** | Pipeline writes | 14 tables (see below) |

> PROD MongoDB uses **camelCase** field names and **snake_case** collection names. PostgreSQL uses **snake_case** for everything. When reading MongoDB in Python, use camelCase field names (the DB schema is the contract).

---

## PostgreSQL — Production Tables

### `sms_chat_segments`

Core pipeline output. One row per conversation segment. Single source of truth for user state.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | DEFAULT gen_random_uuid() |
| `user_id` | TEXT NOT NULL | MongoDB ObjectId as string |
| `chat_id` | TEXT NOT NULL | FK to sms_chats._id |
| `chat_messages` | TEXT[] NOT NULL | Ordered message ObjectIds |
| `topic` | TEXT | **FK → eb1_taxonomy_topics(slug)** |
| `sub_topic` | TEXT | **Composite FK (topic, sub_topic) → subtopics** |
| `label_confidence` | REAL | CHECK 0..1. LLM self-reported confidence |
| `summary` | TEXT | LLM 1-2 sentence summary |
| `sentiment` | TEXT | CHECK IN (positive, negative, neutral, mixed) |
| `cluster` | JSONB | {id, confidence, topic, sub_topic, purity, run_at} |
| `true_topic` | TEXT | **FK → eb1_taxonomy_topics(slug).** Human ground truth |
| `true_sub_topic` | TEXT | **Composite FK.** Human ground truth |
| `reviewed_by` | TEXT | Reviewer identifier |
| `reviewed_at` | TIMESTAMPTZ | When human reviewed |
| `has_user_engagement` | BOOLEAN | Deterministic — at least one user message |
| `has_bot_failure` | BOOLEAN | User message went unanswered |
| `response_rate` | REAL | user responses / bot prompts [0..1] |
| `config_id` | INTEGER | **FK → eb1_pipeline_configs(id)** |
| `chat_started_at` | TIMESTAMPTZ | First message timestamp |
| `chat_ended_at` | TIMESTAMPTZ | Last message timestamp |
| `classified_at` | TIMESTAMPTZ | When Analyzer wrote topic + confidence |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `eb1_taxonomy_topics`

Dual taxonomy (user + bot topics). Seeded from INITIAL_TAXONOMY. Unknown topics auto-upserted with confirmed_by = NULL.

| Column | Type | Notes |
|--------|------|-------|
| `slug` | TEXT PK | e.g. "match_feedback" |
| `name` | TEXT NOT NULL | Display name |
| `description` | TEXT | DEFAULT '' |
| `type` | TEXT NOT NULL | CHECK IN (user, bot) |
| `confirmed_by` | TEXT | NULL = unconfirmed (pending review) |
| `confirmed_at` | TIMESTAMPTZ | |
| `created_by` | TEXT | Model name that discovered this topic |
| `updated_by` | TEXT | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `eb1_taxonomy_subtopics`

PK: (topic_slug, slug). UNIQUE on slug for global uniqueness.

| Column | Type | Notes |
|--------|------|-------|
| `slug` | TEXT NOT NULL | UNIQUE |
| `topic_slug` | TEXT NOT NULL | FK → topics(slug) ON UPDATE CASCADE |
| `name` | TEXT NOT NULL | |
| `description` | TEXT | DEFAULT '' |
| `confirmed_by` | TEXT | |
| `confirmed_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `eb1_template_mappings`

LLM-classified PROD message templates. Used by segmenter's difflib matcher for bot-only segments (no LLM call at runtime).

| Column | Type | Notes |
|--------|------|-------|
| `template_id` | TEXT PK | FK → message_templates._id |
| `topic_slug` | TEXT NOT NULL | Composite FK (topic_slug, subtopic_slug) → subtopics |
| `subtopic_slug` | TEXT NOT NULL | |
| `name` | TEXT NOT NULL | Template name |
| `summary` | TEXT | LLM-generated description |
| `messages` | TEXT[] | Individual message texts from imessageContent |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `matching_signals`

TP/FP signals extracted from PROD matchings. Idempotent: drop and regenerate.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `matching_id` | TEXT NOT NULL UNIQUE | |
| `users` | TEXT[] NOT NULL | Two-element array, index-aligned with signal |
| `signal` | TEXT[] NOT NULL | Per-user: "TP" or "FP" |
| `matching_status` | TEXT NOT NULL | ContactExchanged or Failed - Refused |
| `acceptance_status` | TEXT[] NOT NULL | Raw per-user values from PROD |
| `matching_created_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

---

## PostgreSQL — Infrastructure Tables

### `eb1_pipeline_configs`

One row per unique (model, user_prompt, bot_prompt, temperature). Segments and benchmarks reference this by config_id.

UNIQUE: (model, user_prompt, bot_prompt, temperature)

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | |
| `model` | TEXT NOT NULL | e.g. "openai/gpt-5.4" |
| `user_prompt` | TEXT NOT NULL | Prompt name |
| `bot_prompt` | TEXT NOT NULL | Prompt name |
| `temperature` | REAL | DEFAULT 0.0 |
| `extra` | JSONB | Future params without schema changes |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `eb1_pipeline_logs`

General-purpose event log. Filter by event_type (e.g. "taxonomy_remap").

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | |
| `event_type` | TEXT NOT NULL | Indexed |
| `user_id` | TEXT | Optional |
| `payload` | JSONB NOT NULL | DEFAULT '{}'. Flexible event data |
| `config_id` | INTEGER | FK → eb1_pipeline_configs(id) |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

---

## PostgreSQL — Benchmark Tables (7 tables)

### `eb1_benchmark_groups`

One row per benchmark experiment (e.g. "model comparison Q1 2026").

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | |
| `name` | TEXT NOT NULL UNIQUE | |
| `type` | TEXT | e.g. "model_benchmark" |
| `objective` | TEXT | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

### `eb1_benchmark_runs`

One row per (group, config). Stores evaluation metrics after Jaccard matching vs ground truth.

UNIQUE: (group_id, config_id)

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | |
| `group_id` | INTEGER | FK → groups(id) |
| `config_id` | INTEGER NOT NULL | FK → configs(id) |
| `match_rate` | REAL NOT NULL | % of GT segments matched |
| `avg_iou` | REAL NOT NULL | Mean Jaccard similarity |
| `topic_accuracy` | REAL NOT NULL | |
| `subtopic_accuracy` | REAL NOT NULL | |
| `rank` | INTEGER | Leaderboard rank within group |
| `duration_seconds` | REAL | |
| `run_at` | TIMESTAMPTZ | NOT NULL, DEFAULT NOW() |

Also includes: `total_gt_segments`, `total_model_segments`, `matched_count`, `segment_count_ratio`, `ue_*` (user-engaged subset metrics), `confidence_calibration` (JSONB), `avg_llm_latency_ms`.

### `eb1_benchmark_raw`

Per-segment LLM output from benchmark runs. Mirrors sms_chat_segments structure plus `benchmark_run_id`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | |
| `benchmark_run_id` | INTEGER NOT NULL | FK → runs(id) |
| `user_id` | TEXT NOT NULL | |
| `chat_id` | TEXT NOT NULL | |
| `chat_messages` | TEXT[] NOT NULL | |
| `topic` | TEXT | No FK (UNION ALL taxonomy) |
| `sub_topic` | TEXT | No FK (UNION ALL taxonomy) |
| `label_confidence` | REAL | |
| `summary` | TEXT | |
| `sentiment` | TEXT | |
| `cluster` | JSONB | |

Also includes: `has_user_engagement`, `has_bot_failure`, `response_rate`, `chat_started_at`, `chat_ended_at`, `classified_at`, `created_at`, `updated_at`.

### `eb1_benchmark_matches`

Jaccard match results between ground truth and model segments.

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL PK | |
| `benchmark_run_id` | INTEGER NOT NULL | FK → runs(id) |
| `gt_segment_id` | INTEGER NOT NULL | |
| `gt_topic` | TEXT | **FK → eb1_taxonomy_topics(slug)** |
| `gt_sub_topic` | TEXT | **Composite FK → subtopics** |
| `model_topic` | TEXT | No FK (UNION ALL taxonomy) |
| `model_sub_topic` | TEXT | No FK (UNION ALL taxonomy) |
| `iou` | REAL NOT NULL | Jaccard similarity |
| `matched` | BOOLEAN NOT NULL | |
| `topic_match` | BOOLEAN | |
| `subtopic_match` | BOOLEAN | |

### `eb1_benchmark_taxonomy_topics` and `eb1_benchmark_taxonomy_subtopics`

Same schema as production taxonomy tables plus provenance: `group_id` (FK → groups) and `benchmark_run_id` (FK → runs). Reads use **UNION ALL** across prod + benchmark tables. Writes go to benchmark tables only.

### `eb1_benchmark_pipeline_logs`

Same schema as `eb1_pipeline_logs` plus provenance: `group_id` (FK → groups) and `benchmark_run_id` (FK → runs).

---

## Foreign Key Constraints

All enforced in PostgreSQL. See `db/schema/foreign_keys.sql` for full DDL.

| Source | Target | Notes |
|--------|--------|-------|
| segments.topic | eb1_taxonomy_topics(slug) | AI-assigned topic |
| segments.(topic, sub_topic) | eb1_taxonomy_subtopics(topic_slug, slug) | Composite FK |
| segments.true_topic | eb1_taxonomy_topics(slug) | Human ground truth |
| segments.(true_topic, true_sub_topic) | eb1_taxonomy_subtopics(topic_slug, slug) | Composite FK |
| eb1_template_mappings.topic_slug | eb1_taxonomy_topics(slug) | ON UPDATE CASCADE |
| eb1_template_mappings.(topic_slug, subtopic_slug) | eb1_taxonomy_subtopics | ON UPDATE CASCADE ON DELETE CASCADE |
| benchmark_matches.gt_topic | eb1_taxonomy_topics(slug) | Ground truth only |
| benchmark_matches.(gt_topic, gt_sub_topic) | eb1_taxonomy_subtopics | Ground truth only |

> **No FK on model_topic/model_sub_topic** in benchmark tables. Benchmark models may produce topics from `eb1_benchmark_taxonomy_*` tables (UNION ALL architecture).

---

## MongoDB Collections (PROD, read-only)

The pipeline reads these from PROD Atlas. Field names are **camelCase**. Configured in `pipeline/config/analyzer.toml → [collections]`.

| Collection | Docs | Key Fields (read by pipeline) |
|------------|------|-------------------------------|
| `users` | 135,786 | `_id`, `school`, `pool`, `phone`, `onboardStep` |
| `sms_chats` | 133,595 | `_id`, **`user`** (FK → users, NOT userId), `state` |
| `sms_chat_messages` | 3,090,751 | `_id`, **`chat`** (FK → sms_chats, NOT chatId), `type`, `message`, `createdAt` |
| `matchings` | 5,460 | `_id`, `users` (2-element array), `status`, `acceptanceStatus` |
| `message_templates` | — | `_id`, `name`, `imessageContent` (array of {message, media_url}) |
| `user_profiles` | — | `_id`, `userId`, `basicInfo`, `deepInfo`, `expectedPartner` |

> `sms_chat_messages.type` values: `user`, `assistant`, `automated`, `system`, `team`. Pipeline filters to `user`, `assistant`, `automated`, `team`.
> `matchings.acceptanceStatus[i]` aligns with `matchings.users[i]` (same index).

---

## Table Summary

| Category | Count | Tables |
|----------|-------|--------|
| **Production** | 5 | sms_chat_segments, eb1_taxonomy_topics, eb1_taxonomy_subtopics, eb1_template_mappings, matching_signals |
| **Infrastructure** | 2 | eb1_pipeline_configs, eb1_pipeline_logs |
| **Benchmark** | 7 | eb1_benchmark_groups, eb1_benchmark_runs, eb1_benchmark_raw, eb1_benchmark_matches, eb1_benchmark_taxonomy_topics, eb1_benchmark_taxonomy_subtopics, eb1_benchmark_pipeline_logs |
| **Total PG** | **14** | |
