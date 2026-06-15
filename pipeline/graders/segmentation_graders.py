"""
Deterministic segmentation graders (G0.3, G0.7, G0.8, G0.9, G0.10, G0.11, G1.2, G1.4).

These are structural checks that validate the shape of segmentation output
without any LLM involvement. They run after the segment step.

Usage:
    uv run python -m pipeline --step validate
"""

import logging
from collections import Counter
from dataclasses import dataclass

from bson import ObjectId
from pymongo.database import Database

from db.repositories.segments import SegmentRepository
from pipeline.config.loader import AnalyzerConfig

log = logging.getLogger(__name__)

_USER_FACING = ["user", "assistant", "automated", "team"]


@dataclass
class GraderResult:
    grader_id: str
    name: str
    passed: bool
    total: int
    failures: int
    details: list[str]

    def log_summary(self) -> None:
        status = "PASS" if self.passed else "FAIL"
        passing = self.total - self.failures
        log.info(
            "[%s] %s: %d/%d %s (%d FAIL)",
            self.grader_id, self.name, passing, self.total, status, self.failures,
        )
        for detail in self.details[:20]:  # cap log output
            log.info("  %s", detail)


def run_all_graders(
    segment_repo: SegmentRepository,
    input_db: Database,
    cfg: AnalyzerConfig,
) -> list[GraderResult]:
    """Run all segmentation graders and return results."""
    results = [
        g03_full_message_coverage(segment_repo, input_db, cfg),
        g07_pre_segment_completeness(segment_repo, input_db, cfg),
        g08_non_user_message_uniqueness(segment_repo, input_db, cfg),
        g09_reviewed_segment_integrity(segment_repo, input_db, cfg),
        g010_topic_subtopic_completeness(segment_repo, cfg),
        g011_label_confidence_range(segment_repo, cfg),
        g12_single_message_segments(segment_repo, cfg),
        g14_contiguity_check(segment_repo, input_db, cfg),
    ]
    for r in results:
        r.log_summary()
    return results


def g03_full_message_coverage(
    segment_repo: SegmentRepository,
    input_db: Database,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G0.3 — Full message coverage.

    For each segmented user:
    1. Get all user/assistant messages from sms_chat_messages for that user's chat.
    2. Get all chat_messages arrays from that user's sms_chat_segments.
    3. Union of segment message IDs must equal the full message set.

    No gaps, no overlaps.
    """
    user_ids = segment_repo.distinct_user_ids()
    total = len(user_ids)
    failures = 0
    details: list[str] = []

    for uid in user_ids:
        mongo_uid = ObjectId(uid) if isinstance(uid, str) else uid
        # Get user's chat
        chat = input_db[cfg.col_input_chat].find_one({"user": mongo_uid})
        if not chat:
            continue  # no chat = no messages to check

        # All user-facing messages from PROD (same filter as _build_flat_history)
        expected_ids = set()
        for msg in input_db[cfg.col_input_chat_message].find(
            {
                "chat": chat["_id"],
                "$or": [
                    {"type": {"$in": _USER_FACING}},
                    {"type": "system", "message": "[Tool Call] noReply"},
                ],
            },
            {"_id": 1},
        ):
            expected_ids.add(str(msg["_id"]))

        if not expected_ids:
            continue

        # All chat_messages from segments
        actual_ids = set()
        segment_msg_lists: list[list] = []
        for seg in segment_repo.find_by_user(uid):
            msgs = seg.get("chat_messages") or []
            segment_msg_lists.append(msgs)
            actual_ids.update(msgs)

        # Check for gaps
        missing = expected_ids - actual_ids
        # Check for extra (shouldn't happen but check anyway)
        extra = actual_ids - expected_ids

        # Check for overlaps (message in more than one segment)
        all_msg_ids = []
        for msgs in segment_msg_lists:
            all_msg_ids.extend(msgs)
        has_overlap = len(all_msg_ids) != len(set(all_msg_ids))

        if missing or extra or has_overlap:
            failures += 1
            if missing:
                details.append(f"User {uid}: {len(missing)} messages missing from segments")
            if extra:
                details.append(f"User {uid}: {len(extra)} extra messages in segments (not in PROD)")
            if has_overlap:
                overlap_count = len(all_msg_ids) - len(set(all_msg_ids))
                details.append(f"User {uid}: {overlap_count} overlapping message refs across segments")

    passed = failures == 0 or (failures / max(total, 1)) < 0.05  # < 5% failure = PASS
    return GraderResult(
        grader_id="G0.3",
        name="Full message coverage",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )


def g07_pre_segment_completeness(
    segment_repo: SegmentRepository,
    input_db: Database,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G0.7 — Pre-segmentation message completeness.

    For each segmented user, verify that every message the segmenter
    ingests (user, assistant, automated, team, system-noReply) appears
    in at least one segment's chat_messages array.  Uses the same query
    filter as _build_flat_history so the check is exact.

    Catches silent message drops in both the bot-only and LLM paths.
    """
    user_ids = segment_repo.distinct_user_ids()
    total = len(user_ids)
    failures = 0
    details: list[str] = []

    for uid in user_ids:
        mongo_uid = ObjectId(uid) if isinstance(uid, str) else uid
        chat = input_db[cfg.col_input_chat].find_one({"user": mongo_uid})
        if not chat:
            continue

        # Same $or filter as _build_flat_history in segmenter.py
        expected_ids = {
            str(msg["_id"])
            for msg in input_db[cfg.col_input_chat_message].find(
                {
                    "chat": chat["_id"],
                    "$or": [
                        {"type": {"$in": _USER_FACING}},
                        {"type": "system", "message": "[Tool Call] noReply"},
                    ],
                },
                {"_id": 1},
            )
        }
        if not expected_ids:
            continue

        # Union of chat_messages across all segments for this user
        actual_ids: set = set()
        for seg in segment_repo.find_by_user(uid):
            actual_ids.update(seg.get("chat_messages") or [])

        missing = expected_ids - actual_ids
        extra = actual_ids - expected_ids

        if missing or extra:
            failures += 1
            if missing:
                details.append(
                    f"User {uid}: {len(missing)} message(s) "
                    f"missing from segments"
                )
            if extra:
                details.append(
                    f"User {uid}: {len(extra)} extra message(s) "
                    f"in segments not in source"
                )

    passed = failures == 0 or (failures / max(total, 1)) < 0.05
    return GraderResult(
        grader_id="G0.7",
        name="Pre-segmentation completeness",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )


def g08_non_user_message_uniqueness(
    segment_repo: SegmentRepository,
    input_db: Database,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G0.8 — Non-user message uniqueness.

    For each segmented user, verify that every non-user message (assistant,
    automated, team, system) appears in at most one segment.  Only type="user"
    messages may appear in multiple segments (multi-topic overlap).

    Catches cases where the LLM or a code bug places a bot/system message in
    more than one segment's chat_messages array.
    """
    user_ids = segment_repo.distinct_user_ids()
    total = len(user_ids)
    failures = 0
    details: list[str] = []

    for uid in user_ids:
        # Collect all chat_messages across this user's segments
        all_ids: list = []
        for seg in segment_repo.find_by_user(uid):
            all_ids.extend(seg.get("chat_messages") or [])

        counts = Counter(all_ids)
        duplicated_ids = [mid for mid, c in counts.items() if c > 1]
        if not duplicated_ids:
            continue

        # Batch-query types for duplicated messages — convert IDs to ObjectId for MongoDB
        mongo_dup_ids = [ObjectId(mid) if isinstance(mid, str) else mid for mid in duplicated_ids]
        type_map: dict = {}
        for doc in input_db[cfg.col_input_chat_message].find(
            {"_id": {"$in": mongo_dup_ids}},
            {"_id": 1, "type": 1},
        ):
            type_map[str(doc["_id"])] = doc.get("type")

        user_failed = False
        for mid in duplicated_ids:
            msg_type = type_map.get(str(mid))
            if msg_type == "user":
                continue  # user messages allowed in multiple segments
            user_failed = True
            details.append(
                f"User {uid}: {msg_type} message {mid} "
                f"appears in {counts[mid]} segments"
            )

        if user_failed:
            failures += 1

    passed = failures == 0 or (failures / max(total, 1)) < 0.05
    return GraderResult(
        grader_id="G0.8",
        name="Non-user message uniqueness",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )


def g09_reviewed_segment_integrity(
    segment_repo: SegmentRepository,
    input_db: Database,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G0.9 — Reviewed segment integrity.

    Verify that every segment bearing a review indicator (reviewed_at, true_topic,
    or true_sub_topic is non-null) is fully consistent:
      - true_topic must be non-null
      - true_sub_topic must be non-null
      - reviewed_at must be non-null

    Any mismatch indicates that a write path blanked or partially corrupted a
    reviewed segment.  Zero tolerance — even one failure is a pipeline bug.
    """
    reviewed = [
        s for s in segment_repo.find_all()
        if s.get("reviewed_at") is not None
        or s.get("true_topic") is not None
        or s.get("true_sub_topic") is not None
    ]
    total = len(reviewed)
    failures = 0
    details: list[str] = []

    for seg in reviewed:
        missing: list[str] = []
        if seg.get("true_topic") is None:
            missing.append("true_topic")
        if seg.get("true_sub_topic") is None:
            missing.append("true_sub_topic")
        if seg.get("reviewed_at") is None:
            missing.append("reviewed_at")
        if missing:
            failures += 1
            details.append(
                f"Segment {seg['id']} (user {seg.get('user_id')}): "
                f"missing {', '.join(missing)}"
            )

    passed = failures == 0  # zero tolerance
    return GraderResult(
        grader_id="G0.9",
        name="Reviewed segment integrity",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )


def g010_topic_subtopic_completeness(
    segment_repo: SegmentRepository,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G0.10 — Topic/sub_topic completeness.

    Every segment must have a non-null, non-empty-string topic AND sub_topic.
    A null or empty value in either field is a pipeline bug — the segmenter
    must always assign both (fallback: "unclassified").

    Zero tolerance — even one failure is a FAIL.
    """
    all_segs = segment_repo.find_all()
    total = len(all_segs)
    if total == 0:
        return GraderResult("G0.10", "Topic/sub_topic completeness", True, 0, 0, ["No segments found"])

    bad_segments = [
        s for s in all_segs
        if not s.get("topic") or not s.get("sub_topic")
    ]

    failures = len(bad_segments)
    details: list[str] = []
    for seg in bad_segments[:20]:  # cap output
        topic = seg.get("topic")
        sub = seg.get("sub_topic")
        missing: list[str] = []
        if not topic:
            missing.append(f"topic={topic!r}")
        if not sub:
            missing.append(f"sub_topic={sub!r}")
        details.append(
            f"Segment {seg.get('id')} (user {seg.get('user_id')}): {', '.join(missing)}"
        )

    passed = failures == 0  # zero tolerance
    return GraderResult(
        grader_id="G0.10",
        name="Topic/sub_topic completeness",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )


def g011_label_confidence_range(
    segment_repo: SegmentRepository,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G0.11 — LLM label_confidence range check.

    Two valid ranges depending on segment type:
        - User-engaged (has_user_engagement=True):  0.0 <= label_confidence < 1.0
          LLM-generated confidence must never reach 1.0.
        - Bot-only (has_user_engagement=False):      label_confidence == 1.0
          Deterministic — no LLM uncertainty applies.

    Segments with label_confidence == None are excluded from this check.

    Zero tolerance — even one violation is a FAIL.
    """
    segments = [s for s in segment_repo.find_all() if s.get("label_confidence") is not None]
    total = len(segments)
    if total == 0:
        return GraderResult(
            "G0.11", "LLM label_confidence range", True, 0, 0,
            ["No segments with label_confidence found"],
        )

    failures = 0
    details: list[str] = []
    for seg in segments:
        lc = seg.get("label_confidence")
        if lc is None:
            continue  # defensive — filter above should exclude, but be safe
        try:
            lc_val = float(lc)
        except (TypeError, ValueError):
            failures += 1
            details.append(
                f"Segment {seg.get('id')} (user {seg.get('user_id')}): "
                f"label_confidence={lc!r} is not a valid float"
            )
            continue
        has_user = seg.get("has_user_engagement", True)
        if has_user:
            # LLM-derived: must be in [0.0, 1.0)
            if lc_val < 0.0 or lc_val >= 1.0:
                failures += 1
                details.append(
                    f"Segment {seg.get('id')} (user {seg.get('user_id')}): "
                    f"label_confidence={lc_val} out of range [0.0, 1.0)"
                )
        else:
            # Bot-only: must be exactly 1.0
            if lc_val != 1.0:
                failures += 1
                details.append(
                    f"Segment {seg.get('id')} (user {seg.get('user_id')}): "
                    f"bot-only label_confidence={lc_val} != 1.0"
                )

    passed = failures == 0  # zero tolerance
    return GraderResult(
        grader_id="G0.11",
        name="LLM label_confidence range",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )


def g12_single_message_segments(
    segment_repo: SegmentRepository,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G1.2 — Single-message segment rate.

    Count segments where len(chat_messages) == 1. A user message should have a bot
    reply — 1-message segments are suspicious. Flag as warning if > 20%.
    """
    all_segs = segment_repo.find_all()
    total = len(all_segs)
    if total == 0:
        return GraderResult("G1.2", "Single-message segments", True, 0, 0, ["No segments found"])

    single_count = sum(
        1 for s in all_segs
        if len(s.get("chat_messages") or []) == 1
    )

    pct = 100 * single_count / total
    passed = pct < 20.0
    return GraderResult(
        grader_id="G1.2",
        name="Single-message segments",
        passed=passed,
        total=total,
        failures=single_count,
        details=[f"{single_count}/{total} ({pct:.1f}%) are single-message — threshold < 20%"],
    )


def g14_contiguity_check(
    segment_repo: SegmentRepository,
    input_db: Database,
    cfg: AnalyzerConfig,
) -> GraderResult:
    """
    G1.4 — Contiguity check.

    For each user, verify:
    1. No message appears in more than one segment (no overlaps)
    2. Message indices within each segment are consecutive (no cherry-picking)
       — i.e., if we order all messages by createdAt, each segment covers a contiguous range
    """
    user_ids = segment_repo.distinct_user_ids()
    total = len(user_ids)
    failures = 0
    details: list[str] = []

    for uid in user_ids:
        mongo_uid = ObjectId(uid) if isinstance(uid, str) else uid
        # Get user's chat
        chat = input_db[cfg.col_input_chat].find_one({"user": mongo_uid})
        if not chat:
            continue

        # Build ordered message ID list from PROD (same filter as _build_flat_history)
        ordered_msgs = list(
            input_db[cfg.col_input_chat_message]
            .find(
                {
                    "chat": chat["_id"],
                    "$or": [
                        {"type": {"$in": _USER_FACING}},
                        {"type": "system", "message": "[Tool Call] noReply"},
                    ],
                },
                {"_id": 1},
            )
            .sort("createdAt", 1)
        )
        if not ordered_msgs:
            continue

        # Map message ID → position index
        id_to_idx = {str(m["_id"]): i for i, m in enumerate(ordered_msgs)}

        # Get segments sorted by chat_started_at
        segments = sorted(
            segment_repo.find_by_user(uid),
            key=lambda s: (s.get("chat_started_at") is None, s.get("chat_started_at")),
        )

        user_failed = False
        all_indices_seen: list[int] = []

        for seg in segments:
            msg_ids = seg.get("chat_messages") or []
            # Map to indices
            indices = []
            for mid in msg_ids:
                if mid in id_to_idx:
                    indices.append(id_to_idx[mid])
            if not indices:
                continue

            indices.sort()

            # Check contiguity: indices should be consecutive
            expected = list(range(indices[0], indices[-1] + 1))
            if indices != expected:
                user_failed = True
                details.append(
                    f"User {uid}: segment has non-contiguous indices "
                    f"(got {len(indices)} msgs spanning range {indices[0]}-{indices[-1]})"
                )
                break

            all_indices_seen.extend(indices)

        # Check for overlaps across segments
        if not user_failed and len(all_indices_seen) != len(set(all_indices_seen)):
            user_failed = True
            overlap = len(all_indices_seen) - len(set(all_indices_seen))
            details.append(f"User {uid}: {overlap} message(s) appear in multiple segments")

        if user_failed:
            failures += 1

    passed = failures == 0 or (failures / max(total, 1)) < 0.05
    return GraderResult(
        grader_id="G1.4",
        name="Contiguity",
        passed=passed,
        total=total,
        failures=failures,
        details=details,
    )
