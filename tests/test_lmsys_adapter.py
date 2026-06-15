"""Offline tests for the LMSYS adapter and its metadata seed.

No MongoDB / PostgreSQL / LLM / network access — the LMSYS fixture drives
everything.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from pipeline.adapters import get_loader
from pipeline.adapters.lmsys import LMSYSLoader
from pipeline.metadata.provider import SqliteDatasetProvider
from pipeline.metadata.seed_lmsys import seed as seed_lmsys
from pipeline.segmentation.windowing import _pre_segment

_FIXTURE = Path(__file__).resolve().parents[1] / "datasets" / "lmsys" / "sample.jsonl"
_NORMALIZED_KEYS = {"_id", "chat", "type", "message", "createdAt"}


@pytest.fixture
def lmsys_rows() -> list[dict]:
    text = _FIXTURE.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ── Adapter normalization ─────────────────────────────────────────────────────


class TestLMSYSLoader:
    def test_maps_to_ordered_normalized_messages(self, lmsys_rows):
        msgs = LMSYSLoader().load_conversation(lmsys_rows[0])

        assert len(msgs) == len(lmsys_rows[0]["conversation"])
        for m in msgs:
            assert set(m.keys()) == _NORMALIZED_KEYS
            assert m["type"] in {"user", "assistant"}
            assert isinstance(m["createdAt"], datetime)

        assert [m["type"] for m in msgs] == [
            "user", "assistant", "user", "assistant", "user", "assistant",
        ]

    def test_synthetic_ids_and_chat_id(self, lmsys_rows):
        row = lmsys_rows[0]
        msgs = LMSYSLoader().load_conversation(row)
        chat_id = row["conversation_id"]

        assert all(m["chat"] == chat_id for m in msgs)
        assert [m["_id"] for m in msgs] == [f"{chat_id}:{i}" for i in range(len(msgs))]
        assert str(msgs[0]["_id"]) == f"{chat_id}:0"

    def test_synthesized_timestamps_are_monotonic(self, lmsys_rows):
        msgs = LMSYSLoader().load_conversation(lmsys_rows[0])
        ts = [m["createdAt"] for m in msgs]
        assert ts == sorted(ts)
        for i in range(1, len(ts)):
            assert (ts[i] - ts[i - 1]).total_seconds() == 1

    def test_load_conversations_batches(self, lmsys_rows):
        out = LMSYSLoader().load_conversations(lmsys_rows)
        assert [len(c) for c in out] == [
            len(r["conversation"]) for r in lmsys_rows
        ]

    def test_registry_returns_loader(self):
        assert isinstance(get_loader("lmsys"), LMSYSLoader)


# ── Pre-segmentation on normalized messages (no DB) ───────────────────────────


class TestPreSegmentOnNormalized:
    def test_yields_at_least_one_chunk(self, lmsys_rows):
        msgs = LMSYSLoader().load_conversation(lmsys_rows[0])
        chat_ids = [m["chat"] for m in msgs]

        chunks = _pre_segment(msgs, chat_ids)

        assert len(chunks) >= 1
        covered = [m["_id"] for c in chunks for m in c.messages]
        assert set(covered) == {m["_id"] for m in msgs}


# ── Metadata seed ─────────────────────────────────────────────────────────────


class TestSeedLMSYS:
    def test_seed_roundtrip_dataset_config(self, tmp_path):
        db = tmp_path / "metadata.db"
        seed_lmsys(db)

        config = SqliteDatasetProvider(db).dataset_config()
        assert config.name == "lmsys"
        assert config.prompt_profile == "v4"
        assert config.taxonomy_mode == "open"
        assert config.role_map == {"user": "user", "assistant": "assistant"}
        assert config.accelerators == {
            "p1": False, "p3": False, "p4": False, "templates": False,
        }
        assert all(v is False for v in config.accelerators.values())

    def test_seed_empty_taxonomy_and_rules(self, tmp_path):
        db = tmp_path / "metadata.db"
        seed_lmsys(db)
        provider = SqliteDatasetProvider(db)

        assert provider.taxonomy("user") == []
        assert provider.accelerator_rules() == []
        assert provider.topic_filters() == []
        assert provider.preprocessing_rules() == []
