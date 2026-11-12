"use client";

import { Loader2, LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";

import { LogoMark } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { login, register, type AuthUser } from "@/lib/authApi";

export interface LoginScreenProps {
  registrationEnabled: boolean;
  onSignedIn: (user: AuthUser) => void;
  notice?: string | null;
}

/** Sign in to TaskPilot (your TaskPilot account — never a website's password; those you enter on the site yourself). */
export function LoginScreen({ registrationEnabled, onSignedIn, notice }: LoginScreenProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(notice ?? null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await register(email.trim(), password);
        setInfo("Account created. Please sign in.");
        setMode("login");
      } else {
        onSignedIn(await login(email.trim(), password));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach TaskPilot. Please try again.");
    } finally {
      setBusy(false);
      setPassword("");
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center p-6" data-testid="login-screen">
      <form onSubmit={(e) => void submit(e)} className="flex w-full max-w-sm flex-col gap-4 rounded-xl border border-white/[0.08] bg-white/[0.02] p-6"
        aria-labelledby="login-title">
        <LogoMark className="h-8 w-8" />
        <h1 id="login-title" className="flex items-center gap-2 text-lg font-semibold">
          <LockKeyhole className="h-4 w-4" aria-hidden /> {mode === "login" ? "Sign in to TaskPilot" : "Create your account"}
        </h1>
        {info && <p role="status" className="text-xs text-muted-foreground">{info}</p>}
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-border bg-transparent px-3 py-2" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input type="password" required autoComplete={mode === "login" ? "current-password" : "new-password"} value={password}
            onChange={(e) => setPassword(e.target.value)} className="rounded-md border border-border bg-transparent px-3 py-2" />
        </label>
        {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
        <Button type="submit" disabled={busy || !email || !password} data-testid="login-submit">
          {busy && <Loader2 className="animate-spin" aria-hidden />} {mode === "login" ? "Sign in" : "Create account"}
        </Button>
        {registrationEnabled && (
          <Button type="button" variant="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "Create an account" : "I already have an account"}
          </Button>
        )}
        <p className="text-[11px] text-muted-foreground">
          This signs you in to TaskPilot only. Kamlesh Bhai never types your passwords or OTPs on any website.
        </p>
      </form>
    </main>
  );
}
