"use client";

import { Loader2 } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { setSessionExpiredHandler } from "@/lib/api";
import { getAuthConfig, getMe, logout as logoutRequest, type AuthUser } from "@/lib/authApi";

import { LoginScreen } from "./LoginScreen";

interface AuthState {
  user: AuthUser | null;
  authRequired: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({ user: null, authRequired: false, signOut: async () => undefined });

export const useAuth = () => useContext(AuthContext);

/**
 * Phase 6: when the server enforces authentication, nothing (no telemetry socket, no task data) loads until
 * the user signs in. In development without authentication the dashboard behaves exactly as before.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<"checking" | "anonymous" | "signed-in" | "open">("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [registration, setRegistration] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const config = await getAuthConfig();
        if (!alive) return;
        setRegistration(config.registration_enabled);
        if (!config.auth_required) {
          setPhase("open");
          return;
        }
        try {
          const me = await getMe();
          if (alive) {
            setUser(me);
            setPhase("signed-in");
          }
        } catch {
          if (alive) setPhase("anonymous");
        }
      } catch {
        // Backend unreachable: keep the existing offline/reconnecting experience of the dashboard.
        if (alive) setPhase("open");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setUser(null);
      setNotice("Your session expired. Please sign in again.");
      setPhase((p) => (p === "signed-in" ? "anonymous" : p));
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
      setPhase("anonymous");
    }
  }, []);

  const value = useMemo(() => ({ user, authRequired: phase === "signed-in" || phase === "anonymous", signOut }), [user, phase, signOut]);

  if (phase === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status" aria-live="polite">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden /> <span className="sr-only">Loading…</span>
      </div>
    );
  }
  if (phase === "anonymous") {
    return (
      <LoginScreen registrationEnabled={registration} notice={notice} onSignedIn={(u) => {
        setUser(u);
        setNotice(null);
        setPhase("signed-in");
      }} />
    );
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
