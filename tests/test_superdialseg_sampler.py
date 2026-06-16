"""Tests for the deterministic stratified SuperDialseg worklist sampler.

Uses a SMALL synthetic SuperDialseg-shaped population (normalized
``{dialogue_id, utterances:[{speaker, text, segment_id}]}`` dicts) — the real
gold release is large and not committed. The synthetic dialogues are shaped so
the loader's ``gold_segments`` recovers a controllable number of segments and
the population spans several segment-count x turn-length strata.
"""

from __future__ import annotations

from collections import Counter

import pytest

from annotation.sampling.superdialseg import (
    LABELER_A,
    LABELER_B,
    build_worklist,
    dialogue_strata,
)


def _make_dialogue(dialogue_id: str, n_segments: int, n_turns: int) -> dict:
    """Build a synthetic SuperDialseg dialogue with the requested shape.

    ``n_turns`` utterances are split into ``n_segments`` consecutive maximal
    same-``segment_id`` runs, so the loader recovers exactly ``n_segments``
    gold segments.
    """
    assert 1 <= n_segments <= n_turns
    utterances = []
    for i in range(n_turns):
        segment_id = min(i * n_segments // n_turns, n_segments - 1)
        utterances.append(
            {
                "speaker": "User" if i % 2 == 0 else "Agent",
                "text": f"turn {i}",
                "segment_id": segment_id,
            }
        )
    return {"dialogue_id": dialogue_id, "utterances": utterances}


def _population() -> list[dict]:
    """A synthetic population spanning multiple strata, ~larger than the N used."""
    dialogues: list[dict] = []
    idx = 0
    for n_segments in (1, 2, 3, 4, 5, 7):
        for n_turns in (8, 12, 18):
            for _ in range(6):
                dialogues.append(
                    _make_dialogue(f"dlg-{idx:04d}", n_segments, n_turns)
                )
                idx += 1
    return dialogues


def test_segment_runs_recovered_by_loader():
    from pipeline.adapters.superdialseg import SuperDialsegLoader

    loader = SuperDialsegLoader()
    assert len(loader.gold_segments(_make_dialogue("d", 4, 12))) == 4
    assert len(loader.gold_segments(_make_dialogue("d", 1, 8))) == 1


def test_dialogue_strata_seg_buckets():
    assert dialogue_strata(_make_dialogue("d", 1, 12))[0] == "1-2"
    assert dialogue_strata(_make_dialogue("d", 2, 12))[0] == "1-2"
    assert dialogue_strata(_make_dialogue("d", 3, 12))[0] == "3"
    assert dialogue_strata(_make_dialogue("d", 4, 12))[0] == "4"
    assert dialogue_strata(_make_dialogue("d", 7, 12))[0] == "5+"


def test_len_bucket_uses_tertiles():
    short = dialogue_strata(_make_dialogue("d", 1, 8), tertiles=(10, 14))
    med = dialogue_strata(_make_dialogue("d", 1, 12), tertiles=(10, 14))
    long = dialogue_strata(_make_dialogue("d", 1, 18), tertiles=(10, 14))
    assert short[1] == "short"
    assert med[1] == "med"
    assert long[1] == "long"


def test_build_worklist_selects_exactly_n_distinct():
    pop = _population()
    n = 60
    wl = build_worklist(pop, n=n, overlap=12, seed=20260616)
    assert len(wl) == n
    ids = [r["dialogue_id"] for r in wl]
    assert len(set(ids)) == n
    pop_ids = {d["dialogue_id"] for d in pop}
    assert set(ids) <= pop_ids


def test_row_shape_and_overlap_assignment():
    wl = build_worklist(_population(), n=60, overlap=12, seed=20260616)
    for r in wl:
        assert set(r) == {
            "dialogue_id",
            "seg_bucket",
            "len_bucket",
            "assigned_to",
            "is_overlap",
        }
        assert isinstance(r["assigned_to"], list)
    overlap_rows = [r for r in wl if r["is_overlap"]]
    assert len(overlap_rows) == 12
    for r in overlap_rows:
        assert r["assigned_to"] == [LABELER_A, LABELER_B]
    for r in wl:
        if not r["is_overlap"]:
            assert len(r["assigned_to"]) == 1
            assert r["assigned_to"][0] in (LABELER_A, LABELER_B)


def test_labeler_totals_within_one():
    wl = build_worklist(_population(), n=60, overlap=12, seed=20260616)
    counts = Counter()
    for r in wl:
        for who in r["assigned_to"]:
            counts[who] += 1
    a, b = counts[LABELER_A], counts[LABELER_B]
    assert abs(a - b) <= 1
    solo = sum(1 for r in wl if not r["is_overlap"])
    assert (a - 12) + (b - 12) == solo


def test_proportional_allocation_floor_one():
    pop = _population()
    wl = build_worklist(pop, n=60, overlap=12, seed=20260616)
    from annotation.sampling.superdialseg import _len_tertiles

    tertiles = _len_tertiles(pop)
    pop_strata = {dialogue_strata(d, tertiles) for d in pop}
    wl_strata = {(r["seg_bucket"], r["len_bucket"]) for r in wl}
    assert wl_strata == pop_strata

    sel_counts = Counter((r["seg_bucket"], r["len_bucket"]) for r in wl)
    pop_counts = Counter(dialogue_strata(d, tertiles) for d in pop)
    biggest_pop = max(pop_counts, key=lambda k: pop_counts[k])
    smallest_pop = min(pop_counts, key=lambda k: pop_counts[k])
    assert sel_counts[biggest_pop] >= sel_counts[smallest_pop]
    for k in pop_strata:
        assert sel_counts[k] >= 1


def test_determinism_same_seed_identical():
    pop = _population()
    a = build_worklist(pop, n=60, overlap=12, seed=20260616)
    b = build_worklist(pop, n=60, overlap=12, seed=20260616)
    assert a == b


def test_different_seed_differs():
    pop = _population()
    a = build_worklist(pop, n=60, overlap=12, seed=20260616)
    b = build_worklist(pop, n=60, overlap=12, seed=11111111)
    assert a != b


def test_population_smaller_than_n_returns_all():
    pop = _population()[:20]
    wl = build_worklist(pop, n=250, overlap=8, seed=20260616)
    assert len(wl) == len(pop)
    assert {r["dialogue_id"] for r in wl} == {d["dialogue_id"] for d in pop}
    assert sum(r["is_overlap"] for r in wl) == 8


@pytest.mark.parametrize("seed", [1, 42, 20260616])
def test_overlap_count_exact(seed):
    wl = build_worklist(_population(), n=60, overlap=12, seed=seed)
    assert sum(r["is_overlap"] for r in wl) == 12
