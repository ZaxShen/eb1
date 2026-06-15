"""
Benchmark evaluation — compare model predictions against human-verified ground truth.

All benchmark segments live in the ``eb1_benchmark_raw`` PG table,
distinguished by ``benchmark_run_id`` and ``model`` columns.

For each (benchmark_run_id, model) pair found in the table, this module:
  1. Loads ground truth from ``sms_chat_segments`` (segments with ``true_topic``).
  2. Matches GT segments to model segments using optimal bipartite matching
     (Hungarian algorithm) with combined message-Jaccard + temporal-IoU score.
  3. Computes topic accuracy, subtopic accuracy, and confidence calibration.
  4. Persists match rows + run summaries to PostgreSQL.
  5. Prints a leaderboard to stdout.

No local file writes — all results are persisted in PostgreSQL.

Run via:
    uv run python -m pipeline --benchmark-eval NAME
    uv run python -m pipeline --benchmark-eval          # evaluates all benchmarks
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import linear_sum_assignment

from db.repositories.benchmark import BenchmarkSegmentRepository
from db.repositories.benchmark_groups import BenchmarkGroupRepository
from db.repositories.segments import SegmentRepository

log = logging.getLogger(__name__)

_JACCARD_THRESHOLD = 0.3
_MATCHING_ALPHA = 0.7  # weight for message Jaccard in combined score
_CONFIDENCE_BINS = [
    (0.0, 0.3, "[0.0, 0.3)"),
    (0.3, 0.6, "[0.3, 0.6)"),
    (0.6, 0.8, "[0.6, 0.8)"),
    (0.8, 1.01, "[0.8, 1.0]"),  # 1.01 so 1.0 is included
]

# Unified score weights: per-segment q = jaccard × topic × (_SUB_WEIGHT_TOPIC_ONLY
# + _SUB_WEIGHT_FULL × subtopic_correct). Topic-right-but-sub-wrong gets half credit.
_SUB_WEIGHT_TOPIC_ONLY = 0.5
_SUB_WEIGHT_FULL = 0.5


# ── Public entry point ─────────────────────────────────────────────────────────


def run_benchmark_eval(
    segment_repo: SegmentRepository,
    benchmark_repo: BenchmarkSegmentRepository,
    match_repo=None,
    run_repo=None,
    group_repo: BenchmarkGroupRepository | None = None,
    name: str = "all",
    group_id: str | None = None,
) -> dict:
    """Evaluate benchmark runs against ground truth.

    All benchmark segments live in ``eb1_benchmark_raw``, keyed by
    ``benchmark_run_id`` (FK to ``eb1_benchmark_runs``).

    Args:
        segment_repo: Repository for the canonical sms_chat_segments table.
        benchmark_repo: Repository for the benchmark table.
        match_repo: Optional BenchmarkMatchRepository — when provided,
            Jaccard match rows (Tier 2) are persisted to PG.
        run_repo: Optional BenchmarkRunRepository — when provided,
            run summaries (Tier 3) are persisted to PG and ranks computed.
        group_repo: Optional BenchmarkGroupRepository — used for target
            discovery when run_repo is provided.
        name: Label for report naming (e.g. ``"test1"`` or ``"all"``).
        group_id: When set, evaluate only the group with this name.

    Returns:
        Full evaluation results dict.

    Raises:
        RuntimeError: No benchmark data found, or no ground truth segments.
    """
    targets = _discover_benchmark_targets(run_repo, group_repo, group_id)

    if not targets:
        raise RuntimeError(
            "No benchmark runs found. "
            "Run --benchmark first to populate the table."
        )

    log.info(
        "Discovered %d benchmark run(s): %s",
        len(targets),
        [(t[1], t[3]) for t in targets],
    )

    gt_segments = _load_ground_truth(segment_repo)
    log.info(
        "Ground truth: sms_chat_segments — %d reviewed segment(s), %d user(s)",
        len(gt_segments),
        len({s["user_id"] for s in gt_segments}),
    )

    run_results: dict[str, dict] = {}

    group_ids_processed: set[int] = set()

    for group_id, group_name, benchmark_run_id, model in targets:
        display_key = f"{group_name}::{model}"
        log.info(
            "Evaluating: group=%s benchmark_run_id=%d model=%s",
            group_name, benchmark_run_id, model,
        )
        model_segments = _fetch_segments_by_run(benchmark_repo, benchmark_run_id)

        if not model_segments:
            log.warning(
                "No segments for benchmark_run_id=%d model='%s' — skipping.",
                benchmark_run_id,
                model,
            )
            continue

        meta = _extract_run_metadata(run_repo, benchmark_run_id)

        matches = _match_segments_jaccard(
            gt_segments,
            model_segments,
            _JACCARD_THRESHOLD,
        )

        matched = [m for m in matches if m["matched"]]
        unmatched = [m for m in matches if not m["matched"]]
        avg_iou = (
            sum(m["iou"] for m in matched) / len(matched) if matched else 0.0
        )

        topic_acc = _compute_topic_accuracy(
            matches, total_model_segments=len(model_segments),
        )
        subtopic_acc = _compute_subtopic_accuracy(
            matches, total_model_segments=len(model_segments),
        )
        unified = _compute_unified_score(
            matches, total_model_segments=len(model_segments),
        )
        conf_cal = _compute_confidence_calibration(matches)
        mismatches = _collect_mismatches(matches)
        unmatched_segments = _collect_unmatched(matches)

        seg_ratio = (
            round(len(model_segments) / len(gt_segments), 4) if gt_segments else 0.0
        )

        ue_matches = [m for m in matches if m.get("gt_has_user_engagement") is True]
        ue_matched = [m for m in ue_matches if m["matched"]]
        ue_avg_iou = (
            sum(m["iou"] for m in ue_matched) / len(ue_matched)
            if ue_matched
            else 0.0
        )

        match_rate = round(len(matched) / len(gt_segments), 4) if gt_segments else 0.0
        ue_match_rate = (
            round(len(ue_matched) / len(ue_matches), 4) if ue_matches else 0.0
        )

        run_results[display_key] = {
            "group_id": group_id,
            "group_name": group_name,
            "benchmark_run_id": benchmark_run_id,
            "model": meta["model"],
            "prompt_version": meta["prompt"],
            "is_ground_truth_source": False,
            "coverage": {
                "total_segments": len(model_segments),
                "gt_segments_evaluated": len(gt_segments),
                "matched": len(matched),
                "unmatched": len(unmatched),
                "match_rate": match_rate,
                "avg_iou": round(avg_iou, 4),
                "segment_count_ratio": seg_ratio,
            },
            "topic_accuracy": topic_acc,
            "subtopic_accuracy": subtopic_acc,
            "unified_score": unified,
            "confidence_calibration": conf_cal,
            "mismatches": mismatches,
            "unmatched_segments": unmatched_segments,
            "user_engaged": {
                "gt_segments": len(ue_matches),
                "matched": len(ue_matched),
                "match_rate": ue_match_rate,
                "avg_iou": round(ue_avg_iou, 4),
                # UE model segment count unavailable; pass 0 so precision
                # falls back to m/matched (old behavior).
                "topic_accuracy": _compute_topic_accuracy(
                    ue_matches, total_model_segments=0,
                ),
                "subtopic_accuracy": _compute_subtopic_accuracy(
                    ue_matches, total_model_segments=0,
                ),
                "unified_score": _compute_unified_score(
                    ue_matches, total_model_segments=0,
                ),
                "confidence_calibration": (
                    _compute_confidence_calibration(ue_matches)
                ),
            },
        }

        if match_repo is not None:
            _persist_match_rows(match_repo, benchmark_run_id, matches)

        if run_repo is not None:
            _persist_run_summary(
                run_repo, group_id, benchmark_run_id,
                meta, run_results[display_key],
            )
            group_ids_processed.add(group_id)

    if run_repo is not None:
        for gid in group_ids_processed:
            run_repo.update_ranks(gid)

    report = _build_eval_report(name, gt_segments, run_results)
    _print_eval_summary(report)

    return report


# ── Target discovery ──────────────────────────────────────────────────────────


def _discover_benchmark_targets(
    run_repo=None,
    group_repo: BenchmarkGroupRepository | None = None,
    group_name: str | None = None,
) -> list[tuple[int, str, int, str]]:
    """Discover benchmark runs to evaluate via the groups → runs hierarchy.

    Args:
        run_repo: BenchmarkRunRepository — queries eb1_benchmark_runs.
        group_repo: BenchmarkGroupRepository — queries eb1_benchmark_groups.
        group_name: When set, restrict to the group with this name.

    Returns:
        List of (group_id, group_name, benchmark_run_id, model) tuples.
    """
    if run_repo is None or group_repo is None:
        return []

    if group_name:
        group = group_repo.find_by_name(group_name)
        if not group:
            return []
        groups = [group]
    else:
        groups = group_repo.find_all()

    targets: list[tuple[int, str, int, str]] = []
    for group in groups:
        gid = group["id"]
        gname = group["name"]
        runs = run_repo._fetch_all(
            """SELECT r.id AS benchmark_run_id, c.model
               FROM eb1_benchmark_runs r
               JOIN eb1_pipeline_configs c ON r.config_id = c.id
               WHERE r.group_id = %s
               ORDER BY c.model""",
            (gid,),
        )
        for row in runs:
            targets.append((gid, gname, row["benchmark_run_id"], row["model"]))
    return targets


# ── Ground truth loading ───────────────────────────────────────────────────────


def _load_ground_truth(segment_repo: SegmentRepository) -> list[dict]:
    """Load ground truth from sms_chat_segments (true_topic IS NOT NULL).

    Raises:
        RuntimeError: No reviewed segments found.
    """
    segments = segment_repo.find_reviewed()
    if not segments:
        raise RuntimeError(
            "No reviewed segments (true_topic IS NOT NULL) in sms_chat_segments. "
            "Migrate verified labels first."
        )
    return segments


# ── Benchmark segment loading ──────────────────────────────────────────────────


def _fetch_segments_by_run(
    benchmark_repo: BenchmarkSegmentRepository,
    benchmark_run_id: int,
) -> list[dict]:
    """Fetch benchmark segments for a specific benchmark_run_id."""
    return benchmark_repo.find_by_run(benchmark_run_id)


# ── Run metadata extraction ────────────────────────────────────────────────────


def _extract_run_metadata(
    run_repo,
    benchmark_run_id: int,
) -> dict:
    """Extract model metadata from eb1_benchmark_runs JOIN eb1_pipeline_configs.

    Raises:
        RuntimeError: No run found for the given benchmark_run_id.
    """
    row = run_repo._fetch_one(
        """SELECT r.id, r.run_at, r.config_id, c.model, c.user_prompt
           FROM eb1_benchmark_runs r
           JOIN eb1_pipeline_configs c ON r.config_id = c.id
           WHERE r.id = %s""",
        (benchmark_run_id,),
    )
    if not row:
        raise RuntimeError(
            f"No run found for benchmark_run_id={benchmark_run_id}. "
            "Check that the benchmark ran successfully."
        )
    model_name = row.get("model")
    if not model_name:
        raise RuntimeError(
            f"Run id={benchmark_run_id} has no model name. "
            "The config_id may reference a placeholder row. "
            "Update eb1_pipeline_configs with the correct model."
        )
    return {
        "model": model_name,
        "prompt": row.get("user_prompt", ""),
        "config_id": row.get("config_id"),
        "run_at": row.get("run_at"),
    }


# ── Segment matching helpers ──────────────────────────────────────────────────


def _segment_sort_key(seg: dict):
    """Sort key for chronological segment ordering.

    Primary: ``chat_started_at`` (datetime).
    Fallback: ``datetime.min`` to sort segments without timestamps first.
    """
    ts = seg.get("chat_started_at")
    if ts is not None:
        return ts
    return datetime.min


def _message_jaccard(seg_a: dict, seg_b: dict) -> float:
    """Jaccard IoU over ``chat_messages`` sets."""
    msgs_a = set(seg_a.get("chat_messages") or [])
    msgs_b = set(seg_b.get("chat_messages") or [])
    union = msgs_a | msgs_b
    if not union:
        return 0.0
    return len(msgs_a & msgs_b) / len(union)


def _temporal_iou(seg_a: dict, seg_b: dict) -> float:
    """Temporal IoU from ``[chat_started_at, chat_ended_at]`` intervals.

    Returns 0.0 if either segment is missing start or end timestamps.
    """
    a_start = seg_a.get("chat_started_at")
    a_end = seg_a.get("chat_ended_at")
    b_start = seg_b.get("chat_started_at")
    b_end = seg_b.get("chat_ended_at")

    if not all((a_start, a_end, b_start, b_end)):
        return 0.0

    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    overlap = max((overlap_end - overlap_start).total_seconds(), 0.0)

    union_start = min(a_start, b_start)
    union_end = max(a_end, b_end)
    union = (union_end - union_start).total_seconds()

    if union <= 0:
        return 0.0
    return overlap / union


def _unmatched_record(gt: dict, best_iou: float = 0.0) -> dict:
    """Build a match record for an unmatched GT segment."""
    return {
        "gt_segment_id": gt["id"],
        "gt_user_id": gt["user_id"],
        "gt_topic": gt.get("true_topic"),
        "gt_subtopic": gt.get("true_sub_topic"),
        "gt_has_user_engagement": gt.get("has_user_engagement"),
        "model_segment_id": None,
        "model_topic": None,
        "model_subtopic": None,
        "model_confidence": None,
        "model_summary": None,
        "iou": round(best_iou, 4),
        "matched": False,
    }


# ── Optimal bipartite matching ────────────────────────────────────────────────


def _match_segments_jaccard(
    gt_segments: list[dict],
    model_segments: list[dict],
    threshold: float = _JACCARD_THRESHOLD,
    alpha: float = _MATCHING_ALPHA,
) -> list[dict]:
    """Match GT segments to model segments via optimal bipartite matching.

    Uses the Hungarian algorithm (``scipy.optimize.linear_sum_assignment``) to
    maximise the total combined score per user, where::

        combined = alpha * message_jaccard + (1 - alpha) * temporal_iou

    Hard floor: if ``message_jaccard == 0`` the combined score is forced to 0
    so that temporal overlap alone can never produce a match.

    The ``iou`` field in each match record is **pure message Jaccard** for
    downstream interpretability.

    Args:
        gt_segments: Ground-truth segments (must have ``true_topic``).
        model_segments: Model-predicted segments.
        threshold: Minimum combined score to accept a match.
        alpha: Weight for message Jaccard (1 - alpha for temporal IoU).

    Returns:
        List of match records with keys: ``gt_segment_id``, ``gt_user_id``,
        ``gt_topic``, ``gt_subtopic``, ``model_segment_id``, ``model_topic``,
        ``model_subtopic``, ``model_confidence``, ``model_summary``,
        ``iou``, ``matched``.
    """
    model_by_user: dict[str, list[dict]] = defaultdict(list)
    for seg in model_segments:
        model_by_user[seg["user_id"]].append(seg)
    for uid in model_by_user:
        model_by_user[uid].sort(key=_segment_sort_key)

    gt_by_user: dict[str, list[dict]] = defaultdict(list)
    for seg in gt_segments:
        gt_by_user[seg["user_id"]].append(seg)
    for uid in gt_by_user:
        gt_by_user[uid].sort(key=_segment_sort_key)

    results: list[dict] = []

    for uid, gt_list in gt_by_user.items():
        candidates = model_by_user.get(uid, [])
        n_gt = len(gt_list)
        n_cand = len(candidates)

        if n_cand == 0:
            for gt in gt_list:
                results.append(_unmatched_record(gt))
            continue

        # Build score matrices (n_gt x n_cand)
        score_matrix = np.zeros((n_gt, n_cand))
        jaccard_matrix = np.zeros((n_gt, n_cand))

        for i, gt in enumerate(gt_list):
            for j, cand in enumerate(candidates):
                mj = _message_jaccard(gt, cand)
                jaccard_matrix[i, j] = mj
                if mj == 0:
                    # Hard floor: no message overlap → no match possible
                    continue
                ti = _temporal_iou(gt, cand)
                score_matrix[i, j] = alpha * mj + (1 - alpha) * ti

        # Zero out cells below threshold
        score_matrix[score_matrix < threshold] = 0.0

        # Hungarian algorithm: minimise cost → negate scores for maximisation
        row_ind, col_ind = linear_sum_assignment(-score_matrix)

        # Build assignment map (only where score > 0)
        assignment: dict[int, int] = {}
        for r, c in zip(row_ind, col_ind):
            if score_matrix[r, c] > 0:
                assignment[r] = c

        for i, gt in enumerate(gt_list):
            if i in assignment:
                j = assignment[i]
                cand = candidates[j]
                results.append(
                    {
                        "gt_segment_id": gt["id"],
                        "gt_user_id": gt["user_id"],
                        "gt_topic": gt.get("true_topic"),
                        "gt_subtopic": gt.get("true_sub_topic"),
                        "gt_has_user_engagement": gt.get("has_user_engagement"),
                        "model_segment_id": cand["id"],
                        "model_topic": cand.get("topic"),
                        "model_subtopic": cand.get("sub_topic"),
                        "model_confidence": cand.get("label_confidence"),
                        "model_summary": cand.get("summary"),
                        "iou": round(jaccard_matrix[i, j], 4),
                        "matched": True,
                    }
                )
            else:
                best_jaccard = (
                    float(jaccard_matrix[i].max()) if n_cand > 0 else 0.0
                )
                results.append(_unmatched_record(gt, best_jaccard))

    return results


# ── Metric computation ─────────────────────────────────────────────────────────


def _compute_topic_accuracy(
    matches: list[dict],
    total_model_segments: int = 0,
) -> dict:
    """Compute topic-level accuracy from matched segments.

    Uses F1 (harmonic mean of Precision and Recall) as the primary metric.

    Args:
        matches: List of match records (one per GT segment).
        total_model_segments: Total model segments produced (M). When 0,
            falls back to len(matched) for precision (old behavior).

    Returns a dict with keys: ``correct``, ``total``, ``gt_segments``,
    ``model_segments``, ``precision``, ``recall``, ``f1``, ``accuracy`` (=f1),
    ``matched_accuracy``, ``per_topic``, ``confusion_matrix``.
    """
    matched = [m for m in matches if m["matched"]]

    if not matched:
        return {
            "correct": 0,
            "total": 0,
            "gt_segments": len(matches),
            "model_segments": total_model_segments,
            "precision": None,
            "recall": None,
            "f1": None,
            "accuracy": None,
            "matched_accuracy": None,
            "per_topic": {},
            "confusion_matrix": {},
        }

    correct = sum(1 for m in matched if m["model_topic"] == m["gt_topic"])

    n = len(matches)  # N = total GT segments (matched + unmatched)
    m_correct = correct
    big_m = total_model_segments if total_model_segments > 0 else len(matched)

    precision = m_correct / big_m if big_m > 0 else 0.0
    recall = m_correct / n if n > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    matched_accuracy = correct / len(matched) if matched else None

    # Per-topic metrics — include unmatched GT segments in topic set and FN
    all_topics = {m["gt_topic"] for m in matches if m["gt_topic"]} | {
        m["model_topic"] for m in matched if m["model_topic"]
    }
    per_topic: dict[str, dict] = {}
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for m in matched:
        gt = m["gt_topic"]
        pred = m["model_topic"] or ""
        confusion[gt][pred] += 1

    for topic in all_topics:
        if topic is None:
            continue
        tp = sum(
            1
            for m in matched
            if m["gt_topic"] == topic and m["model_topic"] == topic
        )
        fp = sum(
            1
            for m in matched
            if m["gt_topic"] != topic and m["model_topic"] == topic
        )
        # FN: matched segments misclassified + unmatched GT segments
        fn = sum(
            1
            for m in matches
            if m["gt_topic"] == topic
            and (not m["matched"] or m["model_topic"] != topic)
        )
        support = sum(1 for m in matches if m["gt_topic"] == topic)

        t_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        t_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        t_f1 = (
            2 * t_precision * t_recall / (t_precision + t_recall)
            if (t_precision + t_recall) > 0
            else 0.0
        )

        per_topic[topic] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(t_precision, 4),
            "recall": round(t_recall, 4),
            "f1": round(t_f1, 4),
            "support": support,
        }

    confusion_matrix = {gt_topic: dict(preds) for gt_topic, preds in confusion.items()}

    return {
        "correct": correct,
        "total": len(matched),
        "gt_segments": n,
        "model_segments": big_m,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(f1, 4),
        "matched_accuracy": (
            round(matched_accuracy, 4) if matched_accuracy is not None else None
        ),
        "per_topic": per_topic,
        "confusion_matrix": confusion_matrix,
    }


def _compute_subtopic_accuracy(
    matches: list[dict],
    total_model_segments: int = 0,
) -> dict:
    """Compute subtopic-level accuracy from matched segments.

    Uses F1 (harmonic mean of Precision and Recall) as the primary metric.
    Eligible segments are those where at least one of ``gt_subtopic`` or
    ``model_subtopic`` is non-null. Comparison is case-insensitive and stripped.

    Args:
        matches: List of match records (one per GT segment).
        total_model_segments: Total model segments produced (M). When 0,
            falls back to len(matched_eligible) for precision.

    Returns a dict with keys: ``correct``, ``total``, ``gt_segments``,
    ``precision``, ``recall``, ``f1``, ``accuracy`` (=f1), ``matched_accuracy``.
    """

    def _norm(v: str | None) -> str:
        return (v or "").strip().lower()

    # All eligible: unmatched GT with subtopic, or matched with either subtopic
    all_eligible = [
        m
        for m in matches
        if m.get("gt_subtopic") is not None
        or (m["matched"] and m.get("model_subtopic") is not None)
    ]
    n_eligible = len(all_eligible)

    # Matched eligible (old denominator)
    matched_eligible = [m for m in all_eligible if m["matched"]]

    if not matched_eligible:
        return {
            "correct": 0,
            "total": 0,
            "gt_segments": n_eligible,
            "precision": None,
            "recall": None,
            "f1": None,
            "accuracy": None,
            "matched_accuracy": None,
        }

    correct = sum(
        1
        for m in all_eligible
        if m["matched"]
        and _norm(m.get("gt_subtopic")) == _norm(m.get("model_subtopic"))
    )

    # Old metric: correct / matched_eligible
    matched_correct = sum(
        1
        for m in matched_eligible
        if _norm(m.get("gt_subtopic")) == _norm(m.get("model_subtopic"))
    )
    matched_accuracy = (
        matched_correct / len(matched_eligible) if matched_eligible else None
    )

    # Precision denominator: total_model_segments if provided, else matched_eligible
    precision = (
        correct / total_model_segments
        if total_model_segments > 0
        else (correct / len(matched_eligible) if matched_eligible else 0.0)
    )
    recall = correct / n_eligible if n_eligible > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "correct": correct,
        "total": len(matched_eligible),
        "gt_segments": n_eligible,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(f1, 4),
        "matched_accuracy": (
            round(matched_accuracy, 4) if matched_accuracy is not None else None
        ),
    }


def _compute_unified_score(
    matches: list[dict],
    total_model_segments: int,
) -> dict:
    """Compute the Unified Score — a single 0-1 number combining
    segmentation quality, topic correctness, and subtopic correctness.

    Per-segment quality:
        q = jaccard × topic_correct × (0.5 + 0.5 × subtopic_correct)

    Final score (divided by the larger of GT / model segment counts so
    both under- and over-segmentation are penalised symmetrically):
        score = Σq / max(GT_count, model_count)

    Returns:
        {
          "score":           unified score in [0, 1]
          "topic_score":     correct_topic / max(GT, model)
          "sub_score":       correct_sub / max(GT, model)
          "avg_jaccard":     mean Jaccard over matched pairs (0 when no matches)
          "correct_topic":   # matched with gt_topic == model_topic
          "correct_sub":     # matched with gt_topic == model_topic AND subs equal
          "matched":         # of matched pairs
          "gt_total":        len(matches)  (one record per GT)
          "model_total":     total_model_segments (falls back to matched when 0)
          "denominator":     max(gt_total, model_total) used in normalisation
        }
    """
    gt_total = len(matches)

    def _norm(v):
        return (v or "").strip().lower()

    matched = [m for m in matches if m["matched"]]
    n_matched = len(matched)

    # When caller didn't supply the model total, fall back to matched count.
    model_total = total_model_segments if total_model_segments > 0 else n_matched
    denom = max(gt_total, model_total)

    correct_topic = sum(
        1 for m in matched
        if m["model_topic"] is not None
        and m["model_topic"] == m["gt_topic"]
    )
    correct_sub = sum(
        1 for m in matched
        if m["model_topic"] is not None
        and m["model_topic"] == m["gt_topic"]
        and m.get("gt_subtopic") is not None
        and _norm(m.get("model_subtopic")) == _norm(m.get("gt_subtopic"))
    )

    avg_jaccard = (
        sum(m["iou"] for m in matched) / n_matched
        if n_matched else 0.0
    )

    # Per-segment quality: q_i = jaccard_i × topic_i × (0.5 + 0.5 × sub_i)
    sigma_q = 0.0
    for m in matched:
        topic_ok = (
            m["model_topic"] is not None
            and m["model_topic"] == m["gt_topic"]
        )
        if not topic_ok:
            continue  # topic wrong → q = 0
        sub_ok = (
            m.get("gt_subtopic") is not None
            and _norm(m.get("model_subtopic")) == _norm(m.get("gt_subtopic"))
        )
        sub_weight = _SUB_WEIGHT_TOPIC_ONLY + (
            _SUB_WEIGHT_FULL if sub_ok else 0.0
        )
        sigma_q += float(m["iou"]) * sub_weight

    score = sigma_q / denom if denom > 0 else 0.0
    topic_score = correct_topic / denom if denom > 0 else 0.0
    sub_score = correct_sub / denom if denom > 0 else 0.0

    return {
        "score": round(score, 4),
        "topic_score": round(topic_score, 4),
        "sub_score": round(sub_score, 4),
        "avg_jaccard": round(avg_jaccard, 4),
        "correct_topic": correct_topic,
        "correct_sub": correct_sub,
        "matched": n_matched,
        "gt_total": gt_total,
        "model_total": model_total,
        "denominator": denom,
    }


def _compute_confidence_calibration(matches: list[dict]) -> dict:
    """Compute confidence calibration across ``label_confidence`` bins.

    Bins: ``[0.0, 0.3)``, ``[0.3, 0.6)``, ``[0.6, 0.8)``, ``[0.8, 1.0]``.
    ECE = weighted average of |accuracy - avg_confidence| per bin.

    Only matched segments with non-null ``model_confidence`` are included.

    Returns a dict with keys: ``bins``, ``expected_calibration_error``.
    """
    eligible = [
        m for m in matches if m["matched"] and m.get("model_confidence") is not None
    ]

    bin_results = []
    total_eligible = len(eligible)

    for lo, hi, label in _CONFIDENCE_BINS:
        in_bin = [m for m in eligible if lo <= m["model_confidence"] < hi]
        count = len(in_bin)
        if count == 0:
            bin_results.append(
                {
                    "range": label,
                    "count": 0,
                    "accuracy": 0.0,
                    "avg_confidence": (lo + min(hi, 1.0)) / 2,
                }
            )
            continue

        bin_correct = sum(1 for m in in_bin if m["model_topic"] == m["gt_topic"])
        bin_accuracy = bin_correct / count
        avg_conf = sum(m["model_confidence"] for m in in_bin) / count

        bin_results.append(
            {
                "range": label,
                "count": count,
                "accuracy": round(bin_accuracy, 4),
                "avg_confidence": round(avg_conf, 4),
            }
        )

    ece = 0.0
    if total_eligible > 0:
        ece = sum(
            b["count"] / total_eligible * abs(b["accuracy"] - b["avg_confidence"])
            for b in bin_results
        )

    return {
        "bins": bin_results,
        "expected_calibration_error": round(ece, 4),
    }


def _collect_mismatches(matches: list[dict]) -> list[dict]:
    """Collect all matched segments where ``model_topic`` differs from ``gt_topic``."""
    return [
        {
            "segment_id": str(m["model_segment_id"]),
            "user_id": str(m["gt_user_id"]),
            "predicted": {
                "topic": m.get("model_topic"),
                "sub_topic": m.get("model_subtopic"),
            },
            "ground_truth": {
                "true_topic": m.get("gt_topic"),
                "true_sub_topic": m.get("gt_subtopic"),
            },
            "summary": m.get("model_summary"),
            "label_confidence": m.get("model_confidence"),
            "iou": m["iou"],
        }
        for m in matches
        if m["matched"] and m.get("model_topic") != m.get("gt_topic")
    ]


def _collect_unmatched(matches: list[dict]) -> list[dict]:
    """Collect GT segments that the model failed to produce."""
    return [
        {
            "gt_segment_id": str(m["gt_segment_id"]),
            "user_id": str(m["gt_user_id"]),
            "true_topic": m.get("gt_topic"),
            "true_sub_topic": m.get("gt_subtopic"),
            "best_iou": m["iou"],
        }
        for m in matches
        if not m["matched"]
    ]


# ── PG persistence helpers ────────────────────────────────────────────────────


def _persist_match_rows(
    match_repo,
    benchmark_run_id: int,
    matches: list[dict],
) -> None:
    """Delete stale rows then insert fresh Jaccard match results (Tier 2)."""
    match_repo.delete_by_run(benchmark_run_id)
    rows = [
        {
            "benchmark_run_id": benchmark_run_id,
            "gt_segment_id": m["gt_segment_id"],
            "gt_user_id": str(m["gt_user_id"]),
            "gt_topic": m.get("gt_topic"),
            "gt_sub_topic": m.get("gt_subtopic"),
            "gt_has_user_engagement": m.get("gt_has_user_engagement"),
            "bench_segment_id": m.get("model_segment_id"),
            "model_topic": m.get("model_topic"),
            "model_sub_topic": m.get("model_subtopic"),
            "model_confidence": m.get("model_confidence"),
            "model_summary": m.get("model_summary"),
            "iou": m["iou"],
            "matched": m["matched"],
            "topic_match": (
                m.get("model_topic") == m.get("gt_topic") if m["matched"] else False
            ),
            "subtopic_match": (
                (m.get("model_subtopic") or "").strip().lower()
                == (m.get("gt_subtopic") or "").strip().lower()
                if m["matched"]
                else False
            ),
        }
        for m in matches
    ]
    inserted = match_repo.insert_many(rows)
    log.info(
        "Tier 2: persisted %d match rows for benchmark_run_id=%d",
        inserted,
        benchmark_run_id,
    )


def _persist_run_summary(
    run_repo,
    group_id: int,
    benchmark_run_id: int,
    meta: dict,
    result: dict,
) -> None:
    """Upsert a run summary row (Tier 3)."""
    cov = result["coverage"]
    topic_acc = result["topic_accuracy"]
    subtopic_acc = result["subtopic_accuracy"]
    unified = result.get("unified_score", {})
    conf_cal = result["confidence_calibration"]
    ue = result.get("user_engaged", {})
    ue_topic_acc = ue.get("topic_accuracy", {})
    ue_subtopic_acc = ue.get("subtopic_accuracy", {})
    ue_unified = ue.get("unified_score", {})

    row = {
        "group_id": group_id,
        "config_id": meta["config_id"],
        "summary": None,
        "run_at": meta.get("run_at"),
        "total_gt_segments": cov["gt_segments_evaluated"],
        "total_model_segments": cov["total_segments"],
        "matched_count": cov["matched"],
        "match_rate": cov["match_rate"],
        "avg_iou": cov["avg_iou"],
        "topic_accuracy": topic_acc.get("accuracy"),
        "subtopic_accuracy": subtopic_acc.get("accuracy"),
        "segment_count_ratio": cov.get("segment_count_ratio"),
        "unified_score": unified.get("score"),
        "unified_topic_score": unified.get("topic_score"),
        "unified_sub_score": unified.get("sub_score"),
        "ue_gt_segments": ue.get("gt_segments", 0),
        "ue_matched_count": ue.get("matched", 0),
        "ue_match_rate": ue.get("match_rate", 0.0),
        "ue_topic_accuracy": ue_topic_acc.get("accuracy"),
        "ue_subtopic_accuracy": ue_subtopic_acc.get("accuracy"),
        "ue_unified_score": ue_unified.get("score"),
        "confidence_calibration": conf_cal,
        "rank": None,
    }
    row_id = run_repo.upsert(row)
    log.info(
        "Tier 3: upserted run summary id=%d for group_id=%d benchmark_run_id=%d",
        row_id,
        group_id,
        benchmark_run_id,
    )


# ── Report construction ────────────────────────────────────────────────────────


def _build_leaderboard(
    run_results: dict[str, dict],
    scope: str = "total",
) -> list[dict]:
    """Build a ranked leaderboard from run results.

    Args:
        run_results: Per-run metric dicts keyed by display key.
        scope: ``"total"`` for all segments, ``"user_engaged"`` for
               user-engaged only.

    Returns:
        Sorted list of leaderboard entry dicts.
    """
    entries = []
    for _key, res in run_results.items():
        rid = res.get("run_id", "")

        if scope == "user_engaged":
            ue = res.get("user_engaged", {})
            topic_acc = ue.get("topic_accuracy", {})
            subtopic_acc = ue.get("subtopic_accuracy", {})
            unified = ue.get("unified_score", {})
            ece = ue.get("confidence_calibration", {}).get(
                "expected_calibration_error", 0
            )
            entries.append(
                {
                    "run_id": rid,
                    "model": res["model"],
                    "topic_accuracy": topic_acc.get("accuracy"),
                    "subtopic_accuracy": subtopic_acc.get("accuracy"),
                    "unified_score": unified.get("score"),
                    "avg_iou": ue.get("avg_iou", 0),
                    "match_rate": ue.get("match_rate", 0),
                    "ece": ece,
                    "reviewed_segments": ue.get("gt_segments", 0),
                }
            )
        else:
            topic_acc = res["topic_accuracy"]
            subtopic_acc = res["subtopic_accuracy"]
            unified = res.get("unified_score", {})
            cov = res["coverage"]
            ece = res["confidence_calibration"]["expected_calibration_error"]
            entries.append(
                {
                    "run_id": rid,
                    "model": res["model"],
                    "topic_accuracy": topic_acc.get("accuracy"),
                    "subtopic_accuracy": subtopic_acc.get("accuracy"),
                    "unified_score": unified.get("score"),
                    "avg_iou": cov["avg_iou"],
                    "match_rate": cov["match_rate"],
                    "segment_count_ratio": cov.get("segment_count_ratio", 0.0),
                    "ece": ece,
                    "reviewed_segments": cov["gt_segments_evaluated"],
                }
            )

    entries.sort(
        key=lambda r: (
            r["unified_score"] if r["unified_score"] is not None else -1.0,
            r["topic_accuracy"] if r["topic_accuracy"] is not None else -1.0,
            r["subtopic_accuracy"] if r["subtopic_accuracy"] is not None else -1.0,
        ),
        reverse=True,
    )
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank

    return entries


def _build_eval_report(
    name: str,
    gt_segments: list[dict],
    run_results: dict[str, dict],
) -> dict:
    """Build the full evaluation report dict."""
    gt_user_ids = {str(s["user_id"]) for s in gt_segments}

    leaderboard = _build_leaderboard(run_results, scope="total")
    leaderboard_ue = _build_leaderboard(run_results, scope="user_engaged")

    return {
        "meta": {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "benchmark_name": name,
            "ground_truth_table": "sms_chat_segments",
            "ground_truth_segments": len(gt_segments),
            "ground_truth_users": len(gt_user_ids),
            "jaccard_threshold": _JACCARD_THRESHOLD,
            "matching_alpha": _MATCHING_ALPHA,
        },
        "runs": run_results,
        "leaderboard": leaderboard,
        "leaderboard_user_engaged": leaderboard_ue,
    }



def _print_leaderboard(entries: list[dict], title: str) -> None:
    """Print a formatted leaderboard table to stdout."""
    print(f"\n━━━ {title} ━━━")
    has_ratio = any("segment_count_ratio" in e for e in entries)
    if has_ratio:
        header = (
            f"  {'#':<3}  {'Run ID':<30}  {'Model':<25}"
            f"  {'Unified':>8}  {'Topic F1':>9}  {'SubTopic F1':>12}"
            f"  {'Match%':>7}  {'Seg Ratio':>10}  {'Avg IoU':>8}  {'ECE':>7}"
        )
    else:
        header = (
            f"  {'#':<3}  {'Run ID':<30}  {'Model':<25}"
            f"  {'Unified':>8}  {'Topic F1':>9}  {'SubTopic F1':>12}"
            f"  {'Match%':>7}  {'Avg IoU':>8}  {'ECE':>7}"
        )
    print(header)
    for entry in entries:
        us = (
            f"{entry['unified_score']:.1%}"
            if entry.get("unified_score") is not None
            else "n/a"
        )
        ta = (
            f"{entry['topic_accuracy']:.1%}"
            if entry["topic_accuracy"] is not None
            else "n/a"
        )
        sta = (
            f"{entry['subtopic_accuracy']:.1%}"
            if entry["subtopic_accuracy"] is not None
            else "n/a"
        )
        mr = f"{entry['match_rate']:.1%}"
        rid = entry.get("run_id", "?")
        if has_ratio:
            sr = f"{entry.get('segment_count_ratio', 0):.2f}x"
            print(
                f"  {entry['rank']:<3}  {rid:<30}"
                f"  {entry['model']:<25}  "
                f"{us:>8}  {ta:>9}  {sta:>12}  {mr:>7}"
                f"  {sr:>10}  {entry['avg_iou']:>8.3f}"
                f"  {entry['ece']:>7.3f}"
            )
        else:
            print(
                f"  {entry['rank']:<3}  {rid:<30}"
                f"  {entry['model']:<25}  "
                f"{us:>8}  {ta:>9}  {sta:>12}  {mr:>7}"
                f"  {entry['avg_iou']:>8.3f}  {entry['ece']:>7.3f}"
            )


def _print_eval_summary(report: dict) -> None:
    """Print a console summary of the benchmark evaluation."""
    meta = report["meta"]
    runs = report["runs"]
    leaderboard = report["leaderboard"]

    print(f"\n━━━ Benchmark Evaluation: {meta['benchmark_name']} ━━━")
    print(
        f"Ground truth: {meta['ground_truth_table']} "
        f"({meta['ground_truth_segments']} segments, "
        f"{meta['ground_truth_users']} users)"
    )

    for display_key, res in runs.items():
        cov = res["coverage"]
        topic_acc = res["topic_accuracy"]
        subtopic_acc = res["subtopic_accuracy"]
        ece = res["confidence_calibration"]["expected_calibration_error"]
        ue = res.get("user_engaged", {})

        ta_str = (
            f"{topic_acc['correct']}/{topic_acc.get('gt_segments', topic_acc['total'])}"
            f" (F1={topic_acc['accuracy']:.1%}"
            f" P={topic_acc.get('precision', 0):.1%}"
            f" R={topic_acc.get('recall', 0):.1%})"
            if topic_acc.get("accuracy") is not None
            else "n/a"
        )
        sta_str = (
            f"{subtopic_acc['correct']}/{subtopic_acc.get('gt_segments', subtopic_acc['total'])}"
            f" (F1={subtopic_acc['accuracy']:.1%}"
            f" P={subtopic_acc.get('precision', 0):.1%}"
            f" R={subtopic_acc.get('recall', 0):.1%})"
            if subtopic_acc.get("accuracy") is not None
            else "n/a"
        )

        ue_ta = ue.get("topic_accuracy", {})
        ue_sta = ue.get("subtopic_accuracy", {})
        ue_ece = ue.get("confidence_calibration", {}).get(
            "expected_calibration_error", 0
        )
        ue_ta_str = (
            f"{ue_ta['correct']}/{ue_ta.get('gt_segments', ue_ta['total'])}"
            f" (F1={ue_ta['accuracy']:.1%}"
            f" P={ue_ta.get('precision', 0):.1%}"
            f" R={ue_ta.get('recall', 0):.1%})"
            if ue_ta.get("accuracy") is not None
            else "n/a"
        )
        ue_sta_str = (
            f"{ue_sta['correct']}/{ue_sta.get('gt_segments', ue_sta['total'])}"
            f" (F1={ue_sta['accuracy']:.1%}"
            f" P={ue_sta.get('precision', 0):.1%}"
            f" R={ue_sta.get('recall', 0):.1%})"
            if ue_sta.get("accuracy") is not None
            else "n/a"
        )

        ratio = cov.get("segment_count_ratio", 0)
        if ratio > 1.05:
            ratio_label = f"{ratio:.2f}x (over-segmented)"
        elif ratio < 0.95:
            ratio_label = f"{ratio:.2f}x (under-segmented)"
        else:
            ratio_label = f"{ratio:.2f}x"

        rid = res.get("run_id", "?")
        print(f"\n── {rid} ({res['model']}) ──")
        model_n = cov["total_segments"]
        gt_n = cov["gt_segments_evaluated"]
        print(
            f"  Segments          : {model_n} model vs {gt_n} GT"
            f" — {ratio_label}"
        )
        print(
            f"  Matched           : {cov['matched']}"
            f"/{cov['gt_segments_evaluated']}"
            f" (IoU >= {_JACCARD_THRESHOLD})"
        )
        print(f"  Unmatched (missed): {cov['unmatched']}")
        print(f"  Avg IoU           : {cov['avg_iou']:.3f}")
        unified = res.get("unified_score", {})
        if unified.get("score") is not None:
            print(
                f"  Unified score     : {unified['score']:.1%}"
                f" (topic {unified.get('topic_score', 0):.1%},"
                f" sub {unified.get('sub_score', 0):.1%},"
                f" avg_jaccard {unified.get('avg_jaccard', 0):.3f},"
                f" denom {unified.get('denominator', 0)})"
            )
        print(f"  Topic accuracy    : {ta_str}")
        print(f"  SubTopic accuracy : {sta_str}")
        print(f"  ECE               : {ece:.3f}")
        print(f"  Mismatches        : {len(res['mismatches'])}")

        ue_gt = ue.get("gt_segments", 0)
        ue_matched = ue.get("matched", 0)
        if ue_gt > 0:
            print(f"  ── User-Engaged Only ({ue_gt} GT segments) ──")
            print(f"  UE Matched        : {ue_matched}/{ue_gt}")
            print(f"  UE Avg IoU        : {ue.get('avg_iou', 0):.3f}")
            ue_unified = ue.get("unified_score", {})
            if ue_unified.get("score") is not None:
                print(
                    f"  UE Unified score  : {ue_unified['score']:.1%}"
                    f" (topic {ue_unified.get('topic_score', 0):.1%},"
                    f" sub {ue_unified.get('sub_score', 0):.1%})"
                )
            print(f"  UE Topic accuracy : {ue_ta_str}")
            print(f"  UE SubTopic acc   : {ue_sta_str}")
            print(f"  UE ECE            : {ue_ece:.3f}")

        unmatched_segs = res.get("unmatched_segments", [])
        if unmatched_segs:
            print("  Unmatched GT segments:")
            for u in unmatched_segs[:10]:
                print(
                    f"    - {u['gt_segment_id']} user={u['user_id']}"
                    f" true_topic={u['true_topic']}"
                    f" best_iou={u['best_iou']:.3f}"
                )
            if len(unmatched_segs) > 10:
                print(f"    ... and {len(unmatched_segs) - 10} more")

    _print_leaderboard(leaderboard, "Leaderboard — All Segments")

    leaderboard_ue = report.get("leaderboard_user_engaged", [])
    if leaderboard_ue:
        _print_leaderboard(leaderboard_ue, "Leaderboard — User-Engaged Only")
