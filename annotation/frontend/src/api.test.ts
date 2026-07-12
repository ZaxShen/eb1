import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import {
  api,
  setAuthToken,
  setOnAuthExpired,
  type AnnotateRequest,
  type BoundaryRequest,
} from "./api";

vi.mock("jwt-decode", () => ({
  jwtDecode: () => ({ name: "Ada", email: "ada@example.com" }),
}));
vi.mock("@react-oauth/google", () => ({
  GoogleLogin: () => createElement("button", null, "Sign in with Google"),
}));

function mockFetch(payload: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => payload,
  } as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

function mockErrorFetch(status: number, detail = "error") {
  const fn = vi.fn().mockResolvedValue({
    ok: false,
    status,
    statusText: detail,
    json: async () => ({ detail }),
  } as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("api client request shapes", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setAuthToken(null);
    setOnAuthExpired(null);
  });

  it("attaches an Authorization: Bearer header when an auth token is set", async () => {
    const fetchMock = mockFetch([]);
    setAuthToken("id-token-xyz");
    await api.listDatasets();

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({
      Authorization: "Bearer id-token-xyz",
    });
  });

  it("omits the Authorization header when no auth token is set", async () => {
    const fetchMock = mockFetch([]);
    setAuthToken(null);
    await api.listDatasets();

    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("listConversations issues a GET to the dataset conversations path", async () => {
    const fetchMock = mockFetch({ items: [], total: 0, page: 1, page_size: 50 });
    await api.listConversations("WildChat");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets/WildChat/conversations");
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.headers).toMatchObject({
      "Content-Type": "application/json",
    });
  });

  it("listConversations encodes pagination + search query params", async () => {
    const fetchMock = mockFetch({ items: [], total: 0, page: 2, page_size: 25 });
    await api.listConversations("WildChat", {
      page: 2,
      pageSize: 25,
      q: "refund",
      status: "unreviewed",
      topic: "billing",
    });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string, "http://localhost");
    expect(parsed.pathname).toBe("/api/datasets/WildChat/conversations");
    expect(parsed.searchParams.get("page")).toBe("2");
    expect(parsed.searchParams.get("page_size")).toBe("25");
    expect(parsed.searchParams.get("q")).toBe("refund");
    expect(parsed.searchParams.get("status")).toBe("unreviewed");
    expect(parsed.searchParams.get("topic")).toBe("billing");
  });

  it("annotate POSTs the request body to the segment annotate path", async () => {
    const fetchMock = mockFetch({ gold_segment_id: 1, reviewed: true });
    const body: AnnotateRequest = {
      true_topic: "billing",
      true_subtopic: "refund",
      sentiment: "neutral",
      reviewed_by: "zax",
    };
    await api.annotate("WildChat", 42, body);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets/WildChat/segments/42/annotate");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual(body);
  });

  it("clearAnnotation issues a DELETE to the segment annotate path", async () => {
    const fetchMock = mockFetch({ segment_id: 42, deleted: 1, reviewed: false });
    await api.clearAnnotation("WildChat", 42);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets/WildChat/segments/42/annotate");
    expect(init?.method).toBe("DELETE");
  });

  it("replaceBoundaries POSTs the segment set to the conversation boundaries path", async () => {
    const fetchMock = mockFetch({
      conversation: "conv-1",
      gold_segments_written: 2,
    });
    const body: BoundaryRequest = {
      segments: [{ message_indices: [0, 1] }, { message_indices: [2, 3] }],
      reviewed_by: "zax",
    };
    await api.replaceBoundaries("WildChat", "conv 1", body);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets/WildChat/conversations/conv%201/boundaries");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual(body);
  });
});

describe("api client auth-expiry handling", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    setAuthToken(null);
    setOnAuthExpired(null);
  });

  it("invokes onAuthExpired when a token-bearing request gets a 401", async () => {
    mockErrorFetch(401, "Invalid token");
    const onExpired = vi.fn();
    setOnAuthExpired(onExpired);
    setAuthToken("stale-token");

    await expect(api.listDatasets()).rejects.toThrow("401 Invalid token");
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("does not invoke onAuthExpired on a 401 with no token attached", async () => {
    mockErrorFetch(401, "Invalid token");
    const onExpired = vi.fn();
    setOnAuthExpired(onExpired);
    setAuthToken(null);

    await expect(api.listDatasets()).rejects.toThrow("401 Invalid token");
    expect(onExpired).not.toHaveBeenCalled();
  });

  it("does not invoke onAuthExpired on a non-401 failure", async () => {
    mockErrorFetch(500, "Server error");
    const onExpired = vi.fn();
    setOnAuthExpired(onExpired);
    setAuthToken("valid-token");

    await expect(api.listDatasets()).rejects.toThrow("500 Server error");
    expect(onExpired).not.toHaveBeenCalled();
  });

  it("signs out and re-shows the gate when a live session's request 401s", async () => {
    sessionStorage.setItem(
      "eb1-annotation-auth",
      JSON.stringify({ token: "live-token", user: { name: "Ada", email: "ada@example.com" } }),
    );
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "client-123");
    const { AuthProvider } = await import("./auth/AuthContext");
    const { default: SignInGate } = await import("./auth/SignInGate");

    render(
      createElement(
        AuthProvider,
        null,
        createElement(SignInGate, null, createElement("div", null, "protected content")),
      ),
    );
    expect(screen.getByText("protected content")).toBeInTheDocument();

    mockErrorFetch(401, "Invalid token");
    await act(async () => {
      await expect(api.listDatasets()).rejects.toThrow("401 Invalid token");
    });

    expect(sessionStorage.getItem("eb1-annotation-auth")).toBeNull();
    expect(screen.queryByText("protected content")).toBeNull();
    expect(screen.getByText("Sign in with Google")).toBeInTheDocument();

    const okFetch = mockFetch([]);
    await api.listDatasets();
    const [, reinit] = okFetch.mock.calls[0];
    expect((reinit?.headers as Record<string, string>).Authorization).toBeUndefined();
  });
});
