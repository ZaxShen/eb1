"""DSN-gated tests for the BERTopic DB groundwork.

Exercise ``gold_segment_texts`` (per-gold-segment concatenated utterance text)
and ``write_bertopic_labels`` (round-trips bertopic_topic/subtopic onto gold rows
and surfaces them through the segment read projection). Skipped when
``EB1_ANNOTATION_DSN`` is unset so the offline suite stays green::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_test
    uv run pytest tests/test_annotation_bertopic.py -q
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

from annotation.backend import db  # noqa: E402

DATASET = "superdialseg"
CONV = "bertopic-conv-1"

_CONVERSATIONS = [
    {
        "ext_id": CONV,
        "messages": [
            {"role": "user", "content": "How do I reset my password?"},
            {"role": "agent", "content": "Open settings and click reset."},
            {"role": "user", "content": "What about my billing plan?"},
            {"role": "agent", "content": "You are on the annual plan."},
        ],
        "gold_segments": [
            {"message_indices": [0, 1], "topic": "account", "subtopic": "password"},
            {"message_indices": [2, 3], "topic": "billing", "subtopic": "plan"},
        ],
    }
]


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.reset_pool()
    db.apply_schema()
    yield
    db.reset_pool()


@pytest.fixture()
def seeded():
    db.ensure_dataset(DATASET)
    db.ingest_batch(DATASET, _CONVERSATIONS)
    yield
    db.ingest_batch(DATASET, [{"ext_id": CONV, "messages": [], "gold_segments": []}])


def test_gold_segment_texts_concatenates_span_utterances(seeded):
    rows = db.gold_segment_texts(DATASET)
    rows = [r for r in rows if r["conversation"] == CONV]
    assert len(rows) == 2
    for r in rows:
        assert r["text"]
        assert "segment_id" in r
    first, second = rows
    assert first["text"] == "How do I reset my password?\nOpen settings and click reset."
    assert second["text"] == "What about my billing plan?\nYou are on the annual plan."


def test_write_bertopic_labels_round_trips_onto_gold(seeded):
    texts = [r for r in db.gold_segment_texts(DATASET) if r["conversation"] == CONV]
    seg_id = texts[0]["segment_id"]
    applied = db.write_bertopic_labels(
        [{"segment_id": seg_id, "topic": "account_topic", "subtopic": "password_subtopic"}]
    )
    assert applied == 1

    gold = db.read_gold_segments(DATASET, CONV)
    target = next(g for g in gold if g["id"] == seg_id)
    assert "bertopic_topic" not in target  # gold_segments view omits them

    detail = db.conversation_detail(DATASET, CONV)
    eff = {s["id"]: s for s in detail["gold"]}
    assert eff[seg_id]["bertopic_topic"] == "account_topic"
    assert eff[seg_id]["bertopic_subtopic"] == "password_subtopic"


def test_write_bertopic_labels_empty_is_noop(seeded):
    assert db.write_bertopic_labels([]) == 0
