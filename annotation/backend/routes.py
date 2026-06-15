"""FastAPI routes for the annotation backend (prefix ``/api``)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from annotation.backend import db
from annotation.backend.auth import Identity, require_identity, sso_enabled
from annotation.backend.models import (
    AnnotateRequest,
    AnnotateResponse,
    AuthConfig,
    BoundaryRequest,
    BoundaryResponse,
    ClearAnnotationResponse,
    ConversationSummary,
    ConversationView,
    GoldSegment,
    Message,
    SegmentDetail,
    SegmentSummary,
    Stats,
    TaxonomyEntry,
)

auth_router = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_identity)])

_DATASETS_ROOT: Path | None = None


@auth_router.get("/auth/config", response_model=AuthConfig)
def get_auth_config() -> AuthConfig:
    """Unauthenticated: tell the frontend whether Google SSO is required."""
    return AuthConfig(sso_enabled=sso_enabled())


def set_datasets_root(root: Path | None) -> None:
    """Override the datasets root (used by tests to point at a tmp dir)."""
    global _DATASETS_ROOT
    _DATASETS_ROOT = root


def _root() -> Path | None:
    return _DATASETS_ROOT


def _require_dataset(dataset: str) -> None:
    if not db.output_db_path(dataset, _root()).exists():
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset!r}")


def _reviewer(identity: Identity | None, body_value: str | None) -> str | None:
    """When SSO is on, ``reviewed_by`` is the verified name; else the client value."""
    return identity.name if identity is not None else body_value


def _to_summary(
    seg: dict,
    reviewed_ids: set[int],
    gold_labels: dict[int, dict] | None = None,
) -> SegmentSummary:
    gold = (gold_labels or {}).get(seg["id"]) or {}
    return SegmentSummary(
        id=seg["id"],
        conversation=seg["conversation"],
        chunk_index=seg["chunk_index"],
        message_indices=seg["message_indices"],
        summary=seg["summary"],
        topic=seg["topic"],
        subtopic=seg["subtopic"],
        sentiment=seg["sentiment"],
        label_confidence=seg["label_confidence"],
        reviewed=seg["id"] in reviewed_ids,
        true_topic=gold.get("topic"),
        true_subtopic=gold.get("subtopic"),
    )


@router.get("/datasets", response_model=list[str])
def list_datasets() -> list[str]:
    """List dataset names that have an ``output.db``."""
    return db.list_datasets(_root())


@router.get("/datasets/{dataset}/segments", response_model=list[SegmentSummary])
def list_segments(
    dataset: str,
    status: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
) -> list[SegmentSummary]:
    """Return the review queue: run_segment rows joined with gold review state.

    Filters (all optional): ``status`` (``reviewed``/``unreviewed``), ``topic``
    exact match, ``max_confidence`` (keep segments at or below that confidence).
    """
    _require_dataset(dataset)
    reviewed_ids = db.reviewed_base_segment_ids(dataset, _root())
    segments = db.read_run_segments(dataset, _root())

    result: list[SegmentSummary] = []
    for seg in segments:
        is_reviewed = seg["id"] in reviewed_ids
        if status == "reviewed" and not is_reviewed:
            continue
        if status == "unreviewed" and is_reviewed:
            continue
        if topic is not None and seg["topic"] != topic:
            continue
        if max_confidence is not None and (
            seg["label_confidence"] is None or seg["label_confidence"] > max_confidence
        ):
            continue
        result.append(_to_summary(seg, reviewed_ids))
    return result


@router.get("/datasets/{dataset}/segments/{segment_id}", response_model=SegmentDetail)
def get_segment(dataset: str, segment_id: int) -> SegmentDetail:
    """Return a segment with its conversation messages, span, and siblings."""
    _require_dataset(dataset)
    seg = db.read_run_segment(dataset, segment_id, _root())
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Unknown segment: {segment_id}")

    reviewed_ids = db.reviewed_base_segment_ids(dataset, _root())
    gold_labels = db.gold_labels_by_base_segment(dataset, _root())
    messages = db.serialize_messages(
        db.conversation_messages(dataset, seg["conversation"], _root())
    )
    by_index = {m["index"]: m for m in messages}
    span = [
        Message(**by_index[i]) for i in seg["message_indices"] if i in by_index
    ]
    siblings = [
        _to_summary(s, reviewed_ids, gold_labels)
        for s in db.read_run_segments(dataset, _root())
        if s["conversation"] == seg["conversation"]
    ]
    return SegmentDetail(
        segment=_to_summary(seg, reviewed_ids, gold_labels),
        messages=[Message(**m) for m in messages],
        span=span,
        siblings=siblings,
    )


@router.get("/datasets/{dataset}/conversations", response_model=list[ConversationSummary])
def list_conversations(dataset: str) -> list[ConversationSummary]:
    """Return one row per conversation/user for the review queue.

    Groups ``run_segment`` rows by conversation (segment count, distinct
    topics), counts messages via the dataset adapter, and folds in review
    state from gold.db.
    """
    _require_dataset(dataset)
    reviewed_ids = db.reviewed_base_segment_ids(dataset, _root())
    message_counts = db.conversation_message_counts(dataset, _root())
    segments = db.read_run_segments(dataset, _root())

    grouped: dict[str, dict] = {}
    for seg in segments:
        conv = seg["conversation"]
        row = grouped.setdefault(
            conv, {"segment_count": 0, "topics": [], "reviewed_count": 0}
        )
        row["segment_count"] += 1
        topic = seg["topic"]
        if topic and topic not in row["topics"]:
            row["topics"].append(topic)
        if seg["id"] in reviewed_ids:
            row["reviewed_count"] += 1

    result: list[ConversationSummary] = []
    for conv, row in grouped.items():
        result.append(
            ConversationSummary(
                conversation=conv,
                message_count=message_counts.get(conv, 0),
                segment_count=row["segment_count"],
                topics=row["topics"],
                reviewed_count=row["reviewed_count"],
                reviewed=row["reviewed_count"] == row["segment_count"],
            )
        )
    return result


@router.get("/datasets/{dataset}/conversations/{conversation}", response_model=ConversationView)
def get_conversation(dataset: str, conversation: str) -> ConversationView:
    """Return a conversation's messages plus all its segments (boundary view)."""
    _require_dataset(dataset)
    reviewed_ids = db.reviewed_base_segment_ids(dataset, _root())
    gold_labels = db.gold_labels_by_base_segment(dataset, _root())
    messages = db.serialize_messages(
        db.conversation_messages(dataset, conversation, _root())
    )
    segments = [
        _to_summary(s, reviewed_ids, gold_labels)
        for s in db.read_run_segments(dataset, _root())
        if s["conversation"] == conversation
    ]
    gold = [
        GoldSegment(**g) for g in db.read_gold_segments(dataset, conversation, _root())
    ]
    return ConversationView(
        conversation=conversation,
        messages=[Message(**m) for m in messages],
        segments=segments,
        gold_segments=gold,
    )


@router.get("/datasets/{dataset}/taxonomy", response_model=list[TaxonomyEntry])
def get_taxonomy(dataset: str) -> list[TaxonomyEntry]:
    """Return the dataset's user taxonomy from the metadata provider."""
    _require_dataset(dataset)
    rows = db.load_taxonomy(dataset, _root())
    return [
        TaxonomyEntry(
            topic=r.get("topic"),
            subtopic=r.get("subtopic"),
            description=r.get("description"),
        )
        for r in rows
    ]


@router.post(
    "/datasets/{dataset}/segments/{segment_id}/annotate", response_model=AnnotateResponse
)
def annotate_segment(
    dataset: str,
    segment_id: int,
    request: AnnotateRequest,
    identity: Identity | None = Depends(require_identity),
) -> AnnotateResponse:
    """Write a gold_segment mirroring the base span with corrected labels."""
    _require_dataset(dataset)
    seg = db.read_run_segment(dataset, segment_id, _root())
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Unknown segment: {segment_id}")

    gold_id = db.upsert_gold_for_segment(
        dataset,
        seg,
        topic=request.true_topic,
        subtopic=request.true_subtopic,
        sentiment=request.sentiment,
        reviewed_by=_reviewer(identity, request.reviewed_by),
        root=_root(),
    )
    return AnnotateResponse(gold_segment_id=gold_id)


@router.delete(
    "/datasets/{dataset}/segments/{segment_id}/annotate",
    response_model=ClearAnnotationResponse,
)
def clear_segment_annotation(
    dataset: str,
    segment_id: int,
    identity: Identity | None = Depends(require_identity),
) -> ClearAnnotationResponse:
    """Clear a segment's gold annotation, reverting it to unannotated.

    Deletes the segment's relabel/confirm gold_segment row(s) + its review_state
    entry so undoing a first annotation reverts the segment to unreviewed.
    """
    _require_dataset(dataset)
    seg = db.read_run_segment(dataset, segment_id, _root())
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Unknown segment: {segment_id}")

    deleted = db.clear_segment_annotation(dataset, segment_id, _root())
    return ClearAnnotationResponse(segment_id=segment_id, deleted=deleted)


@router.post(
    "/datasets/{dataset}/conversations/{conversation}/boundaries",
    response_model=BoundaryResponse,
)
def replace_boundaries(
    dataset: str,
    conversation: str,
    request: BoundaryRequest,
    identity: Identity | None = Depends(require_identity),
) -> BoundaryResponse:
    """REPLACE all gold_segments for a conversation with the posted spans."""
    _require_dataset(dataset)
    written = db.replace_conversation_boundaries(
        dataset,
        conversation,
        spans=[s.model_dump() for s in request.segments],
        reviewed_by=_reviewer(identity, request.reviewed_by),
        root=_root(),
    )
    return BoundaryResponse(conversation=conversation, gold_segments_written=written)


@router.get("/datasets/{dataset}/stats", response_model=Stats)
def get_stats(dataset: str) -> Stats:
    """Return review progress: totals and per-topic counts."""
    _require_dataset(dataset)
    reviewed_ids = db.reviewed_base_segment_ids(dataset, _root())
    segments = db.read_run_segments(dataset, _root())
    total = len(segments)
    reviewed = sum(1 for s in segments if s["id"] in reviewed_ids)
    per_topic = Counter(s["topic"] for s in segments if s["topic"])
    return Stats(
        total=total,
        reviewed=reviewed,
        unreviewed=total - reviewed,
        per_topic=dict(per_topic),
    )
