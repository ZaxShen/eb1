"""
Unit tests for bot-only template matching in the segmenter.

Covers:
  - _match_template  (difflib similarity matching)
  - _build_bot_only_segments with template enrichment

No LLM calls. No DB connections.
"""

from __future__ import annotations

from bson import ObjectId

from pipeline.segmentation.bot_processor import (
    _build_bot_only_segments,
    _match_template,
)
from pipeline.segmentation.windowing import PreSegmentChunk

# ── Sample templates ─────────────────────────────────────────────────────────

_TEMPLATES = [
    {
        "template_id": ObjectId(),
        "topic": "onboarding",
        "sub_topic": "profile_setup",
        "summary": "Welcomes the user and prompts profile completion.",
        "messages": [
            "Welcome to Acme! Let's get your profile set up.",
            "Please upload a photo to get started.",
        ],
    },
    {
        "template_id": ObjectId(),
        "topic": "match_status",
        "sub_topic": "match_drop_timing",
        "summary": "Notifies user their match has been dropped.",
        "messages": [
            "Unfortunately, your match didn't work out this time.",
            "Don't worry, we'll find someone great for you!",
        ],
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# _match_template
# ══════════════════════════════════════════════════════════════════════════════


class TestMatchTemplate:

    def test_exact_match_returns_classification(self):
        """Automated message identical to a template message -> matched."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is not None
        assert result["topic"] == "onboarding"
        assert result["sub_topic"] == "profile_setup"
        assert result["summary"] == (
            "Welcomes the user and prompts profile completion."
        )

    def test_similar_match_with_name_substitution(self):
        """Template with a substituted name still matches above 80%."""
        # Original: "Welcome to Acme! Let's get your profile set up."
        # Substituted: "Welcome to Acme! Let's get your profile set up, Sarah."
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": (
                    "Welcome to Acme! Let's get your profile set up, Sarah."
                ),
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is not None
        assert result["topic"] == "onboarding"

    def test_below_threshold_returns_none(self):
        """Message too different from any template -> None."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "This is a completely different message about weather.",
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is None

    def test_non_automated_messages_ignored(self):
        """Only type='automated' messages are compared; others skipped."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "assistant",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
            {
                "_id": ObjectId(),
                "type": "team",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is None

    def test_empty_templates_returns_none(self):
        """No templates loaded -> returns None (graceful fallback)."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "Welcome to Acme!",
            },
        ]
        result = _match_template(messages, [], threshold=0.8)
        assert result is None

    def test_none_templates_returns_none(self):
        """None templates -> returns None."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "Welcome to Acme!",
            },
        ]
        result = _match_template(messages, None, threshold=0.8)
        assert result is None

    def test_picks_best_match_across_templates(self):
        """When multiple templates match, picks the one with highest ratio."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": (
                    "Unfortunately, your match didn't work out this time."
                ),
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is not None
        assert result["topic"] == "match_status"
        assert result["sub_topic"] == "match_drop_timing"

    def test_multiple_automated_messages_best_wins(self):
        """Multiple automated messages — best single match determines result."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "Some random automated message.",
            },
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "Please upload a photo to get started.",
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is not None
        assert result["topic"] == "onboarding"

    def test_empty_message_text_skipped(self):
        """Automated message with empty text -> skipped, no crash."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "",
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is None

    def test_high_threshold_rejects_partial_match(self):
        """Threshold=0.99 rejects anything that isn't near-identical."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": (
                    "Welcome to Acme! Let's get your profile set up, Sarah."
                ),
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.99)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# _build_bot_only_segments with template enrichment
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildBotOnlySegmentsWithTemplates:

    def _make_chunk(self, messages: list[dict]) -> PreSegmentChunk:
        """Build a bot-only PreSegmentChunk from message dicts."""
        chunk = PreSegmentChunk(kind="bot_only")
        chat_id = ObjectId()
        for msg in messages:
            if "_id" not in msg:
                msg["_id"] = ObjectId()
            chunk.messages.append(msg)
            chunk.chat_ids.append(chat_id)
        return chunk

    def test_enriched_when_template_matches(self):
        """Bot-only segment gets topic/subTopic/summary from template match."""
        chunk = self._make_chunk([
            {
                "type": "automated",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
        ])
        uid = ObjectId()
        segs = _build_bot_only_segments(
            uid, chunk, templates=_TEMPLATES, template_match_threshold=0.8,
        )
        assert len(segs) == 1
        seg = segs[0]
        assert seg["topic"] == "onboarding"
        assert seg["sub_topic"] == "profile_setup"
        assert seg["summary"] is not None
        # bot-only — deterministic confidence; template match = deterministic, not LLM
        assert seg["label_confidence"] == 1.0
        assert seg["classified_at"] is not None
        assert seg["has_user_engagement"] is False

    def test_null_when_no_match(self):
        """Bot-only segment keeps null fields when no template matches."""
        chunk = self._make_chunk([
            {
                "type": "automated",
                "message": "Something completely unrecognizable xyz.",
            },
        ])
        uid = ObjectId()
        segs = _build_bot_only_segments(
            uid, chunk, templates=_TEMPLATES, template_match_threshold=0.8,
        )
        assert len(segs) == 1
        seg = segs[0]
        assert seg["topic"] is None
        assert seg["sub_topic"] is None
        assert seg["summary"] is None
        assert seg["label_confidence"] == 1.0  # bot-only — deterministic confidence
        assert seg["classified_at"] is None

    def test_null_when_templates_none(self):
        """templates=None (default) -> null classification, backward compat."""
        chunk = self._make_chunk([
            {
                "type": "automated",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
        ])
        uid = ObjectId()
        segs = _build_bot_only_segments(uid, chunk)
        assert len(segs) == 1
        seg = segs[0]
        assert seg["topic"] is None
        assert seg["sub_topic"] is None
        assert seg["label_confidence"] == 1.0  # bot-only — deterministic confidence
        assert seg["classified_at"] is None

    def test_null_when_templates_empty(self):
        """templates=[] -> null classification."""
        chunk = self._make_chunk([
            {
                "type": "automated",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
        ])
        uid = ObjectId()
        segs = _build_bot_only_segments(
            uid, chunk, templates=[], template_match_threshold=0.8,
        )
        assert len(segs) == 1
        assert segs[0]["topic"] is None

    def test_empty_chunk_returns_empty(self):
        """Empty chunk -> empty list regardless of templates."""
        chunk = PreSegmentChunk(kind="bot_only")
        uid = ObjectId()
        segs = _build_bot_only_segments(
            uid, chunk, templates=_TEMPLATES, template_match_threshold=0.8,
        )
        assert segs == []
