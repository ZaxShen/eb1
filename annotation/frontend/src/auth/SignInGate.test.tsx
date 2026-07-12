import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// @react-oauth/google can't run a real sign-in offline; render a stand-in
// button so the gate's "show sign-in until authed" branch is testable.
const googleLoginProps = vi.fn();
vi.mock("@react-oauth/google", () => ({
  GoogleLogin: (props: Record<string, unknown>) => {
    googleLoginProps(props);
    return <button>Sign in with Google</button>;
  },
}));
vi.mock("jwt-decode", () => ({
  jwtDecode: () => ({ name: "Ada", email: "ada@example.com" }),
}));
vi.mock("../api", () => ({ setAuthToken: vi.fn(), setOnAuthExpired: vi.fn() }));

async function loadModules(clientId: string | undefined) {
  vi.resetModules();
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", clientId ?? "");
  const ctx = await import("./AuthContext");
  const gate = await import("./SignInGate");
  return { ...ctx, SignInGate: gate.default };
}

describe("SignInGate", () => {
  beforeEach(() => {
    sessionStorage.clear();
    googleLoginProps.mockClear();
  });
  afterEach(() => vi.unstubAllEnvs());

  it("renders children directly when SSO is disabled", async () => {
    const { AuthProvider, SignInGate } = await loadModules(undefined);
    render(
      <AuthProvider>
        <SignInGate>
          <div>protected content</div>
        </SignInGate>
      </AuthProvider>,
    );
    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(screen.queryByText("Sign in with Google")).toBeNull();
  });

  it("shows the sign-in screen (not the app) when SSO is on and unauthed", async () => {
    const { AuthProvider, SignInGate } = await loadModules("client-123");
    render(
      <AuthProvider>
        <SignInGate>
          <div>protected content</div>
        </SignInGate>
      </AuthProvider>,
    );
    expect(screen.getByText("Sign in with Google")).toBeInTheDocument();
    expect(screen.queryByText("protected content")).toBeNull();
  });

  it("renders children when SSO is on and a token is already stored", async () => {
    sessionStorage.setItem(
      "eb1-annotation-auth",
      JSON.stringify({ token: "tok", user: { name: "Ada", email: "ada@example.com" } }),
    );
    const { AuthProvider, SignInGate } = await loadModules("client-123");
    render(
      <AuthProvider>
        <SignInGate>
          <div>protected content</div>
        </SignInGate>
      </AuthProvider>,
    );
    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(screen.queryByText("Sign in with Google")).toBeNull();
  });

  it("enables One Tap and auto_select for low-friction re-auth", async () => {
    const { AuthProvider, SignInGate } = await loadModules("client-123");
    render(
      <AuthProvider>
        <SignInGate>
          <div>protected content</div>
        </SignInGate>
      </AuthProvider>,
    );
    expect(googleLoginProps).toHaveBeenCalledWith(
      expect.objectContaining({ useOneTap: true, auto_select: true }),
    );
  });
});
