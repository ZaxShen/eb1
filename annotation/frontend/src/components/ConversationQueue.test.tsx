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
  type BertopicLabels,
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

const EMPTY_BERTOPIC: BertopicLabels = { topics: [], subtopics: [] };

function Harness({
  bertopicLabels = EMPTY_BERTOPIC,
}: {
  bertopicLabels?: BertopicLabels;
}) {
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
        bertopicLabels={bertopicLabels}
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

const BERTOPIC_LABELS: BertopicLabels = {
  topics: [
    { topic: "refunds", count: 7 },
    { topic: "logins", count: 3 },
  ],
  subtopics: [
    { subtopic: "double_charge", topic: "refunds", count: 4 },
    { subtopic: "late_refund", topic: "refunds", count: 3 },
    { subtopic: "mfa_reset", topic: "logins", count: 3 },
  ],
};

// Captures the bertopic_* params each refetch sends so the assertions read the
// production filter contract, not a stub.
function bertopicCapturingHandler(seen: URLSearchParams[]) {
  server.use(
    http.get(`/api/datasets/:dataset/conversations`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url.searchParams);
      const bt = url.searchParams.get("bertopic_topic");
      const all = makeConversations(2);
      const items = bt === "logins" ? all.slice(0, 1) : all;
      return HttpResponse.json({
        items,
        total: items.length,
        page: 1,
        page_size: PAGE_SIZE,
      });
    }),
  );
}

describe("ConversationQueue (BERTopic filters)", () => {
  it("renders both BERTopic dropdowns populated from labels with counts", async () => {
    const user = userEvent.setup();
    usePagedHandler(makeConversations(2));
    renderWithProviders(<Harness bertopicLabels={BERTOPIC_LABELS} />);

    await waitFor(() =>
      expect(screen.getByText("conv-000")).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("combobox", { name: "BERTopic topic" }),
    );
    expect(
      screen.getByRole("option", { name: /Refunds \(7\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Logins \(3\)/ }),
    ).toBeInTheDocument();
    // Close and open the subtopic dropdown.
    await user.keyboard("{Escape}");

    await user.click(
      screen.getByRole("combobox", { name: "BERTopic subtopic" }),
    );
    expect(
      screen.getByRole("option", { name: /Double Charge \(4\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Mfa Reset \(3\)/ }),
    ).toBeInTheDocument();
  });

  it("selecting a BERTopic topic refetches with bertopic_topic and narrows the queue", async () => {
    const user = userEvent.setup();
    const seen: URLSearchParams[] = [];
    bertopicCapturingHandler(seen);
    renderWithProviders(<Harness bertopicLabels={BERTOPIC_LABELS} />);

    await waitFor(() =>
      expect(screen.getByText("conv-001")).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("combobox", { name: "BERTopic topic" }),
    );
    await user.click(screen.getByRole("option", { name: /Logins \(3\)/ }));

    await waitFor(() =>
      expect(screen.queryByText("conv-001")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("conv-000")).toBeInTheDocument();
    expect(
      seen.some((p) => p.get("bertopic_topic") === "logins"),
    ).toBe(true);
  });

  it("subtopic options narrow to the chosen topic's children", async () => {
    const user = userEvent.setup();
    usePagedHandler(makeConversations(2));
    renderWithProviders(<Harness bertopicLabels={BERTOPIC_LABELS} />);

    await waitFor(() =>
      expect(screen.getByText("conv-000")).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("combobox", { name: "BERTopic topic" }),
    );
    await user.click(screen.getByRole("option", { name: /Refunds \(7\)/ }));

    await user.click(
      screen.getByRole("combobox", { name: "BERTopic subtopic" }),
    );
    expect(
      screen.getByRole("option", { name: /Double Charge \(4\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Late Refund \(3\)/ }),
    ).toBeInTheDocument();
    // The login subtopic is excluded now that "refunds" is the chosen topic.
    expect(
      screen.queryByRole("option", { name: /Mfa Reset/ }),
    ).not.toBeInTheDocument();
  });
});
