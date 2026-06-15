"""End-to-end tests for the universal runner (offline, mock analyzer)."""

from __future__ import annotations

import json
import sqlite3
from unittest import mock

from pipeline.analyzer_backends import call_claude_p, get_analyzer, strip_json_fence
from pipeline.metadata.seed_wildchat import seed
from pipeline.run_dataset import run

SAMPLE = "datasets/wildchat/sample.jsonl"


def _seed_metadata(tmp_path):
    db = tmp_path / "metadata.db"
    seed(db)
    return db


def test_run_mock_end_to_end_offline(tmp_path):
    metadata_db = _seed_metadata(tmp_path)
    output_db = tmp_path / "output.db"

    summary = run(
        dataset="wildchat",
        sample=SAMPLE,
        analyzer="mock",
        model="mock",
        metadata_db=metadata_db,
        output_db=output_db,
    )

    assert summary["conversations"] >= 3
    # >=1 segment per sampled conversation
    assert summary["segments"] >= summary["conversations"]
    assert output_db.exists()

    conn = sqlite3.connect(str(output_db))
    try:
        rows = conn.execute(
            "SELECT DISTINCT conversation FROM run_segment"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM run_segment").fetchone()[0]
    finally:
        conn.close()

    assert len(rows) == summary["conversations"]
    assert total == summary["segments"]


def test_run_mock_respects_limit(tmp_path):
    metadata_db = _seed_metadata(tmp_path)
    output_db = tmp_path / "output.db"

    summary = run(
        dataset="wildchat",
        sample=SAMPLE,
        analyzer="mock",
        model="mock",
        limit=1,
        metadata_db=metadata_db,
        output_db=output_db,
    )

    assert summary["conversations"] == 1
    assert summary["segments"] >= 1


def test_get_analyzer_dispatch():
    assert get_analyzer("mock") is not None
    assert get_analyzer("claude_p") is not None
    try:
        get_analyzer("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown analyzer")


def test_strip_json_fence():
    fenced = '```json\n{"segments": []}\n```'
    assert strip_json_fence(fenced) == '{"segments": []}'
    assert json.loads(strip_json_fence(fenced)) == {"segments": []}

    bare = '```\n{"a": 1}\n```'
    assert strip_json_fence(bare) == '{"a": 1}'

    plain = '{"x": 2}'
    assert strip_json_fence(plain) == '{"x": 2}'


def test_call_claude_p_strips_fence_stubbed():
    completed = mock.Mock()
    completed.stdout = '```json\n{"segments": [{"topic": "t"}]}\n```'
    with mock.patch(
        "pipeline.analyzer_backends.subprocess.run", return_value=completed
    ) as run_mock:
        out = call_claude_p("prompt text", model="haiku")

    assert json.loads(out) == {"segments": [{"topic": "t"}]}
    args = run_mock.call_args[0][0]
    assert args[:3] == ["claude", "-p", "--model"]
    assert args[3] == "claude-haiku-4-5"
    assert "claude-haiku-4-5" in args
    assert args[-1] == "prompt text"
