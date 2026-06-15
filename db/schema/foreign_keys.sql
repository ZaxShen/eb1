-- Foreign key constraints across all eb1 tables.
-- Run idempotent — use ADD CONSTRAINT IF NOT EXISTS (PG 17+)
-- or check pg_constraint before adding.

-- ═══════════════════════════════════════════════════════════════════
-- sms_chat_segments → taxonomy
-- ═══════════════════════════════════════════════════════════════════

-- AI-assigned
ALTER TABLE sms_chat_segments
  ADD CONSTRAINT fk_segments_topic
    FOREIGN KEY (topic) REFERENCES eb1_taxonomy_topics(slug);

ALTER TABLE sms_chat_segments
  ADD CONSTRAINT fk_segments_topic_subtopic
    FOREIGN KEY (topic, sub_topic)
    REFERENCES eb1_taxonomy_subtopics(topic_slug, slug);

-- Human-reviewed
ALTER TABLE sms_chat_segments
  ADD CONSTRAINT fk_segments_true_topic
    FOREIGN KEY (true_topic) REFERENCES eb1_taxonomy_topics(slug);

ALTER TABLE sms_chat_segments
  ADD CONSTRAINT fk_segments_true_topic_subtopic
    FOREIGN KEY (true_topic, true_sub_topic)
    REFERENCES eb1_taxonomy_subtopics(topic_slug, slug);

-- ═══════════════════════════════════════════════════════════════════
-- eb1_template_mappings → taxonomy
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE eb1_template_mappings
  ADD CONSTRAINT fk_template_mappings_topic
    FOREIGN KEY (topic_slug) REFERENCES eb1_taxonomy_topics(slug)
    ON UPDATE CASCADE ON DELETE RESTRICT;

-- Composite (topic_slug, subtopic_slug) FK already exists from table creation.

-- ═══════════════════════════════════════════════════════════════════
-- eb1_benchmark_matches → taxonomy (ground truth = prod taxonomy)
-- ═══════════════════════════════════════════════════════════════════

ALTER TABLE eb1_benchmark_matches
  ADD CONSTRAINT fk_benchmark_matches_gt_topic
    FOREIGN KEY (gt_topic) REFERENCES eb1_taxonomy_topics(slug);

ALTER TABLE eb1_benchmark_matches
  ADD CONSTRAINT fk_benchmark_matches_gt_topic_subtopic
    FOREIGN KEY (gt_topic, gt_sub_topic)
    REFERENCES eb1_taxonomy_subtopics(topic_slug, slug);

-- NOTE: model_topic/model_sub_topic intentionally have NO FK.
-- Benchmark models may produce topics in eb1_benchmark_taxonomy_*
-- (UNION ALL architecture) — can't FK across two tables.

-- NOTE: eb1_benchmark_raw topic/sub_topic have NO FK for the same reason.
