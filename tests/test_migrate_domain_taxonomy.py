"""Tests for the taxonomy v2 domain migration (``annotation.migrate_domain_taxonomy``).

The lookup + assembly logic is pure and always runs. The DB round-trip is gated on
``EB1_ANNOTATION_DSN`` like the rest of the annotation suite::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_test
    uv run pytest tests/test_migrate_domain_taxonomy.py -q
"""

from __future__ import annotations

import json
import os

import pytest

from annotation import migrate_domain_taxonomy as m

NAV_MAP = {
    "categories": {"ssa": ["Disability"], "va": ["Disability", "Health Care"]},
    "mapping": [
        {"domain": "ssa", "category": "Disability", "document": "Apply for SSDI"},
        {"domain": "ssa", "category": "General", "document": "About SSA"},
        {"domain": "va", "category": "Disability", "document": "VA Disability Comp"},
        {"domain": "va", "category": "Health Care", "document": "VA Health Enroll"},
    ],
}


def test_build_category_lookup_is_domain_scoped():
    lookup = m.build_category_lookup(NAV_MAP)
    assert lookup[("ssa", "Apply for SSDI")] == "Disability"
    assert lookup[("va", "VA Disability Comp")] == "Disability"
    # Same document string is only resolvable within its own domain.
    assert ("va", "Apply for SSDI") not in lookup


def test_segment_label_resolves_category_and_document():
    lookup = m.build_category_lookup(NAV_MAP)
    # Majority document over the span is "Apply for SSDI" -> category "Disability".
    topic, subtopic, unmapped = m.segment_label(
        [0, 1], ["Apply for SSDI", "Apply for SSDI"], "ssa", lookup
    )
    assert (topic, subtopic, unmapped) == ("Disability", "Apply for SSDI", False)


def test_segment_label_general_bucket():
    lookup = m.build_category_lookup(NAV_MAP)
    topic, subtopic, unmapped = m.segment_label([0], ["About SSA"], "ssa", lookup)
    assert (topic, subtopic, unmapped) == ("General", "About SSA", False)


def test_segment_label_all_null_span():
    lookup = m.build_category_lookup(NAV_MAP)
    assert m.segment_label([0, 1], [None, None], "ssa", lookup) == (None, None, False)


def test_segment_label_unmapped_document_is_flagged():
    lookup = m.build_category_lookup(NAV_MAP)
    topic, subtopic, unmapped = m.segment_label([0], ["Unknown Doc"], "ssa", lookup)
    assert (topic, subtopic, unmapped) == (None, "Unknown Doc", True)


def test_build_taxonomy_rows_are_domain_scoped_and_deduped():
    rows = m.build_taxonomy_rows(NAV_MAP)
    topic_rows = [r for r in rows if r["subtopic"] is None]
    pair_rows = [r for r in rows if r["subtopic"] is not None]

    # One topic row per (domain, category): ssa Disability/General + va Disability/Health Care.
    topic_keys = {(r["domain"], r["topic"]) for r in topic_rows}
    assert topic_keys == {
        ("ssa", "disability"),
        ("ssa", "general"),
        ("va", "disability"),
        ("va", "health_care"),
    }
    # "Disability" is a distinct row per domain (the collision the domain column solves).
    disability = [r for r in topic_rows if r["topic"] == "disability"]
    assert {r["domain"] for r in disability} == {"ssa", "va"}

    # One pair row per mapping entry, carrying display forms + domain provenance.
    ssa_pair = next(
        r for r in pair_rows if r["domain"] == "ssa" and r["subtopic"] == "apply_for_ssdi"
    )
    assert ssa_pair["topic"] == "disability"
    assert ssa_pair["description"] == "Apply for SSDI — Disability · Social Security"
    assert len(pair_rows) == 4


# --- DB round-trip (DSN-gated) ---------------------------------------------

pg = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

DATASET = "superdialseg"
CONV_SSA = "mdt_ssa01"
CONV_VA = "mdt_va01"


@pytest.fixture(autouse=True)
def _cleanup_superdialseg():
    """Leave the shared ``superdialseg`` dataset empty so sibling suites stay clean."""
    yield
    if not os.environ.get("EB1_ANNOTATION_DSN"):
        return
    from annotation.backend import db

    db.reset_pool()
    with db.get_pool().connection() as conn:
        conn.execute("DELETE FROM dataset WHERE name = %s", (DATASET,))
    db.reset_pool()


def _grounding() -> dict:
    return {
        "dataset": DATASET,
        "dialogues": {
            CONV_SSA: {
                "domain": "ssa",
                "doc_by_turn": ["Apply for SSDI", "Apply for SSDI", None, None],
            },
            CONV_VA: {
                "domain": "va",
                "doc_by_turn": ["VA Disability Comp", "VA Disability Comp"],
            },
        },
    }


def _seed() -> None:
    from annotation.backend import db

    db.reset_pool()
    db.apply_schema()
    # Wipe any prior superdialseg rows so each migration test runs in isolation.
    pool = db.get_pool()
    with pool.connection() as conn:
        conn.execute("DELETE FROM dataset WHERE name = %s", (DATASET,))
    db.ingest_batch(
        DATASET,
        [
            {
                "ext_id": CONV_SSA,
                "messages": [
                    {"role": "user", "content": "ssdi?"},
                    {"role": "agent", "content": "yes"},
                    {"role": "user", "content": "more"},
                    {"role": "agent", "content": "ok"},
                ],
                "gold_segments": [
                    {"message_indices": [0, 1]},
                    {"message_indices": [2, 3]},
                ],
            },
            {
                "ext_id": CONV_VA,
                "messages": [
                    {"role": "user", "content": "disability?"},
                    {"role": "agent", "content": "sure"},
                ],
                "gold_segments": [{"message_indices": [0, 1]}],
            },
        ],
    )


def _write_files(tmp_path) -> tuple[str, str]:
    gpath = tmp_path / "g.json"
    npath = tmp_path / "n.json"
    gpath.write_text(json.dumps(_grounding()), encoding="utf-8")
    npath.write_text(json.dumps(NAV_MAP), encoding="utf-8")
    return str(gpath), str(npath)


def _run(gpath: str, npath: str, *extra: str) -> int:
    return m._main(
        ["--dataset", DATASET, "--grounding", gpath, "--nav-map", npath, *extra]
    )


@pg
def test_dry_run_writes_nothing(tmp_path):
    from annotation.backend import db

    _seed()
    gpath, npath = _write_files(tmp_path)
    assert _run(gpath, npath) == 0

    db.reset_pool()
    pool = db.get_pool()
    with pool.connection() as conn:
        domains = conn.execute(
            "SELECT domain FROM conversation WHERE dataset = %s", (DATASET,)
        ).fetchall()
        labelled = conn.execute(
            "SELECT count(*) AS n FROM segment s JOIN conversation c "
            "ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.bertopic_topic IS NOT NULL",
            (DATASET,),
        ).fetchone()["n"]
        tax = conn.execute(
            "SELECT count(*) AS n FROM taxonomy WHERE dataset = %s", (DATASET,)
        ).fetchone()["n"]
    assert all(d["domain"] is None for d in domains)
    assert labelled == 0
    assert tax == 0
    db.reset_pool()


@pg
def test_execute_relabels_sets_domain_and_rebuilds_taxonomy(tmp_path):
    from annotation.backend import db

    _seed()
    gpath, npath = _write_files(tmp_path)
    assert _run(gpath, npath, "--execute") == 0

    db.reset_pool()
    pool = db.get_pool()
    with pool.connection() as conn:
        convs = {
            r["ext_id"]: r["domain"]
            for r in conn.execute(
                "SELECT ext_id, domain FROM conversation WHERE dataset = %s",
                (DATASET,),
            ).fetchall()
        }
        segs = conn.execute(
            "SELECT s.message_indices, c.ext_id, s.bertopic_topic, s.bertopic_subtopic "
            "FROM segment s JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'gold' ORDER BY c.ext_id, s.chunk_index",
            (DATASET,),
        ).fetchall()
        pred = conn.execute(
            "SELECT s.bertopic_topic FROM segment s JOIN conversation c "
            "ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'predicted'",
            (DATASET,),
        ).fetchall()
        tax = conn.execute(
            "SELECT domain, topic, subtopic FROM taxonomy WHERE dataset = %s",
            (DATASET,),
        ).fetchall()

    assert convs == {CONV_SSA: "ssa", CONV_VA: "va"}
    labels = {(r["ext_id"], tuple(r["message_indices"])): r for r in segs}
    assert labels[(CONV_SSA, (0, 1))]["bertopic_topic"] == "Disability"
    assert labels[(CONV_SSA, (0, 1))]["bertopic_subtopic"] == "Apply for SSDI"
    # All-null span stays NULL/NULL.
    assert labels[(CONV_SSA, (2, 3))]["bertopic_topic"] is None
    assert labels[(CONV_VA, (0, 1))]["bertopic_topic"] == "Disability"
    assert all(p["bertopic_topic"] is None for p in pred)

    # Taxonomy is domain-scoped: "disability" exists under BOTH ssa and va.
    disability_domains = {r["domain"] for r in tax if r["topic"] == "disability"}
    assert disability_domains == {"ssa", "va"}
    db.reset_pool()


@pg
def test_execute_is_idempotent(tmp_path):
    from annotation.backend import db

    _seed()
    gpath, npath = _write_files(tmp_path)
    assert _run(gpath, npath, "--execute") == 0
    assert _run(gpath, npath, "--execute") == 0

    db.reset_pool()
    pool = db.get_pool()
    with pool.connection() as conn:
        tax = conn.execute(
            "SELECT count(*) AS n FROM taxonomy WHERE dataset = %s", (DATASET,)
        ).fetchone()["n"]
    # Four mapping entries -> 4 topic rows + 4 pair rows, unchanged on a re-run.
    assert tax == 8
    db.reset_pool()


@pg
def test_execute_aborts_on_human_reviewed_gold(tmp_path):
    from annotation.backend import db

    _seed()
    # Mark one predicted segment as human-reviewed via a relabel gold row.
    pool = db.get_pool()
    with pool.connection() as conn:
        base = conn.execute(
            "SELECT s.id, s.conversation_id FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'predicted' LIMIT 1",
            (DATASET,),
        ).fetchone()
        conn.execute(
            "INSERT INTO segment (conversation_id, chunk_index, message_indices, "
            "topic, source, base_segment_id, reviewed_by, reviewed_at) "
            "VALUES (%s, 0, %s, 'x', 'relabel', %s, 'ann', now())",
            (base["conversation_id"], [0], base["id"]),
        )
    gpath, npath = _write_files(tmp_path)
    # Abort without --force; taxonomy stays empty.
    assert _run(gpath, npath, "--execute") == 1
    db.reset_pool()
    with db.get_pool().connection() as conn:
        tax = conn.execute(
            "SELECT count(*) AS n FROM taxonomy WHERE dataset = %s", (DATASET,)
        ).fetchone()["n"]
    assert tax == 0
    db.reset_pool()
