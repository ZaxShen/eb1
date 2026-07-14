-- PostgreSQL schema for the annotation tool.
--
-- Replaces the per-dataset SQLite triple (output.db / sample.jsonl / gold.db)
-- with one Postgres database. The production campaign holds a sampled
-- SuperDialseg worklist (~1.3K conversations); the schema also supports larger
-- corpora for the labeling site to review at scale.
--
-- Layout:
--   dataset       — one row per corpus (superdialseg is the active corpus;
--                   wildchat / lmsys adapters exist but are dormant).
--   conversation  — one row per conversation, keyed by (dataset, ext_id) where
--                   ext_id is the source id (SuperDialseg dialogue id, etc.).
--   message       — the ordered, normalized messages of a conversation.
--   segment       — both the machine "predicted" seed segments (source='predicted',
--                   one whole-conversation span per conversation) and the human
--                   gold edits (source in 'relabel' | 'confirm' | 'boundary').
--                   `base_segment_id` ties a relabel/confirm gold back to the
--                   predicted segment it mirrors; a boundary edit has it NULL and
--                   replaces a conversation's spans wholesale (split/merge).
--                   reviewed_* records the human review bookkeeping.
--   taxonomy      — per-dataset (topic, subtopic) options for the relabel UI.
--   worklist      — sampled (dataset, ext_id, labeler) assignments that gate the
--                   per-labeler review queue (SuperDialseg name-only labeling). An
--                   overlap dialogue (double-labeled) has one row per labeler.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS dataset (
    name        TEXT PRIMARY KEY,
    description TEXT
);

CREATE TABLE IF NOT EXISTS conversation (
    id            BIGSERIAL PRIMARY KEY,
    dataset       TEXT NOT NULL REFERENCES dataset(name) ON DELETE CASCADE,
    ext_id        TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (dataset, ext_id)
);

CREATE TABLE IF NOT EXISTS message (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    idx             INTEGER NOT NULL,
    role            TEXT,
    content         TEXT,
    created_at      TIMESTAMPTZ,
    UNIQUE (conversation_id, idx)
);

CREATE TABLE IF NOT EXISTS segment (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    chunk_index      INTEGER NOT NULL DEFAULT 0,
    message_indices  INTEGER[] NOT NULL DEFAULT '{}',
    summary          TEXT,
    topic            TEXT,
    subtopic         TEXT,
    sentiment        TEXT,
    label_confidence DOUBLE PRECISION,
    source           TEXT NOT NULL,        -- 'predicted' | 'relabel' | 'confirm' | 'boundary'
    base_segment_id  BIGINT REFERENCES segment(id) ON DELETE CASCADE,
    reviewed_by      TEXT,
    reviewed_at      TIMESTAMPTZ
);

-- BERTopic topic-classification labels on gold segments (issue 19). Distinct
-- from topic/subtopic (eb1 prediction / human relabel). Added via ALTER so
-- existing databases migrate idempotently on apply_schema.
ALTER TABLE segment ADD COLUMN IF NOT EXISTS bertopic_topic    TEXT;
ALTER TABLE segment ADD COLUMN IF NOT EXISTS bertopic_subtopic TEXT;

CREATE TABLE IF NOT EXISTS taxonomy (
    dataset     TEXT NOT NULL REFERENCES dataset(name) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'user',
    topic       TEXT,
    subtopic    TEXT,
    description TEXT
);

-- One (dataset, kind, topic, subtopic) option exists at most once so create and
-- merge are idempotent. NULLS NOT DISTINCT (PG15+) treats a NULL subtopic as a
-- single value, so a topic-only option cannot be duplicated either.
CREATE UNIQUE INDEX IF NOT EXISTS taxonomy_option_uidx
    ON taxonomy (dataset, kind, topic, subtopic) NULLS NOT DISTINCT;

CREATE TABLE IF NOT EXISTS worklist (
    id          BIGSERIAL PRIMARY KEY,
    dataset     TEXT NOT NULL REFERENCES dataset(name) ON DELETE CASCADE,
    ext_id      TEXT NOT NULL,
    labeler     TEXT NOT NULL,
    is_overlap  BOOLEAN NOT NULL DEFAULT FALSE,
    seg_bucket  TEXT,
    len_bucket  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dataset, ext_id, labeler)
);

-- Scale + search indexes.
CREATE INDEX IF NOT EXISTS conversation_dataset_idx ON conversation (dataset);
CREATE INDEX IF NOT EXISTS conversation_dataset_id_idx ON conversation (dataset, id);
CREATE INDEX IF NOT EXISTS conversation_ext_id_trgm_idx
    ON conversation USING gin (ext_id gin_trgm_ops);

CREATE INDEX IF NOT EXISTS message_conversation_idx ON message (conversation_id);
CREATE INDEX IF NOT EXISTS message_content_trgm_idx
    ON message USING gin (content gin_trgm_ops);

CREATE INDEX IF NOT EXISTS segment_conversation_idx ON segment (conversation_id);
CREATE INDEX IF NOT EXISTS segment_source_idx ON segment (source);
CREATE INDEX IF NOT EXISTS segment_base_idx ON segment (base_segment_id);

CREATE INDEX IF NOT EXISTS taxonomy_dataset_idx ON taxonomy (dataset, kind);

CREATE INDEX IF NOT EXISTS worklist_dataset_labeler_idx ON worklist (dataset, labeler);
