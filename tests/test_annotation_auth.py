"""Google SSO tests for the annotation backend — PG-backed, network-free.

The Google ID-token verifier is **mocked** (real sign-in needs the operator's
Client ID and network), so these cover the gate and the
``reviewed_by = verified name`` override without any external dependency. The
backend itself runs on PostgreSQL, so the module is skipped when
``EB1_ANNOTATION_DSN`` is unset (start ``annotation/docker-compose.yml``).

SSO is toggled via the ``GOOGLE_CLIENT_ID`` env var; ``auth._verify_oauth2_token``
is monkeypatched to return a fixed claim set for a known token.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

from annotation.backend import auth, db  # noqa: E402
from annotation.backend.app import create_app  # noqa: E402

DATASET = "wildchat"
CONV_A = "a1f3c9d2e7b40516"

_CONVERSATIONS = [
    {
        "ext_id": CONV_A,
        "messages": [
            {"role": "user", "content": "Draft a cover letter opening."},
            {"role": "assistant", "content": "Here is an opening paragraph."},
        ],
        "segments": [
            {
                "message_indices": [0, 1],
                "topic": "writing_help",
                "subtopic": "cover_letter_drafting",
                "sentiment": "neutral",
                "label_confidence": 0.95,
            }
        ],
    }
]

VALID_TOKEN = "valid-mock-id-token"
VERIFIED_NAME = "Ada Lovelace"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db.reset_pool()
    db.apply_schema()
    yield
    db.reset_pool()


@pytest.fixture()
def seeded():
    db.seed_conversations(DATASET, _CONVERSATIONS, reset=True)
    yield
    db.seed_conversations(DATASET, [], reset=True)


@pytest.fixture()
def client(seeded):
    return TestClient(create_app())


@pytest.fixture()
def sso_on(monkeypatch):
    """Enable SSO and stub the verifier to accept ``VALID_TOKEN`` only."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")

    def fake_verify(token: str, audience: str) -> dict:
        if token != VALID_TOKEN:
            raise ValueError("bad token")
        return {"name": VERIFIED_NAME, "email": "ada@example.com", "sub": "1234567890"}

    monkeypatch.setattr(auth, "_verify_oauth2_token", fake_verify)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seg_id(client, headers: dict[str, str] | None = None) -> int:
    return client.get(
        f"/api/datasets/{DATASET}/segments", headers=headers or {}
    ).json()[0]["id"]


def test_auth_config_reports_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/api/auth/config").json() == {"sso_enabled": False}


def test_auth_config_reports_enabled(client, sso_on):
    assert client.get("/api/auth/config").json() == {"sso_enabled": True}


def test_sso_disabled_endpoints_work_without_token(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/api/datasets").status_code == 200

    seg_id = _seg_id(client)
    resp = client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        json={
            "true_topic": "writing_help",
            "true_subtopic": "cover_letter_drafting",
            "reviewed_by": "manual-reviewer",
        },
    )
    assert resp.status_code == 200
    gold = db.read_gold_segments(DATASET, CONV_A)
    assert gold[0]["reviewed_by"] == "manual-reviewer"


def test_sso_enabled_blocks_missing_token(client, sso_on):
    assert client.get("/api/datasets").status_code == 401
    resp = client.post(
        f"/api/datasets/{DATASET}/segments/1/annotate",
        json={"true_topic": "writing_help", "true_subtopic": "cover_letter_drafting"},
    )
    assert resp.status_code == 401


def test_sso_enabled_rejects_invalid_token(client, sso_on):
    assert client.get("/api/datasets", headers=_bearer("garbage")).status_code == 401


def test_sso_enabled_valid_token_sets_reviewed_by_to_verified_name(client, sso_on):
    seg_id = _seg_id(client, _bearer(VALID_TOKEN))
    resp = client.post(
        f"/api/datasets/{DATASET}/segments/{seg_id}/annotate",
        headers=_bearer(VALID_TOKEN),
        json={
            "true_topic": "writing_help",
            "true_subtopic": "cover_letter_drafting",
            "reviewed_by": "ignored-client-value",
        },
    )
    assert resp.status_code == 200
    gold = db.read_gold_segments(DATASET, CONV_A)
    relabel = [g for g in gold if g["base_segment_id"] == seg_id]
    assert relabel[0]["reviewed_by"] == VERIFIED_NAME


def test_allowlist_permits_listed_email(client, sso_on, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "someone@else.com,ada@example.com")
    assert client.get("/api/datasets", headers=_bearer(VALID_TOKEN)).status_code == 200


def test_allowlist_rejects_unlisted_email_with_403(client, sso_on, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "someone@else.com")
    assert client.get("/api/datasets", headers=_bearer(VALID_TOKEN)).status_code == 403


def test_allowlist_is_case_and_whitespace_tolerant(client, sso_on, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "  ADA@Example.COM , other@x.com ")
    assert client.get("/api/datasets", headers=_bearer(VALID_TOKEN)).status_code == 200


def test_allowlist_unset_permits_any_verified_email(client, sso_on, monkeypatch):
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    assert client.get("/api/datasets", headers=_bearer(VALID_TOKEN)).status_code == 200


def test_sso_enabled_boundaries_use_verified_name(client, sso_on):
    resp = client.post(
        f"/api/datasets/{DATASET}/conversations/{CONV_A}/boundaries",
        headers=_bearer(VALID_TOKEN),
        json={"segments": [{"message_indices": [0, 1]}], "reviewed_by": "ignored"},
    )
    assert resp.status_code == 200
    gold = db.read_gold_segments(DATASET, CONV_A)
    assert all(g["reviewed_by"] == VERIFIED_NAME for g in gold)
