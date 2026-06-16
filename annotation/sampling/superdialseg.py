"""Deterministic stratified sampler for the SuperDialseg test split.

Selects ``N`` dialogues (decision #72: N=250 of 1,322 test dialogues) stratified
by *segment-count* bucket (``1-2`` / ``3`` / ``4`` / ``5+``) crossed with a
*turn-length* bucket (``short`` / ``med`` / ``long`` via tertiles of the turn
count over the sampled population), then writes a worklist assigning each
dialogue to ``labeler_a`` / ``labeler_b`` with a 50-dialogue double-labeled
overlap for inter-annotator agreement.

Everything is pure Python and deterministic: the only randomness is a
``random.Random(seed)`` (default ``seed=20260616``), so re-running with the same
seed and corpus yields a byte-identical worklist. Segment counts come from
:meth:`pipeline.adapters.superdialseg.SuperDialsegLoader.gold_segments`; the
gold dialogues stream from :func:`annotation.ingest.sources.superdialseg_stream`.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from pipeline.adapters.superdialseg import SuperDialsegLoader

DEFAULT_N = 250
DEFAULT_OVERLAP = 50
DEFAULT_SEED = 20260616
DEFAULT_OUT = Path(__file__).resolve().parent / "worklist_superdialseg.json"

LABELER_A = "labeler_a"
LABELER_B = "labeler_b"

_LOADER = SuperDialsegLoader()


def _segment_count(dialogue: dict) -> int:
    """Number of gold topical segments in a dialogue (maximal segment_id runs)."""
    return len(_LOADER.gold_segments(dialogue))


def _turn_count(dialogue: dict) -> int:
    """Number of utterances (turns) in a dialogue."""
    return len(dialogue.get("utterances") or [])


def _seg_bucket(seg_count: int) -> str:
    """Bucket a segment count into ``1-2`` / ``3`` / ``4`` / ``5+``."""
    if seg_count <= 2:
        return "1-2"
    if seg_count == 3:
        return "3"
    if seg_count == 4:
        return "4"
    return "5+"


def _len_tertiles(dialogues: list[dict]) -> tuple[int, int]:
    """Return the (lower, upper) turn-count cut points splitting into tertiles.

    A dialogue is ``short`` when ``turns <= lower``, ``long`` when
    ``turns > upper``, and ``med`` otherwise. Computed over the given population
    so the buckets adapt to the corpus rather than to magic constants.
    """
    counts = sorted(_turn_count(d) for d in dialogues)
    if not counts:
        return (0, 0)
    lower = counts[len(counts) // 3]
    upper = counts[(2 * len(counts)) // 3]
    return (lower, upper)


def _len_bucket(turn_count: int, tertiles: tuple[int, int]) -> str:
    """Bucket a turn count into ``short`` / ``med`` / ``long`` via tertile cuts."""
    lower, upper = tertiles
    if turn_count <= lower:
        return "short"
    if turn_count > upper:
        return "long"
    return "med"


def dialogue_strata(
    dialogue: dict, tertiles: tuple[int, int] = (0, 0)
) -> tuple[str, str]:
    """Return ``(seg_bucket, len_bucket)`` for one dialogue.

    ``seg_bucket`` is self-contained; ``len_bucket`` depends on the population's
    turn-count ``tertiles`` (see :func:`_len_tertiles`). With the default
    ``tertiles`` every dialogue lands in ``long`` — callers that need the
    population-relative bucket pass the tertiles from :func:`_len_tertiles`.
    """
    return (
        _seg_bucket(_segment_count(dialogue)),
        _len_bucket(_turn_count(dialogue), tertiles),
    )


def _allocate(strata_sizes: dict[tuple[str, str], int], n: int) -> dict:
    """Proportionally allocate ``n`` slots across populated strata.

    Every populated stratum gets a floor of 1, allocation is proportional to
    stratum size, and any rounding remainder is handed to the largest strata
    (ties broken by stratum key for determinism). The total never exceeds the
    available population per stratum.
    """
    population = sum(strata_sizes.values())
    if population <= n:
        return dict(strata_sizes)

    keys = sorted(strata_sizes)
    alloc = {k: 1 for k in keys}
    remaining = n - len(keys)

    raw = {k: (strata_sizes[k] / population) * n for k in keys}
    extra = {k: max(0, int(raw[k]) - 1) for k in keys}
    for k in keys:
        give = min(extra[k], remaining, strata_sizes[k] - alloc[k])
        give = max(0, give)
        alloc[k] += give
        remaining -= give

    order = sorted(keys, key=lambda k: (-strata_sizes[k], k))
    while remaining > 0:
        progressed = False
        for k in order:
            if remaining <= 0:
                break
            if alloc[k] < strata_sizes[k]:
                alloc[k] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    return alloc


def _select(dialogues: list[dict], n: int, seed: int) -> list[tuple[dict, str, str]]:
    """Select ``n`` dialogues stratified by (seg_bucket, len_bucket).

    Returns ``[(dialogue, seg_bucket, len_bucket), ...]`` in a deterministic
    order (stratum key, then the seeded within-stratum shuffle). When the
    population is at or below ``n``, all dialogues are returned.
    """
    tertiles = _len_tertiles(dialogues)
    by_stratum: dict[tuple[str, str], list[dict]] = {}
    for d in dialogues:
        key = dialogue_strata(d, tertiles)
        by_stratum.setdefault(key, []).append(d)

    sizes = {k: len(v) for k, v in by_stratum.items()}
    alloc = _allocate(sizes, n)

    selected: list[tuple[dict, str, str]] = []
    for key in sorted(by_stratum):
        bucket = list(by_stratum[key])
        rng = random.Random(f"{seed}:{key[0]}:{key[1]}")
        rng.shuffle(bucket)
        take = min(alloc.get(key, 0), len(bucket))
        for d in bucket[:take]:
            selected.append((d, key[0], key[1]))
    return selected


def build_worklist(
    dialogues: list[dict],
    n: int = DEFAULT_N,
    overlap: int = DEFAULT_OVERLAP,
    seed: int = DEFAULT_SEED,
) -> list[dict]:
    """Build a deterministic stratified worklist over SuperDialseg dialogues.

    Selects ``n`` distinct dialogues (or all of them when the population is
    smaller than ``n``), stratified by segment-count x turn-length buckets with
    proportional, floor>=1 allocation. ``overlap`` of the selected dialogues are
    double-labeled (``assigned_to == [labeler_a, labeler_b]``, ``is_overlap``);
    the remainder is split as evenly as possible between the two labelers so each
    ends within one dialogue of the other.

    Each row is ``{dialogue_id, seg_bucket, len_bucket, assigned_to, is_overlap}``.
    Deterministic in ``seed``: same seed + corpus -> identical worklist.
    """
    selected = _select(dialogues, n, seed)
    chosen = min(n, len(selected))
    overlap_n = min(overlap, chosen)

    rng = random.Random(f"{seed}:assign")
    order = list(range(len(selected)))
    rng.shuffle(order)
    overlap_idx = set(order[:overlap_n])

    solo = [i for i in order if i not in overlap_idx]
    half = len(solo) // 2
    a_idx = set(solo[:half])

    rows: list[dict] = []
    for i, (dialogue, seg_bucket, len_bucket) in enumerate(selected):
        is_overlap = i in overlap_idx
        if is_overlap:
            assigned_to = [LABELER_A, LABELER_B]
        elif i in a_idx:
            assigned_to = [LABELER_A]
        else:
            assigned_to = [LABELER_B]
        rows.append(
            {
                "dialogue_id": str(dialogue["dialogue_id"]),
                "seg_bucket": seg_bucket,
                "len_bucket": len_bucket,
                "assigned_to": assigned_to,
                "is_overlap": is_overlap,
            }
        )
    rows.sort(key=lambda r: r["dialogue_id"])
    return rows


def _main(argv: list[str] | None = None) -> int:
    from annotation.ingest.sources import superdialseg_stream

    parser = argparse.ArgumentParser(
        description="Build a deterministic stratified SuperDialseg worklist."
    )
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    dialogues = list(superdialseg_stream())
    worklist = build_worklist(
        dialogues, n=args.n, overlap=args.overlap, seed=args.seed
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(worklist, indent=2) + "\n", encoding="utf-8")
    n_overlap = sum(r["is_overlap"] for r in worklist)
    print(f"wrote {len(worklist)} rows ({n_overlap} overlap) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
