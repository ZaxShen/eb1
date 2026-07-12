import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { jwtDecode } from "jwt-decode";
import { setAuthToken, setOnAuthExpired } from "../api";

export interface GoogleUser {
  name: string;
  email: string;
  picture?: string;
}

interface GoogleIdClaims {
  name?: string;
  email?: string;
  picture?: string;
}

interface AuthState {
  ssoEnabled: boolean;
  clientId: string | null;
  token: string | null;
  user: GoogleUser | null;
  signIn: (credential: string) => void;
  signOut: () => void;
}

const STORAGE_KEY = "eb1-annotation-auth";

export const GOOGLE_CLIENT_ID: string | null =
  import.meta.env.VITE_GOOGLE_CLIENT_ID || null;

const AuthContext = createContext<AuthState | null>(null);

interface StoredAuth {
  token: string;
  user: GoogleUser;
}

function readStored(): StoredAuth | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
}

export function userFromCredential(credential: string): GoogleUser {
  const claims = jwtDecode<GoogleIdClaims>(credential);
  return {
    name: claims.name ?? claims.email ?? "",
    email: claims.email ?? "",
    picture: claims.picture,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const ssoEnabled = GOOGLE_CLIENT_ID !== null;

  const [stored, setStored] = useState<StoredAuth | null>(() => {
    if (!ssoEnabled) return null;
    const initial = readStored();
    if (initial) setAuthToken(initial.token);
    return initial;
  });

  const token = stored?.token ?? null;
  const user = stored?.user ?? null;

  useEffect(() => {
    setAuthToken(ssoEnabled ? token : null);
  }, [ssoEnabled, token]);

  const signIn = useCallback((credential: string) => {
    setAuthToken(credential);
    const next: StoredAuth = {
      token: credential,
      user: userFromCredential(credential),
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setStored(next);
  }, []);

  const signOut = useCallback(() => {
    setAuthToken(null);
    sessionStorage.removeItem(STORAGE_KEY);
    setStored(null);
  }, []);

  useEffect(() => {
    setOnAuthExpired(signOut);
    return () => setOnAuthExpired(null);
  }, [signOut]);

  const value = useMemo<AuthState>(
    () => ({
      ssoEnabled,
      clientId: GOOGLE_CLIENT_ID,
      token,
      user,
      signIn,
      signOut,
    }),
    [ssoEnabled, token, user, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
