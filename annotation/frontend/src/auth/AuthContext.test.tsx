import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";

// jwt-decode is mocked so tests never need a real Google ID token.
vi.mock("jwt-decode", () => ({
  jwtDecode: (token: string) => {
    if (token === "tok-ada") {
      return {
        name: "Ada Lovelace",
        email: "ada@example.com",
        picture: "https://example.com/ada.png",
      };
    }
    return { name: "Unknown", email: "u@example.com" };
  },
}));

// Spy on the api token setter so we can assert the Bearer token is wired.
const setAuthToken = vi.fn();
const setOnAuthExpired = vi.fn();
vi.mock("../api", () => ({ setAuthToken, setOnAuthExpired }));

async function loadAuth(clientId: string | undefined) {
  vi.resetModules();
  if (clientId === undefined) {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "");
  } else {
    vi.stubEnv("VITE_GOOGLE_CLIENT_ID", clientId);
  }
  return import("./AuthContext");
}

function Probe({
  useAuth,
}: {
  useAuth: () => {
    ssoEnabled: boolean;
    token: string | null;
    user: { name: string } | null;
    signIn: (c: string) => void;
    signOut: () => void;
  };
}) {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="sso">{String(auth.ssoEnabled)}</span>
      <span data-testid="token">{auth.token ?? "none"}</span>
      <span data-testid="name">{auth.user?.name ?? "none"}</span>
      <button onClick={() => auth.signIn("tok-ada")}>in</button>
      <button onClick={() => auth.signOut()}>out</button>
    </div>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    setAuthToken.mockClear();
    setOnAuthExpired.mockClear();
    sessionStorage.clear();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("is disabled and tokenless when no client id is configured", async () => {
    const { AuthProvider, useAuth } = await loadAuth(undefined);
    render(
      <AuthProvider>
        <Probe useAuth={useAuth} />
      </AuthProvider>,
    );
    expect(screen.getByTestId("sso").textContent).toBe("false");
    expect(screen.getByTestId("token").textContent).toBe("none");
    // SSO off → api token cleared, never set to a value.
    expect(setAuthToken).toHaveBeenLastCalledWith(null);
  });

  it("applies a restored token before a child effect runs (no tokenless first fetch)", async () => {
    sessionStorage.setItem(
      "eb1-annotation-auth",
      JSON.stringify({ token: "tok-ada", user: { name: "Ada Lovelace", email: "ada@example.com" } }),
    );
    const { AuthProvider } = await loadAuth("client-123");

    // Stands in for App's data-fetch effect: React runs child effects before the
    // provider's own effect, so this observes exactly what the first fetch sees.
    let callsWhenChildFetched = -1;
    let tokenWhenChildFetched: string | null | undefined;
    function FetchProbe() {
      useEffect(() => {
        callsWhenChildFetched = setAuthToken.mock.calls.length;
        tokenWhenChildFetched = setAuthToken.mock.calls[0]?.[0];
      }, []);
      return null;
    }

    await act(async () => {
      render(
        <AuthProvider>
          <FetchProbe />
        </AuthProvider>,
      );
    });

    expect(callsWhenChildFetched).toBeGreaterThan(0);
    expect(tokenWhenChildFetched).toBe("tok-ada");
  });

  it("sign-in applies the bearer token synchronously, before effects flush", async () => {
    const { AuthProvider, useAuth } = await loadAuth("client-123");
    render(
      <AuthProvider>
        <Probe useAuth={useAuth} />
      </AuthProvider>,
    );
    expect(screen.getByTestId("sso").textContent).toBe("true");

    setAuthToken.mockClear();
    act(() => {
      screen.getByText("in").click();
      // Inside the click handler, before React flushes any effect, the token is
      // already pushed to the api module — the assertion fails on effect-only code.
      expect(setAuthToken).toHaveBeenCalledWith("tok-ada");
    });

    expect(screen.getByTestId("token").textContent).toBe("tok-ada");
    expect(screen.getByTestId("name").textContent).toBe("Ada Lovelace");
    expect(setAuthToken).toHaveBeenLastCalledWith("tok-ada");
    expect(JSON.parse(sessionStorage.getItem("eb1-annotation-auth")!)).toMatchObject({
      token: "tok-ada",
      user: { name: "Ada Lovelace", email: "ada@example.com" },
    });
  });

  it("sign-out clears the token, the user, and storage", async () => {
    const { AuthProvider, useAuth } = await loadAuth("client-123");
    render(
      <AuthProvider>
        <Probe useAuth={useAuth} />
      </AuthProvider>,
    );
    act(() => screen.getByText("in").click());
    act(() => screen.getByText("out").click());

    expect(screen.getByTestId("token").textContent).toBe("none");
    expect(screen.getByTestId("name").textContent).toBe("none");
    expect(sessionStorage.getItem("eb1-annotation-auth")).toBeNull();
    expect(setAuthToken).toHaveBeenLastCalledWith(null);
  });

  it("registers a sign-out handler for expired sessions that clears auth state", async () => {
    const { AuthProvider, useAuth } = await loadAuth("client-123");
    render(
      <AuthProvider>
        <Probe useAuth={useAuth} />
      </AuthProvider>,
    );
    act(() => screen.getByText("in").click());
    expect(screen.getByTestId("token").textContent).toBe("tok-ada");

    // AuthContext registered a callback with the api module; the last one wins.
    const registered = setOnAuthExpired.mock.calls
      .map((c) => c[0])
      .filter((cb): cb is () => void => typeof cb === "function")
      .at(-1);
    expect(registered).toBeTypeOf("function");

    setAuthToken.mockClear();
    act(() => registered!());

    expect(screen.getByTestId("token").textContent).toBe("none");
    expect(sessionStorage.getItem("eb1-annotation-auth")).toBeNull();
    expect(setAuthToken).toHaveBeenLastCalledWith(null);
  });
});
