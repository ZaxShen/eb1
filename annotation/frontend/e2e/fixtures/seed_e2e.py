"""Deterministic E2E fixture builder for the annotation app (PostgreSQL).

Seeds a fresh, self-contained dataset into the annotation Postgres addressed by
``EB1_ANNOTATION_DSN`` (the docker compose service in
``annotation/docker-compose.yml``). The Playwright harness brings that container
up, runs this, then boots the backend against the same database. Everything here
is offline and stable.

Per dataset ``<ds>`` it reads the committed JSONL sample
(``samples/<ds>.jsonl``), normalizes each row through the dataset adapter, and
seeds each conversation as ONE whole-conversation ``predicted`` segment (the new
starting-segmentation model: one segment per conversation, the human segments
from there). A fixed ``mock_topic`` label is attached so split/merge inheritance
and "Confirm AI" relabel have a topic to carry — matching the prior SQLite mock
fixture the specs were written against.

Run standalone::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation
    uv run python annotation/frontend/e2e/fixtures/seed_e2e.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python <path>/seed_e2e.py`` (script dir, not cwd, is sys.path[0]) to
# import the repo's packages regardless of the launch directory.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from annotation.backend import db  # noqa: E402
from pipeline.adapters import get_loader  # noqa: E402

SAMPLES_DIR = Path(__file__).parent / "samples"

DATASETS = ["wildchat", "superdialseg"]

SEED_TOPIC = "mock_topic"
SEED_SUBTOPIC = "mock subtopic"

# A tiny relabel taxonomy so the annotation panel's selects have options.
TAXONOMY = [
    {"topic": SEED_TOPIC, "subtopic": SEED_SUBTOPIC, "description": "Seeded fixture label."},
]


def _read_rows(path: Path) -> list[dict]:
    import json

    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def build_dataset(name: str) -> dict:
    """Seed one dataset from its committed sample; return a summary."""
    loader = get_loader(name)
    rows = _read_rows(SAMPLES_DIR / f"{name}.jsonl")

    conversations: list[dict] = []
    for row in rows:
        messages = loader.load_conversation(row)
        if not messages:
            continue
        conversations.append(
            {
                "ext_id": messages[0]["chat"],
                "messages": [
                    {"role": m.get("type", ""), "content": m.get("message", "")}
                    for m in messages
                ],
                # One whole-conversation predicted segment, labeled so split/merge
                # inheritance and Confirm-AI relabel have a topic to carry.
                "topic": SEED_TOPIC,
                "subtopic": SEED_SUBTOPIC,
                "sentiment": "neutral",
                "label_confidence": 1.0,
                "summary": "Seeded whole-conversation segment.",
            }
        )

    db.seed_conversations(name, conversations, taxonomy=TAXONOMY, reset=True)
    return {"conversations": len(conversations), "segments": len(conversations)}


def build() -> None:
    """Apply the schema and seed every E2E dataset fresh into Postgres."""
    db.reset_pool()
    db.apply_schema()
    try:
        for name in DATASETS:
            summary = build_dataset(name)
            print(
                f"[seed_e2e] {name}: "
                f"{summary['conversations']} conversations, "
                f"{summary['segments']} segments"
            )
    finally:
        db.reset_pool()


def main() -> None:
    build()
    print("[seed_e2e] fixture datasets seeded into Postgres")


if __name__ == "__main__":
    main()
