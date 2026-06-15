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


def test_unknown_dataset_404(client):
    assert client.get("/api/datasets/nope/segments").status_code == 404
    assert client.get("/api/datasets/nope/stats").status_code == 404


def test_unknown_segment_404(client):
    assert client.get("/api/datasets/wildchat/segments/999").status_code == 404
