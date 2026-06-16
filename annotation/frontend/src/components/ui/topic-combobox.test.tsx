import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen } from "../../test/renderWithProviders";
import { TopicCombobox } from "./topic-combobox";

// A controlled wrapper mirroring how AnnotationPanel owns the typed value, so
// the "Add to taxonomy" affordance sees the live input as the user types.
function Controlled({
  suggestions,
  onAddNew,
  onCommit,
}: {
  suggestions: string[];
  onAddNew?: (v: string) => void | Promise<void>;
  onCommit?: (v: string) => void;
}) {
  const [value, setValue] = useState("");
  return (
    <TopicCombobox
      value={value}
      suggestions={suggestions}
      onChange={setValue}
      onAddNew={onAddNew}
      onCommit={onCommit}
      ariaLabel="True Topic"
    />
  );
}

describe("TopicCombobox add-new affordance", () => {
  it("offers 'Add ... to taxonomy' only for a name no suggestion matches", async () => {
    const user = userEvent.setup();
    const onAddNew = vi.fn();
    renderWithProviders(
      <Controlled suggestions={["billing"]} onAddNew={onAddNew} />,
    );

    const input = screen.getByRole("combobox", { name: "True Topic" });
    await user.click(input);

    // A typed name matching an existing suggestion offers no add action.
    await user.type(input, "billing");
    expect(screen.queryByText(/Add ‘.*’ to taxonomy/)).not.toBeInTheDocument();

    // A novel name surfaces the explicit add action.
    await user.clear(input);
    await user.type(input, "warranty_claim");
    expect(
      screen.getByText("Add ‘warranty_claim’ to taxonomy"),
    ).toBeInTheDocument();
  });

  it("calls onAddNew then commits the typed name", async () => {
    const user = userEvent.setup();
    const onAddNew = vi.fn().mockResolvedValue(undefined);
    const onCommit = vi.fn();
    renderWithProviders(
      <Controlled
        suggestions={["billing"]}
        onAddNew={onAddNew}
        onCommit={onCommit}
      />,
    );

    const input = screen.getByRole("combobox", { name: "True Topic" });
    await user.click(input);
    await user.type(input, "warranty_claim");
    await user.click(screen.getByText("Add ‘warranty_claim’ to taxonomy"));

    expect(onAddNew).toHaveBeenCalledWith("warranty_claim");
    expect(onCommit).toHaveBeenLastCalledWith("warranty_claim");
  });

  it("omits the add action when no onAddNew handler is wired", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Controlled suggestions={["billing"]} />);

    const input = screen.getByRole("combobox", { name: "True Topic" });
    await user.click(input);
    await user.type(input, "warranty_claim");
    expect(screen.queryByText(/Add ‘.*’ to taxonomy/)).not.toBeInTheDocument();
  });
});
