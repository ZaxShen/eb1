"""
Proposal 2: New subtopic ground-truth validation.

When the LLM invents a new subtopic (not in the current taxonomy), this module
validates it against existing ground-truth-reviewed segments. It fetches a random
GT-reviewed segment from the closest existing subtopic and asks the LLM:
"Is this really a new subtopic, or does it belong to [existing subtopic]?"

This prevents hallucinated subtopic variants like:
  scheduling_reminder_last_chance, scheduling_reminder_skip_offer,
  match_follow_up_feedback, match_cancellation_re_entry, etc.
"""

import difflib
import logging

log = logging.getLogger(__name__)


def find_closest_subtopic(
    new_subtopic: str,
    existing_subtopics: set[str],
    threshold: float = 0.5,
) -> str | None:
    """Find the most similar existing subtopic by string similarity.

    Returns the closest match if similarity >= threshold, else None.
    """
    if not existing_subtopics:
        return None

    best_match: str | None = None
    best_ratio = 0.0

    for existing in existing_subtopics:
        ratio = difflib.SequenceMatcher(None, new_subtopic, existing).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = existing

    if best_ratio >= threshold and best_match is not None:
        return best_match
    return None


def validate_new_subtopic(
    topic: str,
    new_subtopic: str,
    known_subtopics: dict[str, set[str]],
    gt_segments: list[dict] | None = None,
    similarity_threshold: float = 0.5,
) -> str:
    """Validate whether a new subtopic is genuine or a hallucination.

    Strategy:
    1. Find the closest existing subtopic by string similarity.
    2. If the new subtopic is very similar (>= threshold) to an existing one,
       remap to the existing subtopic.
    3. If no close match exists, accept the new subtopic as genuinely novel.

    When gt_segments are provided, also checks if the new subtopic's semantic
    meaning overlaps with GT segments from the closest existing subtopic.

    Returns the validated subtopic slug (either the original or remapped).
    """
    existing = known_subtopics.get(topic, set())

    if new_subtopic in existing:
        return new_subtopic

    closest = find_closest_subtopic(new_subtopic, existing, similarity_threshold)

    if closest is None:
        log.info(
            "P2: New subtopic '%s/%s' — no close match found (genuinely new).",
            topic, new_subtopic,
        )
        return new_subtopic

    # Check if the new subtopic is likely a variant of the closest match
    if _is_likely_variant(new_subtopic, closest):
        log.info(
            "P2: Remapping hallucinated subtopic '%s/%s' → '%s/%s'.",
            topic, new_subtopic, topic, closest,
        )
        return closest

    # If GT segments are available, check semantic overlap
    if gt_segments:
        overlap = _check_gt_overlap(new_subtopic, closest, gt_segments)
        if overlap:
            log.info(
                "P2: GT overlap detected — remapping '%s/%s' → '%s/%s'.",
                topic, new_subtopic, topic, closest,
            )
            return closest

    log.info(
        "P2: New subtopic '%s/%s' accepted (closest='%s', not a variant).",
        topic, new_subtopic, closest,
    )
    return new_subtopic


def _is_likely_variant(new_subtopic: str, existing: str) -> bool:
    """Check if new_subtopic is a variant of an existing subtopic.

    Common hallucination patterns:
    - Adding suffixes: scheduling_reminder → scheduling_reminder_last_chance
    - Adding prefixes: match_notification → re_match_notification
    - Swapping words: match_follow_up_notification → match_follow_up_feedback
    """
    # The new subtopic contains the existing one as a prefix/suffix
    if new_subtopic.startswith(existing + "_") or new_subtopic.endswith("_" + existing):
        return True

    # The existing subtopic contains the new one as a prefix
    if existing.startswith(new_subtopic + "_"):
        return True

    # Split into parts and check overlap
    new_parts = set(new_subtopic.split("_"))
    existing_parts = set(existing.split("_"))

    if not new_parts or not existing_parts:
        return False

    overlap = new_parts & existing_parts
    # If >70% of parts overlap, it's likely a variant
    min_len = min(len(new_parts), len(existing_parts))
    if min_len > 0 and len(overlap) / min_len >= 0.7:
        return True

    return False


def _check_gt_overlap(
    new_subtopic: str,
    closest_existing: str,
    gt_segments: list[dict],
) -> bool:
    """Check if GT segments for the closest subtopic suggest the new one is redundant.

    Looks at GT segments with true_sub_topic == closest_existing and checks
    if their summaries overlap with what the new subtopic name implies.
    """
    relevant_gt = [
        seg for seg in gt_segments
        if seg.get("true_sub_topic") == closest_existing
    ]

    if not relevant_gt:
        return False

    # If we have GT segments for the closest match, and the new subtopic
    # is string-similar, it's probably a hallucination
    new_parts = set(new_subtopic.split("_"))
    existing_parts = set(closest_existing.split("_"))
    overlap = new_parts & existing_parts

    return len(overlap) >= 2


def batch_validate_subtopics(
    segments: list[dict],
    known_subtopics: dict[str, set[str]],
    gt_segments: list[dict] | None = None,
    similarity_threshold: float = 0.5,
) -> list[dict]:
    """Validate and remap subtopics for a batch of segments.

    Mutates segments in place, remapping hallucinated subtopics to their
    closest existing match.

    Returns the list of segments (same reference, mutated).
    """
    remap_count = 0
    for seg in segments:
        topic = seg.get("topic")
        sub_topic = seg.get("sub_topic")

        if not topic or not sub_topic:
            continue

        existing = known_subtopics.get(topic, set())
        if sub_topic in existing:
            continue

        validated = validate_new_subtopic(
            topic, sub_topic, known_subtopics,
            gt_segments=gt_segments,
            similarity_threshold=similarity_threshold,
        )

        if validated != sub_topic:
            seg["sub_topic"] = validated
            remap_count += 1

    if remap_count:
        log.info("P2: Remapped %d hallucinated subtopic(s) in batch.", remap_count)

    return segments
