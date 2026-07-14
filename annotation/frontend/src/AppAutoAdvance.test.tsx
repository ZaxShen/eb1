import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "./test/msw/server";
import { conversationView } from "./test/msw/handlers";

// @react-oauth/google reaches out to Google's gsi script on mount; App imports
// the provider at module scope, so stub it to inert passthroughs.
vi.mock("@react-oauth/google", () => ({
  GoogleOAuthProvider: ({ children }: { children: ReactNode }) => children,
  GoogleLogin: () => null,
  useGoogleLogin: () => () => {},
}));

const base = "/api";

async function renderApp() {
  vi.resetModules();
  const { default: App } = await import("./App");
  return render(createElement(App));
}

// Open a queue conversation and wait for its stream to load. The queue settles
// in several async phases on mount (datasets → labelers → conversations); click
// once it's stable and retry until a marker from the loaded conversation shows,
// so a click that lands mid-settle can't leave the test hanging on a stale row.
async function openConversation(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
  marker: string,
): Promise<void> {
  await waitFor(() =>
    expect(screen.getByText(name)).toBeInTheDocument(),
  );
  await waitFor(
    async () => {
      await user.click(screen.getByText(name));
      expect(screen.getByText(marker)).toBeInTheDocument();
    },
    { timeout: 3000 },
  );
}

// A conv-002 detail with a single, distinctly-numbered segment (201) so a test
// can prove selection crossed into the next conversation after a save.
const conversationView002 = {
  conversation: "conv-002",
  frozen_boundaries: false,
  messages: [
    {
      index: 0,
      id: "n0",
      type: "user",
      message: "I cannot sign in at all.",
      createdAt: "2026-01-03T10:00:00Z",
    },
    {
      index: 1,
      id: "n1",
      type: "assistant",
      message: "Let us reset your MFA.",
      createdAt: "2026-01-03T10:00:30Z",
    },
  ],
  segments: [
    {
      id: 201,
      conversation: "conv-002",
      chunk_index: 0,
      message_indices: [0, 1],
      summary: "MFA reset.",
      topic: "technical_support",
      subtopic: "login_issue",
      sentiment: null,
      label_confidence: null,
      reviewed: false,
      true_topic: null,
      true_subtopic: null,
      bertopic_topic: "logins",
      bertopic_subtopic: "mfa_reset",
    },
  ],
  gold_segments: [],
};

describe("App auto-advance after save", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllEnvs();
    server.use(
      http.get(`${base}/datasets/:dataset/labelers`, () =>
        HttpResponse.json({ labelers: [] }),
      ),
      http.post(
        `${base}/datasets/:dataset/segments/:segmentId/annotate`,
        () => HttpResponse.json({ ok: true }),
      ),
      http.get(
        `${base}/datasets/:dataset/conversations/:conversation`,
        ({ params }) =>
          HttpResponse.json(
            params.conversation === "conv-002"
              ? conversationView002
              : conversationView,
          ),
      ),
    );
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("advances to the next segment of the same conversation after a save", async () => {
    const user = userEvent.setup();

    await renderApp();

    // Open conv-001: its first segment (101) is auto-selected (Segment Fields
    // shows its id).
    await openConversation(user, "conv-001", "101");

    // Save advances selection to the next segment (102) in document order.
    await user.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(screen.getByText("102")).toBeInTheDocument());
    expect(screen.queryByText("101")).not.toBeInTheDocument();
  });

  it("advances to the next conversation's first segment when the last segment is saved", async () => {
    const user = userEvent.setup();

    await renderApp();

    await openConversation(user, "conv-001", "101");
    // Select the LAST segment (102) by clicking one of its messages.
    await user.click(
      await screen.findByText("Also I cannot log in on mobile."),
    );
    await screen.findByText("102");

    // Saving the last segment crosses into conv-002 and selects its first
    // segment (201).
    await user.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(screen.getByText("201")).toBeInTheDocument());
  });
});
