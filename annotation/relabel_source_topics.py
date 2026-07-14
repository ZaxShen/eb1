"""Relabel SuperDialseg gold segments from real document grounding (issue #23).

Replaces the BERTopic-derived ``bertopic_topic`` / ``bertopic_subtopic`` values
with REAL document-grounded labels recovered by
``analysis.derive_source_grounding``: each gold segment's topic is its domain
display name and its subtopic is the majority cleaned document title over the
segment's turn span. The dataset's taxonomy is replaced with the real hierarchy
(domain -> document) so annotators pick from the true option set. Run::

    python -m annotation.relabel_source_topics --dataset superdialseg \\
        --grounding analysis/superdialseg_grounding.json [--execute]

The column names stay ``bertopic_*`` (the UI wording is retargeted to "Source" in
a parallel task); values are stored as DISPLAY strings ("Social Security",
"Apply for Retirement Benefits") exactly as the current BERTopic labels are, so
the UI filter keeps passing them verbatim. Only ``source='gold'`` segments are
relabelled; the whole-conversation ``source='predicted'`` seeds are left NULL.

Default is a DRY RUN that prints per-domain counts and writes nothing;
``--execute`` applies every segment UPDATE and the taxonomy replacement in a
single transaction against ``EB1_ANNOTATION_DSN``. Because no human gold labels
exist yet, ``--execute`` aborts if any segment has been human-reviewed (guarding
against clobbering real annotations) unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from analysis.derive_source_grounding import DOMAIN_DISPLAY
from annotation.backend import db
from annotation.backend.slug import slugify

DEFAULT_LABEL_MAP = Path("analysis/source_label_map.json")


def majority_title(message_indices: list[int], doc_by_turn: list) -> str | None:
    """Return the majority cleaned title across a segment's turn span.

    Titles are read at ``doc_by_turn[idx]`` for each ``idx`` in
    ``message_indices`` (out-of-range and ``None`` entries skipped). Ties are
    broken by the title that first appears at the LOWEST message index. Returns
    ``None`` when every turn in the span is ungrounded (all-null).
    """
    counts: Counter[str] = Counter()
    first_index: dict[str, int] = {}
    for idx in message_indices:
        if idx < 0 or idx >= len(doc_by_turn):
            continue
        title = doc_by_turn[idx]
        if title is None:
            continue
        counts[title] += 1
        if title not in first_index:
            first_index[title] = idx
    if not counts:
        return None
    best = min(counts, key=lambda t: (-counts[t], first_index[t]))
    return best


def segment_label(
    message_indices: list[int], doc_by_turn: list, domain: str
) -> tuple[str | None, str | None]:
    """Return the ``(topic, subtopic)`` display labels for one gold segment.

    A grounded segment gets ``(domain display, majority title)``; an all-null
    span gets ``(None, None)``.
    """
    subtopic = majority_title(message_indices, doc_by_turn)
    if subtopic is None:
        return (None, None)
    return (DOMAIN_DISPLAY[domain], subtopic)


def build_taxonomy_rows(label_map: dict, dataset: str) -> list[dict]:
    """Build the real taxonomy rows from a source label map (issue #23 shape).

    One ``(topic_slug, NULL)`` row per distinct domain display (description = the
    domain display) followed by one ``(topic_slug, subtopic_slug)`` row per pair
    (description = ``"<title> — source: <domain code> | <raw doc_id>"``). Raises
    ``ValueError`` if the file's ``dataset`` does not match ``dataset``.
    """
    file_dataset = label_map.get("dataset")
    if file_dataset != dataset:
        raise ValueError(
            f"label map dataset {file_dataset!r} does not match --dataset {dataset!r}"
        )
    topic_rows: list[dict] = []
    pair_rows: list[dict] = []
    seen_topics: set[str] = set()
    for pair in label_map.get("pairs", []):
        topic_slug = slugify(pair["topic"])
        if topic_slug not in seen_topics:
            seen_topics.add(topic_slug)
            topic_rows.append(
                {
                    "topic": topic_slug,
                    "subtopic": None,
                    "description": pair["topic"],
                }
            )
        pair_rows.append(
            {
                "topic": topic_slug,
                "subtopic": slugify(pair["subtopic"]),
                "description": (
                    f"{pair['subtopic']} — source: "
                    f"{pair['topic_raw']} | {pair['subtopic_raw']}"
                ),
            }
        )
    return topic_rows + pair_rows


def plan_relabel(dataset: str, grounding: dict) -> tuple[list[dict], Counter, int, int]:
    """Compute the segment relabel plan without writing.

    Returns ``(updates, per_domain_counts, all_null, missing)`` where ``updates``
    is ``[{segment_id, topic, subtopic}]`` for every ``source='gold'`` segment of
    a grounded conversation, ``per_domain_counts`` maps domain display -> number
    relabelled, ``all_null`` counts spans with no grounded turn, and ``missing``
    counts gold segments whose conversation has no grounding entry (skipped).
    """
    dialogues = grounding["dialogues"]
    pool = db.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.id, s.message_indices, c.ext_id FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'gold' "
            "ORDER BY c.ext_id, s.id",
            (dataset,),
        ).fetchall()

    updates: list[dict] = []
    per_domain: Counter[str] = Counter()
    all_null = 0
    missing = 0
    for row in rows:
        entry = dialogues.get(row["ext_id"])
        if entry is None:
            missing += 1
            continue
        topic, subtopic = segment_label(
            list(row["message_indices"] or []), entry["doc_by_turn"], entry["domain"]
        )
        updates.append({"segment_id": row["id"], "topic": topic, "subtopic": subtopic})
        if subtopic is None:
            all_null += 1
        else:
            per_domain[topic] += 1
    return updates, per_domain, all_null, missing


def apply_relabel(
    dataset: str, updates: list[dict], taxonomy_rows: list[dict]
) -> None:
    """Apply the segment relabel + taxonomy replacement in one transaction."""
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            for row in updates:
                conn.execute(
                    "UPDATE segment SET bertopic_topic = %s, bertopic_subtopic = %s "
                    "WHERE id = %s",
                    (row["topic"], row["subtopic"], row["segment_id"]),
                )
            conn.execute("DELETE FROM taxonomy WHERE dataset = %s", (dataset,))
            for tax in taxonomy_rows:
                conn.execute(
                    "INSERT INTO taxonomy (dataset, kind, topic, subtopic, description) "
                    "VALUES (%s, 'user', %s, %s, %s)",
                    (dataset, tax["topic"], tax["subtopic"], tax["description"]),
                )


def _print_plan(
    dataset: str,
    updates: list[dict],
    per_domain: Counter,
    all_null: int,
    missing: int,
    taxonomy_rows: list[dict],
) -> None:
    topic_rows = [t for t in taxonomy_rows if t["subtopic"] is None]
    pair_rows = [t for t in taxonomy_rows if t["subtopic"] is not None]
    print(f"dataset={dataset}")
    print(f"gold segments to relabel: {len(updates)}")
    print("per-domain relabelled:")
    for topic in sorted(per_domain):
        print(f"  {topic}: {per_domain[topic]}")
    print(f"all-null segments (NULL/NULL): {all_null}")
    if missing:
        print(f"gold segments with no grounding (skipped): {missing}")
    print(
        f"taxonomy replacement: {len(topic_rows)} topics + {len(pair_rows)} pairs "
        f"= {len(taxonomy_rows)} rows"
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Relabel gold segments from real document grounding."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--grounding", type=Path, required=True)
    parser.add_argument("--label-map", type=Path, default=DEFAULT_LABEL_MAP)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="apply the relabel + taxonomy replacement (default is a dry run).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="relabel even when segments have been human-reviewed.",
    )
    args = parser.parse_args(argv)

    grounding = json.loads(args.grounding.read_text(encoding="utf-8"))
    if grounding.get("dataset") != args.dataset:
        parser.error(
            f"grounding dataset {grounding.get('dataset')!r} != --dataset "
            f"{args.dataset!r}"
        )
    label_map = json.loads(args.label_map.read_text(encoding="utf-8"))
    taxonomy_rows = build_taxonomy_rows(label_map, args.dataset)

    try:
        updates, per_domain, all_null, missing = plan_relabel(args.dataset, grounding)
        _print_plan(args.dataset, updates, per_domain, all_null, missing, taxonomy_rows)
        if not args.execute:
            print("dry run: no rows written (pass --execute to apply)")
            return 0
        reviewed = db.reviewed_base_segment_ids(args.dataset)
        if reviewed and not args.force:
            print(
                f"ABORT: {len(reviewed)} segment(s) already human-reviewed; "
                "pass --force to relabel anyway."
            )
            return 1
        apply_relabel(args.dataset, updates, taxonomy_rows)
        print(
            f"executed: relabelled {len(updates)} gold segments, replaced taxonomy "
            f"with {len(taxonomy_rows)} rows."
        )
    finally:
        db.reset_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
