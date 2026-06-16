"""Ingest SuperDialseg gold segmentation boundaries into the annotation PG store.

SuperDialseg ships human-authored topic segments: each utterance carries a
``segment_id`` and a segment is a maximal run of consecutive utterances sharing
it. :meth:`SuperDialsegLoader.gold_segments` recovers those spans; this module
persists them into the annotation backend's PostgreSQL ``segment`` table with
``source='gold'`` — the reliable-label anchor the evaluation measures machine
boundaries against. The conversation + its messages are upserted first so the
gold spans attach to real conversation rows.

Idempotent: every prior ``source='gold'`` row for a conversation is replaced on
re-run. The target database is the annotation ``EB1_ANNOTATION_DSN`` Postgres.

Run::

    docker compose -f annotation/docker-compose.yml up -d
    python -m pipeline.metadata.ingest_superdialseg_gold

This module performs NO MongoDB / LLM / network access.
"""

from __future__ import annotations

import json
from pathlib import Path

from annotation.backend import db
from pipeline.adapters.superdialseg import SuperDialsegLoader

DATASET = "superdialseg"
SAMPLE_PATH = Path("datasets/superdialseg/sample.jsonl")
GOLD_SOURCE = "gold"


def _read_dialogues(sample_path: str | Path) -> list[dict]:
    path = Path(sample_path)
    if not path.exists():
        raise FileNotFoundError(f"Sample file not found: {path}")
    dialogues: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            dialogues.append(json.loads(line))
    return dialogues


def _messages(loader: SuperDialsegLoader, dialogue: dict) -> list[dict]:
    return [
        {"role": m.get("type", ""), "content": m.get("message", "")}
        for m in loader.load_conversation(dialogue)
    ]


def ingest(sample_path: str | Path = SAMPLE_PATH) -> int:
    """Ingest SuperDialseg gold spans into PG; return total spans written.

    For each dialogue the conversation + messages are upserted, then its
    ``source='gold'`` segment rows are replaced with one row per recovered span.
    Re-running is idempotent (replace per conversation).
    """
    loader = SuperDialsegLoader()
    dialogues = _read_dialogues(sample_path)

    written = 0
    for dialogue in dialogues:
        spans = loader.gold_segments(dialogue)
        if not spans:
            continue
        conversation = spans[0]["conversation"]
        conv_id = db.upsert_conversation(
            DATASET, conversation, _messages(loader, dialogue)
        )
        written += db.replace_gold_spans(conv_id, spans, source=GOLD_SOURCE)
    return written


def main() -> None:
    written = ingest()
    print(f"Ingested {written} SuperDialseg gold spans -> {DATASET} (Postgres)")


if __name__ == "__main__":
    main()
