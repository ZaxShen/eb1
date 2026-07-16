"""Taxonomy v2 migration: Domain -> nav category -> document (issue #23).

Restructures the SuperDialseg taxonomy around the four source sites. A
conversation's ``domain`` (ssa / va / dmv / studentaid) is a KNOWN attribute
recovered from the grounding; classification happens WITHIN a domain, so the
taxonomy is domain-scoped. Each gold segment is relabelled to
``bertopic_topic`` = the nav CATEGORY (display, e.g. "Vehicles") and
``bertopic_subtopic`` = the majority DOCUMENT title (display) over its turn span,
where the category is the ``analysis/nav_category_map.json`` lookup of
``(domain, document)``. Run::

    python -m annotation.migrate_domain_taxonomy --dataset superdialseg \\
        --grounding analysis/superdialseg_grounding.json \\
        --nav-map analysis/nav_category_map.json [--execute]

The document is resolved exactly as ``annotation.relabel_source_topics`` does
(majority cleaned title over the segment's turn span, ties -> lowest index); an
all-null span stays ``(NULL, NULL)``. Only ``source='gold'`` segments are
relabelled; the whole-conversation ``source='predicted'`` seeds are left NULL.
Every conversation with a grounding entry has its ``domain`` set.

The dataset taxonomy is rebuilt from the nav map: per domain, one
``(domain, slug(category), NULL)`` topic row plus one
``(domain, slug(category), slug(document))`` pair row per mapped document,
descriptions carrying the display forms + domain provenance. ``kind='user'``.

Default is a DRY RUN that prints per-domain counts and writes nothing;
``--execute`` applies every segment UPDATE, the conversation ``domain`` writes,
and the taxonomy rebuild in a SINGLE transaction against ``EB1_ANNOTATION_DSN``.
Because no human gold labels exist yet, ``--execute`` aborts if any segment has
been human-reviewed (guarding against clobbering real annotations) unless
``--force`` is given.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from analysis.derive_source_grounding import DOMAIN_DISPLAY
from annotation.backend import db
from annotation.backend.slug import slugify
from annotation.relabel_source_topics import majority_title


def build_category_lookup(nav_map: dict) -> dict[tuple[str, str], str]:
    """Return ``{(domain, document): category}`` from the nav map ``mapping``."""
    return {
        (entry["domain"], entry["document"]): entry["category"]
        for entry in nav_map.get("mapping", [])
    }


def segment_label(
    message_indices: list[int],
    doc_by_turn: list,
    domain: str,
    lookup: dict[tuple[str, str], str],
) -> tuple[str | None, str | None, bool]:
    """Return ``(category, document, unmapped)`` display labels for one segment.

    A grounded segment gets ``(nav category, majority document, False)``; an
    all-null span gets ``(None, None, False)``. When the majority document has no
    nav category for its domain the segment is ``(None, document, True)`` so the
    caller can count (and loudly report) an unmapped document.
    """
    document = majority_title(message_indices, doc_by_turn)
    if document is None:
        return (None, None, False)
    category = lookup.get((domain, document))
    if category is None:
        return (None, document, True)
    return (category, document, False)


def build_taxonomy_rows(nav_map: dict) -> list[dict]:
    """Build the domain-scoped taxonomy rows from the nav map ``mapping``.

    Per domain: one ``(domain, slug(category), NULL)`` topic row (description =
    ``"<category> — <domain display>"``) followed by one
    ``(domain, slug(category), slug(document))`` pair row per mapped document
    (description = ``"<document> — <category> · <domain display>"``). Rows are
    de-duplicated so a repeated ``(domain, category, document)`` slug triple never
    violates the domain-scoped unique index.
    """
    topic_rows: list[dict] = []
    pair_rows: list[dict] = []
    seen_topics: set[tuple[str, str]] = set()
    seen_pairs: set[tuple[str, str, str]] = set()
    for entry in nav_map.get("mapping", []):
        domain = entry["domain"]
        category = entry["category"]
        document = entry["document"]
        domain_display = DOMAIN_DISPLAY[domain]
        topic_slug = slugify(category)
        subtopic_slug = slugify(document)
        topic_key = (domain, topic_slug)
        if topic_key not in seen_topics:
            seen_topics.add(topic_key)
            topic_rows.append(
                {
                    "domain": domain,
                    "topic": topic_slug,
                    "subtopic": None,
                    "description": f"{category} — {domain_display}",
                }
            )
        pair_key = (domain, topic_slug, subtopic_slug)
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            pair_rows.append(
                {
                    "domain": domain,
                    "topic": topic_slug,
                    "subtopic": subtopic_slug,
                    "description": f"{document} — {category} · {domain_display}",
                }
            )
    return topic_rows + pair_rows


def plan_migration(
    dataset: str, grounding: dict, lookup: dict[tuple[str, str], str]
) -> dict:
    """Compute the conversation-domain + segment-relabel plan without writing.

    Returns a dict with ``conversation_domains`` (``[{id, domain}]`` for every
    conversation carrying a grounding entry), ``segment_updates``
    (``[{segment_id, topic, subtopic}]`` for every ``source='gold'`` segment),
    ``per_domain`` (domain code -> relabelled count), ``general`` (segments landing
    in a "General" category), ``all_null`` (spans with no grounded turn),
    ``unmapped`` (grounded documents absent from the nav map) and ``missing``
    (gold segments whose conversation has no grounding entry, skipped).
    """
    dialogues = grounding["dialogues"]
    pool = db.get_pool()
    with pool.connection() as conn:
        convs = conn.execute(
            "SELECT id, ext_id FROM conversation WHERE dataset = %s ORDER BY ext_id",
            (dataset,),
        ).fetchall()
        segs = conn.execute(
            "SELECT s.id, s.message_indices, c.ext_id FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'gold' "
            "ORDER BY c.ext_id, s.id",
            (dataset,),
        ).fetchall()

    conversation_domains: list[dict] = []
    for conv in convs:
        entry = dialogues.get(conv["ext_id"])
        if entry is not None:
            conversation_domains.append({"id": conv["id"], "domain": entry["domain"]})

    segment_updates: list[dict] = []
    per_domain: Counter[str] = Counter()
    general = 0
    all_null = 0
    unmapped = 0
    missing = 0
    for row in segs:
        entry = dialogues.get(row["ext_id"])
        if entry is None:
            missing += 1
            continue
        domain = entry["domain"]
        topic, subtopic, is_unmapped = segment_label(
            list(row["message_indices"] or []), entry["doc_by_turn"], domain, lookup
        )
        segment_updates.append(
            {"segment_id": row["id"], "topic": topic, "subtopic": subtopic}
        )
        if is_unmapped:
            unmapped += 1
        elif subtopic is None:
            all_null += 1
        else:
            per_domain[domain] += 1
            if topic == "General":
                general += 1
    return {
        "conversation_domains": conversation_domains,
        "segment_updates": segment_updates,
        "per_domain": per_domain,
        "general": general,
        "all_null": all_null,
        "unmapped": unmapped,
        "missing": missing,
    }


def apply_migration(
    dataset: str,
    conversation_domains: list[dict],
    segment_updates: list[dict],
    taxonomy_rows: list[dict],
) -> None:
    """Apply the domain writes + segment relabel + taxonomy rebuild in one txn."""
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            for conv in conversation_domains:
                conn.execute(
                    "UPDATE conversation SET domain = %s WHERE id = %s",
                    (conv["domain"], conv["id"]),
                )
            for row in segment_updates:
                conn.execute(
                    "UPDATE segment SET bertopic_topic = %s, bertopic_subtopic = %s "
                    "WHERE id = %s",
                    (row["topic"], row["subtopic"], row["segment_id"]),
                )
            conn.execute("DELETE FROM taxonomy WHERE dataset = %s", (dataset,))
            for tax in taxonomy_rows:
                conn.execute(
                    "INSERT INTO taxonomy "
                    "(dataset, domain, kind, topic, subtopic, description) "
                    "VALUES (%s, %s, 'user', %s, %s, %s)",
                    (
                        dataset,
                        tax["domain"],
                        tax["topic"],
                        tax["subtopic"],
                        tax["description"],
                    ),
                )


def _print_plan(dataset: str, plan: dict, taxonomy_rows: list[dict]) -> None:
    topic_rows = [t for t in taxonomy_rows if t["subtopic"] is None]
    pair_rows = [t for t in taxonomy_rows if t["subtopic"] is not None]
    per_domain = plan["per_domain"]
    print(f"dataset={dataset}")
    print(f"conversations to set domain: {len(plan['conversation_domains'])}")
    print(f"gold segments to relabel: {len(plan['segment_updates'])}")
    print("per-domain relabelled:")
    for domain in sorted(per_domain):
        print(f"  {DOMAIN_DISPLAY.get(domain, domain)} ({domain}): {per_domain[domain]}")
    print(f"General-category segments: {plan['general']}")
    print(f"all-null segments (NULL/NULL): {plan['all_null']}")
    if plan["unmapped"]:
        print(f"UNMAPPED documents (no nav category): {plan['unmapped']}")
    if plan["missing"]:
        print(f"gold segments with no grounding (skipped): {plan['missing']}")
    print(
        f"taxonomy rebuild: {len(topic_rows)} topics + {len(pair_rows)} pairs "
        f"= {len(taxonomy_rows)} rows"
    )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate to the domain-scoped taxonomy v2."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--grounding", type=Path, required=True)
    parser.add_argument("--nav-map", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="apply the relabel + taxonomy rebuild (default is a dry run).",
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
    nav_map = json.loads(args.nav_map.read_text(encoding="utf-8"))
    lookup = build_category_lookup(nav_map)
    taxonomy_rows = build_taxonomy_rows(nav_map)

    try:
        plan = plan_migration(args.dataset, grounding, lookup)
        _print_plan(args.dataset, plan, taxonomy_rows)
        if not args.execute:
            print("dry run: no rows written (pass --execute to apply)")
            return 0
        if plan["unmapped"]:
            print(
                f"ABORT: {plan['unmapped']} segment(s) reference a document with no "
                "nav category; fix analysis/nav_category_map.json first."
            )
            return 1
        reviewed = db.reviewed_base_segment_ids(args.dataset)
        if reviewed and not args.force:
            print(
                f"ABORT: {len(reviewed)} segment(s) already human-reviewed; "
                "pass --force to relabel anyway."
            )
            return 1
        apply_migration(
            args.dataset,
            plan["conversation_domains"],
            plan["segment_updates"],
            taxonomy_rows,
        )
        print(
            f"executed: set domain on {len(plan['conversation_domains'])} "
            f"conversations, relabelled {len(plan['segment_updates'])} gold "
            f"segments, rebuilt taxonomy with {len(taxonomy_rows)} rows."
        )
    finally:
        db.reset_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
