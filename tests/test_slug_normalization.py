"""Tests for slug normalization and cross-source guard in segmenter.py."""

from unittest.mock import MagicMock

import pipeline.config.loader as loader


class TestNormalizeSlug:
    """Tests for _normalize_slug()."""

    def test_already_normalized(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("hello_world") == "hello_world"

    def test_hyphens_converted(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("non-event_match") == "non_event_match"

    def test_mixed_case_and_hyphens(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("Non-Event_Match") == "non_event_match"

    def test_spaces_converted(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("hello world") == "hello_world"

    def test_multiple_underscores_collapsed(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("hello__world") == "hello_world"

    def test_leading_trailing_underscores_stripped(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("_hello_") == "hello"

    def test_empty_string(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("") == ""

    def test_whitespace_only(self):
        from pipeline.segmentation.preprocessing import _normalize_slug

        assert _normalize_slug("  ") == ""


class TestSlugToDisplayName:
    """Tests for _slug_to_display_name()."""

    def test_multi_word_slug(self):
        from pipeline.segmentation.preprocessing import _slug_to_display_name

        assert _slug_to_display_name("match_feedback") == "Match Feedback"

    def test_three_word_slug(self):
        from pipeline.segmentation.preprocessing import _slug_to_display_name

        assert _slug_to_display_name("post_date_response") == "Post Date Response"

    def test_empty_string(self):
        from pipeline.segmentation.preprocessing import _slug_to_display_name

        assert _slug_to_display_name("") == ""

    def test_single_word(self):
        from pipeline.segmentation.preprocessing import _slug_to_display_name

        assert _slug_to_display_name("single") == "Single"


class TestCrossSourceGuard:
    """Tests for cross-source guard in _ensure_taxonomy_entry()."""

    def test_bot_only_false_skips_upsert_when_topic_in_bot_taxonomy(self, monkeypatch):
        """When bot_only=False and topic exists in BOT_TAXONOMY, update_one must NOT be called."""
        from pipeline.segmentation.segmenter import _ensure_taxonomy_entry

        original_bot_taxonomy = dict(loader.BOT_TAXONOMY)
        original_user_taxonomy = dict(loader.INITIAL_TAXONOMY)
        try:
            # Put the topic in BOT_TAXONOMY (the OTHER source) but not in INITIAL_TAXONOMY
            loader.BOT_TAXONOMY["shared_topic"] = "a bot topic"
            loader.INITIAL_TAXONOMY.pop("shared_topic", None)

            mock_repo = MagicMock()
            mock_cfg = MagicMock()
            mock_cfg.model = "test-model"

            _ensure_taxonomy_entry(mock_repo,"shared_topic", "some_sub", mock_cfg, bot_only=False)

            # update_one must NOT have been called
            assert not mock_repo.upsert_topic.called
        finally:
            loader.BOT_TAXONOMY.clear()
            loader.BOT_TAXONOMY.update(original_bot_taxonomy)
            loader.INITIAL_TAXONOMY.clear()
            loader.INITIAL_TAXONOMY.update(original_user_taxonomy)

    def test_bot_only_true_skips_upsert_when_topic_in_user_taxonomy(self, monkeypatch):
        """When bot_only=True and topic exists in INITIAL_TAXONOMY, update_one must NOT be called."""
        from pipeline.segmentation.segmenter import _ensure_taxonomy_entry

        original_bot_taxonomy = dict(loader.BOT_TAXONOMY)
        original_user_taxonomy = dict(loader.INITIAL_TAXONOMY)
        original_bot_subs = dict(loader.BOT_KNOWN_SUBTOPICS)
        try:
            # Put the topic in INITIAL_TAXONOMY (the OTHER source) but not in BOT_TAXONOMY
            loader.INITIAL_TAXONOMY["user_only_topic"] = "a user topic"
            loader.BOT_TAXONOMY.pop("user_only_topic", None)

            mock_repo = MagicMock()
            mock_cfg = MagicMock()
            mock_cfg.model = "test-model"

            _ensure_taxonomy_entry(mock_repo,"user_only_topic", "some_sub", mock_cfg, bot_only=True)

            # update_one must NOT have been called
            assert not mock_repo.upsert_topic.called
        finally:
            loader.BOT_TAXONOMY.clear()
            loader.BOT_TAXONOMY.update(original_bot_taxonomy)
            loader.INITIAL_TAXONOMY.clear()
            loader.INITIAL_TAXONOMY.update(original_user_taxonomy)
            loader.BOT_KNOWN_SUBTOPICS.clear()
            loader.BOT_KNOWN_SUBTOPICS.update(original_bot_subs)

    def test_no_conflict_allows_upsert(self, monkeypatch):
        """When there is no cross-source conflict, update_one IS called (existing behavior)."""
        from pipeline.segmentation.segmenter import _ensure_taxonomy_entry

        original_user_taxonomy = dict(loader.INITIAL_TAXONOMY)
        original_user_subs = dict(loader.KNOWN_SUBTOPICS)
        original_bot_taxonomy = dict(loader.BOT_TAXONOMY)
        try:
            # Topic is new to both sources
            loader.INITIAL_TAXONOMY.pop("brand_new_topic", None)
            loader.KNOWN_SUBTOPICS.pop("brand_new_topic", None)
            loader.BOT_TAXONOMY.pop("brand_new_topic", None)

            mock_repo = MagicMock()
            mock_cfg = MagicMock()
            mock_cfg.model = "test-model"

            _ensure_taxonomy_entry(mock_repo,"brand_new_topic", "new_sub", mock_cfg, bot_only=False)

            # update_one MUST have been called — normal upsert path
            assert mock_repo.upsert_topic.called
        finally:
            loader.INITIAL_TAXONOMY.clear()
            loader.INITIAL_TAXONOMY.update(original_user_taxonomy)
            loader.KNOWN_SUBTOPICS.clear()
            loader.KNOWN_SUBTOPICS.update(original_user_subs)
            loader.BOT_TAXONOMY.clear()
            loader.BOT_TAXONOMY.update(original_bot_taxonomy)
