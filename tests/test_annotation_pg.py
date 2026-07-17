"""Annotation backend tests against a real PostgreSQL database.

These exercise the PG data layer + FastAPI routes end-to-end: pagination, search,
the EFFECTIVE conversation detail (gold-when-boundary replaces predicted;
inherited topics), annotate/boundaries/clear, and stats.

They require a Postgres reachable at ``EB1_ANNOTATION_DSN`` (the docker compose
service in ``annotation/docker-compose.yml``). When the var is unset the whole
module is skipped so the offline suite stays green::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation
    uv run pytest tests/test_annotation_pg.py -q
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pg = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

from annotation.backend import db  # noqa: E402
from annotation.backend.app import create_app  # noqa: E402

DATASET = "wildchat"
CONV_A = "a1f3c9d2e7b40516"
CONV_B = "b7e2a4f10c8d9933"

_CONVERSATIONS = [
    {
        "ext_id": CONV_A,
        "messages": [
            {"role": "user", "content": "Draft a cover letter opening."},
            {"role": "assistant", "content": "Here is an opening paragraph."},
            {"role": "user", "content": "How far is the Andromeda galaxy?"},
            {"role": "assistant", "content": "About 2.5 million light-years."},
        ],
        "segments": [
            {
                "message_indices": [0, 1],
                "summary": "Cover letter help",
                "topic": "writing_help",
                "subtopic": "cover_letter_drafting",
                "sentiment": "neutral",
                "label_confidence": 0.95,
            },
            {
                "message_indices": [2, 3],
                "summary": "Astronomy fact",
                "topic": "factual_question",
                "subtopic": "astronomy_fact",
                "sentiment": "neutral",
                "label_confidence": 0.40,
            },
        ],
    },
    {
        "ext_id": CONV_B,
        "messages": [
            {"role": "user", "content": "Implement binary search in Python."},
            {"role": "assistant", "content": "Here is a binary search function."},
        ],
        "segments": [
            {
                "message_indices": [0, 1],
                "summary": "Binary search",
                "topic": "coding_help",
                "subtopic": "binary_search_implementation",
                "sentiment": "neutral",
                "label_confidence": 0.92,
            }
        ],
    },
]

_TAXONOMY = [
    {"topic": "writing_help", "subtopic": "cover_letter_drafting", "description": "Cover letters"},
    {"topic": "coding_help", "subtopic": "binary_search_implementation", "description": "Coding"},
]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Apply the PG schema once to the configured database."""
    db.reset_pool()
    db.apply_schema()
    yield
    db.reset_pool()


@pytest.fixture()
def seeded():
    """Seed the wildchat fixture fresh for each test (resets the dataset)."""
    db.seed_conversations(DATASET, _CONVERSATIONS, taxonomy=_TAXONOMY, reset=True)
    yield
    db.seed_conversations(DATASET, [], reset=True)


@pytest.fixture()
def client(seeded):
    return TestClient(create_app())


def _seg_id(client, ext_id: str, message_indices: list[int]) -> int:
    """Resolve a predicted segment id by its conversation + span via /segments."""
    for seg in client.get(f"/api/datasets/{DATASET}/segments").json():
        if seg["conversation"] == ext_id and seg["message_indices"] == message_indices:
            return seg["id"]
    raise AssertionError(f"segment {ext_id} {message_indices} not found")


@pg
def test_list_datasets(client):
    # Membership (not equality): a prior ingest/e2e seed may leave other datasets
    # in the shared database; this test only owns the wildchat fixture.
    assert DATASET in client.get("/api/datasets").json()


@pg
def test_conversations_paginated_shape(client):
    body = client.get(f"/api/datasets/{DATASET}/conversations").json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 2
    assert {r["conversation"] for r in body["items"]} == {CONV_A, CONV_B}


@pg
def test_conversations_pagination_pages(client):
    p1 = client.get(
        f"/api/datasets/{DATASET}/conversations", params={"page": 1, "page_size": 1}
    ).json()
    p2 = client.get(
        f"/api/datasets/{DATASET}/conversations", params={"page": 2, "page_size": 1}
    ).json()
    assert p1["total"] == 2 and p2["total"] == 2
    assert len(p1["items"]) == 1 and len(p2["items"]) == 1
    assert p1["items"][0]["conversation"] != p2["items"][0]["conversation"]


@pg
def test_conversations_search_by_message_content(client):
    body = client.get(
        f"/api/datasets/{DATASET}/conversations", params={"q": "Andromeda"}
    ).json()
    assert [r["conversation"] for r in body["items"]] == [CONV_A]
    assert body["total"] == 1


@pg
def test_conversations_search_by_ext_id(client):
    body = client.get(
        f"/api/datasets/{DATASET}/conversations", params={"q": CONV_B[:8]}
    ).json()
    assert [r["conversation"] for r in body["items"]] == [CONV_B]


@pg
def test_conversation_summary_fields(client):
    rows = {
        r["conversation"]: r
        for r in client.get(f"/api/datasets/{DATASET}/conversations").json()["items"]
    }
    a = rows[CONV_A]
    assert a["message_count"] == 4
    assert a["segment_count"] == 2
    assert set(a["topics"]) == {"writing_help", "factual_question"}
    assert a["reviewed_count"] == 0 and a["reviewed"] is False


@pg
def test_conversation_detail_effective_no_gold(client):
    view = client.get(f"/api/datasets/{DATASET}/conversations/{CONV_B}").json()
    assert len(view["messages"]) == 2
    assert len(view["segments"]) == 1
    assert view["segments"][0]["topic"] == "coding_help"
    assert view["gold_segments"] == []


@pg
def test_annotate_writes_gold_and_flips_stats(client):
    before = client.get(f"/api/datasets/{DATASET}/stats").json()
    assert before["reviewed"] == 0

    seg_id = _seg_id(client, CONV_A, [2, 3])
    resp = client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={
            "true_topic": "science_question",
            "true_subtopic": "astronomy_fact",
            "reviewed_by": "alice",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["gold_segment_id"] >= 1

    gold = db.read_gold_segments(DATASET, CONV_A)
    relabel = [g for g in gold if g["base_segment_id"] == seg_id]
    assert len(relabel) == 1
    assert relabel[0]["topic"] == "science_question"
    assert relabel[0]["reviewed_by"] == "alice"
    assert relabel[0]["source"] == "relabel"

    after = client.get(f"/api/datasets/{DATASET}/stats").json()
    assert after["reviewed"] == 1
    assert after["unreviewed"] == before["unreviewed"] - 1


@pg
def test_annotate_idempotent_no_duplicate(client):
    seg_id = _seg_id(client, CONV_A, [0, 1])
    payload = {"true_topic": "writing_help", "true_subtopic": "cover_letter_drafting"}
    client.post(f"/api/datasets/{DATASET}/segments/{seg_id}/annotate", json=payload)
    client.post(f"/api/datasets/{DATASET}/segments/{seg_id}/annotate", json=payload)

    gold = db.read_gold_segments(DATASET, CONV_A)
    mirrored = [g for g in gold if g["base_segment_id"] == seg_id]
    assert len(mirrored) == 1
    assert mirrored[0]["source"] == "confirm"


@pg
def test_clear_annotation_reverts(client):
    seg_id = _seg_id(client, CONV_A, [2, 3])
    client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={"true_topic": "science_question", "true_subtopic": "astronomy_fact"},
    )
    assert client.get(f"/api/datasets/{DATASET}/stats").json()["reviewed"] == 1

    resp = client.delete(f"/api/datasets/{DATASET}/segments/{seg_id}/annotate")
    assert resp.status_code == 200 and resp.json()["deleted"] == 1
    assert db.read_gold_segments(DATASET, CONV_A) == []
    assert client.get(f"/api/datasets/{DATASET}/stats").json()["reviewed"] == 0


@pg
def test_clear_unknown_segment_404(client):
    assert (
        client.delete(f"/api/datasets/{DATASET}/segments/99999/annotate").status_code
        == 404
    )


@pg
def test_boundaries_split_persists_two_gold_rows(client):
    resp = client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
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
    assert resp.json()["gold_segments_written"] == 2
    gold = db.read_gold_segments(DATASET, CONV_A)
    assert len(gold) == 2
    assert all(g["source"] == "boundary" for g in gold)
    assert all(g["base_segment_id"] is None for g in gold)
    assert [g["message_indices"] for g in gold] == [[0, 1], [2, 3]]


@pg
def test_boundaries_replace_collapses(client):
    client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
        json={
            "segments": [
                {"message_indices": [0]},
                {"message_indices": [1, 2]},
                {"message_indices": [3]},
            ]
        },
    )
    resp = client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
        json={"segments": [{"message_indices": [0, 1, 2, 3]}]},
    )
    assert resp.json()["gold_segments_written"] == 1
    gold = db.read_gold_segments(DATASET, CONV_A)
    assert len(gold) == 1
    assert gold[0]["message_indices"] == [0, 1, 2, 3]


@pg
def test_effective_split_inherits_predicted_topics(client):
    client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
        json={"segments": [{"message_indices": [0, 1]}, {"message_indices": [2, 3]}]},
    )
    view = client.get(f"/api/datasets/{DATASET}/conversations/{CONV_A}").json()
    by_span = {tuple(s["message_indices"]): s for s in view["segments"]}
    assert by_span[(0, 1)]["topic"] == "writing_help"
    assert by_span[(2, 3)]["topic"] == "factual_question"
    assert all(s["topic"] for s in view["segments"])


@pg
def test_effective_merge_takes_primary_topic(client):
    client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
        json={"segments": [{"message_indices": [0, 1, 2, 3]}]},
    )
    view = client.get(f"/api/datasets/{DATASET}/conversations/{CONV_A}").json()
    assert len(view["segments"]) == 1
    assert view["segments"][0]["topic"] in {"writing_help", "factual_question"}


@pg
def test_relabel_overrides_topic_in_effective(client):
    seg_id = _seg_id(client, CONV_A, [2, 3])
    client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={"true_topic": "science_question", "true_subtopic": "astronomy_fact"},
    )
    view = client.get(f"/api/datasets/{DATASET}/conversations/{CONV_A}").json()
    by_span = {tuple(s["message_indices"]): s for s in view["segments"]}
    relabeled = by_span[(2, 3)]
    assert relabeled["topic"] == "science_question"
    assert relabeled["true_topic"] == "science_question"
    assert relabeled["reviewed"] is True

    stats = client.get(f"/api/datasets/{DATASET}/stats").json()
    assert stats["per_topic"].get("science_question") == 1
    assert "factual_question" not in stats["per_topic"]


@pg
def test_list_reflects_effective_after_merge(client):
    client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
        json={"segments": [{"message_indices": [0, 1, 2, 3]}]},
    )
    rows = {
        r["conversation"]: r
        for r in client.get(f"/api/datasets/{DATASET}/conversations").json()["items"]
    }
    assert rows[CONV_A]["segment_count"] == 1
    assert client.get(f"/api/datasets/{DATASET}/stats").json()["total"] == 2


@pg
def test_taxonomy_returns_seeded_topics(client):
    topics = {r["topic"] for r in client.get(f"/api/datasets/{DATASET}/taxonomy").json()}
    assert {"writing_help", "coding_help"} <= topics


@pg
def test_unknown_dataset_404(client):
    assert client.get("/api/datasets/nope/conversations").status_code == 404
    assert client.get("/api/datasets/nope/stats").status_code == 404


@pg
def test_status_filter_on_conversations(client):
    seg_id = _seg_id(client, CONV_B, [0, 1])
    client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={"true_topic": "coding_help", "true_subtopic": "binary_search_implementation"},
    )
    reviewed = client.get(
        f"/api/datasets/{DATASET}/conversations", params={"status": "reviewed"}
    ).json()
    assert [r["conversation"] for r in reviewed["items"]] == [CONV_B]
    unreviewed = client.get(
        f"/api/datasets/{DATASET}/conversations", params={"status": "unreviewed"}
    ).json()
    assert [r["conversation"] for r in unreviewed["items"]] == [CONV_A]


# ---------------------------------------------------------------------------
# Pure-function unit tests (no DB, no DSN) — the boundary-overlay + upsert fixes
# ---------------------------------------------------------------------------


def _boundary_seg(seg_id: int, indices: list[int], **over) -> dict:
    base = {
        "id": seg_id,
        "conversation_id": 1,
        "chunk_index": 0,
        "message_indices": indices,
        "summary": None,
        "topic": None,
        "subtopic": None,
        "sentiment": None,
        "label_confidence": None,
        "bertopic_topic": None,
        "bertopic_subtopic": None,
        "source": "gold",
        "base_segment_id": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    base.update(over)
    return base


def test_effective_boundary_overlays_relabel_by_boundary_id():
    # Imported SuperDialseg boundaries (source='gold', base_segment_id NULL) plus
    # one relabel row keyed to a boundary row's id: the relabel topic/subtopic win
    # on the matching boundary segment and every effective base_segment_id is the
    # boundary row's OWN id (so reviewed matching works).
    boundary_a = _boundary_seg(361052, [0, 1], topic="veterans_affairs")
    boundary_b = _boundary_seg(361053, [2, 3], topic="disability")
    relabel = {
        "id": 367033,
        "conversation_id": 1,
        "chunk_index": 0,
        "message_indices": [0, 1],
        "summary": None,
        "topic": "health_care",
        "subtopic": "enrollment",
        "sentiment": None,
        "label_confidence": None,
        "bertopic_topic": None,
        "bertopic_subtopic": None,
        "source": "relabel",
        "base_segment_id": 361052,
        "reviewed_by": "alice",
        "reviewed_at": "2026-07-17T00:00:00+00:00",
    }
    effective = db._effective_from("conv", [], [boundary_a, boundary_b, relabel])

    by_id = {s["id"]: s for s in effective}
    # Overlaid boundary carries the relabel labels; base_segment_id == its own id.
    assert by_id[361052]["topic"] == "health_care"
    assert by_id[361052]["subtopic"] == "enrollment"
    assert by_id[361052]["base_segment_id"] == 361052
    # The other boundary is untouched but still exposes its own id as base.
    assert by_id[361053]["topic"] == "disability"
    assert by_id[361053]["subtopic"] is None
    assert by_id[361053]["base_segment_id"] == 361053


class _RecordingConn:
    """Minimal recording connection: captures execute() SQL + params."""

    def __init__(self, calls: list[tuple[str, tuple]]):
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def transaction(self):
        return self

    def execute(self, sql, params=None):
        self._calls.append((sql, params))
        return self

    def fetchone(self):
        return {"id": 1}


class _RecordingPool:
    def __init__(self, calls):
        self._calls = calls

    def connection(self):
        return _RecordingConn(self._calls)


def test_upsert_gold_copies_bertopic_from_base(monkeypatch):
    # The INSERT must copy bertopic_topic/bertopic_subtopic off the base segment so
    # the reviewed match/mismatch counters (which need bertopic_topic NOT NULL) see
    # the saved label.
    calls: list[tuple[str, tuple]] = []
    monkeypatch.setattr(db, "get_pool", lambda: _RecordingPool(calls))

    base_segment = {
        "id": 361052,
        "conversation_id": 1,
        "chunk_index": 0,
        "message_indices": [0, 1],
        "topic": "veterans_affairs",
        "subtopic": "disability_claims",
        "bertopic_topic": "Veterans Affairs",
        "bertopic_subtopic": "Disability Claims",
    }
    gold_id = db.upsert_gold_for_segment(
        "superdialseg", base_segment, "health_care", "enrollment", None, "alice"
    )
    assert gold_id == 1

    insert = next(c for c in calls if c[0].startswith("INSERT INTO segment"))
    sql, params = insert
    assert "bertopic_topic, bertopic_subtopic" in sql
    assert "Veterans Affairs" in params
    assert "Disability Claims" in params
