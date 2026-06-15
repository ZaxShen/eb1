// Typed client for the annotation FastAPI backend. Shapes mirror
// annotation/backend/models.py exactly. All paths go through the Vite
// dev proxy at /api -> http://localhost:8000.

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

export interface ConversationView {
  conversation: string;
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
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
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

export const api = {
  listDatasets: () => request<string[]>("/datasets"),

  listConversations: async (
    dataset: string,
    filters: ConversationFilters = {},
  ): Promise<ConversationSummary[]> => {
    const rows = await request<ConversationSummary[]>(
      `/datasets/${encodeURIComponent(dataset)}/conversations`,
    );
    return rows.filter((row) => {
      if (filters.status === "reviewed" && !row.reviewed) return false;
      if (filters.status === "unreviewed" && row.reviewed) return false;
      if (filters.topic && !row.topics.includes(filters.topic)) return false;
      return true;
    });
  },

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

  annotate: (dataset: string, segmentId: number, body: AnnotateRequest) =>
    request<AnnotateResponse>(
      `/datasets/${encodeURIComponent(dataset)}/segments/${segmentId}/annotate`,
      { method: "POST", body: JSON.stringify(body) },
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
