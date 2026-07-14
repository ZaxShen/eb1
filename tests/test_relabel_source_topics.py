"""Tests for the source-grounding relabel migration (``annotation.relabel_source_topics``).

The majority-rule + taxonomy-shape logic is pure and always runs. The DB
round-trip is gated on ``EB1_ANNOTATION_DSN`` like the rest of the annotation
suite::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_test
    uv run pytest tests/test_relabel_source_topics.py -q
"""

from __future__ import annotations

import json
import os

import pytest

from annotation import relabel_source_topics as r


def test_majority_title_picks_most_frequent():
    doc_by_turn = ["A", "A", "B"]
    assert r.majority_title([0, 1, 2], doc_by_turn) == "A"


def test_majority_title_tie_breaks_to_lowest_index():
    doc_by_turn = ["B", "A", "A", "B"]
    # A and B each appear twice; B first appears at index 0.
    assert r.majority_title([0, 1, 2, 3], doc_by_turn) == "B"


def test_majority_title_skips_nulls_and_out_of_range():
    doc_by_turn = ["A", None, "A"]
    assert r.majority_title([0, 1, 2, 99], doc_by_turn) == "A"


def test_majority_title_all_null_returns_none():
    assert r.majority_title([0, 1], [None, None]) is None
    assert r.majority_title([], ["A"]) is None


def test_segment_label_grounded_and_all_null():
    assert r.segment_label([0, 1], ["A", "A"], "ssa") == ("Social Security", "A")
    assert r.segment_label([0], [None], "ssa") == (None, None)


def test_build_taxonomy_rows_shape_and_provenance():
    label_map = {
        "dataset": "superdialseg",
        "pairs": [
            {
                "topic": "Social Security",
                "subtopic": "Retirement Benefits",
                "topic_raw": "ssa",
                "subtopic_raw": "Retirement Benefits | SSA#1_0",
            },
            {
                "topic": "Social Security",
                "subtopic": "Survivors",
                "topic_raw": "ssa",
                "subtopic_raw": "Survivors#2_0",
            },
        ],
    }
    rows = r.build_taxonomy_rows(label_map, "superdialseg")
    topic_rows = [x for x in rows if x["subtopic"] is None]
    pair_rows = [x for x in rows if x["subtopic"] is not None]
    assert len(topic_rows) == 1
    assert topic_rows[0] == {
        "topic": "social_security",
        "subtopic": None,
        "description": "Social Security",
    }
    assert len(pair_rows) == 2
    assert pair_rows[0] == {
        "topic": "social_security",
        "subtopic": "retirement_benefits",
        "description": "Retirement Benefits — source: ssa | Retirement Benefits | SSA#1_0",
    }


def test_build_taxonomy_rows_dataset_mismatch_raises():
    with pytest.raises(ValueError, match="does not match"):
        r.build_taxonomy_rows({"dataset": "other", "pairs": []}, "superdialseg")


# --- DB round-trip (DSN-gated) ---------------------------------------------

pg = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)

DATASET = "superdialseg"
CONV = "reldial01"


@pg
def test_execute_relabels_gold_and_replaces_taxonomy(tmp_path):
    from annotation.backend import db

    db.reset_pool()
    db.apply_schema()
    db.ingest_batch(
        DATASET,
        [
            {
                "ext_id": CONV,
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "more"},
                    {"role": "assistant", "content": "ok"},
                ],
                "gold_segments": [
                    {"message_indices": [0, 1]},
                    {"message_indices": [2, 3]},
                ],
            }
        ],
    )

    grounding = {
        "dataset": DATASET,
        "dialogues": {
            CONV: {
                "domain": "ssa",
                "doc_by_turn": [
                    "Retirement Benefits",
                    "Retirement Benefits",
                    None,
                    None,
                ],
            }
        },
    }
    label_map = {
        "dataset": DATASET,
        "pairs": [
            {
                "topic": "Social Security",
                "subtopic": "Retirement Benefits",
                "topic_raw": "ssa",
                "subtopic_raw": "Retirement Benefits | SSA#1_0",
            }
        ],
    }
    gpath = tmp_path / "g.json"
    mpath = tmp_path / "m.json"
    gpath.write_text(json.dumps(grounding), encoding="utf-8")
    mpath.write_text(json.dumps(label_map), encoding="utf-8")

    rc = r._main(
        [
            "--dataset",
            DATASET,
            "--grounding",
            str(gpath),
            "--label-map",
            str(mpath),
            "--execute",
        ]
    )
    assert rc == 0

    db.reset_pool()
    pool = db.get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.message_indices, s.bertopic_topic, s.bertopic_subtopic "
            "FROM segment s JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'gold' ORDER BY s.chunk_index",
            (DATASET,),
        ).fetchall()
        # Predicted whole-conversation seed stays NULL.
        pred = conn.execute(
            "SELECT bertopic_topic FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'predicted'",
            (DATASET,),
        ).fetchall()
        tax = conn.execute(
            "SELECT topic, subtopic, description FROM taxonomy "
            "WHERE dataset = %s ORDER BY topic, subtopic NULLS FIRST",
            (DATASET,),
        ).fetchall()

    labels = {tuple(row["message_indices"]): row for row in rows}
    assert labels[(0, 1)]["bertopic_topic"] == "Social Security"
    assert labels[(0, 1)]["bertopic_subtopic"] == "Retirement Benefits"
    # All-null span -> NULL/NULL.
    assert labels[(2, 3)]["bertopic_topic"] is None
    assert labels[(2, 3)]["bertopic_subtopic"] is None
    assert all(p["bertopic_topic"] is None for p in pred)

    assert tax[0]["topic"] == "social_security" and tax[0]["subtopic"] is None
    assert tax[1]["topic"] == "social_security"
    assert tax[1]["subtopic"] == "retirement_benefits"

    db.reset_pool()
