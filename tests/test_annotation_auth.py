"""Google SSO tests for the annotation backend — fully offline.

The Google ID-token verifier is **mocked** (real sign-in needs the operator's
Client ID and network), so these tests cover the gate and the
``reviewed_by = verified name`` override without any external dependency.

SSO is toggled via the ``GOOGLE_CLIENT_ID`` env var; ``auth._verify_oauth2_token``
is monkeypatched to return a fixed claim set for a known token.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from annotation.backend import auth, db, routes
from annotation.backend.app import create_app
from pipeline.metadata.seed_wildchat import seed as seed_wildchat

CONV_A = "a1f3c9d2e7b40516"

_SAMPLE_ROWS = [
    {
        "conversation_hash": CONV_A,
        "model": "gpt-4",
        "timestamp": "2023-08-14T09:12:00Z",
        "turn": 2,
        "language": "English",
        "conversation": [
            {"role": "user", "content": "Draft a cover letter opening."},
            {"role": "assistant", "content": "Here is an opening paragraph."},
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

VALID_TOKEN = "valid-mock-id-token"
VERIFIED_NAME = "Ada Lovelace"


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


@pytest.fixture()
def datasets_root(tmp_path):
    ds_dir = tmp_path / "wildchat"
    ds_dir.mkdir(parents=True)
    (ds_dir / "sample.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _SAMPLE_ROWS) + "\n", encoding="utf-8"
    )
    seed_wildchat(ds_dir / "metadata.db")
    _build_output_db(ds_dir / "output.db")
    routes.set_datasets_root(tmp_path)
    yield tmp_path
    routes.set_datasets_root(None)


@pytest.fixture()
def client(datasets_root):
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


def test_auth_config_reports_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/api/auth/config").json() == {"sso_enabled": False}


def test_auth_config_reports_enabled(client, sso_on):
    assert client.get("/api/auth/config").json() == {"sso_enabled": True}


def test_sso_disabled_endpoints_work_without_token(client, monkeypatch, datasets_root):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.get("/api/datasets").status_code == 200

    resp = client.post(
        "/api/datasets/wildchat/segments/1/annotate",
        json={
            "true_topic": "writing_help",
            "true_subtopic": "cover_letter_drafting",
            "reviewed_by": "manual-reviewer",
        },
    )
    assert resp.status_code == 200
    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    assert gold[0]["reviewed_by"] == "manual-reviewer"


def test_sso_enabled_blocks_missing_token(client, sso_on):
    assert client.get("/api/datasets").status_code == 401
    resp = client.post(
        "/api/datasets/wildchat/segments/1/annotate",
        json={"true_topic": "writing_help", "true_subtopic": "cover_letter_drafting"},
    )
    assert resp.status_code == 401


def test_sso_enabled_rejects_invalid_token(client, sso_on):
    resp = client.get("/api/datasets", headers=_bearer("garbage"))
    assert resp.status_code == 401


def test_sso_enabled_valid_token_sets_reviewed_by_to_verified_name(
    client, sso_on, datasets_root
):
    resp = client.post(
        "/api/datasets/wildchat/segments/1/annotate",
        headers=_bearer(VALID_TOKEN),
        json={
            "true_topic": "writing_help",
            "true_subtopic": "cover_letter_drafting",
            "reviewed_by": "ignored-client-value",
        },
    )
    assert resp.status_code == 200
    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    relabel = [g for g in gold if g["base_segment_id"] == 1]
    assert relabel[0]["reviewed_by"] == VERIFIED_NAME


def test_sso_enabled_boundaries_use_verified_name(client, sso_on, datasets_root):
    resp = client.post(
        f"/api/datasets/wildchat/conversations/{CONV_A}/boundaries",
        headers=_bearer(VALID_TOKEN),
        json={
            "segments": [{"message_indices": [0, 1]}],
            "reviewed_by": "ignored",
        },
    )
    assert resp.status_code == 200
    gold = db.read_gold_segments("wildchat", CONV_A, datasets_root)
    assert all(g["reviewed_by"] == VERIFIED_NAME for g in gold)
