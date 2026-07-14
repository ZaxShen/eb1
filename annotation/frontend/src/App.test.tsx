import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "./test/msw/server";

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
