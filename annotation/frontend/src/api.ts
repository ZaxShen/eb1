// Typed client for the annotation FastAPI backend. Shapes mirror
// annotation/backend/models.py exactly. All paths go through the Vite
// dev proxy at /api -> http://localhost:8000.
//
// Contract: the hand-written interfaces below are asserted assignable to the
// generated OpenAPI schema (src/api/schema.d.ts, `npm run types:gen`) at the
// bottom of this file, so a backend field rename becomes a TypeScript error.

import type { components } from "./api/schema";

type Schema = components["schemas"];

export interface Message {
  index: number;
  id: string;
  type: string;
  message: string;
  createdAt: string | null;
}

export interface SegmentSummary {
  id: number;
  conversation: string;
  chunk_index: number;
  message_indices: number[];
  summary: string | null;
  topic: string | null;
  subtopic: string | null;
  sentiment: string | null;
  label_confidence: number | null;
  reviewed: boolean;
  true_topic: string | null;
  true_subtopic: string | null;
}

export interface SegmentDetail {
  segment: SegmentSummary;
  messages: Message[];
  span: Message[];
  siblings: SegmentSummary[];
}

export interface GoldSegment {
  id: number;
  conversation: string;
  message_indices: number[];
  topic: string | null;
  subtopic: string | null;
  sentiment: string | null;
  base_segment_id: number | null;
  source: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface ConversationSummary {
  conversation: string;
  message_count: number;
  segment_count: number;
  topics: string[];
  reviewed_count: number;
  reviewed: boolean;
}

export interface ConversationPage {
  items: ConversationSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface ConversationView {
  conversation: string;
  frozen_boundaries: boolean;
  messages: Message[];
  segments: SegmentSummary[];
  gold_segments: GoldSegment[];
}

export interface TaxonomyEntry {
  topic: string | null;
  subtopic: string | null;
  description: string | null;
}

export interface AnnotateRequest {
  true_topic: string;
  true_subtopic: string;
  sentiment?: string | null;
  reviewed_by?: string | null;
}

export interface AnnotateResponse {
  gold_segment_id: number;
  reviewed: boolean;
}

export interface ClearAnnotationResponse {
  segment_id: number;
  deleted: number;
  reviewed: boolean;
}

export interface BoundarySpan {
  message_indices: number[];
  topic?: string | null;
  subtopic?: string | null;
  sentiment?: string | null;
}

export interface BoundaryRequest {
  segments: BoundarySpan[];
  reviewed_by?: string | null;
}

export interface BoundaryResponse {
  conversation: string;
  gold_segments_written: number;
}

export interface UsedTopics {
  topics: string[];
}

export interface Stats {
  total: number;
  reviewed: number;
  unreviewed: number;
  per_topic: Record<string, number>;
}

export interface SegmentFilters {
  status?: "reviewed" | "unreviewed";
  topic?: string;
  max_confidence?: number;
}

export interface ConversationFilters {
  status?: "reviewed" | "unreviewed";
  topic?: string;
  labeler?: string;
}

export interface ConversationQuery extends ConversationFilters {
  page?: number;
  pageSize?: number;
  q?: string;
}

let authToken: string | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  const res = await fetch(`/api${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const out = search.toString();
  return out ? `?${out}` : "";
}

export interface AuthConfig {
  sso_enabled: boolean;
}

export const api = {
  getAuthConfig: () => request<AuthConfig>("/auth/config"),

  listDatasets: () => request<string[]>("/datasets"),

  // The backend conversations-list is server-side paginated + searchable,
  // returning `{items,total,page,page_size}`. Query params (page/page_size/q/
  // status/topic) drive a SINGLE page so the queue never loads all ~1.85M rows.
  listConversations: (
    dataset: string,
    query: ConversationQuery = {},
  ): Promise<ConversationPage> =>
    request<ConversationPage>(
      `/datasets/${encodeURIComponent(dataset)}/conversations${qs({
        page: query.page,
        page_size: query.pageSize,
        q: query.q,
        status: query.status,
        topic: query.topic,
        labeler: query.labeler,
      })}`,
    ),

  listSegments: (dataset: string, filters: SegmentFilters = {}) =>
    request<SegmentSummary[]>(
      `/datasets/${encodeURIComponent(dataset)}/segments${qs({
        status: filters.status,
        topic: filters.topic,
        max_confidence: filters.max_confidence,
      })}`,
    ),

  getSegment: (dataset: string, segmentId: number) =>
    request<SegmentDetail>(
      `/datasets/${encodeURIComponent(dataset)}/segments/${segmentId}`,
    ),

  getConversation: (dataset: string, conversation: string) =>
    request<ConversationView>(
      `/datasets/${encodeURIComponent(dataset)}/conversations/${encodeURIComponent(conversation)}`,
    ),

  getTaxonomy: (dataset: string) =>
    request<TaxonomyEntry[]>(
      `/datasets/${encodeURIComponent(dataset)}/taxonomy`,
    ),

  // Distinct topic names already saved for this dataset (most-frequent first).
  // Unioned with the taxonomy in the topic combobox for open-vocab suggestions.
  usedTopics: (dataset: string): Promise<string[]> =>
    request<UsedTopics>(
      `/datasets/${encodeURIComponent(dataset)}/used-topics`,
    ).then((r) => r.topics),

  annotate: (dataset: string, segmentId: number, body: AnnotateRequest) =>
    request<AnnotateResponse>(
      `/datasets/${encodeURIComponent(dataset)}/segments/${segmentId}/annotate`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  clearAnnotation: (dataset: string, segmentId: number) =>
    request<ClearAnnotationResponse>(
      `/datasets/${encodeURIComponent(dataset)}/segments/${segmentId}/annotate`,
      { method: "DELETE" },
    ),

  replaceBoundaries: (
    dataset: string,
    conversation: string,
    body: BoundaryRequest,
  ) =>
    request<BoundaryResponse>(
      `/datasets/${encodeURIComponent(dataset)}/conversations/${encodeURIComponent(conversation)}/boundaries`,
      { method: "POST", body: JSON.stringify(body) },
    ),

  getStats: (dataset: string) =>
    request<Stats>(`/datasets/${encodeURIComponent(dataset)}/stats`),
};

// Compile-time contract: each response type must stay assignable to the
// generated backend schema. A renamed/removed backend field breaks `tsc`.
type AssertAssignable<T extends U, U> = T;
export type SchemaContract = [
  AssertAssignable<Message, Schema["Message"]>,
  AssertAssignable<SegmentSummary, Schema["SegmentSummary"]>,
  AssertAssignable<SegmentDetail, Schema["SegmentDetail"]>,
  AssertAssignable<GoldSegment, Schema["GoldSegment"]>,
  AssertAssignable<ConversationSummary, Schema["ConversationSummary"]>,
  AssertAssignable<ConversationPage, Schema["ConversationPage"]>,
  AssertAssignable<ConversationView, Schema["ConversationView"]>,
  AssertAssignable<TaxonomyEntry, Schema["TaxonomyEntry"]>,
  AssertAssignable<AnnotateResponse, Schema["AnnotateResponse"]>,
  AssertAssignable<ClearAnnotationResponse, Schema["ClearAnnotationResponse"]>,
  AssertAssignable<BoundaryResponse, Schema["BoundaryResponse"]>,
  AssertAssignable<AuthConfig, Schema["AuthConfig"]>,
  AssertAssignable<Stats, Schema["Stats"]>,
  AssertAssignable<UsedTopics, Schema["UsedTopics"]>,
];

