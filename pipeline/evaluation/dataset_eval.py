"""
Co-designed per-dataset segmentation evaluation — score predicted spans
against human / corpus gold, sharing the per-dataset SQLite data model.

This closes the loop of the universal pipeline::

    pipeline (producer)  ->  gold (annotation tool + SuperDialseg)  ->  SCORER (this)

For one dataset ``<ds>`` it reads:

  - predicted spans from ``datasets/<ds>/output.db`` (table ``run_segment``);
  - gold spans from ``datasets/<ds>/gold.db`` (table ``gold_segment``).

Both are grouped by conversation; only conversations present in BOTH stores are
scored. Per conversation it computes the field-standard segmentation metrics —
``Pk``, ``WindowDiff`` and boundary precision / recall / F1 (comparable to
SuperDialseg's published numbers) — plus the topic-aware ``Unified Score``.

The Unified Score and the optimal Hungarian span matching are NOT reimplemented:
they are imported from the frozen ``benchmark_eval`` module. The benchmark
segment shape (``user_id`` / ``id`` / ``chat_messages`` / ``true_topic`` /
``true_sub_topic``) is adapted from the SQLite rows; ``message_indices`` is the
message-id set used for Jaccard and there are no temporal fields, so matching
runs with ``alpha = 1.0`` (message overlap only, no temporal IoU).

No MongoDB, PostgreSQL, LLM, or network access — SQLite files only.

Run via::

    uv run python -m pipeline.evaluation.dataset_eval --dataset superdialseg
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from pipeline.evaluation.benchmark_eval import (
    _compute_unified_score,
    _match_segments_jaccard,
)

DATASETS_ROOT = Path("datasets")


# ── Path resolution ────────────────────────────────────────────────────────────


def dataset_dir(dataset: str, root: Path | None = None) -> Path:
    """Return ``<root>/<dataset>`` (defaults to the ``datasets/`` root)."""
    return (root or DATASETS_ROOT) / dataset


def output_db_path(dataset: str, root: Path | None = None) -> Path:
    """Path to the dataset's predicted-segment store (``output.db``)."""
    return dataset_dir(dataset, root) / "output.db"


def gold_db_path(dataset: str, root: Path | None = None) -> Path:
    """Path to the dataset's gold store (``gold.db``)."""
    return dataset_dir(dataset, root) / "gold.db"


def eval_json_path(dataset: str, root: Path | None = None) -> Path:
    """Path the evaluation report is written to (``eval.json``)."""
    return dataset_dir(dataset, root) / "eval.json"


# ── Loaders (SQLite only) ──────────────────────────────────────────────────────


def _decode_indices(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(i) for i in json.loads(raw)]


def load_predicted(
    dataset: str, root: Path | None = None
) -> dict[str, list[dict]]:
    """Load predicted spans from ``output.db`` grouped by conversation.

    Returns ``{conversation: [segment, ...]}`` where each segment is a dict with
    ``conversation``, ``message_indices`` (``list[int]``), ``topic`` and
    ``subtopic``. Returns an empty dict if the store is absent.
    """
    path = output_db_path(dataset, root)
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT conversation, message_indices, topic, subtopic "
            "FROM run_segment ORDER BY conversation, chunk_index, id"
        ).fetchall()
    finally:
        conn.close()
    return _group_by_conversation(rows)


def load_gold(dataset: str, root: Path | None = None) -> dict[str, list[dict]]:
    """Load gold spans from ``gold.db`` grouped by conversation.

    Returns ``{conversation: [segment, ...]}`` with the same segment shape as
    :func:`load_predicted`. Returns an empty dict if the store is absent (a
    dataset with no gold yet), so callers can report zero coverage rather than
    crashing.
    """
    path = gold_db_path(dataset, root)
    if not path.exists():
        return {}
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT conversation, message_indices, topic, subtopic "
            "FROM gold_segment ORDER BY conversation, id"
        ).fetchall()
    finally:
        conn.close()
    return _group_by_conversation(rows)


def _group_by_conversation(rows) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        seg = {
            "conversation": row["conversation"],
            "message_indices": _decode_indices(row["message_indices"]),
            "topic": row["topic"],
            "subtopic": row["subtopic"],
        }
        grouped.setdefault(row["conversation"], []).append(seg)
    return grouped


# ── Boundary-sequence segmentation metrics ─────────────────────────────────────


def segments_to_boundaries(segments: list[dict]) -> list[int]:
    """Convert message-index spans to a per-message boundary sequence.

    The total number of messages is assumed to be ``max(message_index) + 1``.
    Returns a list of length ``n_messages - 1`` where position ``i`` is ``1``
    when a topic boundary falls between message ``i`` and ``i + 1`` (i.e. the
    end of a segment), else ``0``. The final segment end is not a boundary.
    """
    spans = [sorted(s["message_indices"]) for s in segments if s["message_indices"]]
    if not spans:
        return []
    n_messages = max(idx for span in spans for idx in span) + 1
    if n_messages <= 1:
        return []
    boundaries = [0] * (n_messages - 1)
    for span in spans:
        end = span[-1]
        if end < n_messages - 1:
            boundaries[end] = 1
    return boundaries


def _mean_gold_segment_length(ref_segments: list[dict]) -> float:
    lengths = [len(s["message_indices"]) for s in ref_segments if s["message_indices"]]
    if not lengths:
        return 0.0
    return sum(lengths) / len(lengths)


def _default_k(ref: list[int], ref_segments: list[dict] | None = None) -> int:
    """Window size k = round(half the mean gold segment length), floored at 1."""
    if ref_segments:
        mean_len = _mean_gold_segment_length(ref_segments)
    else:
        n_boundaries = sum(ref) + 1
        mean_len = (len(ref) + 1) / n_boundaries if n_boundaries else 0.0
    k = round(mean_len / 2)
    return max(1, int(k))


def _count_boundaries_in_window(seq: list[int], start: int, k: int) -> int:
    return sum(seq[start : start + k])


def pk(
    ref: list[int],
    hyp: list[int],
    k: int | None = None,
    ref_segments: list[dict] | None = None,
) -> float:
    """Pk segmentation error over a per-message boundary sequence.

    Standard Beeferman sliding window: for every window of ``k`` adjacent
    boundary positions, penalise when reference and hypothesis disagree on
    whether the window's two endpoints lie in the same segment. Lower is better;
    ``0.0`` is a perfect match. With fewer than two messages (empty sequence)
    Pk is ``0.0``.
    """
    if k is None:
        k = _default_k(ref, ref_segments)
    n = len(ref)
    if n < k or k < 1:
        return 0.0
    n_windows = n - k + 1
    errors = 0
    for i in range(n_windows):
        ref_diff = _count_boundaries_in_window(ref, i, k) > 0
        hyp_diff = _count_boundaries_in_window(hyp, i, k) > 0
        if ref_diff != hyp_diff:
            errors += 1
    return errors / n_windows


def window_diff(
    ref: list[int],
    hyp: list[int],
    k: int | None = None,
    ref_segments: list[dict] | None = None,
) -> float:
    """WindowDiff segmentation error over a per-message boundary sequence.

    Pevzner & Hearst sliding window: penalise whenever the *count* of reference
    boundaries differs from the count of hypothesis boundaries inside the window.
    Lower is better; ``0.0`` is a perfect match.
    """
    if k is None:
        k = _default_k(ref, ref_segments)
    n = len(ref)
    if n < k or k < 1:
        return 0.0
    n_windows = n - k + 1
    errors = 0
    for i in range(n_windows):
        ref_count = _count_boundaries_in_window(ref, i, k)
        hyp_count = _count_boundaries_in_window(hyp, i, k)
        if ref_count != hyp_count:
            errors += 1
    return errors / n_windows


def boundary_prf(ref: list[int], hyp: list[int]) -> tuple[float, float, float]:
    """Boundary precision, recall and F1 over the boundary sequence.

    A predicted boundary is a true positive when the reference also marks a
    boundary at the same position. When the reference has no boundaries and the
    hypothesis matches it exactly, precision / recall / F1 are all ``1.0``.
    """
    tp = sum(1 for r, h in zip(ref, hyp) if r == 1 and h == 1)
    pred_pos = sum(hyp)
    ref_pos = sum(ref)
    if ref_pos == 0 and pred_pos == 0:
        return 1.0, 1.0, 1.0
    precision = tp / pred_pos if pred_pos else 0.0
    recall = tp / ref_pos if ref_pos else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1


# ── Unified Score adapter (reuses benchmark_eval helpers) ──────────────────────


def _to_benchmark_segment(seg: dict, seg_id: int, conversation: str) -> dict:
    """Adapt a SQLite span to the ``benchmark_eval`` segment shape.

    ``message_indices`` becomes the ``chat_messages`` set used for Jaccard.
    There are no temporal fields, so matching runs with ``alpha = 1.0``.
    """
    return {
        "id": seg_id,
        "user_id": conversation,
        "chat_messages": list(seg["message_indices"]),
        "true_topic": seg.get("topic"),
        "true_sub_topic": seg.get("subtopic"),
        "topic": seg.get("topic"),
        "sub_topic": seg.get("subtopic"),
    }


def unified_score(
    gold_segments: list[dict], pred_segments: list[dict], conversation: str
) -> dict:
    """Unified Score for one conversation via the frozen benchmark helpers.

    Matches gold to predicted spans with the Hungarian Jaccard matcher
    (``alpha = 1.0`` — pure message-index overlap, no temporal IoU) and feeds the
    matches to ``_compute_unified_score``.
    """
    gt = [
        _to_benchmark_segment(s, i, conversation)
        for i, s in enumerate(gold_segments)
    ]
    model = [
        _to_benchmark_segment(s, i, conversation)
        for i, s in enumerate(pred_segments)
    ]
    matches = _match_segments_jaccard(gt, model, threshold=_JACCARD_THRESHOLD, alpha=1.0)
    return _compute_unified_score(matches, total_model_segments=len(model))


_JACCARD_THRESHOLD = 0.3


# ── Per-conversation + dataset evaluation ──────────────────────────────────────


def evaluate_conversation(
    conversation: str, gold_segments: list[dict], pred_segments: list[dict]
) -> dict:
    """Score one conversation that has both gold and predicted spans."""
    ref = segments_to_boundaries(gold_segments)
    hyp = segments_to_boundaries(pred_segments)
    n = max(len(ref), len(hyp))
    ref = ref + [0] * (n - len(ref))
    hyp = hyp + [0] * (n - len(hyp))

    k = _default_k(ref, ref_segments=gold_segments)
    pk_val = pk(ref, hyp, k=k)
    wd_val = window_diff(ref, hyp, k=k)
    precision, recall, f1 = boundary_prf(ref, hyp)
    unified = unified_score(gold_segments, pred_segments, conversation)

    return {
        "conversation": conversation,
        "gold_segments": len(gold_segments),
        "predicted_segments": len(pred_segments),
        "boundaries": n,
        "k": k,
        "pk": round(pk_val, 4),
        "window_diff": round(wd_val, 4),
        "boundary_precision": round(precision, 4),
        "boundary_recall": round(recall, 4),
        "boundary_f1": round(f1, 4),
        "unified_score": unified["score"],
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def evaluate_dataset(dataset: str, root: Path | None = None) -> dict:
    """Score predicted vs gold segmentation for one dataset.

    Loads both stores, scores every conversation present in BOTH, and returns a
    report dict with per-conversation rows, a dataset aggregate, and
    ``gold_coverage`` (scored conversations / total conversations). Missing or
    empty gold yields zero coverage and an empty conversation list — never an
    exception.
    """
    predicted = load_predicted(dataset, root)
    gold = load_gold(dataset, root)

    all_conversations = set(predicted) | set(gold)
    scorable = sorted(c for c in predicted if c in gold)

    rows = [
        evaluate_conversation(conv, gold[conv], predicted[conv])
        for conv in scorable
    ]

    total = len(all_conversations)
    coverage = len(scorable) / total if total else 0.0

    aggregate = {
        "scored_conversations": len(rows),
        "total_conversations": total,
        "gold_coverage": round(coverage, 4),
        "mean_pk": round(_mean([r["pk"] for r in rows]), 4),
        "mean_window_diff": round(_mean([r["window_diff"] for r in rows]), 4),
        "mean_boundary_precision": round(
            _mean([r["boundary_precision"] for r in rows]), 4
        ),
        "mean_boundary_recall": round(
            _mean([r["boundary_recall"] for r in rows]), 4
        ),
        "boundary_f1": round(_mean([r["boundary_f1"] for r in rows]), 4),
        "unified_score": round(_mean([r["unified_score"] for r in rows]), 4),
    }

    return {
        "dataset": dataset,
        "aggregate": aggregate,
        "conversations": rows,
    }


# ── Report writing + CLI ───────────────────────────────────────────────────────


def write_eval_report(dataset: str, report: dict, root: Path | None = None) -> Path:
    """Write the evaluation report to ``datasets/<ds>/eval.json``."""
    path = eval_json_path(dataset, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def print_summary(report: dict) -> None:
    """Print a human-readable summary table to stdout."""
    agg = report["aggregate"]
    print(f"\n━━━ Dataset Evaluation: {report['dataset']} ━━━")
    print(
        f"Coverage: {agg['scored_conversations']}/{agg['total_conversations']}"
        f" conversations scored ({agg['gold_coverage']:.1%})"
    )
    print(f"  Mean Pk          : {agg['mean_pk']:.4f}")
    print(f"  Mean WindowDiff  : {agg['mean_window_diff']:.4f}")
    print(
        f"  Boundary P/R/F1  : {agg['mean_boundary_precision']:.4f}"
        f" / {agg['mean_boundary_recall']:.4f} / {agg['boundary_f1']:.4f}"
    )
    print(f"  Unified Score    : {agg['unified_score']:.4f}")

    rows = report["conversations"]
    if not rows:
        print("  (no conversations with both gold and predictions)")
        return
    print(
        f"\n  {'Conversation':<28}  {'Pk':>6}  {'WD':>6}"
        f"  {'B-F1':>6}  {'Unified':>8}"
    )
    for r in rows:
        print(
            f"  {r['conversation']:<28}  {r['pk']:>6.3f}  {r['window_diff']:>6.3f}"
            f"  {r['boundary_f1']:>6.3f}  {r['unified_score']:>8.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-dataset segmentation eval (Pk / WindowDiff / F1 / Unified)."
    )
    parser.add_argument("--dataset", required=True, help="Dataset name under datasets/.")
    parser.add_argument(
        "--root",
        default=None,
        help="Override the datasets root directory (defaults to datasets/).",
    )
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else None
    report = evaluate_dataset(args.dataset, root)
    out_path = write_eval_report(args.dataset, report, root)
    print_summary(report)
    print(f"\nReport written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
