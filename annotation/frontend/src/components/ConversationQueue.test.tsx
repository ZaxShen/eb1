import { useEffect, useState } from "react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import {
  renderWithProviders,
  screen,
  waitFor,
  within,
} from "../test/renderWithProviders";
import {
  api,
  type ConversationFilters,
  type ConversationSummary,
} from "../api";
import { DATASET } from "../test/msw/handlers";
import { server } from "../test/msw/server";
import { buildTaxonomyMap } from "../lib/taxonomy";
import ConversationQueue from "./ConversationQueue";

// radix ScrollArea observes its viewport; jsdom lacks ResizeObserver.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// Component layer: render the real ConversationQueue wired to the real
// `api.listConversations` against MSW, mirroring how App drives it (page/filter/
// search state → server refetch). This exercises the production pagination +
// search contract, not a stub.

const PAGE_SIZE = 50;

function Harness() {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<ConversationFilters>({});
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .listConversations(DATASET, {
        ...filters,
        page,
        pageSize: PAGE_SIZE,
        q: search || undefined,
      })
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
      })
      .finally(() => setLoading(false));
  }, [page, search, filters]);

  return (
    <>
      <div data-testid="selected">{selected ?? ""}</div>
      <ConversationQueue
        conversations={items}
        selectedConversation={selected}
        filters={filters}
        search={search}
        page={page}
        pageSize={PAGE_SIZE}
        total={total}
        taxonomy={buildTaxonomyMap([])}
        loading={loading}
        onSelect={setSelected}
        onFiltersChange={(f) => {
          setFilters(f);
          setPage(1);
        }}
        onSearchChange={(q) => {
          setSearch(q);
          setPage(1);
        }}
        onPageChange={setPage}
      />
    </>
  );
}

// 60 conversations so the default page_size (50) yields two pages.
function makeConversations(n: number): ConversationSummary[] {
  return Array.from({ length: n }, (_, i) => ({
    conversation: `conv-${String(i).padStart(3, "0")}`,
    message_count: 2,
    segment_count: 1,
    topics: ["billing"],
    reviewed_count: 0,
    reviewed: false,
  }));
}

function usePagedHandler(all: ConversationSummary[]) {
  server.use(
    http.get(`/api/datasets/:dataset/conversations`, ({ request }) => {
      const url = new URL(request.url);
      const page = Number(url.searchParams.get("page") ?? "1");
      const pageSize = Number(url.searchParams.get("page_size") ?? "50");
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const filtered = q
        ? all.filter((c) => c.conversation.toLowerCase().includes(q))
        : all;
      const start = (page - 1) * pageSize;
      return HttpResponse.json({
        items: filtered.slice(start, start + pageSize),
        total: filtered.length,
        page,
        page_size: pageSize,
      });
    }),
  );
}

describe("ConversationQueue (MSW pagination + search)", () => {
  it("renders ONE page and shows the total, not every conversation", async () => {
    usePagedHandler(makeConversations(60));
    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(screen.getByText("conv-000")).toBeInTheDocument(),
    );

    // page_size = 50 → exactly 50 cards rendered though 60 exist.
    expect(screen.getByText("conv-049")).toBeInTheDocument();
    expect(screen.queryByText("conv-050")).not.toBeInTheDocument();
    // The total is surfaced (range "1–50 of 60").
    expect(screen.getByText(/1–50 of 60/)).toBeInTheDocument();
  });

  it("a debounced search refetches server-side and filters the page", async () => {
    const user = userEvent.setup();
    usePagedHandler(makeConversations(60));
    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(screen.getByText("conv-000")).toBeInTheDocument(),
    );

    await user.type(
      screen.getByRole("searchbox", { name: /search conversations/i }),
      "conv-007",
    );

    // The debounced `q` commits, the server refetches, and only the match
    // remains — surfaced by the "1–1 of 1" range.
    await waitFor(() =>
      expect(screen.getByText(/1–1 of 1/)).toBeInTheDocument(),
    );
    expect(screen.getByText("conv-007")).toBeInTheDocument();
    expect(screen.queryByText("conv-000")).not.toBeInTheDocument();
  });

  it("Next page refetches the next slice", async () => {
    const user = userEvent.setup();
    usePagedHandler(makeConversations(60));
    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(screen.getByText("conv-000")).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /next page/i }));

    await waitFor(() =>
      expect(screen.getByText("conv-050")).toBeInTheDocument(),
    );
    expect(screen.queryByText("conv-000")).not.toBeInTheDocument();
    expect(screen.getByText(/51–60 of 60/)).toBeInTheDocument();
  });

  it("selecting a conversation invokes onSelect", async () => {
    const user = userEvent.setup();
    usePagedHandler(makeConversations(3));
    renderWithProviders(<Harness />);

    await waitFor(() =>
      expect(screen.getByText("conv-001")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("conv-001"));
    expect(
      within(screen.getByTestId("selected")).getByText("conv-001"),
    ).toBeInTheDocument();
  });
});
