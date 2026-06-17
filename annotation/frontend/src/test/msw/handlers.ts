import { http, HttpResponse } from "msw";
import type {
  AuthConfig,
  BertopicLabels,
  ConversationSummary,
  ConversationView,
  Stats,
  TaxonomyCreateRequest,
  TaxonomyEntry,
  TaxonomyMergeRequest,
  TaxonomyRenameRequest,
} from "../../api";

// Reusable, realistic `/api` responses mirroring annotation/backend/models.py.
// Component tests render real components against these so a field rename on
// either side (frontend type or backend payload) surfaces as a failing render
// rather than a silent mismatch — the exact integration class the re-segment
// bug exposed.

export const DATASET = "e2e-fixture";

export const datasets: string[] = [DATASET];

export const authConfig: AuthConfig = { sso_enabled: false };

// Mutable so the taxonomy CRUD handlers below can add/rename/merge/delete rows
// and a subsequent GET /taxonomy reflects the write — the refetch-after-mutation
// contract the TaxonomyManager + combobox "Add to taxonomy" flow depend on.
export let taxonomy: TaxonomyEntry[] = [
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

const SEED_TAXONOMY: TaxonomyEntry[] = taxonomy.map((e) => ({ ...e }));

// Restore the taxonomy + used-topics fixtures to their seed so tests that mutate
// them stay order-independent. Call from a test's afterEach/beforeEach.
export function resetTaxonomy(): void {
  taxonomy = SEED_TAXONOMY.map((e) => ({ ...e }));
  usedTopics = [...SEED_USED_TOPICS];
}

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

// BERTopic gold-segment labels per conversation, driving both the
// `/bertopic-labels` options endpoint and the `?bertopic_topic=`/
// `?bertopic_subtopic=` filter the conversations handler honors below.
export const bertopicByConversation: Record<
  string,
  { topic: string; subtopic: string }[]
> = {
  "conv-001": [{ topic: "refunds", subtopic: "double_charge" }],
  "conv-002": [{ topic: "logins", subtopic: "mfa_reset" }],
};

export const bertopicLabels: BertopicLabels = {
  topics: [
    { topic: "refunds", count: 1 },
    { topic: "logins", count: 1 },
  ],
  subtopics: [
    { subtopic: "double_charge", topic: "refunds", count: 1 },
    { subtopic: "mfa_reset", topic: "logins", count: 1 },
  ],
};

// A conversation detail that carries BOTH the machine `segments` and the
// human `gold_segments` — the two arrays the re-segment feature confuses.
// Topic names already saved for the dataset, most-frequent first — the
// `used-topics` endpoint feeds these into the combobox alongside the taxonomy.
export let usedTopics: string[] = ["billing", "shipping_delay"];

const SEED_USED_TOPICS = [...usedTopics];

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
    const bertopicTopic = url.searchParams.get("bertopic_topic");
    const bertopicSubtopic = url.searchParams.get("bertopic_subtopic");

    const filtered = conversations.filter((c) => {
      if (q && !c.conversation.toLowerCase().includes(q)) return false;
      if (status === "reviewed" && !c.reviewed) return false;
      if (status === "unreviewed" && c.reviewed) return false;
      if (topic && !c.topics.includes(topic)) return false;
      if (labeler && !worklist[labeler]?.includes(c.conversation)) return false;
      const bt = bertopicByConversation[c.conversation] ?? [];
      if (bertopicTopic && !bt.some((b) => b.topic === bertopicTopic))
        return false;
      if (bertopicSubtopic && !bt.some((b) => b.subtopic === bertopicSubtopic))
        return false;
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

  // Add a topic (idempotent on topic+subtopic) and surface it in used-topics so
  // both the manager list and the combobox suggestions pick it up on refetch.
  http.post(`${base}/datasets/:dataset/taxonomy`, async ({ request }) => {
    const body = (await request.json()) as TaxonomyCreateRequest;
    const exists = taxonomy.some(
      (e) => e.topic === body.topic && (e.subtopic ?? null) === (body.subtopic ?? null),
    );
    if (!exists) {
      taxonomy = [
        ...taxonomy,
        {
          topic: body.topic,
          subtopic: body.subtopic ?? null,
          description: body.description ?? null,
        },
      ];
    }
    if (!usedTopics.includes(body.topic)) usedTopics = [...usedTopics, body.topic];
    return HttpResponse.json({ dataset: "e2e-fixture", cascaded: 0, deleted: 0 });
  }),

  // Rename a topic (cascade is server-side; here we just rewrite the rows). A
  // topic-level rename leaves new_subtopic unset and rewrites every matching topic.
  http.patch(`${base}/datasets/:dataset/taxonomy`, async ({ request }) => {
    const body = (await request.json()) as TaxonomyRenameRequest;
    let cascaded = 0;
    taxonomy = taxonomy.map((e) => {
      if (e.topic !== body.topic) return e;
      if (body.subtopic != null && (e.subtopic ?? null) !== body.subtopic) return e;
      cascaded += 1;
      return {
        ...e,
        topic: body.new_topic,
        subtopic: body.new_subtopic ?? e.subtopic ?? null,
      };
    });
    usedTopics = usedTopics.map((t) => (t === body.topic ? body.new_topic : t));
    return HttpResponse.json({ dataset: "e2e-fixture", cascaded, deleted: 0 });
  }),

  // Fold one topic into another: rewrite the source rows' topic, drop dup rows.
  http.post(`${base}/datasets/:dataset/taxonomy/merge`, async ({ request }) => {
    const body = (await request.json()) as TaxonomyMergeRequest;
    const seen = new Set<string>();
    const merged: TaxonomyEntry[] = [];
    let cascaded = 0;
    for (const e of taxonomy) {
      const topic = e.topic === body.from_topic ? body.into_topic : e.topic;
      if (e.topic === body.from_topic) cascaded += 1;
      const key = `${topic ?? ""} ${e.subtopic ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push({ ...e, topic });
    }
    taxonomy = merged;
    usedTopics = usedTopics.filter((t) => t !== body.from_topic);
    return HttpResponse.json({ dataset: "e2e-fixture", cascaded, deleted: 0 });
  }),

  // Remove a topic (optionally a single subtopic) from the taxonomy list.
  http.delete(`${base}/datasets/:dataset/taxonomy`, ({ request }) => {
    const url = new URL(request.url);
    const topic = url.searchParams.get("topic");
    const subtopic = url.searchParams.get("subtopic");
    const before = taxonomy.length;
    taxonomy = taxonomy.filter((e) => {
      if (e.topic !== topic) return true;
      if (subtopic != null) return (e.subtopic ?? null) !== subtopic;
      return false;
    });
    const deleted = before - taxonomy.length;
    if (subtopic == null) usedTopics = usedTopics.filter((t) => t !== topic);
    return HttpResponse.json({ dataset: "e2e-fixture", cascaded: 0, deleted });
  }),

  http.get(`${base}/datasets/:dataset/used-topics`, () =>
    HttpResponse.json({ topics: usedTopics }),
  ),

  http.get(`${base}/datasets/:dataset/bertopic-labels`, () =>
    HttpResponse.json(bertopicLabels),
  ),

  http.get(`${base}/datasets/:dataset/stats`, () => HttpResponse.json(stats)),
];
