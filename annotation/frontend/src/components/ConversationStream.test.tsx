import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../test/renderWithProviders";
import { api } from "../api";
import { DATASET } from "../test/msw/handlers";
import ConversationStream from "./ConversationStream";

// Component layer: render the real ConversationStream against the realistic
// `/conversations/:id` response served by MSW. Asserts the component reads the
// machine `segments` array and renders each segment's messages + topic badge —
// the exact path the re-segment bug rendered from the wrong field.
describe("ConversationStream (MSW component)", () => {
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
