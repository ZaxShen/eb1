"""Ingest SuperDialseg gold segmentation boundaries into the per-dataset gold DB.

SuperDialseg ships human-authored topic segments: each utterance carries a
``segment_id`` and a segment is a maximal run of consecutive utterances sharing
it. :meth:`SuperDialsegLoader.gold_segments` recovers those spans; this module
persists them into ``datasets/superdialseg/gold.db`` (the annotation backend's
gold store) as ``gold_segment`` rows with ``source='gold'`` — the reliable-label
anchor the evaluation measures machine boundaries against.

Idempotent: every prior ``source='gold'`` row for a conversation is deleted
before its spans are re-written, so re-running replaces rather than duplicates.

Run::

    python -m pipeline.metadata.ingest_superdialseg_gold

This module performs NO MongoDB / PostgreSQL / LLM / network access.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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


def ingest(
    sample_path: str | Path = SAMPLE_PATH,
    root: Path | None = None,
) -> int:
    """Ingest SuperDialseg gold spans into the gold DB; return spans written.

    For each dialogue, prior ``source='gold'`` rows for that conversation are
    deleted, then one ``gold_segment`` row per recovered span is inserted with
    ``source='gold'``. Re-running is idempotent (replace per conversation).
    """
    loader = SuperDialsegLoader()
    dialogues = _read_dialogues(sample_path)
    now = datetime.now(tz=timezone.utc).isoformat()

    conn = db.open_gold_db(DATASET, root)
    written = 0
    try:
        for dialogue in dialogues:
            spans = loader.gold_segments(dialogue)
            if not spans:
                continue
            conversation = spans[0]["conversation"]
            conn.execute(
                "DELETE FROM gold_segment WHERE conversation = ? AND source = ?",
                (conversation, GOLD_SOURCE),
            )
            for span in spans:
                conn.execute(
                    "INSERT INTO gold_segment "
                    "(conversation, message_indices, topic, subtopic, sentiment, "
                    "base_segment_id, source, reviewed_by, reviewed_at) "
                    "VALUES (?, ?, NULL, NULL, NULL, NULL, ?, NULL, ?)",
                    (
                        conversation,
                        json.dumps(span["message_indices"]),
                        GOLD_SOURCE,
                        now,
                    ),
                )
                written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def main() -> None:
    written = ingest()
    print(f"Ingested {written} SuperDialseg gold spans -> {db.gold_db_path(DATASET)}")


if __name__ == "__main__":
    main()
