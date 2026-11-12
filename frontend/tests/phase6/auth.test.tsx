import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { AuthGate, useAuth } from "@/components/auth/AuthGate";
import { ErrorBoundary } from "@/components/system/ErrorBoundary";
import { TaskHistory } from "@/components/history/TaskHistory";
import { request } from "@/lib/api";
import { approvalStatusSchema } from "@/lib/validators";

type Handler = (url: string, init: RequestInit) => { status: number; body?: unknown };

function mockFetch(handler: Handler) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    calls.push({ url, init });
    const { status, body } = handler(url, init);
    return new Response(body === undefined ? "" : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

const USER = { user_id: "u1", email: "owner@example.test", role: "OWNER" };

function Whoami() {
  const { user } = useAuth();
  return <p data-testid="whoami">{user?.email ?? "nobody"}</p>;
}

beforeEach(() => {
  document.cookie = "tp_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Phase 6 API client", () => {
  it("sends cookies and the CSRF header on mutations only", async () => {
    document.cookie = "tp_csrf=csrf-value";
    const calls = mockFetch(() => ({ status: 200, body: {} }));
    await request("/x", { method: "POST", body: { a: 1 } });
    await request("/y", {});
    expect(calls[0]!.init.credentials).toBe("include");
    expect((calls[0]!.init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-value");
    expect((calls[1]!.init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("refreshes an expired access token once and retries", async () => {
    let first = true;
    const calls = mockFetch((url) => {
      if (url.endsWith("/auth/refresh")) return { status: 200, body: {} };
      if (first) {
        first = false;
        return { status: 401, body: { code: "TOKEN_EXPIRED", message: "expired" } };
      }
      return { status: 200, body: { ok: true } };
    });
    await expect(request("/tasks", { schema: z.object({ ok: z.boolean() }) })).resolves.toEqual({ ok: true });
    expect(calls.map((c) => c.url.split("/api/v1")[1])).toEqual(["/tasks", "/auth/refresh", "/tasks"]);
  });

  it("does not loop when the refresh itself fails", async () => {
    const calls = mockFetch((url) =>
      url.endsWith("/auth/refresh") ? { status: 401, body: { code: "INVALID_TOKEN", message: "no" } } : { status: 401, body: { code: "TOKEN_EXPIRED", message: "expired" } });
    await expect(request("/tasks", {})).rejects.toMatchObject({ status: 401 });
    expect(calls).toHaveLength(2);
  });
});

describe("AuthGate", () => {
  it("leaves the dashboard open when the server does not require auth", async () => {
    mockFetch((url) => (url.endsWith("/auth/config") ? { status: 200, body: { auth_required: false, registration_enabled: true, mode: "local" } } : { status: 404 }));
    render(<AuthGate><Whoami /></AuthGate>);
    expect(await screen.findByTestId("whoami")).toHaveTextContent("nobody");
  });

  it("shows sign-in when auth is required and there is no session; nothing else renders", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/config")) return { status: 200, body: { auth_required: true, registration_enabled: false, mode: "local" } };
      if (url.endsWith("/auth/me")) return { status: 401, body: { code: "NOT_AUTHENTICATED", message: "Sign in" } };
      if (url.endsWith("/auth/login")) return { status: 200, body: { user: USER, access_expires_in: 900, csrf_token: "t" } };
      return { status: 404 };
    });
    render(<AuthGate><Whoami /></AuthGate>);
    expect(await screen.findByTestId("login-screen")).toBeInTheDocument();
    expect(screen.queryByTestId("whoami")).toBeNull();
    expect(screen.queryByText(/create an account/i)).toBeNull();

    await userEvent.type(screen.getByLabelText("Email"), "owner@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByTestId("login-submit"));
    expect(await screen.findByTestId("whoami")).toHaveTextContent("owner@example.test");
  });

  it("shows a wrong-password error without revealing which field was wrong", async () => {
    mockFetch((url) => {
      if (url.endsWith("/auth/config")) return { status: 200, body: { auth_required: true, registration_enabled: false, mode: "local" } };
      if (url.endsWith("/auth/me")) return { status: 401, body: { code: "NOT_AUTHENTICATED", message: "Sign in" } };
      return { status: 401, body: { code: "INVALID_CREDENTIALS", message: "Email or password is incorrect." } };
    });
    render(<AuthGate><Whoami /></AuthGate>);
    await userEvent.type(await screen.findByLabelText("Email"), "a@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password-123");
    await userEvent.click(screen.getByTestId("login-submit"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});

describe("Resilience UI", () => {
  it("an error boundary contains a crashing panel", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const Boom = () => {
      throw new Error("secret internal detail");
    };
    render(<ErrorBoundary label="Panel" inline><Boom /></ErrorBoundary>);
    expect(screen.getByTestId("error-boundary")).toHaveTextContent("Panel hit an unexpected problem.");
    expect(screen.getByTestId("error-boundary")).not.toHaveTextContent("secret internal detail");
    spy.mockRestore();
  });

  it("task history pages through results with a cursor", async () => {
    const task = (n: number) => ({
      task_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, session_id: "00000000-0000-4000-8000-000000000999",
      command: `command ${n}`, state: n === 1 ? "FAILED" : "COMPLETED", error_code: n === 1 ? "EXECUTION_INTERRUPTED" : null,
      error_message: n === 1 ? "Server restarted" : null, execution_status: null,
      recovery_note: n === 1 ? "Nothing was repeated automatically." : null, created_at: "2026-11-10T10:00:00Z", updated_at: "2026-11-10T10:00:00Z",
    });
    const calls = mockFetch((url) => (url.includes("cursor=") ? { status: 200, body: { tasks: [task(3)], next_cursor: null } } : { status: 200, body: { tasks: [task(1), task(2)], next_cursor: "c1" } }));
    render(<TaskHistory sessionId={null} />);
    expect(await screen.findAllByTestId("history-item")).toHaveLength(2);
    await userEvent.click(screen.getByText("command 1"));
    expect(screen.getByTestId("history-details")).toHaveTextContent("Nothing was repeated automatically.");
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));
    await waitFor(() => expect(screen.getAllByTestId("history-item")).toHaveLength(3));
    expect(calls[1]!.url).toContain("cursor=c1");
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });

  it("accepts the WITHDRAWN approval status", () => {
    expect(approvalStatusSchema.parse("WITHDRAWN")).toBe("WITHDRAWN");
  });
});
