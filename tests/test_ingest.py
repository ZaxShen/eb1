"""Tests for the full-dataset streaming ingester (``annotation.ingest``).

Two layers, both offline (no HuggingFace / Drive / network):

- **Source-stream unit tests** exercise the gating + normalization logic that
  has no database dependency (the LMSYS missing-token error; SuperDialseg gold
  recovery from ``segment_id``).
- **PG ingest tests** monkeypatch each source stream to a tiny in-memory fixture
  and run ``annotation.ingest.run.ingest`` against a real Postgres at
  ``EB1_ANNOTATION_DSN`` (the docker compose service). They assert the
  whole-conversation seed semantics, idempotency, and SuperDialseg gold rows.
  The PG layer is skipped when the DSN is unset so the offline suite stays green::

      docker compose -f annotation/docker-compose.yml up -d
      export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation
      uv run pytest tests/test_ingest.py -q
"""

from __future__ import annotations

import os

import pytest

from annotation.ingest import sources
from annotation.ingest.sources import IngestAuthError

# ---------------------------------------------------------------------------
# Tiny offline fixtures (the shape each raw stream yields)
# ---------------------------------------------------------------------------

WILDCHAT_ROW = {
    "conversation_hash": "ingesttest_wc_0001",
    "timestamp": "2023-04-09T00:02:53Z",
    "conversation": [
        {"role": "user", "content": "Draft a cover letter opening."},
        {"role": "assistant", "content": "Here is an opening paragraph."},
        {"role": "user", "content": "How far is the Andromeda galaxy?"},
        {"role": "assistant", "content": "About 2.5 million light-years."},
    ],
}

WILDCHAT_ROW_WITH_NUL = {
    "conversation_hash": "ingesttest_wc_nul",
    "timestamp": "2023-04-09T00:02:53Z",
    "conversation": [
        {"role": "user", "content": "Tell me about\x00 the Andromeda galaxy."},
        {"role": "assistant", "content": "It is\x00 about 2.5 million light-years away."},
    ],
}

SUPERDIALSEG_DIALOGUE = {
    "dialogue_id": "ingesttest_sds_0001",
    "utterances": [
        {"speaker": "User", "text": "Renew my passport?", "segment_id": 0},
        {"speaker": "Agent", "text": "Bring your current passport.", "segment_id": 0},
        {"speaker": "User", "text": "Now book me a flight.", "segment_id": 1},
        {"speaker": "Agent", "text": "Where to?", "segment_id": 1},
    ],
}


# ---------------------------------------------------------------------------
# Source-stream unit tests (no DB, no network)
# ---------------------------------------------------------------------------


def test_lmsys_stream_raises_clear_error_without_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    with pytest.raises(IngestAuthError) as excinfo:
        next(sources.lmsys_stream(limit=1))
    message = str(excinfo.value)
    assert "HF_TOKEN" in message
    assert "lmsys/lmsys-chat-1m" in message


def test_superdialseg_local_path_stream(monkeypatch, tmp_path):
    import json

    path = tmp_path / "sds.jsonl"
    path.write_text(json.dumps(SUPERDIALSEG_DIALOGUE) + "\n", encoding="utf-8")
    monkeypatch.setenv("EB1_SUPERDIALSEG_PATH", str(path))

    dialogues = list(sources.superdialseg_stream())
    assert len(dialogues) == 1
    assert dialogues[0]["dialogue_id"] == "ingesttest_sds_0001"
    assert [u["segment_id"] for u in dialogues[0]["utterances"]] == [0, 0, 1, 1]


def test_streams_registry_covers_three_datasets():
    assert set(sources.STREAMS) == {"wildchat", "lmsys", "superdialseg"}


# ---------------------------------------------------------------------------
# PG ingest tests (real Postgres; monkeypatched streams)
# ---------------------------------------------------------------------------

pg = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)


_TEST_DATASETS = ("wildchat", "superdialseg")


@pytest.fixture()
def _db():
    from annotation.backend import db

    db.reset_pool()
    db.apply_schema()
    for ds in _TEST_DATASETS:
        _wipe_test_rows(db, ds)
    yield db
    for ds in _TEST_DATASETS:
        _wipe_test_rows(db, ds)
    db.reset_pool()


def _wipe_test_rows(db, dataset: str) -> None:
    """Remove only this module's ``ingesttest_*`` rows from the shared dataset."""
    pool = db.get_pool()
    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM conversation WHERE dataset = %s AND ext_id LIKE 'ingesttest%%'",
            (dataset,),
        )


def _counts(db, dataset: str, ext_id: str) -> dict:
    pool = db.get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, ext_id),
        ).fetchone()
        if conv is None:
            return {"messages": 0, "predicted": 0, "gold": 0}
        cid = conv["id"]
        messages = conn.execute(
            "SELECT count(*) AS n FROM message WHERE conversation_id = %s", (cid,)
        ).fetchone()["n"]
        predicted = conn.execute(
            "SELECT message_indices FROM segment "
            "WHERE conversation_id = %s AND source = 'predicted'",
            (cid,),
        ).fetchall()
        gold = conn.execute(
            "SELECT message_indices FROM segment "
            "WHERE conversation_id = %s AND source = 'gold' ORDER BY chunk_index",
            (cid,),
        ).fetchall()
    return {
        "messages": messages,
        "predicted": [list(r["message_indices"]) for r in predicted],
        "gold": [list(r["message_indices"]) for r in gold],
    }


@pg
def test_wildchat_one_conversation_produces_whole_conv_seed(monkeypatch, _db):
    from annotation.ingest import run
    monkeypatch.setattr(
        sources, "wildchat_stream", lambda limit=None: iter([WILDCHAT_ROW])
    )

    result = run.ingest("wildchat", batch_size=10)
    assert result["written"] == 1

    counts = _counts(_db, "wildchat", "ingesttest_wc_0001")
    assert counts["messages"] == 4
    # Exactly ONE predicted segment spanning every message index.
    assert counts["predicted"] == [[0, 1, 2, 3]]
    assert counts["gold"] == []


@pg
def test_wildchat_reingest_is_idempotent(monkeypatch, _db):
    from annotation.ingest import run
    monkeypatch.setattr(
        sources, "wildchat_stream", lambda limit=None: iter([WILDCHAT_ROW])
    )

    first = run.ingest("wildchat", batch_size=10)
    assert first["written"] == 1
    second = run.ingest("wildchat", batch_size=10)
    assert second["written"] == 0 and second["skipped"] == 1

    counts = _counts(_db, "wildchat", "ingesttest_wc_0001")
    assert counts["messages"] == 4
    assert counts["predicted"] == [[0, 1, 2, 3]]


@pg
def test_wildchat_content_with_nul_byte_ingests(monkeypatch, _db):
    """Real WildChat content has NUL (0x00) bytes Postgres TEXT rejects.

    The ingester must strip them; ingest succeeds and stored content equals the
    content with NUL removed.
    """
    from annotation.ingest import run
    monkeypatch.setattr(
        sources, "wildchat_stream", lambda limit=None: iter([WILDCHAT_ROW_WITH_NUL])
    )

    result = run.ingest("wildchat", batch_size=10)
    assert result["written"] == 1

    pool = _db.get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            ("wildchat", "ingesttest_wc_nul"),
        ).fetchone()
        rows = conn.execute(
            "SELECT content FROM message WHERE conversation_id = %s ORDER BY idx",
            (conv["id"],),
        ).fetchall()

    stored = [r["content"] for r in rows]
    expected = [
        m["content"].replace("\x00", "")
        for m in WILDCHAT_ROW_WITH_NUL["conversation"]
    ]
    assert stored == expected
    assert all("\x00" not in c for c in stored)


@pg
def test_superdialseg_writes_gold_segments(monkeypatch, _db):
    from annotation.ingest import run
    monkeypatch.setattr(
        sources,
        "superdialseg_stream",
        lambda limit=None: iter([SUPERDIALSEG_DIALOGUE]),
    )

    result = run.ingest("superdialseg", batch_size=10)
    assert result["written"] == 1

    counts = _counts(_db, "superdialseg", "ingesttest_sds_0001")
    assert counts["messages"] == 4
    # Whole-conversation predicted seed PLUS the two gold spans from segment_id.
    assert counts["predicted"] == [[0, 1, 2, 3]]
    assert counts["gold"] == [[0, 1], [2, 3]]


@pg
def test_superdialseg_gold_idempotent_on_reingest(monkeypatch, _db):
    from annotation.ingest import run
    monkeypatch.setattr(
        sources,
        "superdialseg_stream",
        lambda limit=None: iter([SUPERDIALSEG_DIALOGUE]),
    )

    run.ingest("superdialseg", batch_size=10)
    run.ingest("superdialseg", batch_size=10, skip_existing=False)

    counts = _counts(_db, "superdialseg", "ingesttest_sds_0001")
    assert counts["predicted"] == [[0, 1, 2, 3]]
    assert counts["gold"] == [[0, 1], [2, 3]]
