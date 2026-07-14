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
from annotation.backend.slug import slugify  # noqa: E402

DATASET = "taxotest"

# Parity cases: these MUST match the TS `slugify` tests in
# annotation/frontend/src/lib/utils.test.ts so the live preview equals what the
# backend stores. Keep the two lists identical.
SLUG_CASES = [
    ("Veterans  Affairs!", "veterans_affairs"),
    ("Billing", "billing"),
    ("cover_letter", "cover_letter"),
    ("  spaced  out  ", "spaced_out"),
    ("R&D / ops", "r_d_ops"),
    ("Multi--Dash__Score", "multi_dash_score"),
]
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


@pytest.mark.parametrize(("raw", "expected"), SLUG_CASES)
def test_slugify_parity_cases(raw, expected):
    assert slugify(raw) == expected


@pytest.mark.parametrize("blank", ["", "   ", "!!!", "___"])
def test_slugify_rejects_empty_after_normalization(blank):
    with pytest.raises(ValueError):
        slugify(blank)


def test_create_normalizes_topic_and_subtopic_to_slug(client):
    resp = client.post(
        f"/api/datasets/{DATASET}/taxonomy",
        json={"topic": "Veterans  Affairs!", "subtopic": "Housing Loan"},
    )
    assert resp.status_code == 200
    assert ("veterans_affairs", "housing_loan") in _topics()


def test_create_empty_after_slugify_returns_422(client):
    resp = client.post(
        f"/api/datasets/{DATASET}/taxonomy",
        json={"topic": "!!!"},
    )
    assert resp.status_code == 422


def test_annotate_relabel_stores_slug(client):
    seg_id = db.read_predicted_segments(DATASET)[0]["id"]
    resp = client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={"true_topic": "Veterans  Affairs!", "true_subtopic": "Housing Loan"},
    )
    assert resp.status_code == 200
    gold = db.gold_labels_by_base_segment(DATASET)[seg_id]
    assert gold == {"topic": "veterans_affairs", "subtopic": "housing_loan"}


def test_annotate_empty_topic_after_slugify_returns_422(client):
    seg_id = db.read_predicted_segments(DATASET)[0]["id"]
    resp = client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={"true_topic": "!!!", "true_subtopic": ""},
    )
    assert resp.status_code == 422


def test_rename_normalizes_inputs_to_slug(client):
    resp = client.patch(
        f"/api/datasets/{DATASET}/taxonomy",
        json={"topic": "Coding Help", "new_topic": "Programming Help"},
    )
    assert resp.status_code == 200
    assert ("programming_help", "binary_search") in _topics()
    assert ("programming_help", "binary_search") in _segment_labels()


def test_merge_normalizes_inputs_to_slug(client):
    resp = client.post(
        f"/api/datasets/{DATASET}/taxonomy/merge",
        json={"from_topic": "Coding Help", "into_topic": "Writing Help"},
    )
    assert resp.status_code == 200
    assert resp.json()["cascaded"] == 1
    seg_topics = {t for (t, _) in _segment_labels()}
    assert "coding_help" not in seg_topics
    assert "writing_help" in seg_topics


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


# ---------------------------------------------------------------------------
# Reviewed-vs-source mismatch: stats counts + the mismatch conversation filter.
# A gold segment carries a DISPLAY BERTopic source label (``bertopic_topic`` like
# "Veterans Affairs") and a human gold label stored as a SLUG (``topic`` like
# ``veterans_affairs``); a mismatch bridges the two via ``slugify`` in Python.
# ---------------------------------------------------------------------------

MISMATCH_DATASET = "statsmismatch"


def _seed_gold_segment(
    dataset: str,
    ext_id: str,
    *,
    bertopic_topic: str | None,
    bertopic_subtopic: str | None,
    topic: str | None,
    subtopic: str | None,
    reviewed_by: str | None,
) -> None:
    """Seed one conversation with a single ``source='gold'`` segment.

    Direct SQL so the test controls the four label columns + ``reviewed_by`` the
    mismatch predicate reads, which no public write path sets together.
    """
    conv_id = db.upsert_conversation(dataset, ext_id, [{"role": "user", "content": "hi"}])
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute("DELETE FROM segment WHERE conversation_id = %s", (conv_id,))
            conn.execute(
                "INSERT INTO segment (conversation_id, chunk_index, message_indices, "
                "topic, subtopic, source, bertopic_topic, bertopic_subtopic, "
                "reviewed_by, reviewed_at) "
                "VALUES (%s, 0, %s, %s, %s, 'gold', %s, %s, %s, now())",
                (conv_id, [0], topic, subtopic, bertopic_topic, bertopic_subtopic, reviewed_by),
            )


@pytest.fixture()
def mismatch_seeded():
    db.ensure_dataset(MISMATCH_DATASET)
    # Reviewed, slugified source label MATCHES the human label.
    _seed_gold_segment(
        MISMATCH_DATASET, "mm_match",
        bertopic_topic="Veterans Affairs", bertopic_subtopic="Housing Loan",
        topic="veterans_affairs", subtopic="housing_loan", reviewed_by="ann",
    )
    # Reviewed, human TOPIC disagrees with the source topic -> mismatch.
    _seed_gold_segment(
        MISMATCH_DATASET, "mm_topic",
        bertopic_topic="Veterans Affairs", bertopic_subtopic="Housing Loan",
        topic="billing", subtopic="housing_loan", reviewed_by="ann",
    )
    # Reviewed, NULL human subtopic vs non-NULL source subtopic -> mismatch.
    _seed_gold_segment(
        MISMATCH_DATASET, "mm_subnull",
        bertopic_topic="Veterans Affairs", bertopic_subtopic="Housing Loan",
        topic="veterans_affairs", subtopic=None, reviewed_by="ann",
    )
    # Unreviewed: never counted, never in the mismatch filter.
    _seed_gold_segment(
        MISMATCH_DATASET, "mm_unreviewed",
        bertopic_topic="Veterans Affairs", bertopic_subtopic="Pension",
        topic="billing", subtopic="pension", reviewed_by=None,
    )
    # Reviewed but NULL source label: never a mismatch (excluded from both).
    _seed_gold_segment(
        MISMATCH_DATASET, "mm_nullsource",
        bertopic_topic=None, bertopic_subtopic=None,
        topic="billing", subtopic="pension", reviewed_by="ann",
    )
    yield
    pool = db.get_pool()
    with pool.connection() as conn:
        conn.execute("DELETE FROM dataset WHERE name = %s", (MISMATCH_DATASET,))


@pytest.fixture()
def mismatch_client(mismatch_seeded):
    return TestClient(create_app())


def _conv_ids(payload: dict) -> set[str]:
    return {item["conversation"] for item in payload["items"]}


def test_stats_reports_reviewed_match_and_mismatch(mismatch_client):
    stats = mismatch_client.get(f"/api/datasets/{MISMATCH_DATASET}/stats").json()
    assert stats["reviewed_match"] == 1
    assert stats["reviewed_mismatch"] == 2


def test_stats_match_mismatch_are_null_safe(mismatch_client):
    # Only reviewed, source-labelled segments enter the comparison: 1 + 2 = 3,
    # excluding the unreviewed and the NULL-source rows entirely.
    stats = mismatch_client.get(f"/api/datasets/{MISMATCH_DATASET}/stats").json()
    assert stats["reviewed_match"] + stats["reviewed_mismatch"] == 3


def test_mismatch_filter_returns_only_mismatched_conversations(mismatch_client):
    payload = mismatch_client.get(
        f"/api/datasets/{MISMATCH_DATASET}/conversations",
        params={"mismatch": "true"},
    ).json()
    assert _conv_ids(payload) == {"mm_topic", "mm_subnull"}
    assert payload["total"] == 2


def test_mismatch_filter_off_returns_all_conversations(mismatch_client):
    payload = mismatch_client.get(
        f"/api/datasets/{MISMATCH_DATASET}/conversations"
    ).json()
    assert _conv_ids(payload) == {
        "mm_match", "mm_topic", "mm_subnull", "mm_unreviewed", "mm_nullsource"
    }
