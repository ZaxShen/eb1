import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import {
  renderWithProviders,
  screen,
  waitFor,
  within,
} from "../test/renderWithProviders";
import { api, type TaxonomyEntry } from "../api";
import { DATASET, resetTaxonomy } from "../test/msw/handlers";
import TaxonomyManager from "./TaxonomyManager";

// The manager refetches GET /taxonomy after every mutation, so the harness
// mirrors App.tsx: it holds the entries and re-fetches on `onChanged`, exactly
// the refetch-after-write contract the labeling combobox depends on.
function Harness({ initial }: { initial: TaxonomyEntry[] }) {
  const [entries, setEntries] = useState(initial);
  const refresh = async () => {
    setEntries(await api.getTaxonomy(DATASET));
  };
  return (
    <TaxonomyManager
      open
      onOpenChange={() => {}}
      dataset={DATASET}
      entries={entries}
      onChanged={refresh}
    />
  );
}

async function setup() {
  const entries = await api.getTaxonomy(DATASET);
  const user = userEvent.setup();
  renderWithProviders(<Harness initial={entries} />);
  const dialog = await screen.findByRole("dialog");
  return { user, dialog };
}

describe("TaxonomyManager (MSW component)", () => {
  afterEach(() => resetTaxonomy());

  it("lists the dataset's topics from the taxonomy", async () => {
    const { dialog } = await setup();
    expect(within(dialog).getByText("Billing")).toBeInTheDocument();
    expect(within(dialog).getByText("Technical Support")).toBeInTheDocument();
  });

  it("adds a topic and shows it in the list", async () => {
    const { user, dialog } = await setup();
    const post = vi.spyOn(api, "createTaxonomy");

    await user.type(
      within(dialog).getByLabelText("New topic name"),
      "warranty_claim",
    );
    await user.click(within(dialog).getByRole("button", { name: "Add topic" }));

    expect(post).toHaveBeenCalledWith(DATASET, {
      topic: "warranty_claim",
      kind: "user",
    });
    await waitFor(() =>
      expect(within(dialog).getByText("Warranty Claim")).toBeInTheDocument(),
    );
  });

  it("previews and submits the slug when adding a mixed-case topic", async () => {
    const { user, dialog } = await setup();
    const post = vi.spyOn(api, "createTaxonomy");

    await user.type(
      within(dialog).getByLabelText("New topic name"),
      "Veterans  Affairs!",
    );
    // Live preview shows exactly what the backend will store.
    expect(within(dialog).getByText("veterans_affairs")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Add topic" }));

    expect(post).toHaveBeenCalledWith(DATASET, {
      topic: "veterans_affairs",
      kind: "user",
    });
    await waitFor(() =>
      expect(within(dialog).getByText("Veterans Affairs")).toBeInTheDocument(),
    );
  });

  it("inline-renames a topic via renameTaxonomy", async () => {
    const { user, dialog } = await setup();
    const patch = vi.spyOn(api, "renameTaxonomy");

    await user.click(within(dialog).getByRole("button", { name: "Rename billing" }));
    const input = within(dialog).getByLabelText("Rename billing");
    await user.clear(input);
    await user.type(input, "payments");
    await user.click(within(dialog).getByRole("button", { name: "Save billing" }));

    expect(patch).toHaveBeenCalledWith(DATASET, {
      topic: "billing",
      new_topic: "payments",
      kind: "user",
    });
    await waitFor(() =>
      expect(within(dialog).getByText("Payments")).toBeInTheDocument(),
    );
    expect(within(dialog).queryByText("Billing")).not.toBeInTheDocument();
  });

  it("merges one topic into another via mergeTaxonomy", async () => {
    const { user, dialog } = await setup();
    const merge = vi.spyOn(api, "mergeTaxonomy");

    await user.click(within(dialog).getByLabelText("Merge from"));
    await user.click(screen.getByRole("option", { name: "Technical Support" }));
    await user.click(within(dialog).getByLabelText("Merge into"));
    await user.click(screen.getByRole("option", { name: "Billing" }));
    await user.click(within(dialog).getByRole("button", { name: "Merge" }));

    expect(merge).toHaveBeenCalledWith(DATASET, {
      from_topic: "technical_support",
      into_topic: "billing",
      kind: "user",
    });
    await waitFor(() =>
      expect(
        within(dialog).queryByText("Technical Support"),
      ).not.toBeInTheDocument(),
    );
    expect(within(dialog).getByText("Billing")).toBeInTheDocument();
  });

  it("deletes a topic from the list", async () => {
    const { user, dialog } = await setup();
    const del = vi.spyOn(api, "deleteTaxonomy");

    await user.click(
      within(dialog).getByRole("button", { name: "Delete technical_support" }),
    );

    expect(del).toHaveBeenCalledWith(DATASET, {
      topic: "technical_support",
      kind: "user",
    });
    await waitFor(() =>
      expect(
        within(dialog).queryByText("Technical Support"),
      ).not.toBeInTheDocument(),
    );
  });

  it("scopes the list to a domain and manages within it", async () => {
    const user = userEvent.setup();
    const entries: TaxonomyEntry[] = [
      { domain: "va", topic: "disability", subtopic: null, description: null },
      { domain: "ssa", topic: "retirement", subtopic: null, description: null },
    ];
    const post = vi
      .spyOn(api, "createTaxonomy")
      .mockResolvedValue({ dataset: DATASET, cascaded: 0, deleted: 0 });
    renderWithProviders(
      <TaxonomyManager
        open
        onOpenChange={() => {}}
        dataset={DATASET}
        entries={entries}
        onChanged={() => {}}
      />,
    );
    const dialog = await screen.findByRole("dialog");

    // Defaults to the first available domain (ssa, per DOMAINS order): only its
    // categories show, never va's "Disability".
    expect(within(dialog).getByText("Retirement")).toBeInTheDocument();
    expect(within(dialog).queryByText("Disability")).not.toBeInTheDocument();

    // Switch scope to Veterans Affairs → its category appears.
    await user.click(within(dialog).getByRole("combobox", { name: "Domain" }));
    await user.click(screen.getByRole("option", { name: "Veterans Affairs" }));
    expect(within(dialog).getByText("Disability")).toBeInTheDocument();

    // Adding a topic creates it under the scoped domain.
    await user.type(within(dialog).getByLabelText("New topic name"), "pension");
    await user.click(within(dialog).getByRole("button", { name: "Add topic" }));
    expect(post).toHaveBeenCalledWith(DATASET, {
      topic: "pension",
      kind: "user",
      domain: "va",
    });
  });
});
