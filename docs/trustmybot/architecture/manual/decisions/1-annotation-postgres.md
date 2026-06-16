# 1. Annotation tool storage: PostgreSQL (not per-dataset SQLite)

- Status: Accepted
- Date: 2026-06-15
- Scope: `annotation/` (backend data layer, API contract, e2e harness)

## Context

The annotation tool is the production labeling surface for eb1 — the Founder
needs to label the FULL real corpora soon (~1.85M conversations: ~838K WildChat
+ ~1M LMSYS + ~9.5K SuperDialseg). The pipeline stays an MVP; the labeling
website does not.

The original backend stored each dataset as a SQLite triple read off disk per
request:

- machine segments from `datasets/<ds>/output.db` (`run_segment`),
- conversation messages re-parsed from `datasets/<ds>/sample.jsonl` through the
  adapter **on every call**,
- human gold in a per-dataset `datasets/<ds>/gold.db`.

That shape does not survive the full datasets. `list_conversations`,
`effective_segments`, and `stats` each loaded and re-normalized *every*
conversation in the sample file in Python per request — O(corpus) work with no
index, no pagination, and no text search. At 1.85M conversations the queue
endpoint alone is unusable, and the JSONL-reparse-per-request model has no place
to put an index.

## Decision

Migrate the annotation backend to a single **PostgreSQL** database
(`postgres:18-alpine`), stood up locally via `annotation/docker-compose.yml` on
host port `5544` and addressed by **`EB1_ANNOTATION_DSN`**
(default `postgresql://eb1:eb1@localhost:5544/eb1_annotation`). The backend uses
**psycopg** (already a project dependency) with a process-wide
`psycopg_pool.ConnectionPool`.

### Schema (`annotation/backend/schema.sql`)

| table | purpose |
|---|---|
| `dataset(name PK, description)` | one row per corpus |
| `conversation(id BIGSERIAL, dataset FK, ext_id, message_count, UNIQUE(dataset,ext_id))` | one row per conversation; `ext_id` is the source id (WildChat `conversation_hash`, SuperDialseg `dialogue_id`, …) |
| `message(id, conversation_id FK, idx, role, content, created_at, UNIQUE(conversation_id,idx))` | the ordered normalized messages — stored, not re-parsed per request |
| `segment(id, conversation_id FK, chunk_index, message_indices int[], summary, topic, subtopic, sentiment, label_confidence, source, base_segment_id FK→segment, reviewed_by, reviewed_at)` | both the machine `source='predicted'` seed segments and the human gold (`source IN ('relabel','confirm','boundary','gold')`) |
| `taxonomy(dataset FK, kind, topic, subtopic, description)` | per-dataset relabel options |

Indexes target scale + search: `conversation(dataset)`, `conversation(dataset,id)`,
`segment(conversation_id)`, and **`pg_trgm` GIN** trigram indexes on
`message.content` and `conversation.ext_id` so `q` search (ext_id OR any message
content, ILIKE) is index-backed.

### Starting segmentation

Each conversation seeds as **one whole-conversation `predicted` segment**; the
human segments from there. No LLM pre-segmentation. (The prior SQLite e2e fixture
used the mock analyzer to the same effect — one segment per conversation.)

### Effective-segmentation semantics (preserved)

The gold layer is unchanged in meaning, only re-homed onto Postgres rows:

- a per-segment **relabel/confirm** mirrors a predicted span
  (`base_segment_id` set) and overlays its topic/subtopic in the effective view;
- a **boundary** edit (split/merge) and an ingested **gold** span (SuperDialseg)
  REPLACE the conversation's predicted spans wholesale (`base_segment_id` NULL);
- boundary/gold spans that carry no label INHERIT topic/subtopic from the
  most-overlapped predicted segment, so split children and merges keep a label.

This matches the SQLite behaviour exactly; the same effective-segmentation tests
(now in `tests/test_annotation_pg.py`) keep passing.

### API contract change: paginated + searchable conversations list

`GET /api/datasets/{ds}/conversations` now returns a **paginated** envelope
instead of a bare array:

```json
{ "items": [ConversationSummary, ...], "total": N, "page": 1, "page_size": 50 }
```

Query params: `page`, `page_size`, `q` (ext_id OR message-content search),
`status` (`reviewed`/`unreviewed`), `topic`. All other endpoints keep their
shapes. The paginated/virtualized **queue UI** is a follow-up (task C); for now
`api.listConversations` unwraps `items` so the existing frontend holds.

### Cutover (full, not half)

This task owns the whole cutover so the app runs on Postgres after it:

- `db.py` + `routes.py` rewritten on the pool; `config.py` reads the DSN;
  `models.py` gains `ConversationPage`.
- The SQLite-specific `gold_schema.sql` and the per-dataset path helpers are
  removed. `pipeline/metadata/ingest_superdialseg_gold.py` (the one cross-module
  consumer of the old gold store) is ported to write `source='gold'` segments
  into Postgres.
- pytest: `test_annotation_backend.py` is folded into the new
  `test_annotation_pg.py`; `test_annotation_auth.py` and the SuperDialseg gold
  ingest tests run on Postgres. All Postgres tests skip when
  `EB1_ANNOTATION_DSN` is unset, so the offline suite stays green.
- The Playwright e2e harness boots the docker Postgres + seeds it (replacing the
  SQLite fixture) and the existing smoke + operations specs pass unchanged.

A `db.seed_conversations(...)` helper lets tests and a smoke run populate the
database without the full ingest (the real ingest is task B).

## Consequences

- The queue, search, and stats are now index-backed SQL instead of O(corpus)
  Python — the prerequisite for labeling the full datasets.
- A running Postgres is now required: `docker compose -f annotation/docker-compose.yml up -d`.
  Local default credentials are committed for convenience; production overrides
  `EB1_ANNOTATION_DSN`.
- The conversations-list response shape changed (array → `{items,total,page,page_size}`).
  In-scope consumers were updated; the virtualized queue UI is task C.
- A named docker volume (`eb1_annotation_pgdata`, mounted at
  `/var/lib/postgresql` per the postgres:18 layout) persists the corpus across
  restarts.
