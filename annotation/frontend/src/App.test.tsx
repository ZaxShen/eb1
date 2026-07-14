import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
