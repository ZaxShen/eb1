import type { ReactNode } from "react";
import { GoogleLogin } from "@react-oauth/google";
import { useAuth } from "./AuthContext";

export default function SignInGate({ children }: { children: ReactNode }) {
  const { ssoEnabled, token, signIn } = useAuth();

  if (!ssoEnabled || token) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 bg-muted text-foreground">
      <div className="flex flex-col items-center gap-2">
        <h1 className="text-lg font-semibold tracking-tight">eb1 Annotation</h1>
        <p className="text-sm text-muted-foreground">
          Sign in with Google to continue
        </p>
      </div>
      <GoogleLogin
        onSuccess={(resp) => {
          if (resp.credential) signIn(resp.credential);
        }}
        onError={() => {
          /* surfaced by the Google widget; nothing to persist */
        }}
        useOneTap
      />
    </div>
  );
}
