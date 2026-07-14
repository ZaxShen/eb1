import { useState } from "react";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen } from "../test/renderWithProviders";
import type { ConversationFilters, Stats } from "../api";
import { buildTaxonomyMap } from "../lib/taxonomy";
import StatisticsPanel from "./StatisticsPanel";

// StatisticsPanel is presentational: it renders the review counts as chips and
// turns the mismatch chip into a queue quick-filter. The harness mirrors App's
// state so a click round-trips through onFiltersChange like production.

const STATS: Stats = {
  total: 10,
  reviewed: 6,
  unreviewed: 4,
  per_topic: {},
  reviewed_match: 4,
  reviewed_mismatch: 2,
};

function Harness({ stats }: { stats: Stats | null }) {
  const [filters, setFilters] = useState<ConversationFilters>({});
  return (
    <>
      <div data-testid="mismatch">{String(filters.mismatch ?? "")}</div>
      <StatisticsPanel
        stats={stats}
        filters={filters}
        taxonomy={buildTaxonomyMap([])}
        onFiltersChange={setFilters}
      />
    </>
  );
}

describe("StatisticsPanel (match/mismatch chips)", () => {
  it("renders match + mismatch chips with their counts when reviewed > 0", () => {
    renderWithProviders(<Harness stats={STATS} />);
    expect(screen.getByText(/4 match/)).toBeInTheDocument();
    expect(screen.getByText(/2 mismatch/)).toBeInTheDocument();
  });

  it("hides the match/mismatch chips when nothing is reviewed", () => {
    renderWithProviders(
      <Harness
        stats={{
          total: 5,
          reviewed: 0,
          unreviewed: 5,
          per_topic: {},
          reviewed_match: 0,
          reviewed_mismatch: 0,
        }}
      />,
    );
    expect(screen.queryByText(/match/)).not.toBeInTheDocument();
    expect(screen.queryByText(/mismatch/)).not.toBeInTheDocument();
  });

  it("clicking the mismatch chip toggles the queue mismatch filter", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness stats={STATS} />);

    const chip = screen.getByText(/2 mismatch/);
    await user.click(chip);
    expect(screen.getByTestId("mismatch").textContent).toBe("true");

    await user.click(screen.getByText(/2 mismatch/));
    expect(screen.getByTestId("mismatch").textContent).toBe("");
  });
});
