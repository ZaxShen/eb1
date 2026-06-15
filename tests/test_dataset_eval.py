"""
Unit tests for pipeline/evaluation/dataset_eval.py.

Synthetic fixtures with KNOWN expected values — no Mongo / Postgres / LLM /
network. Tiny ``output.db`` + ``gold.db`` SQLite stores are built in a tmp
datasets root and scored end to end.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pipeline.evaluation import evaluate_dataset as exported_evaluate_dataset
from pipeline.evaluation.dataset_eval import (
    boundary_prf,
    evaluate_conversation,
    evaluate_dataset,
    load_gold,
    load_predicted,
    pk,
    segments_to_boundaries,
    window_diff,
)

_OUTPUT_SCHEMA = """
CREATE TABLE run_segment (
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

_GOLD_SCHEMA = """
CREATE TABLE gold_segment (
    id              INTEGER PRIMARY KEY,
    conversation    TEXT,
    message_indices TEXT,
    topic           TEXT,
    subtopic        TEXT,
    sentiment       TEXT,
    base_segment_id INTEGER,
    source          TEXT,
    reviewed_by     TEXT,
    reviewed_at     TEXT
);
"""


# ── Fixture builders ───────────────────────────────────────────────────────────


def _write_output(root: Path, dataset: str, segments: list[dict]) -> None:
    path = root / dataset / "output.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_OUTPUT_SCHEMA)
        for i, seg in enumerate(segments):
            conn.execute(
                "INSERT INTO run_segment "
                "(dataset, conversation, chunk_index, message_indices, "
                "topic, subtopic) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    dataset,
                    seg["conversation"],
                    i,
                    json.dumps(seg["message_indices"]),
                    seg.get("topic"),
                    seg.get("subtopic"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _write_gold(root: Path, dataset: str, segments: list[dict]) -> None:
    path = root / dataset / "gold.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_GOLD_SCHEMA)
        for seg in segments:
            conn.execute(
                "INSERT INTO gold_segment "
                "(conversation, message_indices, topic, subtopic, source) "
                "VALUES (?, ?, ?, ?, 'gold')",
                (
                    seg["conversation"],
                    json.dumps(seg["message_indices"]),
                    seg.get("topic"),
                    seg.get("subtopic"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _seg(conv: str, indices: list[int], topic: str = "t", subtopic: str = "s") -> dict:
    return {
        "conversation": conv,
        "message_indices": indices,
        "topic": topic,
        "subtopic": subtopic,
    }


# ── boundary-sequence helpers ──────────────────────────────────────────────────


def test_segments_to_boundaries_marks_segment_ends():
    segs = [_seg("c", [0, 1, 2, 3]), _seg("c", [4, 5, 6, 7])]
    assert segments_to_boundaries(segs) == [0, 0, 0, 1, 0, 0, 0]


def test_boundary_prf_perfect_no_boundaries():
    assert boundary_prf([0, 0, 0], [0, 0, 0]) == (1.0, 1.0, 1.0)


# ── Identical predicted == gold → perfect scores ───────────────────────────────


def test_identical_prediction_is_perfect(tmp_path):
    dataset = "syn"
    gold = [_seg("c1", [0, 1, 2, 3]), _seg("c1", [4, 5, 6, 7])]
    _write_gold(tmp_path, dataset, gold)
    _write_output(tmp_path, dataset, list(gold))

    report = evaluate_dataset(dataset, root=tmp_path)
    row = report["conversations"][0]

    assert row["pk"] == 0.0
    assert row["window_diff"] == 0.0
    assert row["boundary_f1"] == 1.0
    assert row["unified_score"] == 1.0

    agg = report["aggregate"]
    assert agg["mean_pk"] == 0.0
    assert agg["mean_window_diff"] == 0.0
    assert agg["boundary_f1"] == 1.0
    assert agg["unified_score"] == 1.0
    assert agg["gold_coverage"] == 1.0


# ── Known single-boundary-off case → hand-computed metrics ─────────────────────


def test_single_boundary_off_hand_computed():
    # 8 messages → boundary sequence length 7.
    # gold boundary at position 3; hyp boundary shifted to position 4.
    gold = [_seg("c", [0, 1, 2, 3]), _seg("c", [4, 5, 6, 7])]
    pred = [_seg("c", [0, 1, 2, 3, 4]), _seg("c", [5, 6, 7])]

    row = evaluate_conversation("c", gold, pred)

    # mean gold segment length = 4 → k = round(4/2) = 2 → 6 windows, 2 errors.
    assert row["k"] == 2
    assert row["pk"] == round(2 / 6, 4)
    assert row["window_diff"] == round(2 / 6, 4)
    # No boundary position coincides → precision = recall = F1 = 0.
    assert row["boundary_f1"] == 0.0


def test_pk_window_diff_direct_known_values():
    ref = [0, 0, 0, 1, 0, 0, 0]
    hyp = [0, 0, 0, 0, 1, 0, 0]
    assert pk(ref, hyp, k=2) == round(2 / 6, 4) or abs(pk(ref, hyp, k=2) - 2 / 6) < 1e-9
    assert abs(window_diff(ref, hyp, k=2) - 2 / 6) < 1e-9
    # identical sequences are error-free
    assert pk(ref, ref, k=2) == 0.0
    assert window_diff(ref, ref, k=2) == 0.0


# ── Missing gold → coverage 0, no crash ────────────────────────────────────────


def test_missing_gold_is_graceful(tmp_path):
    dataset = "nogold"
    _write_output(tmp_path, dataset, [_seg("c1", [0, 1, 2, 3])])
    # No gold.db written at all.

    report = evaluate_dataset(dataset, root=tmp_path)

    assert report["aggregate"]["gold_coverage"] == 0.0
    assert report["aggregate"]["scored_conversations"] == 0
    assert report["conversations"] == []


def test_empty_gold_db_is_graceful(tmp_path):
    dataset = "emptygold"
    _write_output(tmp_path, dataset, [_seg("c1", [0, 1, 2, 3])])
    _write_gold(tmp_path, dataset, [])  # gold.db exists but has no rows

    report = evaluate_dataset(dataset, root=tmp_path)
    assert report["aggregate"]["gold_coverage"] == 0.0
    assert report["conversations"] == []


# ── Partial coverage is reported, not crashed ──────────────────────────────────


def test_partial_coverage(tmp_path):
    dataset = "partial"
    _write_output(
        tmp_path,
        dataset,
        [_seg("c1", [0, 1, 2, 3]), _seg("c2", [0, 1, 2, 3])],
    )
    _write_gold(tmp_path, dataset, [_seg("c1", [0, 1, 2, 3])])  # only c1 has gold

    report = evaluate_dataset(dataset, root=tmp_path)
    agg = report["aggregate"]
    assert agg["total_conversations"] == 2
    assert agg["scored_conversations"] == 1
    assert agg["gold_coverage"] == 0.5
    assert [r["conversation"] for r in report["conversations"]] == ["c1"]


# ── Loaders read the SQLite stores ─────────────────────────────────────────────


def test_loaders_group_by_conversation(tmp_path):
    dataset = "load"
    _write_output(
        tmp_path,
        dataset,
        [_seg("c1", [0, 1]), _seg("c1", [2, 3]), _seg("c2", [0, 1])],
    )
    _write_gold(tmp_path, dataset, [_seg("c1", [0, 1, 2, 3])])

    predicted = load_predicted(dataset, root=tmp_path)
    gold = load_gold(dataset, root=tmp_path)

    assert set(predicted) == {"c1", "c2"}
    assert len(predicted["c1"]) == 2
    assert predicted["c1"][0]["message_indices"] == [0, 1]
    assert set(gold) == {"c1"}


def test_missing_stores_return_empty(tmp_path):
    assert load_predicted("absent", root=tmp_path) == {}
    assert load_gold("absent", root=tmp_path) == {}


# ── Public export ──────────────────────────────────────────────────────────────


def test_evaluate_dataset_is_exported():
    assert exported_evaluate_dataset is evaluate_dataset
