"""
Unit tests for pipeline/segmentation/bot_processor.py.

Covers _match_template — a pure function with no DB or LLM dependencies.
"""

from __future__ import annotations

from bson import ObjectId

from pipeline.segmentation.bot_processor import _match_template

_TEMPLATES = [
    {
        "topic": "onboarding",
        "sub_topic": "profile_setup",
        "summary": "Welcomes the user and prompts profile completion.",
        "messages": [
            "Welcome to Acme! Let's get your profile set up.",
            "Please upload a photo to get started.",
        ],
    },
]


class TestMatchTemplate:

    def test_exact_match_returns_high_score(self):
        """Template with identical messages should match."""
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

    def test_no_match_below_threshold(self):
        """Completely different messages should return None."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "xyz abc completely unrelated content 123",
            },
        ]
        result = _match_template(messages, _TEMPLATES, threshold=0.8)
        assert result is None

    def test_empty_templates(self):
        """No templates -> None."""
        messages = [
            {
                "_id": ObjectId(),
                "type": "automated",
                "message": "Welcome to Acme! Let's get your profile set up.",
            },
        ]
        result = _match_template(messages, [], threshold=0.8)
        assert result is None

    def test_empty_messages(self):
        """No messages -> None."""
        result = _match_template([], _TEMPLATES, threshold=0.8)
        assert result is None
