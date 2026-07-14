"""Deterministically remap an EXISTING worklist from labeler slots to real people.

The original sampler (``annotation.sampling.superdialseg``) assigns dialogues to
placeholder slots (``labeler_a`` / ``labeler_b``). Once the real annotators are
known, this tool rewrites only the ``worklist.labeler`` column — row count,
``ext_id``, ``is_overlap`` and the strata buckets are preserved — so the site's
``/labelers`` endpoint and per-labeler queues pick up the real identities with no
schema or data-shape change::

    python -m annotation.sampling.remap_labelers \\
        --dataset superdialseg --labelers a@x.com,b@x.com,c@x.com [--execute]

The assignment (:func:`assign_labelers`) is a pure, deterministic function — no
RNG, no DB — so the procedure is reproducible for the paper's methodology:

- Rows are grouped by ``ext_id``. A dialogue with 2+ rows is an OVERLAP dialogue
  (double-labeled for inter-annotator agreement); 1 row is a SINGLE.
- Overlap dialogues, in sorted-``ext_id`` order, go to labeler PAIRS — all
  2-combinations of the sorted labeler list, rotated round-robin (3 labelers ->
  AB, AC, BC repeating) so every pair gets a pairwise-kappa sample. A dialogue's
  rows (ordered by row id) take the pair's two labelers.
- Single dialogues, in sorted-``ext_id`` order, each go to the labeler with the
  lowest running assignment count (ties broken by sorted labeler order), so final
  per-labeler loads are balanced within one.

Works for any ``N >= 2`` labelers. A dialogue with more rows than the pair size
(should never happen) fails loudly. Default is a dry run; ``--execute`` applies
all UPDATEs in a single transaction against ``EB1_ANNOTATION_DSN``.
"""

from __future__ import annotations

import argparse
import itertools
from collections import defaultdict

from annotation.backend import db

DEFAULT_DATASET = "superdialseg"


def _group_by_ext_id(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by ``ext_id``, each group ordered by row ``id``."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row["ext_id"])].append(row)
    for group in groups.values():
        group.sort(key=lambda r: r["id"])
    return dict(groups)


def assign_labelers(rows: list[dict], labelers: list[str]) -> dict[object, str]:
    """Return ``{row_id: labeler}`` remapping ``rows`` onto ``labelers``.

    Pure and deterministic (see the module docstring). ``rows`` is any iterable of
    ``{id, ext_id}`` dicts; ``labelers`` is the real identity list (``N >= 2``).
    Raises ``ValueError`` for fewer than two labelers or a dialogue with more rows
    than a labeler pair can carry.
    """
    labelers = sorted(labelers)
    if len(labelers) < 2:
        raise ValueError("need at least 2 labelers to remap a worklist")
    pairs = list(itertools.combinations(labelers, 2))

    groups = _group_by_ext_id(rows)
    overlap_ext_ids = sorted(e for e, g in groups.items() if len(g) >= 2)
    single_ext_ids = sorted(e for e, g in groups.items() if len(g) == 1)

    assignment: dict[object, str] = {}
    counts = {labeler: 0 for labeler in labelers}

    for i, ext_id in enumerate(overlap_ext_ids):
        group = groups[ext_id]
        pair = pairs[i % len(pairs)]
        if len(group) > len(pair):
            raise ValueError(
                f"dialogue {ext_id!r} has {len(group)} rows but pair size is "
                f"{len(pair)}; overlap dialogues cannot exceed the pair size"
            )
        for row, labeler in zip(group, pair):
            assignment[row["id"]] = labeler
            counts[labeler] += 1

    for ext_id in single_ext_ids:
        row = groups[ext_id][0]
        labeler = min(labelers, key=lambda lab: (counts[lab], lab))
        assignment[row["id"]] = labeler
        counts[labeler] += 1

    return assignment


def plan_summary(
    rows: list[dict], labelers: list[str], assignment: dict[object, str]
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    """Return ``(per_labeler_totals, per_pair_overlap_counts)`` for a plan."""
    labelers = sorted(labelers)
    totals = {labeler: 0 for labeler in labelers}
    for labeler in assignment.values():
        totals[labeler] += 1

    pair_counts = {pair: 0 for pair in itertools.combinations(labelers, 2)}
    for group in _group_by_ext_id(rows).values():
        if len(group) < 2:
            continue
        pair = tuple(sorted(assignment[row["id"]] for row in group))
        if pair in pair_counts:
            pair_counts[pair] += 1
    return totals, pair_counts


def _fetch_rows(dataset: str) -> list[dict]:
    """Read the dataset's worklist rows (id, ext_id, labeler, is_overlap)."""
    pool = db.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, ext_id, labeler, is_overlap FROM worklist "
            "WHERE dataset = %s ORDER BY ext_id, id",
            (dataset,),
        ).fetchall()
    return [dict(r) for r in rows]


def apply_assignment(dataset: str, assignment: dict[object, str]) -> int:
    """UPDATE only the ``labeler`` column by row id, in one transaction."""
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            for row_id, labeler in assignment.items():
                conn.execute(
                    "UPDATE worklist SET labeler = %s WHERE id = %s AND dataset = %s",
                    (labeler, row_id, dataset),
                )
    return len(assignment)


def _print_plan(
    dataset: str,
    rows: list[dict],
    labelers: list[str],
    assignment: dict[object, str],
) -> None:
    totals, pair_counts = plan_summary(rows, labelers, assignment)
    groups = _group_by_ext_id(rows)
    n_overlap = sum(1 for g in groups.values() if len(g) >= 2)
    n_single = sum(1 for g in groups.values() if len(g) == 1)

    print(f"dataset={dataset}  labelers={sorted(labelers)}")
    print(f"dialogues: {len(groups)} ({n_overlap} overlap, {n_single} single)")
    print(f"worklist rows: {len(rows)}")

    print("per-labeler totals:")
    for labeler in sorted(labelers):
        print(f"  {labeler}: {totals[labeler]}")

    print("per-pair overlap counts:")
    for pair, count in pair_counts.items():
        print(f"  {pair[0]} + {pair[1]}: {count}")

    print("example assignments:")
    by_id = {row["id"]: row for row in rows}
    for row_id in list(assignment)[:6]:
        row = by_id.get(row_id, {})
        print(
            f"  ext_id={row.get('ext_id')!r} row_id={row_id} "
            f"-> {assignment[row_id]}"
        )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically remap a worklist's labelers to N real people."
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument(
        "--labelers",
        required=True,
        help="comma-separated real annotator identities (>=2)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="apply the remap (default is a dry run that writes nothing)",
    )
    args = parser.parse_args(argv)

    labelers = [x.strip() for x in args.labelers.split(",") if x.strip()]
    if len(labelers) < 2:
        parser.error("need at least 2 labelers (comma-separated)")

    try:
        rows = _fetch_rows(args.dataset)
        if not rows:
            print(f"no worklist rows for dataset {args.dataset!r}; nothing to remap")
            return 1
        assignment = assign_labelers(rows, labelers)
        _print_plan(args.dataset, rows, labelers, assignment)
        if args.execute:
            written = apply_assignment(args.dataset, assignment)
            print(f"executed: updated labeler on {written} worklist rows")
        else:
            print("dry run: no rows written (pass --execute to apply)")
    finally:
        db.reset_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
