"""Load a BERTopic label-map JSON into the annotation ``taxonomy`` table.

The prod taxonomy starts empty, so annotators free-type topics and the labels
fragment (bad for inter-annotator agreement). This CLI seeds the canonical
options from ``analysis/bertopic_label_map.json`` — the human-cleaned BERTopic
labels — normalizing every topic/subtopic to SQL-slug style via the shared
``annotation.backend.slug.slugify`` and stashing the raw keyword dumps in
``description`` for provenance. Run::

    python -m annotation.load_taxonomy --dataset superdialseg \\
        --map-file analysis/bertopic_label_map.json [--execute]

Input shape (see the real file)::

    {"dataset": ..., "pairs": [{"topic_raw", "subtopic_raw", "topic", "subtopic"}, ...]}

Each distinct clean topic becomes one ``(dataset, kind='user', slug, NULL)`` row
(description = the display label); each pair becomes one ``(dataset, 'user',
topic_slug, subtopic_slug)`` row (description = display labels + raw keywords).
Upsert is idempotent via ``taxonomy_option_uidx`` (NULLS NOT DISTINCT), so
re-runs only refresh descriptions. Default is a dry-run that writes nothing;
``--execute`` commits in one transaction. The DSN is read from
``EB1_ANNOTATION_DSN`` (see ``annotation.backend.config``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from annotation.backend import db
from annotation.backend.slug import slugify


def _pair_description(pair: dict) -> str:
    return (
        f"{pair['topic']} / {pair['subtopic']} — keywords: "
        f"{pair['topic_raw']} | {pair['subtopic_raw']}"
    )


def build_taxonomy_rows(payload: dict, dataset: str) -> list[dict]:
    """Transform a label-map payload into ``taxonomy`` rows for ``dataset``.

    Returns the topic-only rows (subtopic ``None``) in first-seen order followed
    by one row per pair. Raises ``ValueError`` if the file's ``dataset`` does not
    match ``dataset`` (fail loudly rather than cross-load).
    """
    file_dataset = payload.get("dataset")
    if file_dataset != dataset:
        raise ValueError(
            f"map file dataset {file_dataset!r} does not match --dataset {dataset!r}"
        )

    pairs = payload.get("pairs", [])
    topic_rows: list[dict] = []
    pair_rows: list[dict] = []
    seen_topics: set[str] = set()

    for pair in pairs:
        topic_slug = slugify(pair["topic"])
        if topic_slug not in seen_topics:
            seen_topics.add(topic_slug)
            topic_rows.append(
                {
                    "dataset": dataset,
                    "kind": "user",
                    "topic": topic_slug,
                    "subtopic": None,
                    "description": pair["topic"],
                }
            )
        pair_rows.append(
            {
                "dataset": dataset,
                "kind": "user",
                "topic": topic_slug,
                "subtopic": slugify(pair["subtopic"]),
                "description": _pair_description(pair),
            }
        )

    return topic_rows + pair_rows


def _existing_keys(dataset: str) -> set[tuple[str | None, str | None]]:
    pool = db.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT topic, subtopic FROM taxonomy WHERE dataset = %s AND kind = 'user'",
            (dataset,),
        ).fetchall()
    return {(r["topic"], r["subtopic"]) for r in rows}


def _upsert(rows: list[dict]) -> None:
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            for row in rows:
                conn.execute(
                    "INSERT INTO taxonomy (dataset, kind, topic, subtopic, description) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (dataset, kind, topic, subtopic) "
                    "DO UPDATE SET description = EXCLUDED.description",
                    (
                        row["dataset"],
                        row["kind"],
                        row["topic"],
                        row["subtopic"],
                        row["description"],
                    ),
                )


def _print_plan(rows: list[dict], existing: set[tuple[str | None, str | None]]) -> None:
    topics = [r for r in rows if r["subtopic"] is None]
    pairs = [r for r in rows if r["subtopic"] is not None]
    inserts = sum(1 for r in rows if (r["topic"], r["subtopic"]) not in existing)
    updates = len(rows) - inserts
    print(f"topics: {len(topics)}  pairs: {len(pairs)}  rows: {len(rows)}")
    print(f"estimated inserts: {inserts}  updates: {updates}")
    print("sample:")
    for r in rows[:5]:
        subtopic = r["subtopic"] if r["subtopic"] is not None else "-"
        print(f"  {r['topic']} / {subtopic}  ::  {r['description']}")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load a BERTopic label-map JSON into the annotation taxonomy."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--map-file", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="write the upsert (default is a dry-run that writes nothing).",
    )
    args = parser.parse_args(argv)

    payload = json.loads(args.map_file.read_text(encoding="utf-8"))
    rows = build_taxonomy_rows(payload, args.dataset)

    try:
        existing = _existing_keys(args.dataset)
        if not args.execute:
            print(f"DRY RUN ({args.map_file}); pass --execute to write.")
            _print_plan(rows, existing)
            return 0
        _upsert(rows)
        topics = sum(1 for r in rows if r["subtopic"] is None)
        pairs = len(rows) - topics
        print(f"upserted {len(rows)} taxonomy rows ({topics} topics, {pairs} pairs) "
              f"into {args.dataset}.")
    finally:
        db.reset_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
