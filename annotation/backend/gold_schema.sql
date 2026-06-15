-- Per-dataset human-gold schema for the annotation site.
--
-- One SQLite file per dataset (datasets/<name>/gold.db). It records the human
-- review layer over the runner's machine segments (datasets/<name>/output.db):
--
--   gold_segment  — the corrected gold spans + labels a reviewer produced.
--                   `source` distinguishes a pure relabel/confirm of a base
--                   span ("relabel" | "confirm", base_segment_id set) from a
--                   boundary edit ("boundary", base_segment_id NULL) where a
--                   conversation's spans are replaced wholesale (split/merge).
--   review_state  — per (conversation, base_segment_id) review bookkeeping so
--                   the queue can filter reviewed vs. unreviewed segments.

CREATE TABLE IF NOT EXISTS gold_segment (
    id              INTEGER PRIMARY KEY,
    conversation    TEXT,
    message_indices TEXT,   -- JSON array of int message indices (the gold span)
    topic           TEXT,
    subtopic        TEXT,
    sentiment       TEXT,
    base_segment_id INTEGER,            -- run_segment.id this gold mirrors, or NULL
    source          TEXT,               -- "relabel" | "confirm" | "boundary"
    reviewed_by     TEXT,
    reviewed_at     TEXT
);

CREATE TABLE IF NOT EXISTS review_state (
    conversation    TEXT,
    base_segment_id INTEGER,
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    status          TEXT,               -- "reviewed"
    PRIMARY KEY (conversation, base_segment_id)
);
