import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api,
  setAuthToken,
  type AnnotateRequest,
  type BoundaryRequest,
} from "./api";

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

describe("api client request shapes", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    setAuthToken(null);
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
    const fetchMock = mockFetch([]);
    await api.listConversations("WildChat");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets/WildChat/conversations");
    expect(init?.method ?? "GET").toBe("GET");
    expect(init?.headers).toMatchObject({
      "Content-Type": "application/json",
    });
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
