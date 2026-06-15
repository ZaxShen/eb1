"""Offline tests for the SuperDialseg adapter, gold spans, and gold ingestion.

No MongoDB / PostgreSQL / LLM / network access — the SuperDialseg fixture drives
everything; gold ingestion runs against a tmp datasets root.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from annotation.backend import db
from pipeline.adapters import get_loader
from pipeline.adapters.superdialseg import SuperDialsegLoader
from pipeline.metadata import ingest_superdialseg_gold
from pipeline.metadata.provider import SqliteDatasetProvider
from pipeline.metadata.seed_superdialseg import seed as seed_superdialseg
from pipeline.segmentation.windowing import _pre_segment

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "datasets" / "superdialseg" / "sample.jsonl"
)
_NORMALIZED_KEYS = {"_id", "chat", "type", "message", "createdAt"}


@pytest.fixture
def superdialseg_dialogues() -> list[dict]:
    text = _FIXTURE.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ── Adapter normalization ─────────────────────────────────────────────────────


class TestSuperDialsegLoader:
    def test_maps_to_ordered_normalized_messages(self, superdialseg_dialogues):
        dialogue = superdialseg_dialogues[0]
        msgs = SuperDialsegLoader().load_conversation(dialogue)

        assert len(msgs) == len(dialogue["utterances"])
        for m in msgs:
            assert set(m.keys()) == _NORMALIZED_KEYS
            assert m["type"] in {"user", "assistant"}
            assert isinstance(m["createdAt"], datetime)

    def test_role_mapping_user_and_agent(self, superdialseg_dialogues):
        dialogue = superdialseg_dialogues[0]
        msgs = SuperDialsegLoader().load_conversation(dialogue)
        expected = [
            "user" if u["speaker"] == "User" else "assistant"
            for u in dialogue["utterances"]
        ]
        assert [m["type"] for m in msgs] == expected

    def test_synthetic_ids_and_chat_id(self, superdialseg_dialogues):
        dialogue = superdialseg_dialogues[0]
        msgs = SuperDialsegLoader().load_conversation(dialogue)
        chat_id = dialogue["dialogue_id"]

        assert all(m["chat"] == chat_id for m in msgs)
        assert [m["_id"] for m in msgs] == [f"{chat_id}:{i}" for i in range(len(msgs))]

    def test_synthesized_timestamps_are_monotonic(self, superdialseg_dialogues):
        msgs = SuperDialsegLoader().load_conversation(superdialseg_dialogues[0])
        ts = [m["createdAt"] for m in msgs]
        assert ts == sorted(ts)
        for i in range(1, len(ts)):
            assert (ts[i] - ts[i - 1]).total_seconds() == 1

    def test_registry_returns_loader(self):
        assert isinstance(get_loader("superdialseg"), SuperDialsegLoader)


# ── Gold segment recovery ─────────────────────────────────────────────────────


class TestGoldSegments:
    def test_two_segment_dialogue_yields_two_spans(self, superdialseg_dialogues):
        dialogue = superdialseg_dialogues[0]
        spans = SuperDialsegLoader().gold_segments(dialogue)

        assert len(spans) == 2
        assert spans[0]["message_indices"] == [0, 1, 2, 3]
        assert spans[1]["message_indices"] == [4, 5, 6]
        assert [s["segment_id"] for s in spans] == [0, 1]
        assert all(s["conversation"] == dialogue["dialogue_id"] for s in spans)

    def test_three_segment_dialogue_yields_three_spans(self, superdialseg_dialogues):
        dialogue = superdialseg_dialogues[1]
        spans = SuperDialsegLoader().gold_segments(dialogue)

        assert len(spans) == 3
        flat = [i for s in spans for i in s["message_indices"]]
        assert flat == list(range(len(dialogue["utterances"])))
        assert [s["segment_id"] for s in spans] == [0, 1, 2]

    def test_indices_align_with_normalized_stream(self, superdialseg_dialogues):
        dialogue = superdialseg_dialogues[0]
        msgs = SuperDialsegLoader().load_conversation(dialogue)
        spans = SuperDialsegLoader().gold_segments(dialogue)
        covered = [i for s in spans for i in s["message_indices"]]
        assert covered == list(range(len(msgs)))


# ── Pre-segmentation on normalized messages (no DB) ───────────────────────────


class TestPreSegmentOnNormalized:
    def test_yields_at_least_one_chunk(self, superdialseg_dialogues):
        msgs = SuperDialsegLoader().load_conversation(superdialseg_dialogues[0])
        chat_ids = [m["chat"] for m in msgs]

        chunks = _pre_segment(msgs, chat_ids)

        assert len(chunks) >= 1
        covered = [m["_id"] for c in chunks for m in c.messages]
        assert set(covered) == {m["_id"] for m in msgs}


# ── Gold ingestion ────────────────────────────────────────────────────────────


class TestIngestGold:
    def _write_sample(self, tmp_path: Path, dialogues: list[dict]) -> Path:
        ds_dir = tmp_path / "superdialseg"
        ds_dir.mkdir(parents=True)
        sample = ds_dir / "sample.jsonl"
        sample.write_text(
            "\n".join(json.dumps(d) for d in dialogues) + "\n", encoding="utf-8"
        )
        return sample

    def test_ingest_writes_gold_rows(self, tmp_path, superdialseg_dialogues):
        sample = self._write_sample(tmp_path, superdialseg_dialogues)
        written = ingest_superdialseg_gold.ingest(sample, root=tmp_path)

        expected = sum(
            len(SuperDialsegLoader().gold_segments(d)) for d in superdialseg_dialogues
        )
        assert written == expected

        conv = superdialseg_dialogues[0]["dialogue_id"]
        gold = db.read_gold_segments("superdialseg", conv, tmp_path)
        assert len(gold) == 2
        assert all(g["source"] == "gold" for g in gold)
        assert all(g["base_segment_id"] is None for g in gold)
        assert [g["message_indices"] for g in gold] == [[0, 1, 2, 3], [4, 5, 6]]

    def test_ingest_is_idempotent(self, tmp_path, superdialseg_dialogues):
        sample = self._write_sample(tmp_path, superdialseg_dialogues)
        ingest_superdialseg_gold.ingest(sample, root=tmp_path)
        ingest_superdialseg_gold.ingest(sample, root=tmp_path)

        conv = superdialseg_dialogues[0]["dialogue_id"]
        gold = db.read_gold_segments("superdialseg", conv, tmp_path)
        assert len(gold) == 2


# ── Metadata seed ─────────────────────────────────────────────────────────────


class TestSeedSuperDialseg:
    def test_seed_roundtrip_dataset_config(self, tmp_path):
        meta = tmp_path / "metadata.db"
        seed_superdialseg(meta)

        config = SqliteDatasetProvider(meta).dataset_config()
        assert config.name == "superdialseg"
        assert config.prompt_profile == "v4"
        assert config.taxonomy_mode == "open"
        assert config.role_map == {"User": "user", "Agent": "assistant"}
        assert config.accelerators == {
            "p1": False, "p3": False, "p4": False, "templates": False,
        }
        assert all(v is False for v in config.accelerators.values())

    def test_seed_empty_taxonomy_and_rules(self, tmp_path):
        meta = tmp_path / "metadata.db"
        seed_superdialseg(meta)
        provider = SqliteDatasetProvider(meta)

        assert provider.taxonomy("user") == []
        assert provider.accelerator_rules() == []
        assert provider.topic_filters() == []
        assert provider.preprocessing_rules() == []
