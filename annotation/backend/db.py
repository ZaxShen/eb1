"""Data access for the annotation backend — resolve, read, and write per-dataset SQLite.

Every reader reuses the existing pipeline plumbing rather than reinventing it:

- machine segments come from ``datasets/<ds>/output.db`` (table ``run_segment``,
  written by ``pipeline.run_dataset``);
- conversation messages come from ``datasets/<ds>/sample.jsonl`` normalized via
  ``pipeline.adapters.get_loader`` (the ``{_id,chat,type,message,createdAt}`` shape);
- taxonomy comes from ``datasets/<ds>/metadata.db`` via
  ``pipeline.metadata.SqliteDatasetProvider``.

Human gold is written to a NEW ``datasets/<ds>/gold.db`` created from
``gold_schema.sql``. Nothing here touches MongoDB, PostgreSQL, an LLM, or the
network.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pipeline.adapters import get_loader
from pipeline.metadata import SqliteDatasetProvider

DATASETS_ROOT = Path("datasets")

GOLD_SCHEMA_PATH = Path(__file__).parent / "gold_schema.sql"


def dataset_dir(dataset: str, root: Path | None = None) -> Path:
    """Return ``<root>/<dataset>`` (defaults to the ``datasets/`` root)."""
    return (root or DATASETS_ROOT) / dataset


def output_db_path(dataset: str, root: Path | None = None) -> Path:
    """Path to the dataset's machine-segment output DB."""
    return dataset_dir(dataset, root) / "output.db"


def metadata_db_path(dataset: str, root: Path | None = None) -> Path:
    """Path to the dataset's metadata DB."""
    return dataset_dir(dataset, root) / "metadata.db"


def sample_path(dataset: str, root: Path | None = None) -> Path:
    """Path to the dataset's raw JSONL sample."""
    return dataset_dir(dataset, root) / "sample.jsonl"


def gold_db_path(dataset: str, root: Path | None = None) -> Path:
    """Path to the dataset's human-gold DB."""
    return dataset_dir(dataset, root) / "gold.db"


def list_datasets(root: Path | None = None) -> list[str]:
    """Return dataset names that have an ``output.db`` under ``root``."""
    base = root or DATASETS_ROOT
    if not base.exists():
        return []
    names = [
        child.name
        for child in sorted(base.iterdir())
        if child.is_dir() and (child / "output.db").exists()
    ]
    return names


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def open_gold_db(dataset: str, root: Path | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the dataset's gold DB from ``gold_schema.sql``."""
    path = gold_db_path(dataset, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    conn.executescript(GOLD_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def read_run_segments(dataset: str, root: Path | None = None) -> list[dict]:
    """Read all ``run_segment`` rows for ``dataset`` as decoded dicts.

    ``message_indices`` is JSON-decoded into a ``list[int]``; ``raw`` is left as
    its stored JSON string. Rows are ordered by conversation then chunk index.
    """
    path = output_db_path(dataset, root)
    if not path.exists():
        raise FileNotFoundError(f"Output DB not found: {path}")
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT * FROM run_segment ORDER BY conversation, chunk_index, id"
        ).fetchall()
    finally:
        conn.close()
    return [_decode_run_segment(r) for r in rows]


def read_run_segment(dataset: str, segment_id: int, root: Path | None = None) -> dict | None:
    """Read a single ``run_segment`` row by id (or ``None`` if absent)."""
    path = output_db_path(dataset, root)
    if not path.exists():
        raise FileNotFoundError(f"Output DB not found: {path}")
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM run_segment WHERE id = ?", (segment_id,)
        ).fetchone()
    finally:
        conn.close()
    return _decode_run_segment(row) if row is not None else None


def _decode_run_segment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "dataset": row["dataset"],
        "conversation": row["conversation"],
        "chunk_index": row["chunk_index"],
        "message_indices": json.loads(row["message_indices"]) if row["message_indices"] else [],
        "summary": row["summary"],
        "topic": row["topic"],
        "subtopic": row["subtopic"],
        "sentiment": row["sentiment"],
        "label_confidence": row["label_confidence"],
    }


def load_conversation_messages(dataset: str, root: Path | None = None) -> dict[str, list[dict]]:
    """Load every conversation's normalized messages keyed by conversation id.

    Reads ``sample.jsonl`` and normalizes each row through the dataset adapter.
    Each value is the ordered ``list[dict]`` the adapter emits
    (``{_id, chat, type, message, createdAt}``).
    """
    path = sample_path(dataset, root)
    if not path.exists():
        raise FileNotFoundError(f"Sample file not found: {path}")
    loader = get_loader(dataset)
    conversations: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        messages = loader.load_conversation(json.loads(line))
        if messages:
            conversations[messages[0]["chat"]] = messages
    return conversations


def conversation_messages(dataset: str, conversation: str, root: Path | None = None) -> list[dict]:
    """Return one conversation's normalized messages (empty list if not found)."""
    return load_conversation_messages(dataset, root).get(conversation, [])


def conversation_message_counts(dataset: str, root: Path | None = None) -> dict[str, int]:
    """Return message count per conversation id (empty if no sample file)."""
    try:
        conversations = load_conversation_messages(dataset, root)
    except FileNotFoundError:
        return {}
    return {conv: len(messages) for conv, messages in conversations.items()}


def serialize_messages(messages: list[dict]) -> list[dict]:
    """Project normalized messages to JSON-safe dicts for the API.

    Adds a positional ``index`` (the message's position in the conversation) so
    the frontend can map ``message_indices`` spans to messages, and renders
    ``createdAt`` as an ISO string.
    """
    out: list[dict] = []
    for i, m in enumerate(messages):
        created = m.get("createdAt")
        out.append({
            "index": i,
            "id": str(m.get("_id", "")),
            "type": m.get("type", ""),
            "message": m.get("message", ""),
            "createdAt": created.isoformat() if isinstance(created, datetime) else created,
        })
    return out


def load_taxonomy(dataset: str, root: Path | None = None) -> list[dict]:
    """Return the dataset's user taxonomy rows via the metadata provider."""
    path = metadata_db_path(dataset, root)
    if not path.exists():
        raise FileNotFoundError(f"Metadata DB not found: {path}")
    provider = SqliteDatasetProvider(path)
    return provider.taxonomy("user")


def upsert_gold_for_segment(
    dataset: str,
    base_segment: dict,
    topic: str,
    subtopic: str,
    sentiment: str | None,
    reviewed_by: str | None,
    root: Path | None = None,
) -> int:
    """Mirror one base run_segment as a gold_segment and mark it reviewed.

    Replaces any prior gold_segment carrying this ``base_segment_id`` so a
    re-annotation does not accumulate duplicates, then records review_state.
    Returns the new gold_segment id.
    """
    now = _utcnow_iso()
    conn = open_gold_db(dataset, root)
    try:
        conn.execute(
            "DELETE FROM gold_segment WHERE base_segment_id = ?",
            (base_segment["id"],),
        )
        source = "confirm" if _is_confirm(base_segment, topic, subtopic) else "relabel"
        cur = conn.execute(
            "INSERT INTO gold_segment "
            "(conversation, message_indices, topic, subtopic, sentiment, "
            "base_segment_id, source, reviewed_by, reviewed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                base_segment["conversation"],
                json.dumps(base_segment["message_indices"]),
                topic,
                subtopic,
                sentiment,
                base_segment["id"],
                source,
                reviewed_by,
                now,
            ),
        )
        gold_id = cur.lastrowid
        conn.execute(
            "INSERT INTO review_state "
            "(conversation, base_segment_id, reviewed_by, reviewed_at, status) "
            "VALUES (?, ?, ?, ?, 'reviewed') "
            "ON CONFLICT(conversation, base_segment_id) DO UPDATE SET "
            "reviewed_by = excluded.reviewed_by, "
            "reviewed_at = excluded.reviewed_at, status = 'reviewed'",
            (base_segment["conversation"], base_segment["id"], reviewed_by, now),
        )
        conn.commit()
    finally:
        conn.close()
    return int(gold_id)


def _is_confirm(base_segment: dict, topic: str, subtopic: str) -> bool:
    return (base_segment.get("topic") == topic) and (base_segment.get("subtopic") == subtopic)


def replace_conversation_boundaries(
    dataset: str,
    conversation: str,
    spans: list[dict],
    reviewed_by: str | None,
    root: Path | None = None,
) -> int:
    """REPLACE all gold_segments for ``conversation`` with the posted spans.

    This is how split/merge persists: every prior gold_segment for the
    conversation is deleted, then one ``source='boundary'`` gold_segment is
    written per posted span. Returns the number of gold_segment rows written.
    """
    now = _utcnow_iso()
    conn = open_gold_db(dataset, root)
    try:
        conn.execute("DELETE FROM gold_segment WHERE conversation = ?", (conversation,))
        for span in spans:
            conn.execute(
                "INSERT INTO gold_segment "
                "(conversation, message_indices, topic, subtopic, sentiment, "
                "base_segment_id, source, reviewed_by, reviewed_at) "
                "VALUES (?, ?, ?, ?, ?, NULL, 'boundary', ?, ?)",
                (
                    conversation,
                    json.dumps(span["message_indices"]),
                    span.get("topic"),
                    span.get("subtopic"),
                    span.get("sentiment"),
                    reviewed_by,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return len(spans)


def read_gold_segments(dataset: str, conversation: str, root: Path | None = None) -> list[dict]:
    """Read all gold_segment rows for one conversation (ordered by id)."""
    conn = open_gold_db(dataset, root)
    try:
        rows = conn.execute(
            "SELECT * FROM gold_segment WHERE conversation = ? ORDER BY id",
            (conversation,),
        ).fetchall()
    finally:
        conn.close()
    return [_decode_gold_segment(r) for r in rows]


def _decode_gold_segment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "conversation": row["conversation"],
        "message_indices": json.loads(row["message_indices"]) if row["message_indices"] else [],
        "topic": row["topic"],
        "subtopic": row["subtopic"],
        "sentiment": row["sentiment"],
        "base_segment_id": row["base_segment_id"],
        "source": row["source"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
    }


def gold_labels_by_base_segment(
    dataset: str, root: Path | None = None
) -> dict[int, dict]:
    """Return current gold ``{topic, subtopic}`` keyed by base_segment_id.

    Only relabel/confirm gold rows carry a base_segment_id; boundary rows have
    NULL and are excluded. Lets segment responses expose the current gold so the
    frontend can snapshot before-state for undo.
    """
    conn = open_gold_db(dataset, root)
    try:
        rows = conn.execute(
            "SELECT base_segment_id, topic, subtopic FROM gold_segment "
            "WHERE base_segment_id IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return {
        r["base_segment_id"]: {"topic": r["topic"], "subtopic": r["subtopic"]}
        for r in rows
    }


def clear_segment_annotation(
    dataset: str, base_segment_id: int, root: Path | None = None
) -> int:
    """Clear a base segment's gold: delete its relabel/confirm gold_segment
    row(s) + its review_state entry, reverting the segment to unannotated.

    Returns the number of gold_segment rows deleted.
    """
    conn = open_gold_db(dataset, root)
    try:
        cur = conn.execute(
            "DELETE FROM gold_segment WHERE base_segment_id = ? "
            "AND source IN ('relabel', 'confirm')",
            (base_segment_id,),
        )
        deleted = cur.rowcount
        conn.execute(
            "DELETE FROM review_state WHERE base_segment_id = ?",
            (base_segment_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return int(deleted)


def reviewed_base_segment_ids(dataset: str, root: Path | None = None) -> set[int]:
    """Return base_segment_ids marked reviewed in review_state."""
    conn = open_gold_db(dataset, root)
    try:
        rows = conn.execute(
            "SELECT base_segment_id FROM review_state WHERE status = 'reviewed'"
        ).fetchall()
    finally:
        conn.close()
    return {r["base_segment_id"] for r in rows if r["base_segment_id"] is not None}
