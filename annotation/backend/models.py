"""Pydantic request/response models for the annotation backend."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Message(BaseModel):
    """One normalized conversation message, with its positional index."""

    index: int
    id: str
    type: str
    message: str
    createdAt: str | None = None


class SegmentSummary(BaseModel):
    """A machine segment as listed in the review queue."""

    id: int
    conversation: str
    chunk_index: int
    message_indices: list[int]
    summary: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    sentiment: str | None = None
    label_confidence: float | None = None
    bertopic_topic: str | None = None
    bertopic_subtopic: str | None = None
    reviewed: bool = False
    true_topic: str | None = None
    true_subtopic: str | None = None


class SegmentDetail(BaseModel):
    """A segment plus its conversation context for the annotation panel."""

    segment: SegmentSummary
    messages: list[Message]
    span: list[Message]
    siblings: list[SegmentSummary]


class GoldSegment(BaseModel):
    """A persisted human-gold segment."""

    id: int
    conversation: str
    message_indices: list[int]
    topic: str | None = None
    subtopic: str | None = None
    sentiment: str | None = None
    base_segment_id: int | None = None
    source: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None


class ConversationSummary(BaseModel):
    """One row in the user/conversation review queue."""

    conversation: str
    domain: str | None = None
    message_count: int
    segment_count: int
    topics: list[str] = Field(default_factory=list)
    reviewed_count: int
    reviewed: bool = False


class ConversationPage(BaseModel):
    """A paginated page of conversation summaries for the review queue."""

    items: list[ConversationSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class ConversationView(BaseModel):
    """All messages + all machine segments for the boundary-edit view."""

    conversation: str
    domain: str | None = None
    messages: list[Message]
    segments: list[SegmentSummary]
    gold_segments: list[GoldSegment]
    frozen_boundaries: bool = False


class TaxonomyEntry(BaseModel):
    """One taxonomy (domain, topic, subtopic) row from the metadata provider."""

    domain: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    description: str | None = None


class UsedTopics(BaseModel):
    """Distinct topic names already used for a dataset, most-frequent first."""

    topics: list[str] = Field(default_factory=list)


class Labelers(BaseModel):
    """Distinct worklist labelers for a dataset, sorted (may be empty)."""

    labelers: list[str] = Field(default_factory=list)


class BertopicTopicCount(BaseModel):
    """A distinct source topic (nav category) with its domain + per-conversation count."""

    topic: str
    domain: str | None = None
    count: int


class BertopicSubtopicCount(BaseModel):
    """A distinct source subtopic with its parent topic, domain, and per-conversation count."""

    subtopic: str
    topic: str | None = None
    domain: str | None = None
    count: int


class BertopicLabels(BaseModel):
    """Distinct BERTopic topics + subtopics (with parent topic) and counts."""

    topics: list[BertopicTopicCount] = Field(default_factory=list)
    subtopics: list[BertopicSubtopicCount] = Field(default_factory=list)


class TaxonomyCreateRequest(BaseModel):
    """Create a taxonomy option (idempotent on dataset/domain/kind/topic/subtopic)."""

    topic: str
    subtopic: str | None = None
    description: str | None = None
    kind: str = "user"
    domain: str | None = None


class TaxonomyRenameRequest(BaseModel):
    """Rename a taxonomy option (within its domain), cascading to segment labels.

    Topic-level rename leaves ``subtopic``/``new_subtopic`` unset; subtopic-level
    rename sets both the matched ``subtopic`` and the ``new_subtopic`` it becomes.
    """

    topic: str
    new_topic: str
    subtopic: str | None = None
    new_subtopic: str | None = None
    kind: str = "user"
    domain: str | None = None


class TaxonomyMergeRequest(BaseModel):
    """Fold ``from_topic`` into ``into_topic`` within a domain (labels cascade)."""

    from_topic: str
    into_topic: str
    kind: str = "user"
    domain: str | None = None


class TaxonomyMutationResponse(BaseModel):
    """Result of a taxonomy create/rename/merge/delete write."""

    dataset: str
    cascaded: int = 0
    deleted: int = 0


class AnnotateRequest(BaseModel):
    """Relabel/confirm one base segment's topic/subtopic."""

    true_topic: str
    true_subtopic: str
    sentiment: str | None = None
    reviewed_by: str | None = None


class BoundarySpan(BaseModel):
    """One corrected gold span in a boundary edit."""

    message_indices: list[int]
    topic: str | None = None
    subtopic: str | None = None
    sentiment: str | None = None


class BoundaryRequest(BaseModel):
    """Replace a conversation's gold spans (split/merge)."""

    segments: list[BoundarySpan]
    reviewed_by: str | None = None


class AnnotateResponse(BaseModel):
    """Result of an annotate write."""

    gold_segment_id: int
    reviewed: bool = True


class ClearAnnotationResponse(BaseModel):
    """Result of clearing a segment's gold annotation."""

    segment_id: int
    deleted: int
    reviewed: bool = False


class BoundaryResponse(BaseModel):
    """Result of a boundary replace."""

    conversation: str
    gold_segments_written: int


class AuthConfig(BaseModel):
    """Whether Google SSO is required (unauthenticated config endpoint)."""

    sso_enabled: bool


class Stats(BaseModel):
    """Review progress for a dataset.

    ``reviewed_match``/``reviewed_mismatch`` compare each reviewed gold segment's
    human topic/subtopic (slugs) against its BERTopic source label (slugified) —
    a quick agreement signal that drives the mismatch quick-filter.
    """

    total: int
    reviewed: int
    unreviewed: int
    per_topic: dict[str, int] = Field(default_factory=dict)
    reviewed_match: int = 0
    reviewed_mismatch: int = 0
