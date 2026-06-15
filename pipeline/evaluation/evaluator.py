"""
Evaluation: Analyzer pipeline quality metrics.

Measures the quality of the segmentation and labeling steps by inspecting
the sms_chat_segments table directly — no external ground truth required.

Metrics:
  - total_segments             : total sms_chat_segments rows processed
  - labeled_segments           : segments with a non-null topic
  - unlabeled_segments         : segments still missing a topic
  - noise_ratio                : fraction of segments with cluster = null (no HDBSCAN run yet)
  - distinct_topics            : number of unique topic labels discovered
  - topic_distribution         : segment count per topic, sorted by frequency
  - low_confidence_count       : segments where min(cluster.confidence, label_confidence) < 0.6
  - unconfirmed_topic_count    : taxonomy topics with confirmedBy = null (P1 review queue)
  - unconfirmed_subtopic_count : taxonomy subtopics with confirmedBy = null (P2 review queue)

Run standalone:
    uv run python -m pipeline --step evaluate
"""

import logging
from collections import Counter

from db.repositories.segments import SegmentRepository
from pipeline.config.loader import AnalyzerConfig

log = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────────────────────


def run_evaluation(segment_repo: SegmentRepository, cfg: AnalyzerConfig) -> dict:
    """Compute Analyzer quality metrics. Prints a summary and returns the dict."""
    all_segs = segment_repo.find_all()
    total_segs = len(all_segs)
    if total_segs > 0:
        log.warning(
            "Loaded %d segments into memory for evaluation. "
            "Consider pagination if this causes OOM at scale.",
            total_segs,
        )

    if total_segs == 0:
        log.warning("No sms_chat_segments rows found. Run the pipeline first.")
        return {}

    labeled_segs = [s for s in all_segs if s.get("topic")]

    # ── Noise ratio (cluster == null → no HDBSCAN run yet) ───────────────────
    noise_count = sum(1 for s in all_segs if s.get("cluster") is None)
    noise_ratio = noise_count / total_segs

    # ── Low-confidence queue: min(cluster.confidence, label_confidence) < 0.6 ─
    low_conf_count = sum(
        1 for s in labeled_segs
        if min(
            (s.get("cluster") or {}).get("confidence", 0.0),
            s.get("label_confidence") or 0.0,
        ) < 0.6
    )

    # ── Unconfirmed taxonomy entries (user + template taxonomies) ─────────────
    from pipeline.config.loader import (
        BOT_SUBTOPIC_CONFIRMED,
        BOT_TOPIC_CONFIRMED,
        SUBTOPIC_CONFIRMED,
        TOPIC_CONFIRMED,
    )
    unconfirmed_topic_count = (
        sum(1 for c in TOPIC_CONFIRMED.values() if not c)
        + sum(1 for c in BOT_TOPIC_CONFIRMED.values() if not c)
    )
    unconfirmed_subtopic_count = (
        sum(
            1 for subs in SUBTOPIC_CONFIRMED.values()
            for c in subs.values() if not c
        )
        + sum(
            1 for subs in BOT_SUBTOPIC_CONFIRMED.values()
            for c in subs.values() if not c
        )
    )

    # ── Topic distribution ────────────────────────────────────────────────────
    topic_dist = Counter(s.get("topic") for s in labeled_segs)

    metrics = {
        "total_segments":       total_segs,
        "labeled_segments":     len(labeled_segs),
        "unlabeled_segments":   total_segs - len(labeled_segs),
        "noise_ratio":          round(noise_ratio, 3),
        "distinct_topics":      len(topic_dist),
        "topic_distribution":   dict(topic_dist.most_common()),
        "low_confidence_count":       low_conf_count,
        "unconfirmed_topic_count":    unconfirmed_topic_count,
        "unconfirmed_subtopic_count": unconfirmed_subtopic_count,
    }

    _print_report(metrics)
    return metrics


# ── Report ────────────────────────────────────────────────────────────────────


def _print_report(m: dict) -> None:
    print("\n" + "=" * 52)
    print("  Analyzer — Evaluation Report")
    print("=" * 52)
    print(f"  Total segments      : {m['total_segments']}")
    print(f"  Labeled             : {m['labeled_segments']}")
    print(f"  Unlabeled           : {m['unlabeled_segments']}")
    print(f"  Noise ratio         : {m['noise_ratio']:.1%}")
    print(f"  Distinct topics     : {m['distinct_topics']}")
    print(f"  Low-confidence queue: {m['low_confidence_count']} segments (P3 review)")
    print(f"  Unconfirmed topics  : {m['unconfirmed_topic_count']} — taxonomy expansion pending (P1)")
    print(f"  Unconfirmed subtopics: {m['unconfirmed_subtopic_count']} — pending review (P2)")
    print()
    print("  Topic distribution:")
    for topic, count in m["topic_distribution"].items():
        bar = "█" * min(count, 40)
        print(f"    {topic:<28} {count:>4}  {bar}")
    print("=" * 52 + "\n")
