"""Stream a full dataset into the annotation PostgreSQL store.

Usage::

    docker compose -f annotation/docker-compose.yml up -d
    export EB1_ANNOTATION_DSN=postgresql://eb1:eb1@localhost:5544/eb1_annotation
    python -m annotation.ingest.run --dataset wildchat [--limit N] [--batch 1000]

The runner pulls RAW rows from :mod:`annotation.ingest.sources`, normalizes each
through the matching ``pipeline.adapters`` loader, and writes — in idempotent,
resumable batches via :func:`annotation.backend.db.ingest_batch` — every
conversation + its messages + ONE whole-conversation ``source='predicted'``
segment (the seed humans segment from). SuperDialseg additionally writes its gold
``segment_id`` boundaries as ``source='gold'`` segments.

Idempotent: ``UNIQUE(dataset, ext_id)`` upsert; an already-loaded ext_id is
skipped (``--no-skip-existing`` to force re-upsert). Resumable: re-running after
an interruption continues from the unseen conversations. Progress prints every
batch. This module touches only PostgreSQL + the HuggingFace/Drive sources — no
MongoDB, no LLM.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator

from annotation.backend import db
from annotation.ingest import sources
from pipeline.adapters.lmsys import LMSYSLoader
from pipeline.adapters.superdialseg import SuperDialsegLoader
from pipeline.adapters.wildchat import WildChatLoader

_ADAPTERS = {
    "wildchat": WildChatLoader,
    "lmsys": LMSYSLoader,
    "superdialseg": SuperDialsegLoader,
}

# Stream functions resolved by NAME off ``sources`` at call time, so tests can
# monkeypatch e.g. ``sources.wildchat_stream`` and the runner picks it up.
_STREAM_FNS = {
    "wildchat": "wildchat_stream",
    "lmsys": "lmsys_stream",
    "superdialseg": "superdialseg_stream",
}


def _messages(normalized: list[dict]) -> list[dict]:
    """Project normalized adapter dicts onto the db ``message`` row shape."""
    return [
        {
            "role": m.get("type", ""),
            "content": m.get("message", ""),
            "created_at": m.get("createdAt"),
        }
        for m in normalized
    ]


def _normalize(dataset: str, loader, row: dict) -> dict | None:
    """Turn one raw row into an ``ingest_batch`` conversation dict (or ``None``).

    Drops conversations with no messages. For SuperDialseg the gold ``segment_id``
    spans are recovered via ``loader.gold_segments`` and carried as
    ``gold_segments`` so the batch writer persists them as ``source='gold'``.
    """
    normalized = loader.load_conversation(row)
    if not normalized:
        return None
    ext_id = normalized[0]["chat"]
    conv: dict = {"ext_id": ext_id, "messages": _messages(normalized)}
    if dataset == "superdialseg":
        conv["gold_segments"] = [
            {"message_indices": span["message_indices"]}
            for span in loader.gold_segments(row)
        ]
    return conv


def _batched(stream: Iterator[dict], size: int) -> Iterator[list[dict]]:
    batch: list[dict] = []
    for item in stream:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def ingest(
    dataset: str,
    limit: int | None = None,
    batch_size: int = 1000,
    skip_existing: bool = True,
) -> dict:
    """Stream + ingest one dataset; return ``{written, skipped, batches}``.

    Streams raw rows, normalizes per batch, skips ext_ids already loaded (when
    ``skip_existing``), upserts the rest, and prints per-batch progress.
    """
    if dataset not in _STREAM_FNS:
        raise SystemExit(
            f"Unknown dataset {dataset!r}. Choose one of "
            f"{', '.join(sorted(_STREAM_FNS))}."
        )

    db.apply_schema()
    db.ensure_dataset(dataset)

    loader = _ADAPTERS[dataset]()
    # Resolve the stream by attribute so tests can monkeypatch ``sources.*``.
    stream = getattr(sources, _STREAM_FNS[dataset])(limit=limit)

    written = 0
    skipped = 0
    batch_no = 0
    started = time.monotonic()

    for raw_batch in _batched(stream, batch_size):
        batch_no += 1
        convs: list[dict] = []
        for row in raw_batch:
            conv = _normalize(dataset, loader, row)
            if conv is not None:
                convs.append(conv)

        if skip_existing and convs:
            present = db.existing_ext_ids(dataset, [c["ext_id"] for c in convs])
            before = len(convs)
            convs = [c for c in convs if c["ext_id"] not in present]
            skipped += before - len(convs)

        written += db.ingest_batch(dataset, convs)
        elapsed = time.monotonic() - started
        print(
            f"[{dataset}] batch {batch_no}: +{len(convs)} written "
            f"(total {written}, skipped {skipped}) in {elapsed:.1f}s",
            flush=True,
        )

    print(
        f"[{dataset}] done: {written} conversations written, "
        f"{skipped} skipped over {batch_no} batch(es).",
        flush=True,
    )
    return {"written": written, "skipped": skipped, "batches": batch_no}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m annotation.ingest.run",
        description="Stream a full dataset into the annotation Postgres store.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        choices=sorted(sources.STREAMS),
        help="Which corpus to ingest.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Ingest at most N conversations (default: the full corpus).",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=1000,
        help="Conversations per upsert transaction (default 1000).",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-upsert conversations that already exist (default: skip them).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        ingest(
            dataset=args.dataset,
            limit=args.limit,
            batch_size=args.batch,
            skip_existing=not args.no_skip_existing,
        )
    finally:
        db.reset_pool()
    return 0


if __name__ == "__main__":
    sys.exit(main())
