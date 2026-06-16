"""Data access for the annotation backend — PostgreSQL via a psycopg pool.

Replaces the per-dataset SQLite layer with one PostgreSQL database addressed by
``EB1_ANNOTATION_DSN`` (see ``annotation/docker-compose.yml``). It holds the FULL
datasets (~1.85M conversations) so the labeling site scales to production.

Storage model (``schema.sql``):

- ``conversation`` rows keyed by ``(dataset, ext_id)`` carry the messages
  (``message`` table) and the segments (``segment`` table);
- a conversation's MACHINE seed is ``source='predicted'`` segment rows (the
  whole-conversation starting segment plus any others an ingest produces);
- HUMAN gold is more ``segment`` rows: ``source in ('relabel','confirm')`` mirror
  a predicted span (``base_segment_id`` set), ``source='boundary'`` replaces a
  conversation's spans wholesale (``base_segment_id`` NULL).

The EFFECTIVE segmentation (gold-when-boundary-edited replaces predicted
per-conversation; inherited topics) matches the prior SQLite semantics — see
``effective_segments``. Nothing here touches MongoDB, an LLM, or the network.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from annotation.backend.config import annotation_dsn

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_POOL: ConnectionPool | None = None
_POOL_DSN: str | None = None
_POOL_LOCK = threading.Lock()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def get_pool() -> ConnectionPool:
    """Return the process-wide connection pool, opening it on first use.

    The pool is bound to the current ``EB1_ANNOTATION_DSN``; if the DSN changes
    (tests pointing at an isolated db) the pool is transparently rebuilt.
    """
    global _POOL, _POOL_DSN
    dsn = annotation_dsn()
    with _POOL_LOCK:
        if _POOL is None or _POOL_DSN != dsn:
            if _POOL is not None:
                _POOL.close()
            _POOL = ConnectionPool(
                dsn,
                min_size=1,
                max_size=8,
                open=True,
                kwargs={"row_factory": dict_row},
            )
            _POOL_DSN = dsn
        return _POOL


def reset_pool() -> None:
    """Close and forget the pool (tests call this when the DSN changes)."""
    global _POOL, _POOL_DSN
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
        _POOL = None
        _POOL_DSN = None


def apply_schema(dsn: str | None = None) -> None:
    """Apply ``schema.sql`` to the target database (idempotent)."""
    target = dsn or annotation_dsn()
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute(sql)


# ---------------------------------------------------------------------------
# Seeding (tests + smoke; the real ingest is a separate task)
# ---------------------------------------------------------------------------


def seed_conversations(
    dataset: str,
    conversations: list[dict],
    description: str | None = None,
    taxonomy: list[dict] | None = None,
    reset: bool = True,
) -> None:
    """Seed one dataset's conversations + whole-conversation predicted segments.

    Each conversation dict is::

        {
          "ext_id": "<source id>",
          "messages": [{"role","content","created_at"?}, ...],
          "segments": [   # optional; default = one whole-conversation span
            {"message_indices":[...], "topic","subtopic","sentiment",
             "summary","label_confidence","chunk_index"?},
            ...
          ],
        }

    When ``segments`` is omitted a single ``source='predicted'`` segment spanning
    every message is created (the whole-conversation starting segment). When
    ``reset`` is true the dataset's existing rows are wiped first so seeding is
    deterministic. ``taxonomy`` is a list of ``{topic,subtopic,description}``.
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            if reset:
                conn.execute("DELETE FROM dataset WHERE name = %s", (dataset,))
            conn.execute(
                "INSERT INTO dataset (name, description) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description",
                (dataset, description),
            )
            for entry in taxonomy or []:
                conn.execute(
                    "INSERT INTO taxonomy (dataset, kind, topic, subtopic, description) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        dataset,
                        entry.get("kind", "user"),
                        entry.get("topic"),
                        entry.get("subtopic"),
                        entry.get("description"),
                    ),
                )
            for conv in conversations:
                messages = conv.get("messages", [])
                conv_id = conn.execute(
                    "INSERT INTO conversation (dataset, ext_id, message_count) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (dataset, conv["ext_id"], len(messages)),
                ).fetchone()["id"]
                for idx, m in enumerate(messages):
                    conn.execute(
                        "INSERT INTO message (conversation_id, idx, role, content, created_at) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            conv_id,
                            idx,
                            m.get("role", ""),
                            m.get("content", ""),
                            m.get("created_at"),
                        ),
                    )
                segments = conv.get("segments")
                if not segments:
                    segments = [
                        {
                            "message_indices": list(range(len(messages))),
                            "topic": conv.get("topic"),
                            "subtopic": conv.get("subtopic"),
                            "sentiment": conv.get("sentiment"),
                            "summary": conv.get("summary"),
                            "label_confidence": conv.get("label_confidence"),
                        }
                    ]
                for chunk_index, seg in enumerate(segments):
                    conn.execute(
                        "INSERT INTO segment "
                        "(conversation_id, chunk_index, message_indices, summary, "
                        "topic, subtopic, sentiment, label_confidence, source) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'predicted')",
                        (
                            conv_id,
                            seg.get("chunk_index", chunk_index),
                            list(seg.get("message_indices", [])),
                            seg.get("summary"),
                            seg.get("topic"),
                            seg.get("subtopic"),
                            seg.get("sentiment"),
                            seg.get("label_confidence"),
                        ),
                    )


def upsert_conversation(
    dataset: str,
    ext_id: str,
    messages: list[dict],
    description: str | None = None,
) -> int:
    """Upsert a dataset + one conversation with its messages; return the conv id.

    Idempotent on ``(dataset, ext_id)``: an existing conversation's messages are
    replaced. Used by gold ingesters that need conversation rows to attach spans
    to without the full seed payload.
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(
                "INSERT INTO dataset (name, description) VALUES (%s, %s) "
                "ON CONFLICT (name) DO NOTHING",
                (dataset, description),
            )
            conn.execute(
                "INSERT INTO conversation (dataset, ext_id, message_count) "
                "VALUES (%s, %s, %s) ON CONFLICT (dataset, ext_id) "
                "DO UPDATE SET message_count = EXCLUDED.message_count",
                (dataset, ext_id, len(messages)),
            )
            conv_id = conn.execute(
                "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
                (dataset, ext_id),
            ).fetchone()["id"]
            conn.execute("DELETE FROM message WHERE conversation_id = %s", (conv_id,))
            for idx, m in enumerate(messages):
                conn.execute(
                    "INSERT INTO message (conversation_id, idx, role, content, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (conv_id, idx, m.get("role", ""), m.get("content", ""), m.get("created_at")),
                )
    return int(conv_id)


def replace_gold_spans(
    conv_id: int,
    spans: list[dict],
    source: str,
    reviewed_by: str | None = None,
) -> int:
    """REPLACE a conversation's ``source`` gold rows with one row per span.

    Returns the number of rows written. Idempotent per (conversation, source).
    """
    now = _utcnow()
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(
                "DELETE FROM segment WHERE conversation_id = %s AND source = %s",
                (conv_id, source),
            )
            for i, span in enumerate(spans):
                conn.execute(
                    "INSERT INTO segment "
                    "(conversation_id, chunk_index, message_indices, topic, subtopic, "
                    "sentiment, source, base_segment_id, reviewed_by, reviewed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s)",
                    (
                        conv_id,
                        i,
                        list(span.get("message_indices", [])),
                        span.get("topic"),
                        span.get("subtopic"),
                        span.get("sentiment"),
                        source,
                        reviewed_by,
                        now,
                    ),
                )
    return len(spans)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def list_datasets() -> list[str]:
    """Return dataset names (alphabetical)."""
    pool = get_pool()
    with pool.connection() as conn:
        rows = conn.execute("SELECT name FROM dataset ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def dataset_exists(dataset: str) -> bool:
    """True when ``dataset`` is registered."""
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM dataset WHERE name = %s", (dataset,)
        ).fetchone()
    return row is not None


def conversation_id(dataset: str, ext_id: str) -> int | None:
    """Resolve a conversation's surrogate id from its ``(dataset, ext_id)``."""
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, ext_id),
        ).fetchone()
    return row["id"] if row else None


def serialize_messages(conv_id: int, conn: psycopg.Connection) -> list[dict]:
    """Return a conversation's messages as API dicts ordered by ``idx``."""
    rows = conn.execute(
        "SELECT idx, id, role, content, created_at FROM message "
        "WHERE conversation_id = %s ORDER BY idx",
        (conv_id,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        created = r["created_at"]
        out.append(
            {
                "index": r["idx"],
                "id": str(r["id"]),
                "type": r["role"] or "",
                "message": r["content"] or "",
                "createdAt": created.isoformat() if isinstance(created, datetime) else created,
            }
        )
    return out


def _read_predicted(conv_id: int, conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM segment WHERE conversation_id = %s AND source = 'predicted' "
        "ORDER BY chunk_index, id",
        (conv_id,),
    ).fetchall()
    return [_seg_dict(r) for r in rows]


GOLD_SOURCES = ("relabel", "confirm", "boundary", "gold")


def _read_gold(conv_id: int, conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM segment WHERE conversation_id = %s "
        "AND source = ANY(%s) ORDER BY id",
        (conv_id, list(GOLD_SOURCES)),
    ).fetchall()
    return [_seg_dict(r) for r in rows]


def _seg_dict(row: dict) -> dict:
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "chunk_index": row["chunk_index"],
        "message_indices": list(row["message_indices"] or []),
        "summary": row["summary"],
        "topic": row["topic"],
        "subtopic": row["subtopic"],
        "sentiment": row["sentiment"],
        "label_confidence": row["label_confidence"],
        "source": row["source"],
        "base_segment_id": row["base_segment_id"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"].isoformat()
        if isinstance(row["reviewed_at"], datetime)
        else row["reviewed_at"],
    }


def read_predicted_segments(dataset: str) -> list[dict]:
    """Read every predicted ``segment`` row for a dataset (with conversation ext_id)."""
    pool = get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.*, c.ext_id FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source = 'predicted' "
            "ORDER BY c.ext_id, s.chunk_index, s.id",
            (dataset,),
        ).fetchall()
    out: list[dict] = []
    for row in rows:
        seg = _seg_dict(row)
        seg["conversation"] = row["ext_id"]
        out.append(seg)
    return out


def read_segment(dataset: str, segment_id: int) -> dict | None:
    """Read a single predicted ``segment`` row (with its conversation ext_id)."""
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT s.*, c.ext_id, c.dataset FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE s.id = %s AND c.dataset = %s",
            (segment_id, dataset),
        ).fetchone()
    if row is None:
        return None
    seg = _seg_dict(row)
    seg["conversation"] = row["ext_id"]
    return seg


# ---------------------------------------------------------------------------
# Effective segmentation (gold-when-boundary replaces predicted; inheritance)
# ---------------------------------------------------------------------------


def _overlap(a: list[int], b: list[int]) -> int:
    return len(set(a) & set(b))


def _inherit_label(span_indices: list[int], predicted: list[dict]) -> dict:
    best: dict | None = None
    best_overlap = 0
    for seg in predicted:
        overlap = _overlap(span_indices, seg["message_indices"])
        if overlap > best_overlap:
            best_overlap = overlap
            best = seg
    if best is None:
        return {"topic": None, "subtopic": None, "sentiment": None}
    return {
        "topic": best["topic"],
        "subtopic": best["subtopic"],
        "sentiment": best["sentiment"],
    }


def _effective_from(conv_ext: str, predicted: list[dict], gold: list[dict]) -> list[dict]:
    """Compute the EFFECTIVE segmentation from predicted + gold rows.

    A boundary edit REPLACES predicted per-conversation. With no boundary rows,
    predicted stands with relabel/confirm gold overlaid onto its topic/subtopic.
    """
    boundary = [g for g in gold if g["source"] in ("boundary", "gold")]

    if not boundary:
        overlay = {
            g["base_segment_id"]: g
            for g in gold
            if g["base_segment_id"] is not None and g["source"] in ("relabel", "confirm")
        }
        result: list[dict] = []
        for s in predicted:
            g = overlay.get(s["id"])
            result.append(
                {
                    "id": s["id"],
                    "conversation": conv_ext,
                    "chunk_index": s["chunk_index"],
                    "message_indices": s["message_indices"],
                    "summary": s["summary"],
                    "topic": g["topic"] if g is not None else s["topic"],
                    "subtopic": g["subtopic"] if g is not None else s["subtopic"],
                    "sentiment": s["sentiment"],
                    "label_confidence": s["label_confidence"],
                    "base_segment_id": s["id"],
                }
            )
        return result

    effective: list[dict] = []
    for i, g in enumerate(boundary):
        inherited = _inherit_label(g["message_indices"], predicted)
        effective.append(
            {
                "id": g["id"],
                "conversation": conv_ext,
                "chunk_index": i,
                "message_indices": g["message_indices"],
                "summary": None,
                "topic": g["topic"] if g["topic"] is not None else inherited["topic"],
                "subtopic": g["subtopic"]
                if g["subtopic"] is not None
                else inherited["subtopic"],
                "sentiment": g["sentiment"]
                if g["sentiment"] is not None
                else inherited["sentiment"],
                "label_confidence": None,
                "base_segment_id": g["base_segment_id"],
            }
        )
    return effective


def effective_segments(dataset: str, conversation: str) -> list[dict]:
    """Return the EFFECTIVE segmentation for one conversation (by ext_id)."""
    pool = get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, conversation),
        ).fetchone()
        if conv is None:
            return []
        predicted = _read_predicted(conv["id"], conn)
        gold = _read_gold(conv["id"], conn)
    return _effective_from(conversation, predicted, gold)


def read_gold_segments(dataset: str, conversation: str) -> list[dict]:
    """Read all gold ``segment`` rows for one conversation (ordered by id)."""
    pool = get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, conversation),
        ).fetchone()
        if conv is None:
            return []
        gold = _read_gold(conv["id"], conn)
    return [
        {
            "id": g["id"],
            "conversation": conversation,
            "message_indices": g["message_indices"],
            "topic": g["topic"],
            "subtopic": g["subtopic"],
            "sentiment": g["sentiment"],
            "base_segment_id": g["base_segment_id"],
            "source": g["source"],
            "reviewed_by": g["reviewed_by"],
            "reviewed_at": g["reviewed_at"],
        }
        for g in gold
    ]


# ---------------------------------------------------------------------------
# Conversation detail + paginated list
# ---------------------------------------------------------------------------


def conversation_detail(dataset: str, conversation: str) -> dict | None:
    """Return one conversation's messages + effective segments + gold rows."""
    pool = get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, conversation),
        ).fetchone()
        if conv is None:
            return None
        messages = serialize_messages(conv["id"], conn)
        predicted = _read_predicted(conv["id"], conn)
        gold = _read_gold(conv["id"], conn)
    effective = _effective_from(conversation, predicted, gold)
    return {"messages": messages, "effective": effective, "gold": gold}


def list_conversations(
    dataset: str,
    page: int = 1,
    page_size: int = 50,
    q: str | None = None,
    status: str | None = None,
    topic: str | None = None,
) -> dict:
    """Return a PAGINATED, searchable page of conversation summaries.

    ``q`` matches a conversation's ext_id OR any message content (trigram ILIKE).
    ``status`` (``reviewed``/``unreviewed``) and ``topic`` filter on the EFFECTIVE
    segmentation. Returns ``{items, total, page, page_size}`` where ``total`` is
    the count AFTER the ``q`` search but BEFORE status/topic (which are computed
    per-conversation on the page). Items are summaries:
    ``{conversation, message_count, segment_count, topics, reviewed_count, reviewed}``.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    offset = (page - 1) * page_size
    pool = get_pool()

    where = [sql.SQL("c.dataset = %s")]
    params: list[object] = [dataset]
    if q:
        like = f"%{q}%"
        where.append(
            sql.SQL(
                "(c.ext_id ILIKE %s OR EXISTS ("
                "SELECT 1 FROM message m WHERE m.conversation_id = c.id "
                "AND m.content ILIKE %s))"
            )
        )
        params.extend([like, like])
    where_sql = sql.SQL(" AND ").join(where)

    count_query = sql.SQL("SELECT count(*) AS n FROM conversation c WHERE {}").format(
        where_sql
    )
    page_query = sql.SQL(
        "SELECT c.id, c.ext_id, c.message_count FROM conversation c "
        "WHERE {} ORDER BY c.ext_id LIMIT %s OFFSET %s"
    ).format(where_sql)

    with pool.connection() as conn:
        total = conn.execute(count_query, params).fetchone()["n"]
        rows = conn.execute(page_query, [*params, page_size, offset]).fetchall()

        items: list[dict] = []
        for r in rows:
            predicted = _read_predicted(r["id"], conn)
            gold = _read_gold(r["id"], conn)
            effective = _effective_from(r["ext_id"], predicted, gold)
            reviewed_ids = _reviewed_base_ids(r["id"], conn)

            topics: list[str] = []
            reviewed_count = 0
            for seg in effective:
                t = seg["topic"]
                if t and t not in topics:
                    topics.append(t)
                base_id = seg.get("base_segment_id")
                if base_id is not None and base_id in reviewed_ids:
                    reviewed_count += 1
            segment_count = len(effective)
            summary = {
                "conversation": r["ext_id"],
                "message_count": r["message_count"],
                "segment_count": segment_count,
                "topics": topics,
                "reviewed_count": reviewed_count,
                "reviewed": segment_count > 0 and reviewed_count == segment_count,
            }
            if status == "reviewed" and not summary["reviewed"]:
                continue
            if status == "unreviewed" and summary["reviewed"]:
                continue
            if topic is not None and topic not in topics:
                continue
            items.append(summary)

    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# Review state + gold writes
# ---------------------------------------------------------------------------


def _reviewed_base_ids(conv_id: int, conn: psycopg.Connection) -> set[int]:
    rows = conn.execute(
        "SELECT base_segment_id FROM segment WHERE conversation_id = %s "
        "AND source IN ('relabel','confirm') AND base_segment_id IS NOT NULL "
        "AND reviewed_at IS NOT NULL",
        (conv_id,),
    ).fetchall()
    return {r["base_segment_id"] for r in rows}


def reviewed_base_segment_ids(dataset: str) -> set[int]:
    """Return predicted-segment ids that carry a reviewed relabel/confirm gold."""
    pool = get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.base_segment_id FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source IN ('relabel','confirm') "
            "AND s.base_segment_id IS NOT NULL AND s.reviewed_at IS NOT NULL",
            (dataset,),
        ).fetchall()
    return {r["base_segment_id"] for r in rows}


def gold_labels_by_base_segment(dataset: str) -> dict[int, dict]:
    """Return current gold ``{topic, subtopic}`` keyed by base predicted-segment id."""
    pool = get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT s.base_segment_id, s.topic, s.subtopic FROM segment s "
            "JOIN conversation c ON c.id = s.conversation_id "
            "WHERE c.dataset = %s AND s.source IN ('relabel','confirm') "
            "AND s.base_segment_id IS NOT NULL",
            (dataset,),
        ).fetchall()
    return {
        r["base_segment_id"]: {"topic": r["topic"], "subtopic": r["subtopic"]}
        for r in rows
    }


def _is_confirm(base_segment: dict, topic: str, subtopic: str) -> bool:
    return (base_segment.get("topic") == topic) and (base_segment.get("subtopic") == subtopic)


def upsert_gold_for_segment(
    dataset: str,
    base_segment: dict,
    topic: str,
    subtopic: str,
    sentiment: str | None,
    reviewed_by: str | None,
) -> int:
    """Mirror one predicted segment as a relabel/confirm gold row, marked reviewed.

    Replaces any prior relabel/confirm gold for this ``base_segment_id`` so a
    re-annotation does not accumulate duplicates. Returns the new gold id.
    """
    now = _utcnow()
    base_id = base_segment["id"]
    conv_id = base_segment["conversation_id"]
    source = "confirm" if _is_confirm(base_segment, topic, subtopic) else "relabel"
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute(
                "DELETE FROM segment WHERE base_segment_id = %s "
                "AND source IN ('relabel','confirm')",
                (base_id,),
            )
            row = conn.execute(
                "INSERT INTO segment "
                "(conversation_id, chunk_index, message_indices, topic, subtopic, "
                "sentiment, source, base_segment_id, reviewed_by, reviewed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    conv_id,
                    base_segment["chunk_index"],
                    list(base_segment["message_indices"]),
                    topic,
                    subtopic,
                    sentiment,
                    source,
                    base_id,
                    reviewed_by,
                    now,
                ),
            ).fetchone()
    return int(row["id"])


def clear_segment_annotation(dataset: str, base_segment_id: int) -> int:
    """Delete a predicted segment's relabel/confirm gold rows. Returns the count."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.transaction():
            cur = conn.execute(
                "DELETE FROM segment WHERE base_segment_id = %s "
                "AND source IN ('relabel','confirm')",
                (base_segment_id,),
            )
            deleted = cur.rowcount
    return int(deleted)


def inherited_boundary_spans(
    dataset: str, conversation: str, spans: list[dict]
) -> list[dict]:
    """Fill each boundary span's missing topic/subtopic/sentiment by INHERITING
    from the overlapping predicted segment, leaving explicit values untouched.
    """
    pool = get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, conversation),
        ).fetchone()
        predicted = _read_predicted(conv["id"], conn) if conv else []
    filled: list[dict] = []
    for span in spans:
        inherited = _inherit_label(span.get("message_indices", []), predicted)
        filled.append(
            {
                "message_indices": span.get("message_indices", []),
                "topic": span.get("topic")
                if span.get("topic") is not None
                else inherited["topic"],
                "subtopic": span.get("subtopic")
                if span.get("subtopic") is not None
                else inherited["subtopic"],
                "sentiment": span.get("sentiment")
                if span.get("sentiment") is not None
                else inherited["sentiment"],
            }
        )
    return filled


def replace_conversation_boundaries(
    dataset: str,
    conversation: str,
    spans: list[dict],
    reviewed_by: str | None,
) -> int:
    """REPLACE all gold for ``conversation`` with one boundary row per span.

    Returns the number of boundary rows written.
    """
    now = _utcnow()
    pool = get_pool()
    with pool.connection() as conn:
        conv = conn.execute(
            "SELECT id FROM conversation WHERE dataset = %s AND ext_id = %s",
            (dataset, conversation),
        ).fetchone()
        if conv is None:
            return 0
        conv_id = conv["id"]
        with conn.transaction():
            conn.execute(
                "DELETE FROM segment WHERE conversation_id = %s "
                "AND source IN ('relabel','confirm','boundary')",
                (conv_id,),
            )
            for i, span in enumerate(spans):
                conn.execute(
                    "INSERT INTO segment "
                    "(conversation_id, chunk_index, message_indices, topic, subtopic, "
                    "sentiment, source, base_segment_id, reviewed_by, reviewed_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'boundary', NULL, %s, %s)",
                    (
                        conv_id,
                        i,
                        list(span["message_indices"]),
                        span.get("topic"),
                        span.get("subtopic"),
                        span.get("sentiment"),
                        reviewed_by,
                        now,
                    ),
                )
    return len(spans)


# ---------------------------------------------------------------------------
# Taxonomy + stats
# ---------------------------------------------------------------------------


def load_taxonomy(dataset: str) -> list[dict]:
    """Return the dataset's user taxonomy rows."""
    pool = get_pool()
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT topic, subtopic, description FROM taxonomy "
            "WHERE dataset = %s AND kind = 'user' ORDER BY topic, subtopic",
            (dataset,),
        ).fetchall()
    return [dict(r) for r in rows]


def stats(dataset: str) -> dict:
    """Return review progress over the EFFECTIVE set: totals + per-topic counts."""
    pool = get_pool()
    total = 0
    reviewed = 0
    per_topic: dict[str, int] = {}
    with pool.connection() as conn:
        convs = conn.execute(
            "SELECT id, ext_id FROM conversation WHERE dataset = %s",
            (dataset,),
        ).fetchall()
        for c in convs:
            predicted = _read_predicted(c["id"], conn)
            gold = _read_gold(c["id"], conn)
            reviewed_ids = _reviewed_base_ids(c["id"], conn)
            for seg in _effective_from(c["ext_id"], predicted, gold):
                total += 1
                base_id = seg.get("base_segment_id")
                if base_id is not None and base_id in reviewed_ids:
                    reviewed += 1
                if seg["topic"]:
                    per_topic[seg["topic"]] = per_topic.get(seg["topic"], 0) + 1
    return {
        "total": total,
        "reviewed": reviewed,
        "unreviewed": total - reviewed,
        "per_topic": per_topic,
    }
