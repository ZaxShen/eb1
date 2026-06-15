import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "../test/renderWithProviders";
import { api } from "../api";
import { buildTaxonomyMap } from "../lib/taxonomy";
import { DATASET } from "../test/msw/handlers";
import AnnotationPanel from "./AnnotationPanel";

// Component layer: render the real AnnotationPanel against the realistic
// taxonomy + conversation responses served by MSW, and assert its fields show
// the data the backend actually returned.
describe("AnnotationPanel (MSW component)", () => {
  async function setup() {
    const [entries, view] = await Promise.all([
      api.getTaxonomy(DATASET),
      api.getConversation(DATASET, "conv-001"),
    ]);
    const segment = view.segments[0];
    return { taxonomy: buildTaxonomyMap(entries), segment };
  }

  function noopHandlers() {
    return {
      onTopicChange: vi.fn(),
      onSubtopicChange: vi.fn(),
      onReviewedByChange: vi.fn(),
      onConfirmAi: vi.fn(),
      onSave: vi.fn(),
      onPrev: vi.fn(),
      onNext: vi.fn(),
    };
  }

  it("renders the annotation fields for a selected segment", async () => {
    const { taxonomy, segment } = await setup();

    renderWithProviders(
      <AnnotationPanel
        segment={segment}
        taxonomy={taxonomy}
        topic={segment.topic ?? ""}
        subtopic={segment.subtopic ?? ""}
        reviewedBy="Ada Lovelace"
        reviewedByLocked
        saving={false}
        {...noopHandlers()}
      />,
    );

    expect(screen.getByText("Annotation")).toBeInTheDocument();
    expect(screen.getByText("True Topic")).toBeInTheDocument();
    expect(screen.getByText("True Subtopic")).toBeInTheDocument();
    // The verified Google name is mirrored read-only.
    expect(screen.getByText("Reviewed by (Google account)")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    // Confirm AI is enabled because the segment carries a machine topic.
    expect(screen.getByText("Confirm AI")).toBeEnabled();
    expect(screen.getByText("Save")).toBeEnabled();
  });

  it("shows the placeholder when no segment is selected", async () => {
    const { taxonomy } = await setup();

    renderWithProviders(
      <AnnotationPanel
        segment={null}
        taxonomy={taxonomy}
        topic=""
        subtopic=""
        reviewedBy=""
        saving={false}
        {...noopHandlers()}
      />,
    );

    expect(
      screen.getByText("Select a segment in the stream"),
    ).toBeInTheDocument();
  });
});
