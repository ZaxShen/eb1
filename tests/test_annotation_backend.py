"""TestClient tests for the annotation backend — fully offline, no network.

A fixture datasets dir is built in a tmp path: a tiny ``sample.jsonl`` (WildChat
shape), a seeded ``metadata.db`` (with a couple of taxonomy rows), and an
``output.db`` whose ``run_segment`` rows are inserted directly so a conversation
has multiple segments to split/merge. The backend's datasets root is pointed at
this tmp dir via ``routes.set_datasets_root``.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from annotation.backend import db, routes
from annotation.backend.app import create_app
from pipeline.metadata.seed_wildchat import seed as seed_wildchat

CONV_A = "a1f3c9d2e7b40516"
CONV_B = "b7e2a4f10c8d9933"

_SAMPLE_ROWS = [
    {
        "conversation_hash": CONV_A,
        "model": "gpt-4",
        "timestamp": "2023-08-14T09:12:00Z",
        "turn": 3,
        "language": "English",
        "conversation": [
            {"role": "user", "content": "Draft a cover letter opening."},
            {"role": "assistant", "content": "Here is an opening paragraph."},
            {"role": "user", "content": "How far is the Andromeda galaxy?"},
            {"role": "assistant", "content": "About 2.5 million light-years."},
        ],
    },
    {
        "conversation_hash": CONV_B,
        "model": "gpt-4",
        "timestamp": "2023-08-15T10:00:00Z",
        "turn": 2,
        "language": "English",
        "conversation": [
            {"role": "user", "content": "Implement binary search in Python."},
            {"role": "assistant", "content": "Here is a binary search function."},
        ],
    },
]

_RUN_SEGMENTS = [
    {
        "dataset": "wildchat",
        "conversation": CONV_A,
        "chunk_index": 0,
        "message_indices": [0, 1],
        "summary": "Cover letter help",
        "topic": "writing_help",
        "subtopic": "cover_letter_drafting",
        "sentiment": "neutral",
        "label_confidence": 0.95,
    },
    {
        "dataset": "wildchat",
        "conversation": CONV_A,
        "chunk_index": 0,
        "message_indices": [2, 3],
        "summary": "Astronomy fact",
        "topic": "factual_question",
        "subtopic": "astronomy_fact",
        "sentiment": "neutral",
        "label_confidence": 0.40,
    },
    {
        "dataset": "wildchat",
        "conversation": CONV_B,
        "chunk_index": 0,
        "message_indices": [0, 1],
        "summary": "Binary search",
        "topic": "coding_help",
        "subtopic": "binary_search_implementation",
        "sentiment": "neutral",
        "label_confidence": 0.92,
    },
]

_OUTPUT_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_segment (
    id            INTEGER PRIMARY KEY,
    dataset       TEXT,
    conversation  TEXT,
    chunk_index   INTEGER,
    message_indices TEXT,
    summary       TEXT,
    topic         TEXT,
    subtopic      TEXT,
    sentiment     TEXT,
    label_confidence REAL,
    raw           TEXT
);
"""


def _build_output_db(path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_OUTPUT_SCHEMA)
        for rec in _RUN_SEGMENTS:
            conn.execute(
                "INSERT INTO run_segment "
                "(dataset, conversation, chunk_index, message_indices, summary, "
                "topic, subtopic, sentiment, label_confidence, raw) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec["dataset"],
                    rec["conversation"],
                    rec["chunk_index"],
                    json.dumps(rec["message_indices"]),
                    rec["summary"],
                    rec["topic"],
                    rec["subtopic"],
                    rec["sentiment"],
                    rec["label_confidence"],
                    json.dumps(rec),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_taxonomy(metadata_db) -> None:
    conn = sqlite3.connect(str(metadata_db))
    try:
        conn.execute(
            "INSERT INTO taxonomy (kind, topic, subtopic, description) VALUES (?, ?, ?, ?)",
            ("user", "writing_help", "cover_letter_drafting", "Drafting cover letters"),
        )
        conn.execute(
            "INSERT INTO taxonomy (kind, topic, subtopic, description) VALUES (?, ?, ?, ?)",
            ("user", "coding_help", "binary_search_implementation", "Coding assistance"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def datasets_root(tmp_path):
    """Build a tmp ``datasets/wildchat`` fixture and point the backend at it."""
    ds_dir = tmp_path / "wildchat"
    ds_dir.mkdir(parents=True)

    sample = ds_dir / "sample.jsonl"
    sample.write_text(
        "\n".join(json.dumps(r) for r in _SAMPLE_ROWS) + "\n", encoding="utf-8"
    )

    seed_wildchat(ds_dir / "metadata.db")
    _seed_taxonomy(ds_dir / "metadata.db")
    _build_output_db(ds_dir / "output.db")

    routes.set_datasets_root(tmp_path)
    yield tmp_path
    routes.set_datasets_root(None)


@pytest.fixture()
def client(datasets_root):
    return TestClient(create_app())


def test_list_datasets(client):
    resp = client.get("/api/datasets")
    assert resp.status_code == 200
    assert resp.json() == ["wildchat"]


def test_list_segments_lists_fixture_rows(client):
    resp = client.get("/api/datasets/wildchat/segments")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(_RUN_SEGMENTS)
    topics = {s["topic"] for s in body}
    assert {"writing_help", "factual_question", "coding_help"} <= topics
    assert all(s["reviewed"] is False for s in body)


def test_list_segments_filters(client):
    resp = client.get("/api/datasets/wildchat/segments", params={"topic": "coding_help"})
    assert [s["topic"] for s in resp.json()] == ["coding_help"]

    resp = client.get(
        "/api/datasets/wildchat/segments", params={"max_confidence": 0.5}
    )
    confidences = [s["label_confidence"] for s in resp.json()]
    assert confidences == [0.40]


def test_get_segment_returns_messages_and_span(client):
    resp = client.get("/api/datasets/wildchat/segments/1")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["segment"]["id"] == 1
    assert len(detail["messages"]) == 4
    span_indices = [m["index"] for m in detail["span"]]
    assert span_indices == [0, 1]
    sibling_ids = {s["id"] for s in detail["siblings"]}
    assert sibling_ids == {1, 2}


def test_list_conversations_one_row_per_conversation(client):
    resp = client.get("/api/datasets/wildchat/conversations")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    by_conv = {r["conversation"]: r for r in rows}
    assert set(by_conv) == {CONV_A, CONV_B}

    a = by_conv[CONV_A]
    assert a["message_count"] == 4
    assert a["segment_count"] == 2
    assert set(a["topics"]) == {"writing_help", "factual_question"}
    assert a["reviewed_count"] == 0
    assert a["reviewed"] is False

    b = by_conv[CONV_B]
    assert b["message_count"] == 2
    assert b["segment_count"] == 1
    assert b["topics"] == ["coding_help"]


def test_list_conversations_reflects_review_state(client):
    client.post(
        "/api/datasets/wildchat/segments/3/annotate",
        json={"true_topic": "coding_help", "true_subtopic": "binary_search_implementation"},
    )
    rows = {r["conversation"]: r for r in client.get(
        "/api/datasets/wildchat/conversations"
    ).json()}
    assert rows[CONV_B]["reviewed_count"] == 1
    assert rows[CONV_B]["reviewed"] is True
    assert rows[CONV_A]["reviewed"] is False


def test_get_conversation_boundary_view(client):
    resp = client.get(f"/api/datasets/wildchat/conversations/{CONV_A}")
    assert resp.status_code == 200
    view = resp.json()
    assert view["conversation"] == CONV_A
    assert len(view["messages"]) == 4
    assert len(view["segments"]) == 2
    assert view["gold_segments"] == []


def test_taxonomy_returns_provider_topics(client):
    resp = client.get("/api/datasets/wildchat/taxonomy")
    assert resp.status_code == 200
    topics = {row["topic"] for row in resp.json()}
    assert {"writing_help", "coding_help"} <= topics


def test_annotate_writes_gold_and_flips_stats(client, datasets_root):
    before = client.get("/api/datasets/wildchat/stats").json()
    assert before["reviewed"] == 0

    resp = client.post(
        "/api/datasets/wildchat/segments/2/annotate",
        json={
            "true_topic": "science_question",
            "true_subtopic": "astronomy_fact",
            "reviewed_by": "alice",
        },
    )
    assert resp.status_code == 200
    gold_id = resp.json()["gold_segment_id"]
    assert gold_id >= 1

    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    relabel = [g for g in gold if g["base_segment_id"] == 2]
    assert len(relabel) == 1
    assert relabel[0]["topic"] == "science_question"
    assert relabel[0]["reviewed_by"] == "alice"
    assert relabel[0]["source"] == "relabel"

    after = client.get("/api/datasets/wildchat/stats").json()
    assert after["reviewed"] == 1
    assert after["unreviewed"] == before["unreviewed"] - 1


def test_annotate_is_idempotent_no_duplicate_gold(client, datasets_root):
    payload = {"true_topic": "writing_help", "true_subtopic": "cover_letter_drafting"}
    client.post("/api/datasets/wildchat/segments/1/annotate", json=payload)
    client.post("/api/datasets/wildchat/segments/1/annotate", json=payload)

    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    mirrored = [g for g in gold if g["base_segment_id"] == 1]
    assert len(mirrored) == 1
    assert mirrored[0]["source"] == "confirm"


def test_clear_annotation_reverts_segment_to_unannotated(client, datasets_root):
    client.post(
        "/api/datasets/wildchat/segments/2/annotate",
        json={"true_topic": "science_question", "true_subtopic": "astronomy_fact"},
    )
    assert client.get("/api/datasets/wildchat/stats").json()["reviewed"] == 1
    detail = client.get("/api/datasets/wildchat/segments/2").json()
    assert detail["segment"]["true_topic"] == "science_question"
    assert detail["segment"]["reviewed"] is True

    resp = client.delete("/api/datasets/wildchat/segments/2/annotate")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    assert [g for g in gold if g["base_segment_id"] == 2] == []
    assert client.get("/api/datasets/wildchat/stats").json()["reviewed"] == 0
    detail = client.get("/api/datasets/wildchat/segments/2").json()
    assert detail["segment"]["true_topic"] is None
    assert detail["segment"]["reviewed"] is False


def test_clear_annotation_unknown_segment_404(client):
    assert (
        client.delete("/api/datasets/wildchat/segments/999/annotate").status_code
        == 404
    )


def test_boundaries_split_persists_two_gold_rows(client, datasets_root):
    resp = client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries",
        json={
            "segments": [
                {
                    "message_indices": [0, 1],
                    "topic": "writing_help",
                    "subtopic": "cover_letter_drafting",
                },
                {
                    "message_indices": [2, 3],
                    "topic": "factual_question",
                    "subtopic": "astronomy_fact",
                },
            ],
            "reviewed_by": "bob",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["gold_segments_written"] == 2

    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    assert len(gold) == 2
    assert all(g["source"] == "boundary" for g in gold)
    assert all(g["base_segment_id"] is None for g in gold)
    assert [g["message_indices"] for g in gold] == [[0, 1], [2, 3]]


def test_boundaries_replace_collapses_to_posted_spans(client, datasets_root):
    three = {
        "segments": [
            {"message_indices": [0]},
            {"message_indices": [1, 2]},
            {"message_indices": [3]},
        ]
    }
    client.post(f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries", json=three)

    one = {"segments": [{"message_indices": [0, 1, 2, 3]}]}
    resp = client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries", json=one
    )
    assert resp.json()["gold_segments_written"] == 1

    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    assert len(gold) == 1
    assert gold[0]["message_indices"] == [0, 1, 2, 3]


def _split_conv_a(client) -> None:
    """Split CONV_A's predicted [0,1]+[2,3] into a single [0,1,2,3] gold span,
    then re-split into [0,1]+[2,3] WITHOUT posting topics, so the effective
    topics must be inherited from the overlapping predicted segments."""
    client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries",
        json={
            "segments": [
                {"message_indices": [0, 1]},
                {"message_indices": [2, 3]},
            ]
        },
    )


def test_effective_split_inherits_predicted_topics(client):
    """After splitting a predicted span without explicit topics, /conversations
    returns the new spans with INHERITED topics, not empty — the core re-segment
    fix. Predicted [0,1]=writing_help, [2,3]=factual_question."""
    _split_conv_a(client)
    view = client.get(f"/api/datasets/wildchat/conversations/{CONV_A}").json()
    spans = view["segments"]
    assert len(spans) == 2
    by_span = {tuple(s["message_indices"]): s for s in spans}
    assert by_span[(0, 1)]["topic"] == "writing_help"
    assert by_span[(0, 1)]["subtopic"] == "cover_letter_drafting"
    assert by_span[(2, 3)]["topic"] == "factual_question"
    assert by_span[(2, 3)]["subtopic"] == "astronomy_fact"
    assert all(s["topic"] for s in spans)


def test_effective_merge_takes_primary_overlapped_topic(client):
    """Merging predicted [0,1]+[2,3] into one [0,1,2,3] span (no topic posted)
    inherits the primary (most-overlapped) predicted segment's topic."""
    client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries",
        json={"segments": [{"message_indices": [0, 1, 2, 3]}]},
    )
    view = client.get(f"/api/datasets/wildchat/conversations/{CONV_A}").json()
    assert len(view["segments"]) == 1
    assert view["segments"][0]["topic"] in {"writing_help", "factual_question"}
    assert view["segments"][0]["topic"]


def test_effective_no_gold_returns_predicted_unchanged(client):
    """A conversation with no gold edits returns the predicted segments verbatim."""
    view = client.get(f"/api/datasets/wildchat/conversations/{CONV_B}").json()
    spans = view["segments"]
    assert len(spans) == 1
    assert spans[0]["message_indices"] == [0, 1]
    assert spans[0]["topic"] == "coding_help"


def test_list_and_stats_reflect_effective_after_split(client):
    """A split that yields the same span count keeps counts; a merge to one span
    drops the effective count in both the conversations list and /stats."""
    client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries",
        json={"segments": [{"message_indices": [0, 1, 2, 3]}]},
    )
    rows = {r["conversation"]: r for r in client.get(
        "/api/datasets/wildchat/conversations"
    ).json()}
    assert rows[CONV_A]["segment_count"] == 1
    assert rows[CONV_B]["segment_count"] == 1

    stats = client.get("/api/datasets/wildchat/stats").json()
    assert stats["total"] == 2


def test_list_and_stats_reflect_effective_split_into_three(client):
    """Splitting CONV_A into three spans surfaces three effective segments in the
    list and bumps /stats total to 4 (3 for CONV_A + 1 for CONV_B)."""
    client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries",
        json={
            "segments": [
                {"message_indices": [0]},
                {"message_indices": [1, 2]},
                {"message_indices": [3]},
            ]
        },
    )
    rows = {r["conversation"]: r for r in client.get(
        "/api/datasets/wildchat/conversations"
    ).json()}
    assert rows[CONV_A]["segment_count"] == 3
    assert client.get("/api/datasets/wildchat/stats").json()["total"] == 4


def test_relabel_overrides_topic_in_effective(client):
    """A relabel overrides the segment's topic/subtopic in the effective view
    while leaving the conversation's segment count unchanged (no boundary edit)."""
    client.post(
        "/api/datasets/wildchat/segments/2/annotate",
        json={"true_topic": "science_question", "true_subtopic": "astronomy_fact"},
    )
    view = client.get(f"/api/datasets/wildchat/conversations/{CONV_A}").json()
    assert len(view["segments"]) == 2
    by_span = {tuple(s["message_indices"]): s for s in view["segments"]}
    relabeled = by_span[(2, 3)]
    assert relabeled["topic"] == "science_question"
    assert relabeled["true_topic"] == "science_question"
    assert relabeled["reviewed"] is True

    stats = client.get("/api/datasets/wildchat/stats").json()
    assert stats["per_topic"].get("science_question") == 1
    assert "factual_question" not in stats["per_topic"]


def test_unknown_dataset_404(client):
    assert client.get("/api/datasets/nope/segments").status_code == 404
    assert client.get("/api/datasets/nope/stats").status_code == 404


def test_unknown_segment_404(client):
    assert client.get("/api/datasets/wildchat/segments/999").status_code == 404


def test_datasets_root_defaults_to_datasets(monkeypatch):
    monkeypatch.delenv("EB1_DATASETS_DIR", raising=False)
    assert db.datasets_root() == db.DEFAULT_DATASETS_ROOT


def test_datasets_root_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("EB1_DATASETS_DIR", str(tmp_path))
    assert db.datasets_root() == tmp_path
    # The override flows through to every path helper, isolating fixture data.
    assert db.output_db_path("wildchat") == tmp_path / "wildchat" / "output.db"


def test_env_override_lists_only_fixture_datasets(monkeypatch, tmp_path):
    ds_dir = tmp_path / "wildchat"
    ds_dir.mkdir()
    _build_output_db(ds_dir / "output.db")
    monkeypatch.setenv("EB1_DATASETS_DIR", str(tmp_path))

    client = TestClient(create_app())
    assert client.get("/api/datasets").json() == ["wildchat"]
