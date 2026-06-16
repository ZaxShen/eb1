"""Tests for the SuperDialseg worklist: load, per-labeler queue, filtered ingest.

Two layers:

- An offline check that ``db.frozen_boundaries`` is data-driven (no DB needed).
- DSN-gated PG tests that exercise ``load_worklist`` idempotency/overlap, the
  ``?labeler=`` conversation-queue filter, the ``frozen_boundaries`` flag on the
  conversation view, and ``run.ingest(worklist=...)`` filtering. They require a
  Postgres at ``EB1_ANNOTATION_DSN`` and skip cleanly when it is unset::

      docker compose -f annotation/docker-compose.yml up -d
      export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation
      uv run pytest tests/test_annotation_worklist.py -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from annotation.backend import db


def test_frozen_boundaries_is_data_driven():
    assert db.frozen_boundaries("superdialseg") is True
    assert db.frozen_boundaries("wildchat") is False
    assert db.frozen_boundaries("lmsys") is False


pytestmark_pg = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

DATASET = "superdialseg"

# Worklist rows in the sampler's output shape. ``wl_overlap`` is double-labeled.
_WORKLIST = [
    {
        "dialogue_id": "wltest_solo_a",
        "seg_bucket": "1-2",
        "len_bucket": "short",
        "assigned_to": ["labeler_a"],
        "is_overlap": False,
    },
    {
        "dialogue_id": "wltest_solo_b",
        "seg_bucket": "3",
        "len_bucket": "med",
        "assigned_to": ["labeler_b"],
        "is_overlap": False,
    },
    {
        "dialogue_id": "wltest_overlap",
        "seg_bucket": "5+",
        "len_bucket": "long",
        "assigned_to": ["labeler_a", "labeler_b"],
        "is_overlap": True,
    },
]

# Three SuperDialseg dialogues whose ids match the worklist, plus one NOT in it.
_DIALOGUES = {
    "wltest_solo_a": {
        "dialogue_id": "wltest_solo_a",
        "utterances": [
            {"speaker": "User", "text": "A0", "segment_id": 0},
            {"speaker": "Agent", "text": "A1", "segment_id": 0},
        ],
    },
    "wltest_solo_b": {
        "dialogue_id": "wltest_solo_b",
        "utterances": [
            {"speaker": "User", "text": "B0", "segment_id": 0},
            {"speaker": "Agent", "text": "B1", "segment_id": 1},
        ],
    },
    "wltest_overlap": {
        "dialogue_id": "wltest_overlap",
        "utterances": [
            {"speaker": "User", "text": "O0", "segment_id": 0},
            {"speaker": "Agent", "text": "O1", "segment_id": 0},
        ],
    },
    "wltest_offlist": {
        "dialogue_id": "wltest_offlist",
        "utterances": [
            {"speaker": "User", "text": "X0", "segment_id": 0},
            {"speaker": "Agent", "text": "X1", "segment_id": 0},
        ],
    },
}


def _wipe(db_) -> None:
    pool = db_.get_pool()
    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM worklist WHERE dataset = %s AND ext_id LIKE 'wltest%%'",
            (DATASET,),
        )
        conn.execute(
            "DELETE FROM conversation WHERE dataset = %s AND ext_id LIKE 'wltest%%'",
            (DATASET,),
        )


@pytest.fixture()
def _db():
    db.reset_pool()
    db.apply_schema()
    db.ensure_dataset(DATASET)
    _wipe(db)
    yield db
    _wipe(db)
    db.reset_pool()


def _worklist_count(db_, labeler: str) -> int:
    pool = db_.get_pool()
    with pool.connection() as conn:
        return conn.execute(
            "SELECT count(*) AS n FROM worklist "
            "WHERE dataset = %s AND ext_id LIKE 'wltest%%' AND labeler = %s",
            (DATASET, labeler),
        ).fetchone()["n"]


@pytestmark_pg
def test_load_worklist_one_row_per_labeler(_db):
    written = db.load_worklist(DATASET, _WORKLIST)
    # 1 + 1 + 2 (overlap) = 4 rows.
    assert written == 4
    assert _worklist_count(_db, "labeler_a") == 2  # solo_a + overlap
    assert _worklist_count(_db, "labeler_b") == 2  # solo_b + overlap


@pytestmark_pg
def test_load_worklist_is_idempotent(_db):
    db.load_worklist(DATASET, _WORKLIST)
    db.load_worklist(DATASET, _WORKLIST)
    assert _worklist_count(_db, "labeler_a") == 2
    assert _worklist_count(_db, "labeler_b") == 2
    assert db.worklist_ext_ids(DATASET, "labeler_a") == {
        "wltest_solo_a",
        "wltest_overlap",
    }


@pytestmark_pg
def test_labeler_queue_filters_conversations(_db):
    for ext_id in ("wltest_solo_a", "wltest_solo_b", "wltest_overlap"):
        db.ingest_batch(DATASET, [{"ext_id": ext_id, "messages": []}])
    db.load_worklist(DATASET, _WORKLIST)

    page_a = db.list_conversations(DATASET, labeler="labeler_a", page_size=500)
    convs_a = {r["conversation"] for r in page_a["items"] if r["conversation"].startswith("wltest")}
    assert convs_a == {"wltest_solo_a", "wltest_overlap"}
    assert page_a["total"] == 2

    page_b = db.list_conversations(DATASET, labeler="labeler_b", page_size=500)
    convs_b = {r["conversation"] for r in page_b["items"] if r["conversation"].startswith("wltest")}
    assert convs_b == {"wltest_solo_b", "wltest_overlap"}


@pytestmark_pg
def test_worklist_ingest_filters_to_listed_ids(_db, tmp_path: Path, monkeypatch):
    from annotation.ingest import run, sources

    monkeypatch.setattr(
        sources,
        "superdialseg_stream",
        lambda limit=None: iter(list(_DIALOGUES.values())),
    )
    worklist_path = tmp_path / "worklist.json"
    worklist_path.write_text(json.dumps(_WORKLIST), encoding="utf-8")

    result = run.ingest(DATASET, batch_size=10, worklist=worklist_path)
    # Only the 3 worklisted dialogues ingest; wltest_offlist is dropped.
    assert result["written"] == 3
    assert result["worklist_loaded"] == 4

    pool = _db.get_pool()
    with pool.connection() as conn:
        present = {
            r["ext_id"]
            for r in conn.execute(
                "SELECT ext_id FROM conversation "
                "WHERE dataset = %s AND ext_id LIKE 'wltest%%'",
                (DATASET,),
            ).fetchall()
        }
    assert present == {"wltest_solo_a", "wltest_solo_b", "wltest_overlap"}
    assert "wltest_offlist" not in present
    assert db.worklist_ext_ids(DATASET, "labeler_a") == {
        "wltest_solo_a",
        "wltest_overlap",
    }


@pytestmark_pg
def test_used_topics_returns_distinct_frequent_first(_db):
    db.ingest_batch(
        DATASET,
        [
            {
                "ext_id": "wltest_solo_a",
                "messages": [{"role": "User", "content": "hi"}],
                "gold_segments": [
                    {"message_indices": [0], "topic": "billing"},
                ],
            },
            {
                "ext_id": "wltest_solo_b",
                "messages": [{"role": "User", "content": "yo"}],
                "gold_segments": [
                    {"message_indices": [0], "topic": "billing"},
                    {"message_indices": [0], "topic": "shipping"},
                ],
            },
        ],
    )
    topics = db.used_topics(DATASET)
    seen = [t for t in topics if t in {"billing", "shipping"}]
    # "billing" appears twice, "shipping" once -> most-frequent first.
    assert seen == ["billing", "shipping"]
    assert None not in topics


@pytestmark_pg
def test_used_topics_endpoint(_db):
    from fastapi.testclient import TestClient

    from annotation.backend.app import create_app

    db.ingest_batch(
        DATASET,
        [
            {
                "ext_id": "wltest_solo_a",
                "messages": [{"role": "User", "content": "hi"}],
                "gold_segments": [{"message_indices": [0], "topic": "refunds"}],
            }
        ],
    )
    client = TestClient(create_app())
    resp = client.get(f"/api/datasets/{DATASET}/used-topics")
    assert resp.status_code == 200
    assert "refunds" in resp.json()["topics"]


@pytestmark_pg
def test_conversation_view_carries_frozen_boundaries(_db):
    from fastapi.testclient import TestClient

    from annotation.backend.app import create_app

    db.ingest_batch(DATASET, [{"ext_id": "wltest_solo_a", "messages": []}])
    db.ensure_dataset("wildchat")
    db.ingest_batch("wildchat", [{"ext_id": "wltest_wc", "messages": []}])

    client = TestClient(create_app())
    sds = client.get(f"/api/datasets/{DATASET}/conversations/wltest_solo_a").json()
    assert sds["frozen_boundaries"] is True
    wc = client.get("/api/datasets/wildchat/conversations/wltest_wc").json()
    assert wc["frozen_boundaries"] is False

    pool = _db.get_pool()
    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM conversation WHERE dataset = 'wildchat' AND ext_id = 'wltest_wc'"
        )
