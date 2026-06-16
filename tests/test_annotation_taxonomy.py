"""Taxonomy CRUD + cascade + export tests against a real PostgreSQL database.

These exercise the editable-taxonomy data layer and routes: idempotent create,
rename with label cascade, merge with label cascade, delete-keeps-labels, and the
deterministic export JSON shape. Segment labels are tied to a dataset through
``segment.conversation_id -> conversation.dataset``.

They require a Postgres reachable at ``EB1_ANNOTATION_DSN``. When the var is unset
the whole module is skipped so the offline suite stays green::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_test
    uv run pytest tests/test_annotation_taxonomy.py -q
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

from annotation.backend import db  # noqa: E402
from annotation.backend.app import create_app  # noqa: E402

DATASET = "taxotest"
CONV = "tx_conv_0001"

_CONVERSATIONS = [
    {
        "ext_id": CONV,
        "messages": [
            {"role": "user", "content": "Help me draft a cover letter."},
            {"role": "assistant", "content": "Here is an opening."},
            {"role": "user", "content": "Now implement binary search."},
            {"role": "assistant", "content": "Here is the function."},
        ],
        "segments": [
            {
                "message_indices": [0, 1],
                "topic": "writing_help",
                "subtopic": "cover_letter",
                "label_confidence": 0.9,
            },
            {
                "message_indices": [2, 3],
                "topic": "coding_help",
                "subtopic": "binary_search",
                "label_confidence": 0.9,
            },
        ],
    }
]

_TAXONOMY = [
    {"topic": "writing_help", "subtopic": "cover_letter", "description": "Cover letters"},
    {"topic": "coding_help", "subtopic": "binary_search", "description": "Coding"},
]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    db.reset_pool()
    db.apply_schema()
    yield
    db.reset_pool()


@pytest.fixture()
def seeded():
    db.seed_conversations(DATASET, _CONVERSATIONS, taxonomy=_TAXONOMY, reset=True)
    yield
    db.seed_conversations(DATASET, [], reset=True)


@pytest.fixture()
def client(seeded):
    return TestClient(create_app())


def _topics():
    return {(r.get("topic"), r.get("subtopic")) for r in db.load_taxonomy(DATASET)}


def _segment_labels():
    pool = db.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.topic, s.subtopic FROM segment s "
            "JOIN conversation c ON s.conversation_id = c.id "
            "WHERE c.dataset = %s ORDER BY s.topic, s.subtopic",
            (DATASET,),
        ).fetchall()
    return {(r["topic"], r["subtopic"]) for r in rows}


def test_create_inserts_entry(client):
    resp = client.post(
        f"/api/datasets/{DATASET}/taxonomy",
        json={"topic": "travel_help", "subtopic": "flights", "description": "Trips"},
    )
    assert resp.status_code == 200
    assert ("travel_help", "flights") in _topics()


def test_create_is_idempotent(client):
    body = {"topic": "writing_help", "subtopic": "cover_letter"}
    client.post(f"/api/datasets/{DATASET}/taxonomy", json=body)
    client.post(f"/api/datasets/{DATASET}/taxonomy", json=body)
    matches = [t for t in _topics() if t == ("writing_help", "cover_letter")]
    assert len(matches) == 1


def test_rename_subtopic_cascades_to_segments(client):
    resp = client.patch(
        f"/api/datasets/{DATASET}/taxonomy",
        json={
            "topic": "writing_help",
            "new_topic": "writing_help",
            "subtopic": "cover_letter",
            "new_subtopic": "resume_letter",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["cascaded"] == 1
    assert ("writing_help", "resume_letter") in _topics()
    assert ("writing_help", "cover_letter") not in _topics()
    assert ("writing_help", "resume_letter") in _segment_labels()
    assert ("writing_help", "cover_letter") not in _segment_labels()


def test_rename_topic_cascades_to_segments(client):
    resp = client.patch(
        f"/api/datasets/{DATASET}/taxonomy",
        json={"topic": "coding_help", "new_topic": "programming_help"},
    )
    assert resp.status_code == 200
    assert resp.json()["cascaded"] == 1
    assert ("programming_help", "binary_search") in _topics()
    assert ("programming_help", "binary_search") in _segment_labels()


def test_merge_folds_into_single_entry_and_cascades(client):
    client.post(
        f"/api/datasets/{DATASET}/taxonomy",
        json={"topic": "writing_help", "subtopic": "blog_post"},
    )
    resp = client.post(
        f"/api/datasets/{DATASET}/taxonomy/merge",
        json={"from_topic": "coding_help", "into_topic": "writing_help"},
    )
    assert resp.status_code == 200
    assert resp.json()["cascaded"] == 1
    topics = {t for (t, _) in _topics()}
    assert "coding_help" not in topics
    assert "writing_help" in topics
    seg_topics = {t for (t, _) in _segment_labels()}
    assert "coding_help" not in seg_topics
    assert "writing_help" in seg_topics


def test_delete_removes_option_but_keeps_labels(client):
    resp = client.delete(
        f"/api/datasets/{DATASET}/taxonomy",
        params={"topic": "coding_help", "subtopic": "binary_search"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert ("coding_help", "binary_search") not in _topics()
    assert ("coding_help", "binary_search") in _segment_labels()


def test_export_taxonomy_shape_and_determinism(client):
    payload = db.export_taxonomy(DATASET)
    assert payload["dataset"] == DATASET
    assert payload["kind_default"] == "user"
    entries = payload["entries"]
    assert all(set(e) == {"kind", "topic", "subtopic", "description"} for e in entries)
    keys = [(e["kind"], e["topic"] or "", e["subtopic"] or "") for e in entries]
    assert keys == sorted(keys)
    assert db.export_taxonomy(DATASET) == payload
