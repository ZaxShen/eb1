import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../test/renderWithProviders";
import { api } from "../api";
import { DATASET, conversationView } from "../test/msw/handlers";
import { server } from "../test/msw/server";
import type { ConversationView } from "../api";
import { formatChatTimestamp } from "../lib/utils";
import ConversationStream from "./ConversationStream";

// Component layer: render the real ConversationStream against the realistic
// `/conversations/:id` response served by MSW. Asserts the component reads the
// machine `segments` array and renders each segment's messages + topic badge —
// the exact path the re-segment bug rendered from the wrong field.
describe("ConversationStream (MSW component)", () => {
  it("renders Tooltip-wrapped Buttons without a ref warning (Bug B)", async () => {
    // TooltipTrigger forwards a ref into its `asChild` Button (the split/merge
    // controls). Before Button used React.forwardRef this logged
    // "Function components cannot be given refs". forwardRef silences it.
    const errors: string[] = [];
    const spy = vi
      .spyOn(console, "error")
      .mockImplementation((msg: unknown) => {
        errors.push(String(msg));
      });

    const view = await api.getConversation(DATASET, "conv-001");
    renderWithProviders(
      <ConversationStream
        view={view}
        loading={false}
        selectedSegmentId={101}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );

    expect(
      errors.some((e) => e.includes("Function components cannot be given refs")),
    ).toBe(false);
    spy.mockRestore();
  });


  it("renders the segments from a realistic conversation response", async () => {
    const view = await api.getConversation(DATASET, "conv-001");

    renderWithProviders(
      <ConversationStream
        view={view}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );

    // Two machine segments → two dividers labelled in order.
    expect(screen.getByText("Segment 1")).toBeInTheDocument();
    expect(screen.getByText("Segment 2")).toBeInTheDocument();

    // Each segment's topic badge is rendered from segment.topic (formatted).
    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.getByText("Technical Support")).toBeInTheDocument();

    // Every message in the response is rendered as a bubble.
    for (const msg of view.messages) {
      expect(screen.getByText(msg.message)).toBeInTheDocument();
    }
  });

  it("renders the EDITED (effective) segmentation after a split", async () => {
    // Backend Task A returns the EFFECTIVE segmentation as `segments`: a
    // conversation whose single predicted segment was split into two gold spans
    // comes back as two segments, each INHERITING the parent topic. The stream
    // must render two dividers — the exact path the re-segment bug broke (it
    // rendered the predicted field and never reflected the edit).
    const splitView: ConversationView = {
      ...conversationView,
      segments: [
        {
          ...conversationView.segments[0],
          id: 201,
          message_indices: [0, 1],
          topic: "billing",
          subtopic: "refund_request",
        },
        {
          ...conversationView.segments[0],
          id: 202,
          message_indices: [2, 3],
          topic: "billing",
          subtopic: "refund_request",
        },
      ],
    };
    server.use(
      http.get(
        "/api/datasets/:dataset/conversations/:conversation",
        () => HttpResponse.json(splitView),
      ),
    );

    const view = await api.getConversation(DATASET, "conv-001");
    renderWithProviders(
      <ConversationStream
        view={view}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );

    // The split is reflected: two ordered dividers, both inheriting "Billing".
    const dividers = screen.getAllByText(/^Segment \d+$/);
    expect(dividers.map((d) => d.textContent)).toEqual([
      "Segment 1",
      "Segment 2",
    ]);
    expect(screen.getAllByText("Billing")).toHaveLength(2);
  });

  it("hides the re-segmentation controls when frozen_boundaries is true", () => {
    // Frozen datasets (SuperDialseg gold): no split scissors, no merge arrows —
    // the gold boundaries are authoritative. Segments stay selectable for naming.
    const onSelectSegment = vi.fn();
    const frozenView: ConversationView = {
      ...conversationView,
      frozen_boundaries: true,
    };

    const { rerender } = renderWithProviders(
      <ConversationStream
        view={frozenView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={onSelectSegment}
        onReplaceBoundaries={vi.fn()}
      />,
    );

    // No re-segmentation control is reachable.
    expect(screen.queryAllByRole("button")).toHaveLength(0);

    // Segments still render and stay selectable.
    expect(screen.getByText("Segment 1")).toBeInTheDocument();
    screen.getByText("Segment 1").click();
    expect(onSelectSegment).toHaveBeenCalled();

    // Sanity: the SAME conversation un-frozen DOES expose re-segment controls,
    // so the assertion above is about the flag, not an empty stream.
    rerender(
      <ConversationStream
        view={{ ...conversationView, frozen_boundaries: false }}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    expect(screen.getAllByRole("button").length).toBeGreaterThan(0);
  });

  it("renders per-message time captions when timestamps vary (real corpus)", () => {
    // conversationView carries varying timestamps → the caption for the first
    // message renders normally.
    renderWithProviders(
      <ConversationStream
        view={conversationView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    const caption = formatChatTimestamp(conversationView.messages[0].createdAt);
    expect(screen.getAllByText(caption).length).toBeGreaterThan(0);
  });

  it("hides time captions when every message shares one timestamp (synthetic)", () => {
    // SuperDialseg ingest fabricates a single uniform timestamp for the whole
    // dialogue; the stream suppresses the per-message time captions but still
    // renders the messages and their sender labels.
    const uniform = "2020-01-01T00:00:00Z";
    const uniformView: ConversationView = {
      ...conversationView,
      messages: conversationView.messages.map((m) => ({
        ...m,
        createdAt: uniform,
      })),
    };
    renderWithProviders(
      <ConversationStream
        view={uniformView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    // Messages and sender labels still render.
    expect(
      screen.getByText(conversationView.messages[0].message),
    ).toBeInTheDocument();
    expect(screen.getAllByText("User").length).toBeGreaterThan(0);
    // No time caption for the fabricated uniform timestamp.
    expect(screen.queryByText(formatChatTimestamp(uniform))).toBeNull();
  });

  it("hides time captions for epoch-era sequential timestamps (synthetic)", () => {
    // SuperDialseg's prod ingest fabricates `1970-01-01T00:00:00Z + Ns` per
    // message — sequential, so exact-equality never fires, but every timestamp
    // predates 2000 → still synthetic. Captions must be suppressed.
    const epochView: ConversationView = {
      ...conversationView,
      messages: conversationView.messages.map((m, i) => ({
        ...m,
        createdAt: new Date(i * 1000).toISOString(),
      })),
    };
    renderWithProviders(
      <ConversationStream
        view={epochView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    // Messages and sender labels still render.
    expect(
      screen.getByText(conversationView.messages[0].message),
    ).toBeInTheDocument();
    expect(screen.getAllByText("User").length).toBeGreaterThan(0);
    // No time caption for any fabricated epoch timestamp.
    for (const msg of epochView.messages) {
      expect(
        screen.queryByText(formatChatTimestamp(msg.createdAt)),
      ).toBeNull();
    }
  });

  it("sizes bubble rows against the stream column, not their own content", async () => {
    // Regression (Founder bug: short messages wrapped mid-word, e.g. "corre/ct.").
    // The bubble keeps max-w-[80%], but that percentage must resolve against the
    // full stream column — not a shrink-to-fit row. jsdom can't measure real
    // layout, so pin the class contract that produces correct layout: the bubble
    // row is w-full and the column wrapper no longer shrink-to-fits its rows with
    // items-start/items-end.
    const view = await api.getConversation(DATASET, "conv-001");
    renderWithProviders(
      <ConversationStream
        view={view}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );

    const bubble = screen.getByText(view.messages[0].message);
    const row = bubble.parentElement as HTMLElement;
    const column = row.parentElement as HTMLElement;

    // The row holding the bubble stretches to the full stream width.
    expect(row.className).toContain("w-full");
    // Bubble stays capped at 80% of that now-full-width row.
    expect(bubble.className).toContain("max-w-[80%]");
    // The column wrapper no longer collapses its rows to content width.
    expect(column.className).not.toContain("items-start");
    expect(column.className).not.toContain("items-end");
  });

  it("shows a muted source chip on the divider when the segment has no gold topic", () => {
    // Validate-first: an unlabeled segment (no gold topic) still carries source
    // BERTopic labels — surfaced as a muted `src: …` chip, category + document,
    // distinct from a gold chip and titled with the full text.
    const sourceView: ConversationView = {
      ...conversationView,
      segments: [
        {
          ...conversationView.segments[0],
          topic: null,
          subtopic: null,
          reviewed: false,
          true_topic: null,
          true_subtopic: null,
          bertopic_topic: "Licenses, Permits & IDs",
          bertopic_subtopic: "Medical Certification Requirements",
        },
      ],
    };
    renderWithProviders(
      <ConversationStream
        view={sourceView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );

    const chip = screen.getByText(
      "src: Licenses, Permits & IDs · Medical Certification Requirements",
    );
    expect(chip).toBeInTheDocument();
    // Full text preserved in the title even when the chip truncates.
    expect(chip).toHaveAttribute(
      "title",
      "src: Licenses, Permits & IDs · Medical Certification Requirements",
    );
    // Styled distinct from a gold chip (dashed/muted, not a topic color).
    expect(chip.className).toContain("border-dashed");
    // Not the empty "No topic" state.
    expect(screen.queryByText("No topic")).not.toBeInTheDocument();
  });

  it("shows only the category when the source has no document subtopic", () => {
    const sourceView: ConversationView = {
      ...conversationView,
      segments: [
        {
          ...conversationView.segments[0],
          topic: null,
          subtopic: null,
          reviewed: false,
          true_topic: null,
          true_subtopic: null,
          bertopic_topic: "Veterans Affairs",
          bertopic_subtopic: null,
        },
      ],
    };
    renderWithProviders(
      <ConversationStream
        view={sourceView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    expect(screen.getByText("src: Veterans Affairs")).toBeInTheDocument();
  });

  it("shows the gold chip (not the source chip) once a gold topic exists", () => {
    // Gold wins: a segment with a gold topic renders the topic chip exactly as
    // before and the source chip disappears.
    const goldView: ConversationView = {
      ...conversationView,
      segments: [
        {
          ...conversationView.segments[0],
          topic: "billing",
          subtopic: "refund_request",
          reviewed: true,
          true_topic: "billing",
          true_subtopic: "refund_request",
          bertopic_topic: "Licenses, Permits & IDs",
          bertopic_subtopic: "Medical Certification Requirements",
        },
      ],
    };
    renderWithProviders(
      <ConversationStream
        view={goldView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.queryByText(/^src:/)).not.toBeInTheDocument();
  });

  it("shows 'No topic' when the segment has neither gold nor source labels", () => {
    const bareView: ConversationView = {
      ...conversationView,
      segments: [
        {
          ...conversationView.segments[0],
          topic: null,
          subtopic: null,
          reviewed: false,
          true_topic: null,
          true_subtopic: null,
          bertopic_topic: null,
          bertopic_subtopic: null,
        },
      ],
    };
    renderWithProviders(
      <ConversationStream
        view={bareView}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    expect(screen.getByText("No topic")).toBeInTheDocument();
    expect(screen.queryByText(/^src:/)).not.toBeInTheDocument();
  });

  it("shows the empty-state when a conversation has no segments", () => {
    renderWithProviders(
      <ConversationStream
        view={{
          conversation: "empty",
          frozen_boundaries: false,
          messages: [],
          segments: [],
          gold_segments: [],
        }}
        loading={false}
        selectedSegmentId={null}
        onSelectSegment={vi.fn()}
        onReplaceBoundaries={vi.fn()}
      />,
    );
    expect(
      screen.getByText("No segments for this conversation"),
    ).toBeInTheDocument();
  });
});
