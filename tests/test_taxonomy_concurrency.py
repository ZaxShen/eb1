"""Tests for taxonomy concurrency safety — append-only writes + freshness checks."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pipeline.config.loader as loader


class TestEnsureTaxonomyAppendOnly:
    """Verify _ensure_taxonomy_entry upserts via TaxonomyRepository."""

    def test_new_topic_calls_upsert_topic_and_subtopic(self, monkeypatch):
        """When a topic is new to the cache, upsert_topic and upsert_subtopic are called."""
        from pipeline.segmentation.segmenter import _ensure_taxonomy_entry

        original_taxonomy = dict(loader.INITIAL_TAXONOMY)
        original_subs = dict(loader.KNOWN_SUBTOPICS)
        try:
            loader.INITIAL_TAXONOMY.clear()
            loader.KNOWN_SUBTOPICS.clear()
            loader.SUBTOPIC_DESCRIPTIONS.clear()
            loader.TOPIC_CONFIRMED.clear()
            loader.SUBTOPIC_CONFIRMED.clear()

            mock_repo = MagicMock()
            mock_cfg = MagicMock()
            mock_cfg.model = "test-model"

            _ensure_taxonomy_entry(mock_repo, "new_topic", "new_sub", mock_cfg)

            mock_repo.upsert_topic.assert_called_once()
            call_kwargs = mock_repo.upsert_topic.call_args
            assert call_kwargs.kwargs["slug"] == "new_topic"
            assert call_kwargs.kwargs["name"] == "New Topic"
            assert call_kwargs.kwargs["topic_type"] == "user"

            mock_repo.upsert_subtopic.assert_called_once()
            sub_kwargs = mock_repo.upsert_subtopic.call_args
            assert sub_kwargs.kwargs["slug"] == "new_sub"
            assert sub_kwargs.kwargs["topic_slug"] == "new_topic"
            assert sub_kwargs.kwargs["name"] == "New Sub"
        finally:
            loader.INITIAL_TAXONOMY.update(original_taxonomy)
            loader.KNOWN_SUBTOPICS.update(original_subs)

    def test_existing_topic_new_subtopic_only(self, monkeypatch):
        """When topic exists but subtopic is new, only upsert_subtopic is called."""
        from pipeline.segmentation.segmenter import _ensure_taxonomy_entry

        original_subs = dict(loader.KNOWN_SUBTOPICS)
        try:
            loader.KNOWN_SUBTOPICS["pre_match_inquiry"] = {"match_release_inquiry"}

            mock_repo = MagicMock()
            mock_cfg = MagicMock()
            mock_cfg.model = "test-model"

            _ensure_taxonomy_entry(mock_repo, "pre_match_inquiry", "brand_new_sub", mock_cfg)

            mock_repo.upsert_topic.assert_not_called()
            mock_repo.upsert_subtopic.assert_called_once()
            sub_kwargs = mock_repo.upsert_subtopic.call_args
            assert sub_kwargs.kwargs["slug"] == "brand_new_sub"
            assert sub_kwargs.kwargs["name"] == "Brand New Sub"
        finally:
            loader.KNOWN_SUBTOPICS.update(original_subs)


class TestSaveTaxonomyAppendOnly:
    """Verify save_taxonomy_to_db delegates to repo.batch_upsert with correct shape."""

    def test_calls_batch_upsert_with_user_type(self):
        """save_taxonomy_to_db must call repo.batch_upsert with type='user'."""
        from pipeline.config.loader import SubtopicEntry, TaxonomyTopic, save_taxonomy_to_db

        mock_repo = MagicMock()

        taxonomy = {
            "test_topic": TaxonomyTopic(
                description="A test topic",
                confirmed_by="human",
                confirmed_at="2026-01-01",
                created_by="human",
                updated_by="human",
                subtopics={
                    "test_sub": SubtopicEntry(description="A subtopic"),
                },
            ),
        }

        save_taxonomy_to_db(mock_repo, taxonomy)

        assert mock_repo.batch_upsert.called
        args = mock_repo.batch_upsert.call_args
        topics_list, topic_type = args[0]
        assert topic_type == "user"
        assert len(topics_list) == 1

        topic = topics_list[0]
        assert topic["slug"] == "test_topic"
        assert topic["name"] == "Test Topic"
        assert topic["description"] == "A test topic"
        assert topic["confirmed_by"] == "human"
        assert topic["created_by"] == "human"
        assert len(topic["subtopics"]) == 1
        sub = topic["subtopics"][0]
        assert sub["slug"] == "test_sub"
        assert sub["name"] == "Test Sub"
        assert sub["description"] == "A subtopic"

    def test_save_template_taxonomy_calls_batch_upsert_with_bot_type(self):
        """save_template_taxonomy_to_db must call repo.batch_upsert with type='bot'."""
        from pipeline.config.loader import (
            SubtopicEntry,
            TaxonomyTopic,
            save_template_taxonomy_to_db,
        )

        mock_repo = MagicMock()

        taxonomy = {
            "bot_topic": TaxonomyTopic(
                description="A bot topic",
                subtopics={
                    "bot_sub": SubtopicEntry(description="A bot subtopic"),
                },
            ),
        }

        save_template_taxonomy_to_db(mock_repo, taxonomy)

        assert mock_repo.batch_upsert.called
        args = mock_repo.batch_upsert.call_args
        topics_list, topic_type = args[0]
        assert topic_type == "bot"
        assert len(topics_list) == 1

        topic = topics_list[0]
        assert topic["slug"] == "bot_topic"
        assert len(topic["subtopics"]) == 1
        assert topic["subtopics"][0]["slug"] == "bot_sub"

    def test_empty_taxonomy_does_not_call_batch_upsert(self):
        """save_taxonomy_to_db must not call batch_upsert when taxonomy is empty."""
        from pipeline.config.loader import save_taxonomy_to_db

        mock_repo = MagicMock()
        save_taxonomy_to_db(mock_repo, {})
        assert not mock_repo.batch_upsert.called


class TestTaxonomyFreshness:
    """Verify freshness detection and reload logic."""

    def test_refresh_returns_false_when_fresh(self):
        """When no external changes, refresh should return False."""
        mock_repo = MagicMock()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        loader._taxonomy_loaded_at = now

        # Repo returns updated_at BEFORE our load time
        old_time = now - timedelta(minutes=5)
        mock_repo.get_max_updated_at.return_value = old_time

        result = loader.refresh_taxonomy_if_stale(mock_repo)
        assert result is False
        mock_repo.get_max_updated_at.assert_called_once_with("user")

    def test_refresh_returns_true_when_stale(self):
        """When external changes detected, refresh should return True and reload."""
        mock_repo = MagicMock()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        loader._taxonomy_loaded_at = now - timedelta(minutes=10)

        # Repo returns updated_at AFTER our load time (external change)
        mock_repo.get_max_updated_at.return_value = now
        mock_repo.load_topics.return_value = [
            {"slug": "test_topic", "description": "test", "subtopics": []}
        ]

        result = loader.refresh_taxonomy_if_stale(mock_repo)
        assert result is True

    def test_refresh_template_returns_false_when_fresh(self):
        """refresh_template_taxonomy_if_stale returns False when cache is current."""
        mock_repo = MagicMock()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        loader._template_taxonomy_loaded_at = now

        old_time = now - timedelta(minutes=5)
        mock_repo.get_max_updated_at.return_value = old_time

        result = loader.refresh_template_taxonomy_if_stale(mock_repo)
        assert result is False
        mock_repo.get_max_updated_at.assert_called_once_with("bot")

    def test_refresh_template_returns_true_when_stale(self):
        """refresh_template_taxonomy_if_stale returns True on external changes."""
        mock_repo = MagicMock()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        loader._template_taxonomy_loaded_at = now - timedelta(minutes=10)

        mock_repo.get_max_updated_at.return_value = now
        mock_repo.load_topics.return_value = [
            {"slug": "bot_topic", "description": "bot", "subtopics": []}
        ]

        result = loader.refresh_template_taxonomy_if_stale(mock_repo)
        assert result is True

    def test_refresh_returns_true_when_never_loaded(self):
        """refresh_taxonomy_if_stale returns True and triggers init when never loaded."""
        mock_repo = MagicMock()

        loader._taxonomy_loaded_at = None
        mock_repo.load_topics.return_value = [
            {"slug": "some_topic", "description": "x", "subtopics": []}
        ]

        result = loader.refresh_taxonomy_if_stale(mock_repo)
        assert result is True
        assert loader._taxonomy_loaded_at is not None
