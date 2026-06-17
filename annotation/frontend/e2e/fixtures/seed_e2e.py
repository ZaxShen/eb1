"""Deterministic E2E fixture builder for the annotation app (PostgreSQL).

Seeds a fresh, self-contained dataset into the annotation Postgres addressed by
``EB1_ANNOTATION_DSN`` (the docker compose service in
``annotation/docker-compose.yml``). The Playwright harness brings that container
up, runs this, then boots the backend against the same database. Everything here
is offline and stable.

.. warning::

   This script RESETS every dataset it touches (``reset=True``). The harness
   points it at a DEDICATED throwaway database (``eb1_annotation_e2e``), never
   the production ``eb1_annotation`` DB. If you run it standalone, set
   ``EB1_ANNOTATION_DSN`` to that dedicated DB — pointing it at production will
   destroy real labeling data.

Per dataset ``<ds>`` it reads the committed JSONL sample
(``samples/<ds>.jsonl``), normalizes each row through the dataset adapter, and
seeds each conversation as ONE whole-conversation ``predicted`` segment (the new
starting-segmentation model: one segment per conversation, the human segments
from there). A fixed ``mock_topic`` label is attached so split/merge inheritance
and "Confirm AI" relabel have a topic to carry — matching the prior SQLite mock
fixture the specs were written against.

Run standalone (against the dedicated e2e DB, NOT production)::

    docker compose -f annotation/docker-compose.yml up -d
    docker exec eb1-annotation-pg createdb -U eb1 eb1_annotation_e2e 2>/dev/null || true
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation_e2e
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

# Per-labeler worklist assignments for the name-only labeling flow. Keyed by
# dataset; each row mirrors the sampler JSON (``dialogue_id`` + ``assigned_to``)
# so the ``?labeler=`` queue filter has something to resolve. Assigned on the
# FROZEN superdialseg dataset (the real flow's home), keeping the per-labeler
# label spec off the wildchat conversations the re-segment spec mutates.
WORKLIST: dict[str, list[dict]] = {
    "superdialseg": [
        {
            "dialogue_id": "e2e_superdialseg_0001",
            "seg_bucket": "1-2",
            "len_bucket": "short",
            "assigned_to": ["labeler_a"],
            "is_overlap": False,
        },
    ],
}

SEED_TOPIC = "mock_topic"
SEED_SUBTOPIC = "mock subtopic"

# BERTopic gold labels for the queue's BERTopic filter, keyed by dataset then
# conversation ext_id: each named conversation gets one whole-conversation
# ``source='gold'`` segment carrying a distinct BERTopic topic/subtopic, so
# picking a BERTopic topic in the queue narrows it to exactly that conversation.
# Scoped to ``e2e_superdialseg_0002`` — a conversation no other spec opens — so
# the injected gold segment never disturbs the labeling/operations fixtures.
BERTOPIC_GOLD: dict[str, dict[str, dict]] = {
    "superdialseg": {
        "e2e_superdialseg_0002": {
            "bertopic_topic": "billing_disputes",
            "bertopic_subtopic": "double_charge",
        },
    },
}

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


def _seed_bertopic_gold(name: str, conversations: list[dict]) -> int:
    """Attach one BERTopic-labeled ``source='gold'`` segment per conversation.

    The queue's BERTopic filter restricts to conversations with a gold segment
    carrying the chosen label, so the e2e flow needs gold rows whose
    ``bertopic_topic``/``bertopic_subtopic`` columns are set. Idempotent: the
    seed resets the dataset on every run.
    """
    labels = BERTOPIC_GOLD.get(name)
    if not labels:
        return 0
    by_ext = {conv["ext_id"]: conv for conv in conversations}
    written = 0
    pool = db.get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            for ext_id, label in labels.items():
                conv = by_ext.get(ext_id)
                conv_id = db.conversation_id(name, ext_id)
                if conv is None or conv_id is None:
                    continue
                conn.execute(
                    "INSERT INTO segment (conversation_id, chunk_index, "
                    "message_indices, source, bertopic_topic, bertopic_subtopic) "
                    "VALUES (%s, 0, %s, 'gold', %s, %s)",
                    (
                        conv_id,
                        list(range(len(conv["messages"]))),
                        label["bertopic_topic"],
                        label["bertopic_subtopic"],
                    ),
                )
                written += 1
    return written


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
    bertopic = _seed_bertopic_gold(name, conversations)
    worklist = WORKLIST.get(name, [])
    if worklist:
        db.load_worklist(name, worklist)
    return {
        "conversations": len(conversations),
        "segments": len(conversations),
        "bertopic": bertopic,
        "worklist": len(worklist),
    }


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
