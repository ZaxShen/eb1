"""Apply human-readable labels over raw c-TF-IDF BERTopic cluster names.

:func:`analysis.bertopic_classify` writes raw c-TF-IDF keyword strings (e.g.
``aid / loan / federal / student``) into ``segment.bertopic_topic`` /
``segment.bertopic_subtopic``. This script rewrites those raw strings to clean
human labels (``Federal Student Aid``) from a committed mapping artifact, making
the rename reproducible and auditable: the JSON is the source of truth, re-running
is idempotent, and the queue filter + ``bertopic-labels`` endpoint pick up the new
names automatically (they read the same columns).

The mapping is keyed on the full ``(topic_raw, subtopic_raw)`` pair, so it is
robust to subtopic keyword strings that repeat across topics. Each pair's segments
are matched by their raw values and rewritten in one transaction.

Generate ``analysis/bertopic_label_map.json`` once (keywords + sample segments ->
labels), review it, commit it, then apply with::

    uv run python -m analysis.bertopic_rename --apply
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from annotation.backend import db

log = logging.getLogger(__name__)

DEFAULT_MAP = Path(__file__).with_name("bertopic_label_map.json")


def load_pairs(map_path: Path) -> list[dict]:
    """Load and validate the ``(topic_raw, subtopic_raw) -> (topic, subtopic)`` map."""
    data = json.loads(map_path.read_text())
    pairs = data["pairs"]
    required = {"topic_raw", "subtopic_raw", "topic", "subtopic"}
    for i, p in enumerate(pairs):
        missing = required - p.keys()
        if missing:
            raise ValueError(f"pair {i} missing keys: {sorted(missing)}")
    seen = {(p["topic_raw"], p["subtopic_raw"]) for p in pairs}
    if len(seen) != len(pairs):
        raise ValueError("duplicate (topic_raw, subtopic_raw) keys in map")
    return pairs


def apply_rename(pairs: list[dict], *, dry_run: bool = False) -> int:
    """Rewrite raw cluster strings to clean labels for each mapped pair.

    Matches gold segments by their raw ``(bertopic_topic, bertopic_subtopic)`` pair
    and sets the clean labels. One transaction; idempotent (re-running over already
    clean rows matches nothing). Returns the number of segment rows updated.
    """
    import psycopg

    pool = db.get_pool()
    updated = 0
    with pool.connection() as conn:
        try:
            with conn.transaction():
                for p in pairs:
                    cur = conn.execute(
                        "UPDATE segment SET bertopic_topic = %s, bertopic_subtopic = %s "
                        "WHERE bertopic_topic = %s AND bertopic_subtopic = %s",
                        (p["topic"], p["subtopic"], p["topic_raw"], p["subtopic_raw"]),
                    )
                    updated += cur.rowcount
                    log.info("%4d  %s / %s", cur.rowcount, p["topic"], p["subtopic"])
                if dry_run:
                    raise psycopg.Rollback
        except psycopg.Rollback:
            pass
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map",
        type=Path,
        default=DEFAULT_MAP,
        help="path to the label-map JSON artifact",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the rename (omit for a dry run that rolls back)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pairs = load_pairs(args.map)
    try:
        updated = apply_rename(pairs, dry_run=not args.apply)
    finally:
        db.reset_pool()
    verb = "Renamed" if args.apply else "Would rename (dry run)"
    print(f"{verb} {updated} gold segment(s) across {len(pairs)} cluster pair(s).")


if __name__ == "__main__":
    main()
