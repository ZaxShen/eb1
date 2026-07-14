"""Tests for the taxonomy loader (``annotation.load_taxonomy``).

The transform tests (map JSON -> row set) are pure and always run. The DB
round-trip is gated on ``EB1_ANNOTATION_DSN`` like the rest of the annotation
suite::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_test
    uv run pytest tests/test_load_taxonomy.py -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from annotation import load_taxonomy

REAL_MAP = Path(__file__).resolve().parents[1] / "analysis" / "bertopic_label_map.json"

DATASET = "superdialseg"

SMALL_MAP = {
    "dataset": "loadertest",
    "pairs": [
        {
            "topic_raw": "va / benefits",
            "subtopic_raw": "disability / claim",
            "topic": "Veterans Affairs",
            "subtopic": "Disability Claims",
        },
        {
            "topic_raw": "va / benefits",
            "subtopic_raw": "pension / monthly",
            "topic": "Veterans Affairs",
            "subtopic": "Pension",
        },
        {
            "topic_raw": "address / plates",
            "subtopic_raw": "surrender / plates",
            "topic": "Vehicle Registration & ID",
            "subtopic": "Surrendering Plates",
        },
    ],
}


# --- pure transform ---------------------------------------------------------


def test_build_rows_topics_then_pairs():
    rows = load_taxonomy.build_taxonomy_rows(SMALL_MAP, "loadertest")
    topics = [r for r in rows if r["subtopic"] is None]
    pairs = [r for r in rows if r["subtopic"] is not None]

    assert [r["topic"] for r in topics] == ["veterans_affairs", "vehicle_registration_id"]
    assert topics[0]["description"] == "Veterans Affairs"
    assert all(r["kind"] == "user" and r["dataset"] == "loadertest" for r in rows)
    assert rows[: len(topics)] == topics  # topic rows come first

    disability = next(r for r in pairs if r["subtopic"] == "disability_claims")
    assert disability["topic"] == "veterans_affairs"
    assert disability["description"] == (
        "Veterans Affairs / Disability Claims — keywords: va / benefits | disability / claim"
    )
    assert len(pairs) == 3


def test_build_rows_dataset_mismatch_fails():
    with pytest.raises(ValueError):
        load_taxonomy.build_taxonomy_rows(SMALL_MAP, "superdialseg")


def test_build_rows_real_file_counts():
    payload = json.loads(REAL_MAP.read_text(encoding="utf-8"))
    rows = load_taxonomy.build_taxonomy_rows(payload, DATASET)
    topics = [r for r in rows if r["subtopic"] is None]
    pairs = [r for r in rows if r["subtopic"] is not None]
    assert len(topics) == 14
    assert len(pairs) == 184
    assert all(r["topic"] == r["topic"].lower() for r in rows)


# --- DB round-trip (DSN-gated) ----------------------------------------------

pytestmark_dsn = pytest.mark.skipif(
    not os.environ.get("EB1_ANNOTATION_DSN"),
    reason="EB1_ANNOTATION_DSN unset; start annotation/docker-compose.yml to run",
)


@pytestmark_dsn
def test_execute_upserts_and_is_idempotent(tmp_path):
    from annotation.backend import db

    db.reset_pool()
    db.apply_schema()
    db.ensure_dataset("loadertest")
    pool = db.get_pool()
    with pool.connection() as conn, conn.transaction():
        conn.execute("DELETE FROM taxonomy WHERE dataset = %s", ("loadertest",))
    db.reset_pool()

    map_file = tmp_path / "map.json"
    map_file.write_text(json.dumps(SMALL_MAP), encoding="utf-8")
    argv = ["--dataset", "loadertest", "--map-file", str(map_file)]

    assert load_taxonomy._main(argv) == 0  # dry-run
    assert db.load_taxonomy("loadertest") == []  # wrote nothing

    assert load_taxonomy._main([*argv, "--execute"]) == 0
    first = {(r["topic"], r["subtopic"]): r["description"] for r in db.load_taxonomy("loadertest")}
    assert (("veterans_affairs", None)) in first
    assert first[("veterans_affairs", None)] == "Veterans Affairs"
    assert ("veterans_affairs", "disability_claims") in first
    assert len(first) == 5  # 2 topics + 3 pairs

    assert load_taxonomy._main([*argv, "--execute"]) == 0
    second = {(r["topic"], r["subtopic"]): r["description"] for r in db.load_taxonomy("loadertest")}
    assert second == first  # re-run is a no-op

    db.reset_pool()
