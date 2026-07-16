"""DSN-gated tests for the BERTopic queue filters + bertopic-labels endpoint.

Exercise the ``bertopic_topic``/``bertopic_subtopic`` query filters on the
conversations list (each an EXISTS on a conversation's ``source='gold'`` segment
labels), their composition with each other and pagination, and the
``GET /datasets/{dataset}/bertopic-labels`` endpoint (distinct topics+subtopics
with per-conversation counts). Skipped without ``EB1_ANNOTATION_DSN`` so the
offline suite stays green. Use the SEPARATE test database::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_test
    uv run pytest tests/test_annotation_bertopic_filter.py -q
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

DATASET = "bertopic-filter-ds"
CONV_ACCOUNT = "btf-conv-account"
CONV_BILLING = "btf-conv-billing"
CONV_BOTH = "btf-conv-both"

_CONVERSATIONS = [
    {
        "ext_id": CONV_ACCOUNT,
        "messages": [
            {"role": "user", "content": "How do I reset my password?"},
            {"role": "agent", "content": "Open settings and click reset."},
        ],
        "gold_segments": [{"message_indices": [0, 1]}],
    },
    {
        "ext_id": CONV_BILLING,
        "messages": [
            {"role": "user", "content": "What about my billing plan?"},
            {"role": "agent", "content": "You are on the annual plan."},
        ],
        "gold_segments": [{"message_indices": [0, 1]}],
    },
    {
        "ext_id": CONV_BOTH,
        "messages": [
            {"role": "user", "content": "Reset password and check billing."},
            {"role": "agent", "content": "Sure, here is how."},
            {"role": "user", "content": "And my plan?"},
            {"role": "agent", "content": "Annual plan."},
        ],
        "gold_segments": [
            {"message_indices": [0, 1]},
            {"message_indices": [2, 3]},
        ],
    },
]


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.reset_pool()
    db.apply_schema()
    yield
    db.reset_pool()


def _label_gold(dataset: str, conv: str, idx: int, topic: str, subtopic: str) -> None:
    """Write BERTopic labels onto the ``idx``-th gold segment of ``conv``."""
    texts = [r for r in db.gold_segment_texts(dataset) if r["conversation"] == conv]
    seg_id = sorted(r["segment_id"] for r in texts)[idx]
    db.write_bertopic_labels([{"segment_id": seg_id, "topic": topic, "subtopic": subtopic}])


@pytest.fixture()
def seeded():
    db.ensure_dataset(DATASET)
    db.ingest_batch(DATASET, _CONVERSATIONS)
    _label_gold(DATASET, CONV_ACCOUNT, 0, "account", "password")
    _label_gold(DATASET, CONV_BILLING, 0, "billing", "plan")
    _label_gold(DATASET, CONV_BOTH, 0, "account", "password")
    _label_gold(DATASET, CONV_BOTH, 1, "billing", "plan")
    yield
    for conv in (CONV_ACCOUNT, CONV_BILLING, CONV_BOTH):
        db.ingest_batch(DATASET, [{"ext_id": conv, "messages": [], "gold_segments": []}])


@pytest.fixture()
def client(seeded):
    return TestClient(create_app())


def _ext_ids(payload: dict) -> set[str]:
    return {item["conversation"] for item in payload["items"]}


def test_filter_by_bertopic_topic(client):
    resp = client.get(
        f"/api/datasets/{DATASET}/conversations",
        params={"bertopic_topic": "account"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert _ext_ids(payload) == {CONV_ACCOUNT, CONV_BOTH}
    assert payload["total"] == 2


def test_filter_by_bertopic_subtopic(client):
    resp = client.get(
        f"/api/datasets/{DATASET}/conversations",
        params={"bertopic_subtopic": "plan"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert _ext_ids(payload) == {CONV_BILLING, CONV_BOTH}
    assert payload["total"] == 2


def test_bertopic_filters_compose(client):
    resp = client.get(
        f"/api/datasets/{DATASET}/conversations",
        params={"bertopic_topic": "account", "bertopic_subtopic": "plan"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert _ext_ids(payload) == {CONV_BOTH}
    assert payload["total"] == 1


def test_bertopic_filter_composes_with_pagination(client):
    resp = client.get(
        f"/api/datasets/{DATASET}/conversations",
        params={"bertopic_topic": "account", "page_size": 1, "page": 1},
    )
    payload = resp.json()
    assert payload["total"] == 2
    assert len(payload["items"]) == 1


def test_bertopic_labels_endpoint(client):
    resp = client.get(f"/api/datasets/{DATASET}/bertopic-labels")
    assert resp.status_code == 200
    payload = resp.json()

    topics = {t["topic"]: t["count"] for t in payload["topics"]}
    assert topics == {"account": 2, "billing": 2}
    counts = [t["count"] for t in payload["topics"]]
    assert counts == sorted(counts, reverse=True)

    subs = {s["subtopic"]: (s["topic"], s["count"]) for s in payload["subtopics"]}
    assert subs == {"password": ("account", 2), "plan": ("billing", 2)}


def test_bertopic_labels_excludes_nulls(client):
    """Conversations whose gold segments carry no BERTopic label are excluded."""
    db.ingest_batch(
        DATASET,
        [
            {
                "ext_id": "btf-conv-unlabeled",
                "messages": [{"role": "user", "content": "hi"}],
                "gold_segments": [{"message_indices": [0]}],
            }
        ],
    )
    resp = client.get(f"/api/datasets/{DATASET}/bertopic-labels")
    topics = {t["topic"] for t in resp.json()["topics"]}
    assert None not in topics
    assert topics == {"account", "billing"}
    db.ingest_batch(
        DATASET, [{"ext_id": "btf-conv-unlabeled", "messages": [], "gold_segments": []}]
    )


# ---------------------------------------------------------------------------
# Domain in the labels endpoint (taxonomy v2, issue #23): a nav category like
# "Disability" can exist in two domains, so every topic/subtopic entry carries the
# conversation's domain and the same name yields one entry per domain.
# ---------------------------------------------------------------------------

DOMAIN_DS = "bertopic-domain-ds"


@pytest.fixture()
def domain_seeded():
    db.ensure_dataset(DOMAIN_DS)
    db.ingest_batch(
        DOMAIN_DS,
        [
            {
                "ext_id": "bd-ssa",
                "messages": [{"role": "user", "content": "ssdi"}],
                "gold_segments": [{"message_indices": [0]}],
            },
            {
                "ext_id": "bd-va",
                "messages": [{"role": "user", "content": "va comp"}],
                "gold_segments": [{"message_indices": [0]}],
            },
        ],
    )
    pool = db.get_pool()
    with pool.connection() as conn:
        conn.execute(
            "UPDATE conversation SET domain = 'ssa' "
            "WHERE dataset = %s AND ext_id = 'bd-ssa'",
            (DOMAIN_DS,),
        )
        conn.execute(
            "UPDATE conversation SET domain = 'va' "
            "WHERE dataset = %s AND ext_id = 'bd-va'",
            (DOMAIN_DS,),
        )
    for conv, sub in (("bd-ssa", "Apply SSDI"), ("bd-va", "VA Comp")):
        texts = [r for r in db.gold_segment_texts(DOMAIN_DS) if r["conversation"] == conv]
        db.write_bertopic_labels(
            [{"segment_id": texts[0]["segment_id"], "topic": "Disability", "subtopic": sub}]
        )
    yield
    pool = db.get_pool()
    with pool.connection() as conn:
        conn.execute("DELETE FROM dataset WHERE name = %s", (DOMAIN_DS,))


@pytest.fixture()
def domain_client(domain_seeded):
    return TestClient(create_app())


def test_bertopic_labels_split_same_category_by_domain(domain_client):
    payload = domain_client.get(f"/api/datasets/{DOMAIN_DS}/bertopic-labels").json()
    # "Disability" is one entry per domain, each with its own domain code.
    disability = {t["domain"] for t in payload["topics"] if t["topic"] == "Disability"}
    assert disability == {"ssa", "va"}
    subs = {(s["subtopic"], s["domain"]) for s in payload["subtopics"]}
    assert ("Apply SSDI", "ssa") in subs
    assert ("VA Comp", "va") in subs
