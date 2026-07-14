import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen, within } from "../test/renderWithProviders";
import { api } from "../api";
import { buildTaxonomyMap } from "../lib/taxonomy";
import { DATASET } from "../test/msw/handlers";
import AnnotationPanel from "./AnnotationPanel";

// The topic field is a controlled combobox: filtering depends on the parent
// holding `topic`, exactly as App.tsx wires it. This harness mirrors that so a
// test can type and see the suggestion list narrow, while still spying on the
// committed value via `onCommit`.
function ControlledPanel({
  onCommit,
  ...props
}: Omit<ComponentProps<typeof AnnotationPanel>, "topic" | "onTopicChange"> & {
  onCommit: (topic: string) => void;
}) {
  const [topic, setTopic] = useState("");
  return (
    <AnnotationPanel
      {...props}
      topic={topic}
      onTopicChange={(t) => {
        setTopic(t);
        onCommit(t);
      }}
    />
  );
}

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

  // Handlers a test doesn't drive. `onTopicChange` is separate so the controlled
  // harness (which owns topic state) can override it without a duplicate key.
  function passiveHandlers() {
    return {
      onSubtopicChange: vi.fn(),
      onReviewedByChange: vi.fn(),
      onSave: vi.fn(),
      onPrev: vi.fn(),
      onNext: vi.fn(),
    };
  }

  function noopHandlers() {
    return { onTopicChange: vi.fn(), ...passiveHandlers() };
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
    expect(screen.getByText("Save")).toBeEnabled();
    // The dead demo-era "Confirm AI" control and gold-cluster hint are gone.
    expect(screen.queryByText("Confirm AI")).not.toBeInTheDocument();
    expect(screen.queryByText(/Gold cluster:/)).not.toBeInTheDocument();
  });

  it("suggests taxonomy ∪ used-topics, filters as typed, and commits a pick", async () => {
    const user = userEvent.setup();
    const { taxonomy, segment } = await setup();
    const onCommit = vi.fn();

    renderWithProviders(
      <ControlledPanel
        segment={segment}
        taxonomy={taxonomy}
        usedTopics={["billing", "shipping_delay"]}
        subtopic=""
        reviewedBy=""
        saving={false}
        {...passiveHandlers()}
        onCommit={onCommit}
      />,
    );

    const input = screen.getByRole("combobox", { name: "True Topic" });
    await user.click(input);

    const listbox = screen.getByRole("listbox");
    // Suggestions are the union: taxonomy names + a used-topic the taxonomy
    // doesn't cover (shipping_delay), de-duplicated (billing appears once).
    expect(within(listbox).getByText("Billing")).toBeInTheDocument();
    expect(within(listbox).getByText("Technical Support")).toBeInTheDocument();
    expect(within(listbox).getByText("Shipping Delay")).toBeInTheDocument();
    expect(within(listbox).getAllByText("Billing")).toHaveLength(1);

    // Typing filters the list to substring matches.
    await user.type(input, "ship");
    expect(screen.getByText("Shipping Delay")).toBeInTheDocument();
    expect(screen.queryByText("Technical Support")).not.toBeInTheDocument();

    // Clicking a suggestion commits its raw value through onTopicChange.
    await user.click(screen.getByRole("option", { name: "Shipping Delay" }));
    expect(onCommit).toHaveBeenLastCalledWith("shipping_delay");
  });

  it("accepts an arbitrary new topic name on Enter (open vocab)", async () => {
    const user = userEvent.setup();
    const { taxonomy, segment } = await setup();
    const onTopicChange = vi.fn();

    renderWithProviders(
      <AnnotationPanel
        segment={segment}
        taxonomy={taxonomy}
        usedTopics={["billing"]}
        topic="warranty_claim"
        subtopic=""
        reviewedBy=""
        saving={false}
        {...noopHandlers()}
        onTopicChange={onTopicChange}
      />,
    );

    const input = screen.getByRole<HTMLInputElement>("combobox", {
      name: "True Topic",
    });
    // A name absent from both taxonomy and used-topics is still committable.
    expect(input.value).toBe("warranty_claim");
    await user.click(input);
    await user.keyboard("{Enter}");
    expect(onTopicChange).toHaveBeenLastCalledWith("warranty_claim");

    // Save is enabled because a topic is present (it feeds api.annotate upstream).
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
