"""
Unit tests for pure functions in pipeline/evaluation/benchmark_eval.py.

No DB connection required — all functions under test are pure (no I/O).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pipeline.evaluation.benchmark_eval import (
    _collect_mismatches,
    _collect_unmatched,
    _compute_confidence_calibration,
    _compute_subtopic_accuracy,
    _compute_topic_accuracy,
    _compute_unified_score,
    _match_segments_jaccard,
)

# ── Factories ─────────────────────────────────────────────────────────────────


def _gt(
    user_id: str = "user1",
    messages: list | None = None,
    true_topic: str = "TopicA",
    true_subtopic: str | None = None,
    has_user_engagement: bool | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    seg_id: int = 1,
) -> dict:
    start = started_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return {
        "id": seg_id,
        "user_id": user_id,
        "chat_messages": messages if messages is not None else ["msg1", "msg2"],
        "chat_started_at": start,
        "chat_ended_at": ended_at or start + timedelta(hours=1),
        "true_topic": true_topic,
        "true_sub_topic": true_subtopic,
        "has_user_engagement": has_user_engagement,
    }


def _model(
    user_id: str = "user1",
    messages: list | None = None,
    topic: str = "TopicA",
    subtopic: str | None = None,
    confidence: float | None = 0.9,
    summary: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    seg_id: int = 2,
) -> dict:
    start = started_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return {
        "id": seg_id,
        "user_id": user_id,
        "chat_messages": messages if messages is not None else ["msg1", "msg2"],
        "chat_started_at": start,
        "chat_ended_at": ended_at or start + timedelta(hours=1),
        "topic": topic,
        "sub_topic": subtopic,
        "label_confidence": confidence,
        "summary": summary,
        "run_id": "run1",
        "model": "gpt-4o",
        "prompt": "v3",
    }


def _match(
    matched: bool = True,
    gt_topic: str = "TopicA",
    model_topic: str | None = "TopicA",
    gt_subtopic: str | None = None,
    model_subtopic: str | None = None,
    confidence: float | None = 0.9,
    iou: float = 0.8,
    has_user_engagement: bool | None = None,
) -> dict:
    return {
        "gt_segment_id": 1,
        "gt_user_id": "user1",
        "gt_topic": gt_topic,
        "gt_subtopic": gt_subtopic,
        "gt_has_user_engagement": has_user_engagement,
        "model_segment_id": 2 if matched else None,
        "model_topic": model_topic if matched else None,
        "model_subtopic": model_subtopic if matched else None,
        "model_confidence": confidence if matched else None,
        "model_summary": "summary" if matched else None,
        "iou": iou,
        "matched": matched,
    }


# ── TestMatchSegmentsJaccard ──────────────────────────────────────────────────


class TestMatchSegmentsJaccard:
    def test_perfect_match(self):
        msgs = ["a", "b", "c"]
        gt = [_gt(messages=msgs)]
        model = [_model(messages=msgs)]

        results = _match_segments_jaccard(gt, model, threshold=0.3)

        assert len(results) == 1
        assert results[0]["matched"] is True
        assert results[0]["iou"] == 1.0

    def test_no_overlap_unmatched(self):
        gt = [_gt(
            messages=["a", "b"],
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ended_at=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        )]
        model = [_model(
            messages=["c", "d"],
            started_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            ended_at=datetime(2024, 6, 1, 1, tzinfo=timezone.utc),
        )]

        results = _match_segments_jaccard(gt, model, threshold=0.3)

        assert len(results) == 1
        assert results[0]["matched"] is False
        assert results[0]["iou"] == 0.0

    def test_partial_overlap_above_threshold(self):
        shared = ["a", "b"]
        gt = [_gt(messages=shared + ["c"])]
        model = [_model(messages=shared + ["d"])]

        # IoU = 2 / 4 = 0.5, which is >= 0.3
        results = _match_segments_jaccard(gt, model, threshold=0.3)

        assert results[0]["matched"] is True
        assert results[0]["iou"] == pytest.approx(0.5, abs=0.001)

    def test_different_users_not_matched(self):
        msgs = ["a", "b"]
        gt = [_gt(user_id="user1", messages=msgs)]
        model = [_model(user_id="user2", messages=msgs)]

        results = _match_segments_jaccard(gt, model, threshold=0.3)

        assert len(results) == 1
        assert results[0]["matched"] is False

    def test_sequential_matching_no_reuse(self):
        shared = ["a", "b", "c"]
        gt1 = _gt(
            user_id="u1",
            messages=shared,
            started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        gt2 = _gt(
            user_id="u1",
            messages=shared,
            started_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
        model_seg = _model(user_id="u1", messages=shared)

        results = _match_segments_jaccard([gt1, gt2], [model_seg], threshold=0.3)

        assert len(results) == 2
        matched_count = sum(1 for r in results if r["matched"])
        # Only one model segment — it can only match once
        assert matched_count == 1

    def test_empty_inputs(self):
        assert _match_segments_jaccard([], [], threshold=0.3) == []
        assert _match_segments_jaccard([], [_model()], threshold=0.3) == []
        # GT with no model candidates -> unmatched
        results = _match_segments_jaccard([_gt()], [], threshold=0.3)
        assert len(results) == 1
        assert results[0]["matched"] is False

    def test_hungarian_optimal_assignment(self):
        """Greedy would grab a weak match for GT1, leaving GT2 worse off.

        Hungarian should find the globally optimal assignment.
        """
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        # GT1 shares {a,b} with M1 (IoU=2/4=0.5) and {a,b,c} with M2 (IoU=3/4=0.75)
        # GT2 shares {d,e,f} with M1 (IoU=3/5=0.6) and nothing with M2
        # Greedy (GT1 first): GT1->M1(0.5), GT2 can't match M2 → suboptimal
        # Optimal: GT1->M2(0.75), GT2->M1(0.6) → total 1.35
        gt1 = _gt(
            seg_id=1, user_id="u1", messages=["a", "b", "c"],
            started_at=t0, ended_at=t0 + timedelta(hours=1),
        )
        gt2 = _gt(
            seg_id=2, user_id="u1", messages=["d", "e", "f"],
            started_at=t0 + timedelta(hours=2),
            ended_at=t0 + timedelta(hours=3),
        )
        m1 = _model(
            seg_id=10, user_id="u1", messages=["a", "b", "d", "e", "f"],
            started_at=t0 + timedelta(hours=2),
            ended_at=t0 + timedelta(hours=3),
        )
        m2 = _model(
            seg_id=11, user_id="u1", messages=["a", "b", "c", "x"],
            started_at=t0, ended_at=t0 + timedelta(hours=1),
        )

        results = _match_segments_jaccard([gt1, gt2], [m1, m2], threshold=0.3)

        assert len(results) == 2
        matched = {r["gt_segment_id"]: r for r in results}
        # Optimal: GT1 -> M2, GT2 -> M1
        assert matched[1]["matched"] is True
        assert matched[1]["model_segment_id"] == 11
        assert matched[2]["matched"] is True
        assert matched[2]["model_segment_id"] == 10

    def test_temporal_iou_breaks_tie(self):
        """Two model candidates with identical message Jaccard but different
        temporal overlap — the one with better temporal match should win."""
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        gt_seg = _gt(
            seg_id=1, user_id="u1", messages=["a", "b", "c"],
            started_at=t0, ended_at=t0 + timedelta(hours=2),
        )
        # M1: same messages, same time window (temporal IoU ~ 1.0)
        m1 = _model(
            seg_id=10, user_id="u1", messages=["a", "b", "c"],
            started_at=t0, ended_at=t0 + timedelta(hours=2),
        )
        # M2: same messages, very different time window (temporal IoU ~ 0)
        m2 = _model(
            seg_id=11, user_id="u1", messages=["a", "b", "c"],
            started_at=t0 + timedelta(days=30),
            ended_at=t0 + timedelta(days=30, hours=2),
        )

        results = _match_segments_jaccard([gt_seg], [m1, m2], threshold=0.3)

        assert len(results) == 1
        assert results[0]["matched"] is True
        # Should prefer M1 (better temporal overlap)
        assert results[0]["model_segment_id"] == 10

    def test_zero_message_jaccard_never_matches(self):
        """Even with perfect temporal overlap, zero message overlap should
        never produce a match (hard floor)."""
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        gt_seg = _gt(
            seg_id=1, user_id="u1", messages=["a", "b"],
            started_at=t0, ended_at=t0 + timedelta(hours=1),
        )
        model_seg = _model(
            seg_id=10, user_id="u1", messages=["x", "y"],
            started_at=t0, ended_at=t0 + timedelta(hours=1),
        )

        results = _match_segments_jaccard([gt_seg], [model_seg], threshold=0.3)

        assert len(results) == 1
        assert results[0]["matched"] is False

    def test_missing_chat_ended_at_degrades_gracefully(self):
        """Segment without chat_ended_at falls back to message-Jaccard-only."""
        msgs = ["a", "b", "c"]
        gt_seg = _gt(seg_id=1, messages=msgs)
        model_seg = _model(seg_id=10, messages=msgs)
        # Remove chat_ended_at to simulate missing data
        del model_seg["chat_ended_at"]

        results = _match_segments_jaccard([gt_seg], [model_seg], threshold=0.3)

        assert len(results) == 1
        assert results[0]["matched"] is True
        assert results[0]["iou"] == 1.0

    def test_alpha_message_only(self):
        """alpha=1.0 means only message Jaccard matters."""
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        gt_seg = _gt(
            seg_id=1, user_id="u1", messages=["a", "b"],
            started_at=t0, ended_at=t0 + timedelta(hours=1),
        )
        # Partial overlap: IoU = 1/3 ≈ 0.33
        model_seg = _model(
            seg_id=10, user_id="u1", messages=["a", "x"],
            started_at=t0 + timedelta(days=100),
            ended_at=t0 + timedelta(days=100, hours=1),
        )

        # alpha=1.0 ignores temporal → combined = 0.33 >= 0.3 → match
        results = _match_segments_jaccard(
            [gt_seg], [model_seg], threshold=0.3, alpha=1.0,
        )
        assert results[0]["matched"] is True

    def test_alpha_temporal_heavy(self):
        """alpha=0.3 weights temporal IoU heavily — poor temporal overlap
        can drop combined score below threshold even with some message overlap."""
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        gt_seg = _gt(
            seg_id=1, user_id="u1", messages=["a", "b"],
            started_at=t0, ended_at=t0 + timedelta(hours=1),
        )
        # Message IoU = 1/3 ≈ 0.33, temporal IoU ≈ 0 (months apart)
        model_seg = _model(
            seg_id=10, user_id="u1", messages=["a", "x"],
            started_at=t0 + timedelta(days=100),
            ended_at=t0 + timedelta(days=100, hours=1),
        )

        # alpha=0.3 → combined ≈ 0.3*0.33 + 0.7*0 ≈ 0.1 < 0.3 → no match
        results = _match_segments_jaccard(
            [gt_seg], [model_seg], threshold=0.3, alpha=0.3,
        )
        assert results[0]["matched"] is False


# ── TestComputeTopicAccuracy ──────────────────────────────────────────────────


class TestComputeTopicAccuracy:
    def test_perfect_accuracy(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicA"),
            _match(gt_topic="TopicB", model_topic="TopicB"),
        ]
        result = _compute_topic_accuracy(matches, total_model_segments=2)

        assert result["accuracy"] == 1.0
        assert result["f1"] == 1.0
        assert result["correct"] == 2
        assert result["total"] == 2

    def test_zero_accuracy(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicB"),
            _match(gt_topic="TopicB", model_topic="TopicA"),
        ]
        result = _compute_topic_accuracy(matches, total_model_segments=2)

        assert result["accuracy"] == 0.0
        assert result["f1"] == 0.0
        assert result["correct"] == 0

    def test_unmatched_excluded(self):
        matches = [
            _match(matched=False),
            _match(matched=False),
        ]
        result = _compute_topic_accuracy(matches)

        assert result["accuracy"] is None
        assert result["f1"] is None
        assert result["total"] == 0
        assert result["gt_segments"] == 2
        assert result["matched_accuracy"] is None

    def test_per_topic_metrics(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicA"),
            _match(gt_topic="TopicA", model_topic="TopicB"),
            _match(gt_topic="TopicB", model_topic="TopicB"),
        ]
        result = _compute_topic_accuracy(matches)

        per_a = result["per_topic"]["TopicA"]
        # TP=1 (A->A), FN=1 (A->B), FP=0
        assert per_a["tp"] == 1
        assert per_a["fn"] == 1
        assert per_a["support"] == 2

        per_b = result["per_topic"]["TopicB"]
        # TP=1 (B->B), FP=1 (A->B), FN=0
        assert per_b["tp"] == 1
        assert per_b["fp"] == 1

    def test_f1_with_unmatched_gt(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicA"),  # correct
            _match(gt_topic="TopicA", model_topic="TopicB"),  # wrong
            _match(gt_topic="TopicB", model_topic="TopicB"),  # correct
            _match(matched=False, gt_topic="TopicA"),          # unmatched GT
            _match(matched=False, gt_topic="TopicB"),          # unmatched GT
        ]
        result = _compute_topic_accuracy(matches, total_model_segments=4)

        # N=5, M=4, m=2
        # Precision = 2/4 = 0.5, Recall = 2/5 = 0.4
        # F1 = 2*0.5*0.4/(0.5+0.4) = 0.4444
        assert result["precision"] == pytest.approx(0.5, abs=0.001)
        assert result["recall"] == pytest.approx(0.4, abs=0.001)
        assert result["f1"] == pytest.approx(0.4444, abs=0.001)
        assert result["accuracy"] == pytest.approx(0.4444, abs=0.001)
        assert result["matched_accuracy"] == pytest.approx(2 / 3, abs=0.001)

        # Per-topic: TopicA FN should include the unmatched GT segment
        per_a = result["per_topic"]["TopicA"]
        assert per_a["fn"] == 2  # 1 misclassified + 1 unmatched
        assert per_a["tp"] == 1

    def test_f1_no_model_segments_fallback(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicA"),
            _match(matched=False, gt_topic="TopicB"),
        ]
        result = _compute_topic_accuracy(matches, total_model_segments=0)

        # N=2, M fallback=len(matched)=1, m=1
        # Precision = 1/1 = 1.0, Recall = 1/2 = 0.5
        # F1 = 2*1.0*0.5/(1.0+0.5) = 0.6667
        assert result["f1"] == pytest.approx(0.6667, abs=0.001)


# ── TestComputeSubtopicAccuracy ───────────────────────────────────────────────


class TestComputeSubtopicAccuracy:
    def test_exact_match(self):
        matches = [
            _match(gt_subtopic="sub_a", model_subtopic="sub_a"),
            _match(gt_subtopic="sub_b", model_subtopic="sub_b"),
        ]
        result = _compute_subtopic_accuracy(matches, total_model_segments=2)

        assert result["f1"] == 1.0
        assert result["accuracy"] == 1.0
        assert result["correct"] == 2

    def test_case_insensitive(self):
        matches = [
            _match(gt_subtopic="Foo_Bar", model_subtopic="foo_bar"),
        ]
        result = _compute_subtopic_accuracy(matches, total_model_segments=1)

        assert result["accuracy"] == 1.0
        assert result["correct"] == 1

    def test_both_null_excluded(self):
        # Both null -> not eligible (neither has a subtopic)
        matches = [
            _match(gt_subtopic=None, model_subtopic=None),
        ]
        result = _compute_subtopic_accuracy(matches)

        assert result["accuracy"] is None
        assert result["f1"] is None
        assert result["total"] == 0
        assert result["matched_accuracy"] is None

    def test_one_null_one_value_is_eligible(self):
        matches = [
            _match(gt_subtopic="sub_a", model_subtopic=None),
        ]
        result = _compute_subtopic_accuracy(matches)

        # eligible (gt_subtopic is not None), but values don't match
        assert result["total"] == 1
        assert result["correct"] == 0
        assert result["accuracy"] == 0.0

    def test_f1_with_unmatched_gt(self):
        matches = [
            _match(gt_subtopic="sub_a", model_subtopic="sub_a"),  # correct
            _match(gt_subtopic="sub_b", model_subtopic="sub_x"),  # wrong
            _match(matched=False, gt_topic="TopicA", gt_subtopic="sub_a"),  # unmatched
        ]
        result = _compute_subtopic_accuracy(matches, total_model_segments=3)

        # all_eligible: 3 (all have gt_subtopic)
        # matched_eligible: 2, correct: 1
        # precision = 1/3, recall = 1/3, f1 = 2*(1/3)*(1/3)/((1/3)+(1/3)) = 1/3
        assert result["correct"] == 1
        assert result["gt_segments"] == 3
        assert result["f1"] == pytest.approx(1 / 3, abs=0.001)
        assert result["matched_accuracy"] == pytest.approx(0.5, abs=0.001)


# ── TestComputeUnifiedScore ───────────────────────────────────────────────────


class TestComputeUnifiedScore:
    def test_perfect_match_all_correct(self):
        """100 GT, 100 model, all matched with jaccard=1.0, topic+sub correct → 1.0."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a1",
                iou=1.0,
            ),
            _match(
                gt_topic="B", model_topic="B",
                gt_subtopic="b1", model_subtopic="b1",
                iou=1.0,
            ),
        ]
        result = _compute_unified_score(matches, total_model_segments=2)

        assert result["score"] == 1.0
        assert result["topic_score"] == 1.0
        assert result["sub_score"] == 1.0
        assert result["avg_jaccard"] == 1.0
        assert result["correct_topic"] == 2
        assert result["correct_sub"] == 2
        assert result["denominator"] == 2

    def test_over_segmentation_penalised(self):
        """100 GT, 110 model, 100 matched correctly → 100/max(100,110) = 0.909."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a1",
                iou=1.0,
            ),
        ]
        # One GT but 2 model segments (over-segmentation)
        result = _compute_unified_score(matches, total_model_segments=2)

        # Σq = 1.0, denominator = max(1, 2) = 2 → score = 0.5
        assert result["score"] == 0.5
        assert result["denominator"] == 2
        assert result["model_total"] == 2

    def test_under_segmentation_penalised(self):
        """2 GT, 1 matched, 1 unmatched → score = 1/2 = 0.5."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a1",
                iou=1.0,
            ),
            _match(matched=False, gt_topic="B", gt_subtopic="b1"),
        ]
        result = _compute_unified_score(matches, total_model_segments=1)

        # Σq = 1.0, denominator = max(2, 1) = 2 → score = 0.5
        assert result["score"] == 0.5
        assert result["topic_score"] == 0.5
        assert result["sub_score"] == 0.5

    def test_topic_correct_sub_wrong_half_credit(self):
        """Matched with correct topic but wrong subtopic → q = 0.5."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a2",
                iou=1.0,
            ),
        ]
        result = _compute_unified_score(matches, total_model_segments=1)

        # q = 1.0 × 1 × (0.5 + 0.5 × 0) = 0.5
        assert result["score"] == 0.5
        assert result["topic_score"] == 1.0   # topic is right
        assert result["sub_score"] == 0.0     # sub is wrong
        assert result["correct_topic"] == 1
        assert result["correct_sub"] == 0

    def test_topic_wrong_zero_credit(self):
        """Wrong topic gets 0 credit regardless of subtopic."""
        matches = [
            _match(
                gt_topic="A", model_topic="B",
                gt_subtopic="a1", model_subtopic="a1",
                iou=1.0,
            ),
        ]
        result = _compute_unified_score(matches, total_model_segments=1)

        assert result["score"] == 0.0
        assert result["topic_score"] == 0.0
        assert result["sub_score"] == 0.0

    def test_partial_jaccard_proportional_penalty(self):
        """Jaccard 0.6 on a perfect-label match → q = 0.6."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a1",
                iou=0.6,
            ),
        ]
        result = _compute_unified_score(matches, total_model_segments=1)

        # q = 0.6 × 1 × 1 = 0.6
        assert result["score"] == 0.6
        assert result["avg_jaccard"] == 0.6

    def test_unmatched_only_zero_score(self):
        """Nothing matched → score = 0."""
        matches = [
            _match(matched=False, gt_topic="A", gt_subtopic="a1"),
            _match(matched=False, gt_topic="B", gt_subtopic="b1"),
        ]
        result = _compute_unified_score(matches, total_model_segments=5)

        assert result["score"] == 0.0
        assert result["matched"] == 0
        assert result["avg_jaccard"] == 0.0
        assert result["denominator"] == 5  # max(2, 5)

    def test_total_model_zero_falls_back_to_matched(self):
        """When caller can't supply model_total, use matched count."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a1",
                iou=1.0,
            ),
        ]
        result = _compute_unified_score(matches, total_model_segments=0)

        # model_total = 1 (matched), gt = 1, denom = 1, score = 1.0
        assert result["model_total"] == 1
        assert result["score"] == 1.0

    def test_empty_matches(self):
        result = _compute_unified_score([], total_model_segments=0)

        assert result["score"] == 0.0
        assert result["matched"] == 0
        assert result["gt_total"] == 0
        assert result["denominator"] == 0

    def test_mixed_correctness(self):
        """Spot-check mixed case: 1 perfect, 1 topic-only, 1 wrong, 1 unmatched."""
        matches = [
            # perfect: q = 1.0
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="a1", model_subtopic="a1",
                iou=1.0,
            ),
            # topic right, sub wrong: q = 0.5
            _match(
                gt_topic="B", model_topic="B",
                gt_subtopic="b1", model_subtopic="b2",
                iou=1.0,
            ),
            # topic wrong: q = 0
            _match(
                gt_topic="C", model_topic="D",
                gt_subtopic="c1", model_subtopic="d1",
                iou=1.0,
            ),
            # unmatched: q = 0
            _match(matched=False, gt_topic="E", gt_subtopic="e1"),
        ]
        result = _compute_unified_score(matches, total_model_segments=4)

        # Σq = 1.5, denom = max(4, 4) = 4 → score = 0.375
        assert result["score"] == 0.375
        assert result["correct_topic"] == 2
        assert result["correct_sub"] == 1

    def test_case_insensitive_subtopic(self):
        """Subtopic comparison is case-insensitive and strips whitespace."""
        matches = [
            _match(
                gt_topic="A", model_topic="A",
                gt_subtopic="Foo_Bar", model_subtopic="  foo_bar  ",
                iou=1.0,
            ),
        ]
        result = _compute_unified_score(matches, total_model_segments=1)

        assert result["correct_sub"] == 1
        assert result["score"] == 1.0


# ── TestComputeConfidenceCalibration ─────────────────────────────────────────


class TestComputeConfidenceCalibration:
    def test_single_bin(self):
        matches = [
            _match(confidence=0.85, gt_topic="TopicA", model_topic="TopicA"),
            _match(confidence=0.90, gt_topic="TopicA", model_topic="TopicA"),
        ]
        result = _compute_confidence_calibration(matches)

        bins = {b["range"]: b for b in result["bins"]}
        high_bin = bins["[0.8, 1.0]"]
        assert high_bin["count"] == 2
        assert high_bin["accuracy"] == 1.0

    def test_no_confidence_empty(self):
        matches = [
            _match(confidence=None),
        ]
        result = _compute_confidence_calibration(matches)

        # Null confidence segments are excluded — all bins should be empty
        for b in result["bins"]:
            assert b["count"] == 0
        assert result["expected_calibration_error"] == 0.0

    def test_ece_perfect_calibration(self):
        # Confidence ~0.9, topic always correct -> ECE should be small
        matches = [
            _match(confidence=0.9, gt_topic="TopicA", model_topic="TopicA"),
            _match(confidence=0.9, gt_topic="TopicA", model_topic="TopicA"),
            _match(confidence=0.9, gt_topic="TopicA", model_topic="TopicA"),
        ]
        result = _compute_confidence_calibration(matches)

        # accuracy=1.0, avg_confidence~0.9 -> |1.0 - 0.9| = 0.1
        # Not truly "perfect" but ECE should be small (<0.2)
        assert result["expected_calibration_error"] < 0.2

    def test_unmatched_excluded_from_calibration(self):
        matches = [
            _match(matched=False),
            _match(confidence=0.85, gt_topic="A", model_topic="A"),
        ]
        result = _compute_confidence_calibration(matches)

        total_count = sum(b["count"] for b in result["bins"])
        assert total_count == 1


# ── TestCollectMismatchesAndUnmatched ─────────────────────────────────────────


class TestCollectMismatchesAndUnmatched:
    def test_mismatches_collected(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicB"),
        ]
        result = _collect_mismatches(matches)

        assert len(result) == 1
        assert result[0]["ground_truth"]["true_topic"] == "TopicA"
        assert result[0]["predicted"]["topic"] == "TopicB"

    def test_no_mismatches_when_correct(self):
        matches = [
            _match(gt_topic="TopicA", model_topic="TopicA"),
        ]
        result = _collect_mismatches(matches)

        assert result == []

    def test_unmatched_not_in_mismatches(self):
        matches = [
            _match(matched=False),
        ]
        result = _collect_mismatches(matches)

        assert result == []

    def test_unmatched_collected(self):
        matches = [
            _match(matched=False, gt_topic="TopicA"),
        ]
        result = _collect_unmatched(matches)

        assert len(result) == 1
        assert result[0]["true_topic"] == "TopicA"

    def test_matched_not_in_unmatched(self):
        matches = [
            _match(matched=True),
        ]
        result = _collect_unmatched(matches)

        assert result == []

    def test_unmatched_has_expected_keys(self):
        matches = [
            _match(matched=False, gt_topic="TopicZ", iou=0.1),
        ]
        result = _collect_unmatched(matches)

        assert len(result) == 1
        record = result[0]
        assert "gt_segment_id" in record
        assert "user_id" in record
        assert "true_topic" in record
        assert record["best_iou"] == pytest.approx(0.1)
