import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, delay } from "msw";
import { server } from "./test/msw/server";
import { conversations, worklist } from "./test/msw/handlers";

// @react-oauth/google reaches out to Google's gsi script on mount; App imports
// the provider at module scope, so stub it to inert passthroughs.
vi.mock("@react-oauth/google", () => ({
  GoogleOAuthProvider: ({ children }: { children: ReactNode }) => children,
  GoogleLogin: () => null,
  useGoogleLogin: () => () => {},
}));

const base = "/api";

// GOOGLE_CLIENT_ID is captured at AuthContext module-load, so each test stubs
// the env BEFORE a fresh dynamic import of App.
async function renderApp() {
  vi.resetModules();
  const { default: App } = await import("./App");
  return render(createElement(App));
}

// A conversation whose KNOWN domain is Veterans Affairs, plus a taxonomy that
// spans va + ssa, exercising the v2 domain scoping end to end.
const VA_CONV = "conv-va";

function domainScopedServer(created: { body: unknown }[]) {
  server.use(
    http.get(`${base}/datasets/:dataset/labelers`, () =>
      HttpResponse.json({ labelers: [] }),
    ),
    http.get(`${base}/datasets/:dataset/used-topics`, () =>
      HttpResponse.json({ topics: [] }),
    ),
    http.get(`${base}/datasets/:dataset/taxonomy`, () =>
      HttpResponse.json([
        { domain: "va", topic: "appeals", subtopic: null, description: null },
        {
          domain: "va",
          topic: "appeals",
          subtopic: "higher_level",
          description: null,
        },
        { domain: "ssa", topic: "retirement", subtopic: null, description: null },
      ]),
    ),
    http.get(`${base}/datasets/:dataset/conversations`, () =>
      HttpResponse.json({
        items: [
          {
            conversation: VA_CONV,
            domain: "va",
            message_count: 2,
            segment_count: 1,
            topics: [],
            reviewed_count: 0,
            reviewed: false,
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      }),
    ),
    http.get(`${base}/datasets/:dataset/conversations/:conversation`, () =>
      HttpResponse.json({
        conversation: VA_CONV,
        domain: "va",
        frozen_boundaries: false,
        messages: [
          { index: 0, id: "m0", type: "user", message: "Appeal?", createdAt: null },
          { index: 1, id: "m1", type: "agent", message: "Sure.", createdAt: null },
        ],
        segments: [
          {
            id: 501,
            conversation: VA_CONV,
            chunk_index: 0,
            message_indices: [0, 1],
            summary: null,
            topic: null,
            subtopic: null,
            sentiment: null,
            label_confidence: null,
            reviewed: false,
            true_topic: null,
            true_subtopic: null,
            bertopic_topic: "Disability",
            bertopic_subtopic: "VA Disability Comp",
          },
        ],
        gold_segments: [],
      }),
    ),
    http.post(`${base}/datasets/:dataset/taxonomy`, async ({ request }) => {
      created.push({ body: await request.json() });
      return HttpResponse.json({ dataset: "e2e-fixture", cascaded: 0, deleted: 0 });
    }),
  );
}

describe("App domain-scoped taxonomy (issue #23)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllEnvs();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("scopes the True Topic picker to the conversation's domain and creates add-new under it", async () => {
    const user = userEvent.setup();
    const created: { body: unknown }[] = [];
    domainScopedServer(created);

    await renderApp();

    await user.click(await screen.findByText(VA_CONV));

    // Wait for the conversation to load (its message renders) and its first
    // segment to select (the Annotation panel replaces the empty state).
    await screen.findByText("Appeal?", {}, { timeout: 4000 });
    await screen.findByText("Annotation", {}, { timeout: 4000 });

    // The True pickers only offer the va-domain taxonomy — ssa's "Retirement"
    // is never shown to a VA annotator.
    const topicPicker = await screen.findByRole("combobox", {
      name: "True Topic",
    });
    await user.click(topicPicker);
    expect(screen.getByRole("option", { name: "Appeals" })).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Retirement" }),
    ).not.toBeInTheDocument();

    // Add-new creates the option under the conversation's domain (va). Drive the
    // inline input with fireEvent — Radix Select's focus-restore races userEvent
    // keystrokes here (the combobox reclaims focus from the autofocused input).
    await user.click(screen.getByRole("option", { name: "+ New topic…" }));
    const nameInput = screen.getByLabelText("True Topic new name");
    fireEvent.change(nameInput, { target: { value: "widows_pension" } });
    fireEvent.keyDown(nameInput, { key: "Enter" });

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0].body).toMatchObject({
      topic: "widows_pension",
      domain: "va",
    });
  });

  it("the queue Domain filter drives a scoped server refetch", async () => {
    const user = userEvent.setup();
    const created: { body: unknown }[] = [];
    const seen: URLSearchParams[] = [];
    domainScopedServer(created);
    server.use(
      http.get(`${base}/datasets/:dataset/conversations`, ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: [
            {
              conversation: VA_CONV,
              domain: "va",
              message_count: 2,
              segment_count: 1,
              topics: [],
              reviewed_count: 0,
              reviewed: false,
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        });
      }),
    );

    await renderApp();
    await screen.findByText(VA_CONV);

    await user.click(await screen.findByRole("combobox", { name: "Domain" }));
    await user.click(screen.getByRole("option", { name: "Veterans Affairs" }));

    await waitFor(() =>
      expect(seen.some((p) => p.get("domain") === "va")).toBe(true),
    );
  });
});


describe("App labeler filter (identity-bound)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllEnvs();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("hides the labeler Select when the dataset has no worklist labelers", async () => {
    server.use(
      http.get(`${base}/datasets/:dataset/labelers`, () =>
        HttpResponse.json({ labelers: [] }),
      ),
    );

    await renderApp();

    // Wait until the dataset has loaded (the dataset Select shows the fixture).
    await waitFor(() =>
      expect(screen.getByText("e2e-fixture")).toBeInTheDocument(),
    );
    // With an empty labeler list the filter is not rendered at all.
    expect(
      screen.queryByRole("combobox", { name: "Labeler" }),
    ).not.toBeInTheDocument();
  });

  it("defaults the filter to the signed-in email when it is a labeler", async () => {
    const email = "ada@example.com";
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "test-client");
    sessionStorage.setItem(
      "eb1-annotation-auth",
      JSON.stringify({ token: "tkn", user: { name: "Ada", email } }),
    );
    server.use(
      http.get(`${base}/datasets/:dataset/labelers`, () =>
        HttpResponse.json({ labelers: [email, "labeler_b"] }),
      ),
    );

    await renderApp();

    // The labeler filter renders and defaults to the signed-in identity.
    const filter = await screen.findByRole("combobox", { name: "Labeler" });
    await waitFor(() => expect(filter).toHaveTextContent(email));
  });
});

// A conversations handler that resolves the UNFILTERED (no ?labeler) response
// after `unfilteredDelay`ms — the shape that lets a premature mount fetch land
// last and clobber the filtered list in the pre-fix code.
function delayedConversations(unfilteredDelay: number) {
  return http.get(`${base}/datasets/:dataset/conversations`, async ({ request }) => {
    const url = new URL(request.url);
    const labeler = url.searchParams.get("labeler");
    const items = labeler
      ? conversations.filter((c) => worklist[labeler]?.includes(c.conversation))
      : conversations;
    if (!labeler) await delay(unfilteredDelay);
    return HttpResponse.json({
      items,
      total: items.length,
      page: 1,
      page_size: 50,
    });
  });
}

describe("App queue fetch race", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllEnvs();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders only the filtered queue on mount with a persisted labeler, even when labelers resolves slowly and an unfiltered response lands last", async () => {
    localStorage.setItem("eb1.labeler", "labeler_a");
    server.use(
      http.get(`${base}/datasets/:dataset/labelers`, async () => {
        await delay(60);
        return HttpResponse.json({ labelers: ["labeler_a", "labeler_b"] });
      }),
      delayedConversations(120),
    );

    await renderApp();

    // labeler_a's worklist is [conv-001]; the unfiltered dataset also holds
    // conv-002. The queue must show the filtered list and never flash conv-002.
    await screen.findByText("conv-001");
    // Wait past the unfiltered response's delay: pre-fix that stale response
    // arrives here and clobbers state, surfacing conv-002.
    await delay(160);
    expect(screen.queryByText("conv-002")).not.toBeInTheDocument();
    expect(screen.getByText("conv-001")).toBeInTheDocument();
  });

  it("drops an out-of-order stale response: the newer filter wins even when the older request resolves last", async () => {
    const user = userEvent.setup();
    localStorage.setItem("eb1.labeler", "labeler_a");
    server.use(
      // The first (labeler_a) request is slow; the later labeler_b request is
      // fast, so the older response resolves last.
      http.get(`${base}/datasets/:dataset/conversations`, async ({ request }) => {
        const url = new URL(request.url);
        const labeler = url.searchParams.get("labeler");
        const items = labeler
          ? conversations.filter((c) => worklist[labeler]?.includes(c.conversation))
          : conversations;
        if (labeler === "labeler_a") await delay(150);
        return HttpResponse.json({
          items,
          total: items.length,
          page: 1,
          page_size: 50,
        });
      }),
    );

    await renderApp();

    // Switch to labeler_b while the initial labeler_a request is still in flight.
    await user.click(await screen.findByRole("combobox", { name: "Labeler" }));
    await user.click(screen.getByRole("option", { name: "labeler_b" }));

    // labeler_b's worklist is [conv-002]; assert it wins and stays after the
    // slower labeler_a response resolves.
    await screen.findByText("conv-002");
    await delay(200);
    expect(screen.getByText("conv-002")).toBeInTheDocument();
    expect(screen.queryByText("conv-001")).not.toBeInTheDocument();
  });

  it("fetches unfiltered exactly as before on a dataset with no worklist", async () => {
    server.use(
      http.get(`${base}/datasets/:dataset/labelers`, () =>
        HttpResponse.json({ labelers: [] }),
      ),
    );

    await renderApp();

    // No worklist → no filter Select and the full unfiltered queue.
    await screen.findByText("conv-001");
    expect(screen.getByText("conv-002")).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Labeler" }),
    ).not.toBeInTheDocument();
  });
});

describe("App validate-first prefill", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllEnvs();
    server.use(
      http.get(`${base}/datasets/:dataset/labelers`, () =>
        HttpResponse.json({ labelers: [] }),
      ),
    );
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("prefills an unreviewed segment's pickers from source labels and Save sends those slugs", async () => {
    // conv-001 segment 101 is unreviewed with source labels refunds/double_charge
    // (no gold). The pickers prefill the slugified source, so a single Save
    // validates it — and the payload is identical to a manual pick (slugs).
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.post(
        `${base}/datasets/:dataset/segments/:segmentId/annotate`,
        async ({ request }) => {
          bodies.push((await request.json()) as Record<string, unknown>);
          return HttpResponse.json({ ok: true });
        },
      ),
    );
    const user = userEvent.setup();

    await renderApp();

    await waitFor(() =>
      expect(screen.getByText("conv-001")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("conv-001"));
    await screen.findByText("Annotation", {}, { timeout: 4000 });

    // The True Topic picker prefilled from the source category (slug refunds →
    // "Refunds"), instead of empty.
    const topicPicker = await screen.findByRole("combobox", {
      name: "True Topic",
    });
    await waitFor(() => expect(topicPicker).toHaveTextContent("Refunds"));

    await user.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    expect(bodies[0]).toMatchObject({
      true_topic: "refunds",
      true_subtopic: "double_charge",
    });
  });

  it("prefills gold for a reviewed segment and re-derives the prefill on segment switch", async () => {
    const user = userEvent.setup();

    await renderApp();

    await waitFor(() =>
      expect(screen.getByText("conv-001")).toBeInTheDocument(),
    );
    await user.click(screen.getByText("conv-001"));
    await screen.findByText("Annotation", {}, { timeout: 4000 });

    // Segment 101 (unreviewed) → source prefill "Refunds".
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "True Topic" }),
      ).toHaveTextContent("Refunds"),
    );

    // Switch to segment 102 (reviewed, gold technical_support): the prefill
    // re-derives from gold, with no stale carryover from 101.
    await user.click(screen.getByText("Also I cannot log in on mobile."));
    await screen.findByText("102");
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "True Topic" }),
      ).toHaveTextContent("Technical Support"),
    );
  });
});
