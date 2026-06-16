import { http, HttpResponse } from "msw";
import type {
  AuthConfig,
  ConversationSummary,
  ConversationView,
  Stats,
  TaxonomyEntry,
} from "../../api";

// Reusable, realistic `/api` responses mirroring annotation/backend/models.py.
// Component tests render real components against these so a field rename on
// either side (frontend type or backend payload) surfaces as a failing render
// rather than a silent mismatch — the exact integration class the re-segment
// bug exposed.

export const DATASET = "e2e-fixture";

export const datasets: string[] = [DATASET];

export const authConfig: AuthConfig = { sso_enabled: false };

export const taxonomy: TaxonomyEntry[] = [
  {
    topic: "billing",
    subtopic: "refund_request",
    description: "Customer asks for a refund.",
  },
  {
    topic: "billing",
    subtopic: "invoice_question",
    description: "Customer asks about an invoice.",
  },
  {
    topic: "technical_support",
    subtopic: "login_issue",
    description: "Customer cannot sign in.",
  },
];

export const stats: Stats = {
  total: 2,
  reviewed: 1,
  unreviewed: 1,
  per_topic: { billing: 1, technical_support: 1 },
};

export const conversations: ConversationSummary[] = [
  {
    conversation: "conv-001",
    message_count: 4,
    segment_count: 2,
    topics: ["billing", "technical_support"],
    reviewed_count: 1,
    reviewed: false,
  },
  {
    conversation: "conv-002",
    message_count: 2,
    segment_count: 1,
    topics: ["billing"],
    reviewed_count: 1,
    reviewed: true,
  },
];

// A conversation detail that carries BOTH the machine `segments` and the
// human `gold_segments` — the two arrays the re-segment feature confuses.
// Topic names already saved for the dataset, most-frequent first — the
// `used-topics` endpoint feeds these into the combobox alongside the taxonomy.
export const usedTopics: string[] = ["billing", "shipping_delay"];

// Per-labeler worklist: which conversations each labeler is assigned. Drives the
// `?labeler=` filter the queue handler honors below.
export const worklist: Record<string, string[]> = {
  labeler_a: ["conv-001"],
  labeler_b: ["conv-002"],
};

export const conversationView: ConversationView = {
  conversation: "conv-001",
  frozen_boundaries: false,
  messages: [
    {
      index: 0,
      id: "m0",
      type: "user",
      message: "I was charged twice for my subscription.",
      createdAt: "2026-01-01T10:00:00Z",
    },
    {
      index: 1,
      id: "m1",
      type: "assistant",
      message: "I can help with that refund.",
      createdAt: "2026-01-01T10:00:30Z",
    },
    {
      index: 2,
      id: "m2",
      type: "user",
      message: "Also I cannot log in on mobile.",
      createdAt: "2026-01-01T10:05:00Z",
    },
    {
      index: 3,
      id: "m3",
      type: "assistant",
      message: "Let us reset your session.",
      createdAt: "2026-01-01T10:05:20Z",
    },
  ],
  segments: [
    {
      id: 101,
      conversation: "conv-001",
      chunk_index: 0,
      message_indices: [0, 1],
      summary: "Double-charge refund request.",
      topic: "billing",
      subtopic: "refund_request",
      sentiment: "negative",
      label_confidence: 0.82,
      reviewed: false,
      true_topic: null,
      true_subtopic: null,
    },
    {
      id: 102,
      conversation: "conv-001",
      chunk_index: 1,
      message_indices: [2, 3],
      summary: "Mobile login failure.",
      topic: "technical_support",
      subtopic: "login_issue",
      sentiment: "neutral",
      label_confidence: 0.74,
      reviewed: true,
      true_topic: "technical_support",
      true_subtopic: "login_issue",
    },
  ],
  gold_segments: [
    {
      id: 9001,
      conversation: "conv-001",
      message_indices: [2, 3],
      topic: "technical_support",
      subtopic: "login_issue",
      sentiment: "neutral",
      base_segment_id: 102,
      source: "human",
      reviewed_by: "Ada Lovelace",
      reviewed_at: "2026-01-02T09:00:00Z",
    },
  ],
};

const base = "/api";

export const handlers = [
  http.get(`${base}/auth/config`, () => HttpResponse.json(authConfig)),

  http.get(`${base}/datasets`, () => HttpResponse.json(datasets)),

  // Server-driven pagination + search: honor page/page_size/q/status/topic so
  // component tests exercise the real refetch-on-change contract.
  http.get(`${base}/datasets/:dataset/conversations`, ({ request }) => {
    const url = new URL(request.url);
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "50");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const status = url.searchParams.get("status");
    const topic = url.searchParams.get("topic");
    const labeler = url.searchParams.get("labeler");

    const filtered = conversations.filter((c) => {
      if (q && !c.conversation.toLowerCase().includes(q)) return false;
      if (status === "reviewed" && !c.reviewed) return false;
      if (status === "unreviewed" && c.reviewed) return false;
      if (topic && !c.topics.includes(topic)) return false;
      if (labeler && !worklist[labeler]?.includes(c.conversation)) return false;
      return true;
    });

    const start = (page - 1) * pageSize;
    return HttpResponse.json({
      items: filtered.slice(start, start + pageSize),
      total: filtered.length,
      page,
      page_size: pageSize,
    });
  }),

  http.get(`${base}/datasets/:dataset/conversations/:conversation`, () =>
    HttpResponse.json(conversationView),
  ),

  http.get(`${base}/datasets/:dataset/taxonomy`, () =>
    HttpResponse.json(taxonomy),
  ),

  http.get(`${base}/datasets/:dataset/used-topics`, () =>
    HttpResponse.json({ topics: usedTopics }),
  ),

  http.get(`${base}/datasets/:dataset/stats`, () => HttpResponse.json(stats)),
];
