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


# ---------------------------------------------------------------------------
# Domain-scoped taxonomy (taxonomy v2, issue #23). The nav category "Disability"
# exists in BOTH ssa and va; every taxonomy operation is scoped to a domain so the
# two are managed independently, and the conversations list carries a domain
# exact-match filter.
# ---------------------------------------------------------------------------

DOMAIN_DATASET = "domaintax"
DCV_SSA = "dtx_ssa"
DCV_VA = "dtx_va"

_DOMAIN_CONVERSATIONS = [
    {
        "ext_id": DCV_SSA,
        "domain": "ssa",
        "messages": [
            {"role": "user", "content": "Am I eligible for SSDI?"},
            {"role": "assistant", "content": "Let's check."},
        ],
        "segments": [
            {"message_indices": [0, 1], "topic": "disability", "subtopic": "apply_ssdi"},
        ],
    },
    {
        "ext_id": DCV_VA,
        "domain": "va",
        "messages": [
            {"role": "user", "content": "VA disability compensation?"},
            {"role": "assistant", "content": "Here's how."},
        ],
        "segments": [
            {"message_indices": [0, 1], "topic": "disability", "subtopic": "va_comp"},
        ],
    },
]

_DOMAIN_TAXONOMY = [
    {"domain": "ssa", "topic": "disability", "subtopic": None, "description": "Disability"},
    {"domain": "ssa", "topic": "disability", "subtopic": "apply_ssdi", "description": "Apply"},
    {"domain": "va", "topic": "disability", "subtopic": None, "description": "Disability"},
    {"domain": "va", "topic": "disability", "subtopic": "va_comp", "description": "Comp"},
]


@pytest.fixture()
def domain_seeded():
    db.seed_conversations(
        DOMAIN_DATASET, _DOMAIN_CONVERSATIONS, taxonomy=_DOMAIN_TAXONOMY, reset=True
    )
    yield
    db.seed_conversations(DOMAIN_DATASET, [], reset=True)


@pytest.fixture()
def domain_client(domain_seeded):
    return TestClient(create_app())


def _domain_options() -> set[tuple]:
    return {
        (r.get("domain"), r.get("topic"), r.get("subtopic"))
        for r in db.load_taxonomy(DOMAIN_DATASET)
    }


def _domain_segment_labels(domain: str) -> set[tuple]:
    pool = db.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.topic, s.subtopic FROM segment s "
            "JOIN conversation c ON s.conversation_id = c.id "
            "WHERE c.dataset = %s AND c.domain = %s",
            (DOMAIN_DATASET, domain),
        ).fetchall()
    return {(r["topic"], r["subtopic"]) for r in rows}


def test_taxonomy_list_carries_domain(domain_client):
    resp = domain_client.get(f"/api/datasets/{DOMAIN_DATASET}/taxonomy")
    assert resp.status_code == 200
    assert ("ssa", "disability", None) in _domain_options()
    assert ("va", "disability", None) in _domain_options()


def test_create_same_name_in_two_domains_coexists(domain_client):
    for dom in ("ssa", "va"):
        resp = domain_client.post(
            f"/api/datasets/{DOMAIN_DATASET}/taxonomy",
            json={"topic": "General", "domain": dom},
        )
        assert resp.status_code == 200
    options = _domain_options()
    assert ("ssa", "general", None) in options
    assert ("va", "general", None) in options


def test_rename_is_scoped_to_domain(domain_client):
    # Rename ssa's "disability" -> "disability_claims"; va's must be untouched.
    resp = domain_client.patch(
        f"/api/datasets/{DOMAIN_DATASET}/taxonomy",
        json={"topic": "disability", "new_topic": "disability_claims", "domain": "ssa"},
    )
    assert resp.status_code == 200
    options = _domain_options()
    assert ("ssa", "disability_claims", None) in options
    assert ("ssa", "disability", None) not in options
    # va's identically-named category is independent and unchanged.
    assert ("va", "disability", None) in options
    # Cascade touched only the ssa conversation's segment.
    assert ("disability_claims", "apply_ssdi") in _domain_segment_labels("ssa")
    assert ("disability", "va_comp") in _domain_segment_labels("va")


def test_merge_is_scoped_to_domain(domain_client):
    # Seed a va target then merge va's "disability" into it; ssa is untouched.
    domain_client.post(
        f"/api/datasets/{DOMAIN_DATASET}/taxonomy",
        json={"topic": "health_care", "domain": "va"},
    )
    resp = domain_client.post(
        f"/api/datasets/{DOMAIN_DATASET}/taxonomy/merge",
        json={"from_topic": "disability", "into_topic": "health_care", "domain": "va"},
    )
    assert resp.status_code == 200
    assert resp.json()["cascaded"] == 1
    assert {t for (t, _) in _domain_segment_labels("va")} == {"health_care"}
    # ssa's disability segment is untouched by a va-scoped merge.
    assert {t for (t, _) in _domain_segment_labels("ssa")} == {"disability"}
    options = _domain_options()
    assert ("va", "disability", None) not in options
    assert ("ssa", "disability", None) in options


def test_delete_is_scoped_to_domain(domain_client):
    resp = domain_client.delete(
        f"/api/datasets/{DOMAIN_DATASET}/taxonomy",
        params={"topic": "disability", "domain": "ssa"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    options = _domain_options()
    assert ("ssa", "disability", None) not in options
    assert ("va", "disability", None) in options


def test_conversations_domain_filter(domain_client):
    payload = domain_client.get(
        f"/api/datasets/{DOMAIN_DATASET}/conversations",
        params={"domain": "va"},
    ).json()
    assert _conv_ids(payload) == {DCV_VA}
    assert payload["total"] == 1
    assert payload["items"][0]["domain"] == "va"
