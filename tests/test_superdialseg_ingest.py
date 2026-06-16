"""Offline tests for the SuperDialseg gold ingest loader.

No MongoDB / PostgreSQL / LLM / network access. A small fixture mirrors the real
gold release shape (``{"dial_data": {"superseg-v2": [...]}}``); the full release
is exercised opportunistically when ``EB1_SUPERDIALSEG_PATH`` points at it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from annotation.ingest.sources import (
    _coerce_dialogue,
    _dialogue_records,
    superdialseg_stream,
)
from pipeline.adapters.superdialseg import SuperDialsegLoader


def _gold_dialogue(dial_id: str, labels: list[int], topic_ids: list[int]) -> dict:
    return {
        "dial_id": dial_id,
        "turns": [
            {
                "role": "user" if i % 2 == 0 else "agent",
                "utterance": f"turn {i}",
                "topic_id": topic_ids[i],
                "segmentation_label": labels[i],
            }
            for i in range(len(labels))
        ],
    }


# Real-shape fixture: nested under dial_data -> superseg-v2. The first dialogue
# uses the example boundaries from segmentation_file_test.json (4 label==1 turns
# -> 5 segments); the second deliberately gives topic_id a boundary that the
# canonical segmentation_label does NOT, to pin that segment_id follows the
# label, not topic_id.
_FIXTURE = {
    "dial_data": {
        "superseg-v2": [
            _gold_dialogue(
                "dial-0",
                labels=[0, 0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],
                topic_ids=[0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4],
            ),
            _gold_dialogue(
                "dial-1",
                labels=[0, 1, 0, 0],
                topic_ids=[0, 0, 7, 9],
            ),
        ]
    }
}


@pytest.fixture
def gold_path(tmp_path: Path) -> Path:
    path = tmp_path / "segmentation_file_test.json"
    path.write_text(json.dumps(_FIXTURE), encoding="utf-8")
    return path


# ── Nesting unwrap ────────────────────────────────────────────────────────────


class TestDialogueRecords:
    def test_unwraps_dial_data_variant_nesting(self):
        records = list(_dialogue_records(_FIXTURE))
        assert len(records) == 2
        assert [r["dial_id"] for r in records] == ["dial-0", "dial-1"]

    def test_accepts_bare_list(self):
        items = [{"dial_id": "a"}, {"dial_id": "b"}]
        assert list(_dialogue_records(items)) == items

    def test_accepts_single_object(self):
        item = {"dial_id": "solo"}
        assert list(_dialogue_records(item)) == [item]


# ── Stream over the real-shape fixture ────────────────────────────────────────


class TestSuperdialsegStream:
    def test_yields_all_nonempty_dialogues(self, gold_path, monkeypatch):
        monkeypatch.setenv("EB1_SUPERDIALSEG_PATH", str(gold_path))
        dialogues = list(superdialseg_stream())
        assert len(dialogues) == 2
        assert all(d["utterances"] for d in dialogues)
        assert [d["dialogue_id"] for d in dialogues] == ["dial-0", "dial-1"]

    def test_limit_is_honored(self, gold_path, monkeypatch):
        monkeypatch.setenv("EB1_SUPERDIALSEG_PATH", str(gold_path))
        assert len(list(superdialseg_stream(limit=1))) == 1


# ── segment_id derivation from segmentation_label ─────────────────────────────


class TestSegmentIdDerivation:
    def test_segment_id_increments_after_label_one(self):
        dialogue = _coerce_dialogue(_FIXTURE["dial_data"]["superseg-v2"][0])
        seg_ids = [u["segment_id"] for u in dialogue["utterances"]]
        assert seg_ids == [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4]

    def test_segment_id_follows_label_not_topic_id(self):
        # topic_id breaks at turns 2 and 3, but the gold label breaks only after
        # turn 1 -> two segments, not three.
        dialogue = _coerce_dialogue(_FIXTURE["dial_data"]["superseg-v2"][1])
        seg_ids = [u["segment_id"] for u in dialogue["utterances"]]
        assert seg_ids == [0, 0, 1, 1]

    def test_gold_segment_boundaries_match_segmentation_label(self):
        record = _FIXTURE["dial_data"]["superseg-v2"][0]
        labels = [t["segmentation_label"] for t in record["turns"]]
        dialogue = _coerce_dialogue(record)
        seg_ids = [u["segment_id"] for u in dialogue["utterances"]]

        mismatches = 0
        for i in range(len(labels) - 1):
            gold_break = labels[i] == 1
            seg_break = seg_ids[i] != seg_ids[i + 1]
            if gold_break != seg_break:
                mismatches += 1
        assert mismatches == 0

    def test_segment_count_equals_label_ones_plus_one(self):
        record = _FIXTURE["dial_data"]["superseg-v2"][0]
        labels = [t["segmentation_label"] for t in record["turns"]]
        dialogue = _coerce_dialogue(record)
        segments = SuperDialsegLoader().gold_segments(dialogue)
        assert len(segments) == sum(labels) + 1

    def test_topic_id_is_carried_through(self):
        record = _FIXTURE["dial_data"]["superseg-v2"][0]
        dialogue = _coerce_dialogue(record)
        assert [u["topic_id"] for u in dialogue["utterances"]] == [
            t["topic_id"] for t in record["turns"]
        ]


# ── Backward compat: explicit segment_id and topic_id fallback ────────────────


class TestSegmentIdPrecedence:
    def test_explicit_segment_id_wins(self):
        item = {
            "dialogue_id": "x",
            "utterances": [
                {"speaker": "User", "text": "a", "segment_id": 5},
                {"speaker": "Agent", "text": "b", "segment_id": 5},
            ],
        }
        dialogue = _coerce_dialogue(item)
        assert [u["segment_id"] for u in dialogue["utterances"]] == [5, 5]

    def test_topic_id_fallback_when_no_label(self):
        item = {
            "dial_id": "y",
            "turns": [
                {"role": "user", "utterance": "a", "topic_id": 3},
                {"role": "agent", "utterance": "b", "topic_id": 8},
            ],
        }
        dialogue = _coerce_dialogue(item)
        assert [u["segment_id"] for u in dialogue["utterances"]] == [3, 8]


# ── Full real release (opportunistic) ─────────────────────────────────────────

_REAL_GOLD = Path(
    "/Users/Zax/Git/GitHub/eb1/data/extracted/Dialogue_Segmentation/superseg/"
    "segmentation_file_test.json"
)


@pytest.mark.skipif(
    not _REAL_GOLD.exists(),
    reason="full SuperDialseg gold release not present (untracked data file)",
)
class TestRealGoldRelease:
    def test_yields_1322_nonempty_dialogues(self, monkeypatch):
        monkeypatch.setenv("EB1_SUPERDIALSEG_PATH", str(_REAL_GOLD))
        dialogues = list(superdialseg_stream())
        assert len(dialogues) == 1322
        assert sum(1 for d in dialogues if d["utterances"]) == 1322

    def test_no_boundary_mismatches_across_corpus(self, monkeypatch):
        monkeypatch.setenv("EB1_SUPERDIALSEG_PATH", str(_REAL_GOLD))
        raw = json.loads(_REAL_GOLD.read_text(encoding="utf-8"))
        records = raw["dial_data"]["superseg-v2"]
        dialogues = list(superdialseg_stream())
        loader = SuperDialsegLoader()

        for dialogue, record in zip(dialogues, records, strict=True):
            labels = [t["segmentation_label"] for t in record["turns"]]
            seg_ids = [u["segment_id"] for u in dialogue["utterances"]]
            for i in range(len(labels) - 1):
                assert (labels[i] == 1) == (seg_ids[i] != seg_ids[i + 1])
            assert len(loader.gold_segments(dialogue)) == sum(labels) + 1
