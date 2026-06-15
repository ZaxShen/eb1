import type { ReactElement, ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "../auth/AuthContext";

// @react-oauth/google reaches out to Google's gsi script on mount; component
// tests never need real SSO, so stub the provider/button to inert passthroughs.
vi.mock("@react-oauth/google", () => ({
  GoogleOAuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  GoogleLogin: () => null,
  useGoogleLogin: () => () => {},
}));

function AllProviders({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <TooltipProvider delayDuration={0}>{children}</TooltipProvider>
    </AuthProvider>
  );
}

// One-liner render that wraps a component in the app's providers (Auth +
// Tooltip), so component tests don't re-assemble the tree each time.
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
) {
  return render(ui, { wrapper: AllProviders, ...options });
}

export * from "@testing-library/react";
