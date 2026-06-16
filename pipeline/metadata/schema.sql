-- Per-dataset metadata schema for the universal eb1 pipeline.
--
-- One SQLite file per dataset (datasets/<name>/metadata.db). Each table
-- externalizes a domain knob the segmentation engine consumes at runtime:
-- the dataset config (role map, prompt profile, taxonomy mode, accelerator
-- toggles), the taxonomy, P1/P4 accelerator rules, P3 topic filters, and
-- preprocessing rules. Empty rule tables make the corresponding accelerator a
-- clean no-op.

CREATE TABLE IF NOT EXISTS dataset (
    name           TEXT PRIMARY KEY,
    description    TEXT,
    role_map       TEXT,   -- JSON object: corpus role -> pipeline message type
    prompt_profile TEXT,   -- prompt version, e.g. "v4"
    taxonomy_mode  TEXT,   -- "open" | "closed"
    accelerators   TEXT    -- JSON object: {p1, p3, p4, templates} booleans
);

CREATE TABLE IF NOT EXISTS taxonomy (
    id           INTEGER PRIMARY KEY,
    kind         TEXT,    -- "user" | "bot"
    topic        TEXT,
    subtopic     TEXT,
    description  TEXT,
    confirmed_by TEXT,
    true_topic   TEXT,
    true_subtopic TEXT,
    UNIQUE (kind, topic, subtopic)
);

CREATE TABLE IF NOT EXISTS accelerator_rule (
    id             INTEGER PRIMARY KEY,
    rule           TEXT,   -- e.g. "p1" | "p4"
    pattern        TEXT,
    target_topic   TEXT,
    target_subtopic TEXT,
    position       INTEGER
);

CREATE TABLE IF NOT EXISTS topic_filter (
    id            INTEGER PRIMARY KEY,
    scope         TEXT,   -- e.g. pool / segment scope (P3)
    kind          TEXT,   -- "user" | "bot"
    allowed_topic TEXT
);

CREATE TABLE IF NOT EXISTS preprocessing_rule (
    id          INTEGER PRIMARY KEY,
    kind        TEXT,
    pattern     TEXT,
    replacement TEXT
);
