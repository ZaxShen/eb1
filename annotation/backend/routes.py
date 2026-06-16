"""FastAPI routes for the annotation backend (prefix ``/api``).

Backed by PostgreSQL (``annotation.backend.db``). The conversations-list is
server-side paginated + searchable; every other endpoint returns the EFFECTIVE
segmentation (gold-when-boundary-edited replaces predicted; inherited topics).
"""

from __future__ import annotations

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
    ConversationPage,
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


@auth_router.get("/auth/config", response_model=AuthConfig)
def get_auth_config() -> AuthConfig:
    """Unauthenticated: tell the frontend whether Google SSO is required."""
    return AuthConfig(sso_enabled=sso_enabled())


def _require_dataset(dataset: str) -> None:
    if not db.dataset_exists(dataset):
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset!r}")


def _reviewer(identity: Identity | None, body_value: str | None) -> str | None:
    """When SSO is on, ``reviewed_by`` is the verified name; else the client value."""
    return identity.name if identity is not None else body_value


def _effective_summary(
    seg: dict,
    reviewed_ids: set[int],
    gold_labels: dict[int, dict] | None = None,
) -> SegmentSummary:
    """Build a SegmentSummary from an effective-segment dict.

    Review state and gold true_topic/true_subtopic resolve via the effective
    span's ``base_segment_id`` (the predicted segment it derives from).
    """
    base_id = seg.get("base_segment_id")
    gold = (gold_labels or {}).get(base_id) or {}
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
        reviewed=base_id is not None and base_id in reviewed_ids,
        true_topic=gold.get("topic"),
        true_subtopic=gold.get("subtopic"),
    )


def _resolve_effective(predicted_seg: dict, effective: list[dict]) -> dict:
    """Map a predicted segment to its effective span (exact id else most overlap)."""
    for seg in effective:
        if seg["id"] == predicted_seg["id"] and seg.get("base_segment_id") == (
            predicted_seg["id"]
        ):
            return seg
    target = set(predicted_seg["message_indices"])
    best = None
    best_overlap = -1
    for seg in effective:
        overlap = len(target & set(seg["message_indices"]))
        if overlap > best_overlap:
            best_overlap = overlap
            best = seg
    return best if best is not None else predicted_seg


@router.get("/datasets", response_model=list[str])
def list_datasets() -> list[str]:
    """List registered dataset names."""
    return db.list_datasets()


@router.get("/datasets/{dataset}/segments", response_model=list[SegmentSummary])
def list_segments(
    dataset: str,
    status: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    max_confidence: float | None = Query(default=None),
) -> list[SegmentSummary]:
    """Return the predicted-segment review queue with gold review state.

    Filters (optional): ``status`` (``reviewed``/``unreviewed``), ``topic`` exact
    match, ``max_confidence`` (keep segments at or below that confidence).
    """
    _require_dataset(dataset)
    reviewed_ids = db.reviewed_base_segment_ids(dataset)
    gold_labels = db.gold_labels_by_base_segment(dataset)
    segments = db.read_predicted_segments(dataset)

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
        summary = _effective_summary(
            {**seg, "base_segment_id": seg["id"]}, reviewed_ids, gold_labels
        )
        result.append(summary)
    return result


@router.get("/datasets/{dataset}/segments/{segment_id}", response_model=SegmentDetail)
def get_segment(dataset: str, segment_id: int) -> SegmentDetail:
    """Return a segment with its conversation messages, span, and siblings."""
    _require_dataset(dataset)
    seg = db.read_segment(dataset, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Unknown segment: {segment_id}")

    reviewed_ids = db.reviewed_base_segment_ids(dataset)
    gold_labels = db.gold_labels_by_base_segment(dataset)
    detail = db.conversation_detail(dataset, seg["conversation"])
    messages = detail["messages"] if detail else []
    by_index = {m["index"]: m for m in messages}
    effective = detail["effective"] if detail else []

    effective_seg = _resolve_effective(seg, effective)
    span = [
        Message(**by_index[i])
        for i in effective_seg["message_indices"]
        if i in by_index
    ]
    siblings = [
        _effective_summary(s, reviewed_ids, gold_labels) for s in effective
    ]
    return SegmentDetail(
        segment=_effective_summary(effective_seg, reviewed_ids, gold_labels),
        messages=[Message(**m) for m in messages],
        span=span,
        siblings=siblings,
    )


@router.get("/datasets/{dataset}/conversations", response_model=ConversationPage)
def list_conversations(
    dataset: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    topic: str | None = Query(default=None),
) -> ConversationPage:
    """Return a PAGINATED, searchable page of conversation summaries.

    ``q`` matches conversation ext_id OR message content. ``status``/``topic``
    filter on the effective segmentation. Shape: ``{items,total,page,page_size}``.
    """
    _require_dataset(dataset)
    result = db.list_conversations(
        dataset, page=page, page_size=page_size, q=q, status=status, topic=topic
    )
    return ConversationPage(
        items=[ConversationSummary(**row) for row in result["items"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )


@router.get(
    "/datasets/{dataset}/conversations/{conversation}", response_model=ConversationView
)
def get_conversation(dataset: str, conversation: str) -> ConversationView:
    """Return a conversation's messages plus its effective + gold segments."""
    _require_dataset(dataset)
    detail = db.conversation_detail(dataset, conversation)
    if detail is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown conversation: {conversation!r}"
        )
    reviewed_ids = db.reviewed_base_segment_ids(dataset)
    gold_labels = db.gold_labels_by_base_segment(dataset)
    segments = [
        _effective_summary(s, reviewed_ids, gold_labels) for s in detail["effective"]
    ]
    gold = [
        GoldSegment(
            id=g["id"],
            conversation=conversation,
            message_indices=g["message_indices"],
            topic=g["topic"],
            subtopic=g["subtopic"],
            sentiment=g["sentiment"],
            base_segment_id=g["base_segment_id"],
            source=g["source"],
            reviewed_by=g["reviewed_by"],
            reviewed_at=g["reviewed_at"].isoformat()
            if hasattr(g["reviewed_at"], "isoformat")
            else g["reviewed_at"],
        )
        for g in detail["gold"]
    ]
    return ConversationView(
        conversation=conversation,
        messages=[Message(**m) for m in detail["messages"]],
        segments=segments,
        gold_segments=gold,
    )


@router.get("/datasets/{dataset}/taxonomy", response_model=list[TaxonomyEntry])
def get_taxonomy(dataset: str) -> list[TaxonomyEntry]:
    """Return the dataset's user taxonomy."""
    _require_dataset(dataset)
    rows = db.load_taxonomy(dataset)
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
    """Write a relabel/confirm gold mirroring the predicted span with new labels."""
    _require_dataset(dataset)
    seg = db.read_segment(dataset, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Unknown segment: {segment_id}")

    gold_id = db.upsert_gold_for_segment(
        dataset,
        seg,
        topic=request.true_topic,
        subtopic=request.true_subtopic,
        sentiment=request.sentiment,
        reviewed_by=_reviewer(identity, request.reviewed_by),
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
    """Clear a segment's relabel/confirm gold, reverting it to unannotated."""
    _require_dataset(dataset)
    seg = db.read_segment(dataset, segment_id)
    if seg is None:
        raise HTTPException(status_code=404, detail=f"Unknown segment: {segment_id}")

    deleted = db.clear_segment_annotation(dataset, segment_id)
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
    """REPLACE all gold for a conversation with the posted spans (split/merge).

    Each new span inherits topic/subtopic/sentiment from the overlapping
    predicted segment when the client leaves them unset.
    """
    _require_dataset(dataset)
    spans = db.inherited_boundary_spans(
        dataset, conversation, [s.model_dump() for s in request.segments]
    )
    written = db.replace_conversation_boundaries(
        dataset,
        conversation,
        spans=spans,
        reviewed_by=_reviewer(identity, request.reviewed_by),
    )
    return BoundaryResponse(conversation=conversation, gold_segments_written=written)


@router.get("/datasets/{dataset}/stats", response_model=Stats)
def get_stats(dataset: str) -> Stats:
    """Return review progress: totals and per-topic counts on the effective set."""
    _require_dataset(dataset)
    result = db.stats(dataset)
    return Stats(
        total=result["total"],
        reviewed=result["reviewed"],
        unreviewed=result["unreviewed"],
        per_topic=result["per_topic"],
    )
