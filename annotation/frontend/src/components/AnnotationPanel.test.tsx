import { useState, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import {
  renderWithProviders,
  screen,
  waitFor,
  within,
} from "../test/renderWithProviders";
import { api } from "../api";
import { buildTaxonomyMap } from "../lib/taxonomy";
import { DATASET } from "../test/msw/handlers";
import AnnotationPanel from "./AnnotationPanel";

// The topic/subtopic fields are controlled dropdowns: the parent holds `topic`
// and `subtopic`, exactly as App.tsx wires them. This harness mirrors that so a
// test can drive the Select + inline add-new flow while spying on the committed
// value via `onCommit`.
function ControlledPanel({
  onCommit,
  initialTopic = "",
  ...props
}: Omit<ComponentProps<typeof AnnotationPanel>, "topic" | "onTopicChange"> & {
  onCommit: (topic: string) => void;
  initialTopic?: string;
}) {
  const [topic, setTopic] = useState(initialTopic);
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
      onAddTopic: vi.fn(),
      onAddSubtopic: vi.fn(),
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

  it("lists taxonomy ∪ used-topics plus a '+ New topic…' item, and commits a pick", async () => {
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

    await user.click(screen.getByRole("combobox", { name: "True Topic" }));

    const listbox = screen.getByRole("listbox");
    // Options are the union: taxonomy names + a used-topic the taxonomy doesn't
    // cover (shipping_delay), de-duplicated (billing appears once), plus add-new.
    expect(within(listbox).getByRole("option", { name: "Billing" })).toBeInTheDocument();
    expect(
      within(listbox).getByRole("option", { name: "Technical Support" }),
    ).toBeInTheDocument();
    expect(
      within(listbox).getByRole("option", { name: "Shipping Delay" }),
    ).toBeInTheDocument();
    expect(within(listbox).getAllByRole("option", { name: "Billing" })).toHaveLength(1);
    expect(
      within(listbox).getByRole("option", { name: "+ New topic…" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: "Shipping Delay" }));
    expect(onCommit).toHaveBeenLastCalledWith("shipping_delay");
  });

  it("reveals an inline input on '+ New topic…', previews the slug, and persists+selects it", async () => {
    const user = userEvent.setup();
    const { taxonomy, segment } = await setup();
    const onCommit = vi.fn();
    const onAddTopic = vi.fn();

    renderWithProviders(
      <ControlledPanel
        segment={segment}
        taxonomy={taxonomy}
        subtopic=""
        reviewedBy=""
        saving={false}
        {...passiveHandlers()}
        onAddTopic={onAddTopic}
        onCommit={onCommit}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "True Topic" }));
    await user.click(screen.getByRole("option", { name: "+ New topic…" }));

    const input = screen.getByLabelText("True Topic new name");
    await user.type(input, "Veterans  Affairs!");
    // Live slug preview reflects exactly what the backend will store.
    expect(screen.getByText("veterans_affairs")).toBeInTheDocument();

    // Enter confirms: persist the new option, then select it (as the slug).
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(onAddTopic).toHaveBeenCalledWith("veterans_affairs"),
    );
    expect(onCommit).toHaveBeenLastCalledWith("veterans_affairs");
  });

  it("keeps the subtopic disabled without a topic and scopes it to the chosen topic", async () => {
    const user = userEvent.setup();
    const { taxonomy, segment } = await setup();

    const { rerender } = renderWithProviders(
      <AnnotationPanel
        segment={segment}
        taxonomy={taxonomy}
        topic=""
        subtopic=""
        reviewedBy=""
        saving={false}
        {...noopHandlers()}
      />,
    );

    // No topic → subtopic dropdown is disabled.
    expect(screen.getByRole("combobox", { name: "True Subtopic" })).toBeDisabled();

    // With "billing" selected, the subtopic options are that topic's subtopics.
    rerender(
      <AnnotationPanel
        segment={segment}
        taxonomy={taxonomy}
        topic="billing"
        subtopic=""
        reviewedBy=""
        saving={false}
        {...noopHandlers()}
      />,
    );
    const subtopicTrigger = screen.getByRole("combobox", { name: "True Subtopic" });
    expect(subtopicTrigger).toBeEnabled();
    await user.click(subtopicTrigger);
    const listbox = screen.getByRole("listbox");
    expect(
      within(listbox).getByRole("option", { name: "Refund Request" }),
    ).toBeInTheDocument();
    expect(
      within(listbox).getByRole("option", { name: "Invoice Question" }),
    ).toBeInTheDocument();
    // Subtopics from a different topic are not offered here.
    expect(
      within(listbox).queryByRole("option", { name: "Login Issue" }),
    ).not.toBeInTheDocument();
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
