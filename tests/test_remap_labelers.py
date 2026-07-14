"""Tests for the deterministic worklist labeler remap.

The core is a pure assignment function (:func:`assign_labelers`) exercised without
a DB: balance, pair coverage, determinism, no self-overlap, and the ``N=2``
degenerate case. One DSN-gated round-trip proves ``--execute`` rewrites only the
``labeler`` column while preserving ext_ids / is_overlap; it skips when
``EB1_ANNOTATION_DSN`` is unset::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation
    uv run pytest tests/test_remap_labelers.py -q
"""

from __future__ import annotations

import os

import pytest

from annotation.sampling import remap_labelers as rl

LABELERS3 = ["a@x.com", "b@x.com", "c@x.com"]


def _shape(n_single: int, n_overlap: int) -> list[dict]:
    """Build worklist rows: ``n_single`` 1-row + ``n_overlap`` 2-row dialogues."""
    rows: list[dict] = []
    row_id = 1
    for i in range(n_single):
        rows.append({"id": row_id, "ext_id": f"single_{i:04d}"})
        row_id += 1
    for i in range(n_overlap):
        for _ in range(2):
            rows.append({"id": row_id, "ext_id": f"overlap_{i:04d}"})
            row_id += 1
    return rows


def _by_ext(rows: list[dict], assignment: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["ext_id"], []).append(assignment[row["id"]])
    return out


def test_balanced_totals_for_250_50_shape():
    rows = _shape(200, 50)
    assignment = rl.assign_labelers(rows, LABELERS3)
    totals, _ = rl.plan_summary(rows, LABELERS3, assignment)
    assert sum(totals.values()) == len(rows) == 300
    assert max(totals.values()) - min(totals.values()) <= 1
    for total in totals.values():
        assert abs(total - 100) <= 1


def test_all_pairs_used_and_roughly_even():
    rows = _shape(200, 50)
    assignment = rl.assign_labelers(rows, LABELERS3)
    _, pair_counts = rl.plan_summary(rows, LABELERS3, assignment)
    assert len(pair_counts) == 3
    assert sum(pair_counts.values()) == 50
    for count in pair_counts.values():
        assert count in (16, 17)


def test_deterministic_same_input_same_output():
    rows = _shape(200, 50)
    assert rl.assign_labelers(rows, LABELERS3) == rl.assign_labelers(rows, LABELERS3)
    assert rl.assign_labelers(rows, LABELERS3) == rl.assign_labelers(
        list(reversed(rows)), LABELERS3
    )


def test_labeler_order_independent():
    rows = _shape(200, 50)
    assert rl.assign_labelers(rows, LABELERS3) == rl.assign_labelers(
        rows, list(reversed(LABELERS3))
    )


def test_overlap_rows_never_share_a_labeler():
    rows = _shape(50, 50)
    assignment = rl.assign_labelers(rows, LABELERS3)
    for ext_id, labs in _by_ext(rows, assignment).items():
        if ext_id.startswith("overlap_"):
            assert len(labs) == 2
            assert labs[0] != labs[1]


def test_n2_degenerate_case():
    labelers = ["a@x.com", "b@x.com"]
    rows = _shape(200, 50)
    assignment = rl.assign_labelers(rows, labelers)
    totals, pair_counts = rl.plan_summary(rows, labelers, assignment)
    assert max(totals.values()) - min(totals.values()) <= 1
    assert list(pair_counts.values()) == [50]
    for ext_id, labs in _by_ext(rows, assignment).items():
        if ext_id.startswith("overlap_"):
            assert set(labs) == set(labelers)


def test_too_few_labelers_raises():
    with pytest.raises(ValueError):
        rl.assign_labelers(_shape(2, 0), ["only@x.com"])


def test_oversized_overlap_fails_loudly():
    rows = [
        {"id": 1, "ext_id": "trio"},
        {"id": 2, "ext_id": "trio"},
        {"id": 3, "ext_id": "trio"},
    ]
    with pytest.raises(ValueError):
        rl.assign_labelers(rows, LABELERS3)


# ---------------------------------------------------------------------------
# DSN-gated round-trip (skips without EB1_ANNOTATION_DSN)
# ---------------------------------------------------------------------------

pytestmark_pg = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

DATASET = "superdialseg"

_SEED_WORKLIST = [
    {
        "dialogue_id": "rmtest_solo_a",
        "seg_bucket": "1-2",
        "len_bucket": "short",
        "assigned_to": ["labeler_a"],
        "is_overlap": False,
    },
    {
        "dialogue_id": "rmtest_solo_b",
        "seg_bucket": "3",
        "len_bucket": "med",
        "assigned_to": ["labeler_b"],
        "is_overlap": False,
    },
    {
        "dialogue_id": "rmtest_overlap",
        "seg_bucket": "5+",
        "len_bucket": "long",
        "assigned_to": ["labeler_a", "labeler_b"],
        "is_overlap": True,
    },
]


def _wipe(db_) -> None:
    pool = db_.get_pool()
    with pool.connection() as conn:
        conn.execute(
            "DELETE FROM worklist WHERE dataset = %s AND ext_id LIKE 'rmtest%%'",
            (DATASET,),
        )


@pytest.fixture()
def _db():
    from annotation.backend import db

    db.reset_pool()
    db.apply_schema()
    db.ensure_dataset(DATASET)
    _wipe(db)
    yield db
    _wipe(db)
    db.reset_pool()


def _rmtest_rows(db_) -> list[dict]:
    pool = db_.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, ext_id, labeler, is_overlap FROM worklist "
            "WHERE dataset = %s AND ext_id LIKE 'rmtest%%' ORDER BY ext_id, id",
            (DATASET,),
        ).fetchall()
    return [dict(r) for r in rows]


@pytestmark_pg
def test_execute_rewrites_only_labeler_column(_db):
    _db.load_worklist(DATASET, _SEED_WORKLIST)
    before = _rmtest_rows(_db)
    assert len(before) == 4

    assignment = rl.assign_labelers(before, LABELERS3)
    rl.apply_assignment(DATASET, assignment)

    after = _rmtest_rows(_db)
    # ext_ids, is_overlap, and row identities are preserved; only labeler changes.
    assert {r["id"] for r in after} == {r["id"] for r in before}
    assert {r["ext_id"] for r in after} == {r["ext_id"] for r in before}
    assert {(r["id"], r["is_overlap"]) for r in after} == {
        (r["id"], r["is_overlap"]) for r in before
    }
    new_labelers = {r["labeler"] for r in after}
    assert new_labelers <= set(LABELERS3)
    assert new_labelers.isdisjoint({"labeler_a", "labeler_b"})

    overlap_labs = [r["labeler"] for r in after if r["ext_id"] == "rmtest_overlap"]
    assert len(overlap_labs) == 2
    assert overlap_labs[0] != overlap_labs[1]
