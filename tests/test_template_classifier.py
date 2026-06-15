"""
Unit tests for template classification pipeline.

Uses lightweight mocks (no real DB connection or API key required).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bson import ObjectId

from pipeline.config.loader import AnalyzerConfig, SubtopicEntry
from pipeline.templates.classifier import (
    _parse_classification,
    _update_template_taxonomy,
    fetch_templates,
    run_template_classifier,
)

# ── Mock helpers ─────────────────────────────────────────────────────────────


def _cfg() -> AnalyzerConfig:
    """Build a minimal AnalyzerConfig with default collection names."""
    return AnalyzerConfig(
        model="test-model",
        prompt_version="v2",
        bot_prompt_version="bot_v1",
        temperature=0.0,
        base_url="https://test.example.com/v1",
        drop_existing=False,
        drop_reviewed=False,
        seg_concurrency=1,
        benchmark_mode=False,
        window_size=200,
        bot_gap_seconds=60,
        user_window_days=7,
        cluster_confidence_threshold=0.6,
        template_match_threshold=0.8,
        user_limit=0,
        relabel=False,
        col_input_user="users",
        col_input_chat="sms_chats",
        col_input_chat_message="sms_chat_messages",
        col_input_matching="matchings",
        col_input_message_template="message_templates",
        col_output_chat_segment="sms_chat_segments",
        col_output_matching_signal="matching_signals",
        col_output_template_classification="message_template_classifications",
        col_output_chat_taxonomy="sms_chat_taxonomy",
    )


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = docs
        self._inserted: list[dict] = []

    def find(self, query=None, projection=None):
        # Simplified: return all docs (tests control input data)
        return FakeCursor(self._docs)

    def distinct(self, field: str):
        vals: list = []
        for doc in self._docs:
            v = doc.get(field)
            if v is not None and v not in vals:
                vals.append(v)
        return vals

    def insert_one(self, doc: dict):
        self._inserted.append(doc)

    def count_documents(self, query=None):
        return len(self._docs)


class FakeDB:
    def __init__(self, collections: dict[str, FakeCollection]):
        self._collections = collections

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.get(name, FakeCollection([]))


# ── Fetch tests ──────────────────────────────────────────────────────────────


class TestFetchTemplates:

    def test_skips_docs_without_imessage_content(self):
        """Doc without imessageContent field is excluded."""
        docs = [
            {"_id": ObjectId(), "name": "no-imsg", "content": "hello"},
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(docs),
        })
        result = fetch_templates(input_db, _cfg())
        assert len(result) == 0

    def test_skips_empty_imessage_content(self):
        """Doc with imessageContent: [] is excluded."""
        docs = [
            {
                "_id": ObjectId(),
                "name": "empty",
                "imessageContent": [],
            },
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(docs),
        })
        result = fetch_templates(input_db, _cfg())
        assert len(result) == 0

    def test_extracts_messages(self):
        """Doc with 2 imessageContent objects -> list of 2 messages."""
        tid = ObjectId()
        docs = [
            {
                "_id": tid,
                "name": "welcome",
                "imessageContent": [
                    {"message": "Hello!"},
                    {"message": "Welcome to Acme!"},
                ],
            },
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(docs),
        })
        result = fetch_templates(input_db, _cfg())
        assert len(result) == 1
        assert result[0]["_id"] == tid
        assert result[0]["messages"] == ["Hello!", "Welcome to Acme!"]
        assert result[0]["full_text"] == "Hello!\nWelcome to Acme!"

    def test_skips_imessage_objects_without_message(self):
        """imessageContent objects without 'message' key are ignored."""
        docs = [
            {
                "_id": ObjectId(),
                "name": "media-only",
                "imessageContent": [
                    {"media_url": "http://example.com/img.png"},
                ],
            },
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(docs),
        })
        result = fetch_templates(input_db, _cfg())
        assert len(result) == 0


# ── Parse tests ──────────────────────────────────────────────────────────────


class TestParseClassification:

    def test_valid_json(self):
        """Valid LLM JSON response -> parsed dict."""
        raw = (
            '{"topic": "technical_issues",'
            ' "subTopic": "app_glitch",'
            ' "summary": "App crash report"}'
        )
        result = _parse_classification(raw)
        assert result is not None
        assert result["topic"] == "technical_issues"
        assert result["subTopic"] == "app_glitch"
        assert result["summary"] == "App crash report"

    def test_markdown_fences_stripped(self):
        """JSON wrapped in markdown fences -> still parsed."""
        raw = (
            '```json\n{"topic": "technical_issues",'
            ' "subTopic": "app_glitch",'
            ' "summary": "test"}\n```'
        )
        result = _parse_classification(raw)
        assert result is not None
        assert result["topic"] == "technical_issues"

    def test_any_topic_accepted(self):
        """Any topic string accepted — no taxonomy validation."""
        raw = (
            '{"topic": "brand_new_topic",'
            ' "subTopic": "new_sub",'
            ' "summary": "test"}'
        )
        result = _parse_classification(raw)
        assert result is not None
        assert result["topic"] == "brand_new_topic"
        assert result["subTopic"] == "new_sub"

    def test_missing_fields_rejected(self):
        """Missing required fields -> returns None."""
        raw = '{"topic": "technical_issues"}'
        result = _parse_classification(raw)
        assert result is None

    def test_no_json_returns_none(self):
        """No JSON in response -> returns None."""
        raw = "I cannot classify this template."
        result = _parse_classification(raw)
        assert result is None


# ── Template taxonomy update tests ───────────────────────────────────────────


class TestUpdateTemplateTaxonomy:

    def test_new_topic_added(self):
        """New topic -> added to taxonomy."""
        from pipeline.config.loader import TaxonomyTopic
        taxonomy: dict[str, TaxonomyTopic] = {}
        changed = _update_template_taxonomy(
            taxonomy, "match_notification", "match_reveal",
            "Notifies user about match reveal",
        )
        assert changed is True
        assert "match_notification" in taxonomy
        assert "match_reveal" in taxonomy["match_notification"].subtopics

    def test_new_subtopic_added(self):
        """Existing topic, new subtopic -> subtopic added."""
        from pipeline.config.loader import TaxonomyTopic
        taxonomy = {
            "match_notification": TaxonomyTopic(
                description="Match notifications",
                subtopics={"match_reveal": SubtopicEntry(description="Match reveal")},
            ),
        }
        changed = _update_template_taxonomy(
            taxonomy, "match_notification", "match_reminder",
            "Reminds user about upcoming match",
        )
        assert changed is True
        assert "match_reminder" in taxonomy["match_notification"].subtopics

    def test_existing_pair_not_changed(self):
        """Existing topic + subtopic -> no change."""
        from pipeline.config.loader import TaxonomyTopic
        taxonomy = {
            "match_notification": TaxonomyTopic(
                description="Match notifications",
                subtopics={"match_reveal": SubtopicEntry(description="Match reveal")},
            ),
        }
        changed = _update_template_taxonomy(
            taxonomy, "match_notification", "match_reveal",
            "Same summary",
        )
        assert changed is False


# ── Orchestrator tests ───────────────────────────────────────────────────────


def _make_template_repo(existing_ids: set[str] | None = None) -> MagicMock:
    """Build a mock TemplateMappingRepository."""
    repo = MagicMock()
    repo.existing_template_ids.return_value = existing_ids or set()
    return repo


class TestRunTemplateClassifier:

    @patch("pipeline.templates.classifier.save_template_taxonomy_to_db")
    @patch("pipeline.templates.classifier.load_template_taxonomy_from_db")
    def test_idempotency_skips_already_classified(
        self, mock_load_tax, mock_save_tax,
    ):
        """Template already in PG -> not re-classified."""
        mock_load_tax.return_value = {}
        tid = ObjectId()
        templates = [
            {
                "_id": tid,
                "name": "welcome",
                "imessageContent": [{"message": "Hello!"}],
            },
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(templates),
        })
        template_repo = _make_template_repo(existing_ids={str(tid)})

        result = run_template_classifier(
            input_db, _cfg(), template_repo=template_repo,
        )
        assert result["templates_skipped"] == 1
        assert result["templates_classified"] == 0
        template_repo.upsert.assert_not_called()

    @patch("pipeline.templates.classifier.save_template_taxonomy_to_db")
    @patch("pipeline.templates.classifier.load_template_taxonomy_from_db")
    @patch("pipeline.templates.classifier.classify_one")
    def test_classifies_new_template(
        self, mock_classify, mock_load_tax, mock_save_tax,
    ):
        """New template -> classified, upserted to PG, taxonomy updated."""
        mock_load_tax.return_value = {}
        mock_classify.return_value = {
            "topic": "pre_match_inquiry",
            "subTopic": "match_status_inquiry",
            "summary": "Notifies user about match status",
        }
        tid = ObjectId()
        templates = [
            {
                "_id": tid,
                "name": "match-update",
                "imessageContent": [
                    {"message": "Your match is ready!"},
                ],
            },
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(templates),
        })
        template_repo = _make_template_repo()

        taxonomy_repo = MagicMock()
        result = run_template_classifier(
            input_db, _cfg(), template_repo=template_repo,
            taxonomy_repo=taxonomy_repo,
        )
        assert result["templates_classified"] == 1
        assert result["templates_skipped"] == 0
        template_repo.upsert.assert_called_once_with(
            template_id=str(tid),
            topic_slug="pre_match_inquiry",
            subtopic_slug="match_status_inquiry",
            name="match-update",
            summary="Notifies user about match status",
            messages=["Your match is ready!"],
        )
        # Taxonomy should have been saved with new topic
        mock_save_tax.assert_called_once()

    @patch("pipeline.templates.classifier.save_template_taxonomy_to_db")
    @patch("pipeline.templates.classifier.load_template_taxonomy_from_db")
    @patch("pipeline.templates.classifier.classify_one")
    def test_skips_on_classification_failure(
        self, mock_classify, mock_load_tax, mock_save_tax,
    ):
        """LLM returns None -> template skipped, not upserted."""
        mock_load_tax.return_value = {}
        mock_classify.return_value = None
        templates = [
            {
                "_id": ObjectId(),
                "name": "broken",
                "imessageContent": [{"message": "???"}],
            },
        ]
        input_db = FakeDB({
            "message_templates": FakeCollection(templates),
        })
        template_repo = _make_template_repo()

        result = run_template_classifier(
            input_db, _cfg(), template_repo=template_repo,
            taxonomy_repo=MagicMock(),
        )
        assert result["templates_classified"] == 0
        assert result["templates_skipped"] == 1
        template_repo.upsert.assert_not_called()

    @patch("pipeline.templates.classifier.save_template_taxonomy_to_db")
    @patch("pipeline.templates.classifier.load_template_taxonomy_from_db")
    def test_empty_collection(self, mock_load_tax, mock_save_tax):
        """No templates in PROD -> returns zeros."""
        mock_load_tax.return_value = {}
        input_db = FakeDB({
            "message_templates": FakeCollection([]),
        })
        result = run_template_classifier(
            input_db, _cfg(), template_repo=_make_template_repo(),
            taxonomy_repo=MagicMock(),
        )
        assert result["templates_fetched"] == 0
        assert result["templates_classified"] == 0
