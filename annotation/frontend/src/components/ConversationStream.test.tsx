import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../test/renderWithProviders";
import { api } from "../api";
import { DATASET, conversationView } from "../test/msw/handlers";
import { server } from "../test/msw/server";
import type { ConversationView } from "../api";
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

  it("shows the empty-state when a conversation has no segments", () => {
    renderWithProviders(
      <ConversationStream
        view={{
          conversation: "empty",
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
