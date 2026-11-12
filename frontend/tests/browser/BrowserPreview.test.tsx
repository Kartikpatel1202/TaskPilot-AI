import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BrowserPreview, type BrowserPreviewProps } from "@/components/browser/BrowserPreview";
import { INITIAL_BROWSER_PREVIEW, INITIAL_BROWSER_STATE } from "@/context/taskPilotReducer";

import { SESSION, uuidFor } from "../fixtures";

import type { BrowserLiveState, LiveFrame } from "@/types/browser";

function frame(sequence = 3): LiveFrame {
  return {
    url: `blob:frame-${sequence}`,
    receivedAt: Date.now(),
    meta: {
      frame_id: uuidFor(sequence),
      session_id: SESSION,
      task_id: null,
      sequence,
      captured_at: "2026-11-05T10:00:00+00:00",
      mime_type: "image/jpeg",
      width: 1440,
      height: 900,
    },
  };
}

const running: BrowserLiveState = {
  ...INITIAL_BROWSER_STATE,
  sessionStatus: "READY",
  headless: true,
  engine: "chromium",
  url: "http://127.0.0.1:8000/api/v1/dev/fixtures/shop/cart.html",
  title: "Cart — TaskPilot Demo Shop",
  domain: "127.0.0.1",
};

function renderPreview(props: Partial<BrowserPreviewProps> = {}) {
  return render(
    <BrowserPreview
      preview={INITIAL_BROWSER_PREVIEW}
      browser={INITIAL_BROWSER_STATE}
      sessionId={SESSION}
      onReconnect={vi.fn()}
      onClose={vi.fn().mockResolvedValue({ ok: true })}
      {...props}
    />,
  );
}

describe("BrowserPreview", () => {
  it("is honest when no browser runs: no image, explains Run Plan", () => {
    renderPreview();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("browser-empty")).toHaveAttribute("data-reason", "idle");
    expect(screen.getByTestId("browser-empty")).toHaveTextContent(/planning never opens one/i);
    expect(screen.getByTestId("browser-status")).toHaveTextContent("No browser running");
  });

  it("invites Run Plan when a plan is ready", () => {
    renderPreview({ planReady: true });
    expect(screen.getByTestId("browser-empty")).toHaveAttribute("data-reason", "plan_ready");
  });

  it("shows the real streamed frame with URL, mode and sequence", () => {
    renderPreview({ browser: running, frame: frame(7), streamStatus: "live" });
    const img = screen.getByRole("img", { name: /live browser screenshot #7/i });
    expect(img).toHaveAttribute("src", "blob:frame-7");
    expect(screen.getByTestId("browser-url")).toHaveTextContent("/fixtures/shop/cart.html");
    expect(screen.getByTestId("browser-status")).toHaveTextContent("Live");
    expect(screen.getByText("Headless")).toBeInTheDocument();
    expect(screen.getByTestId("browser-session-info")).toHaveTextContent("#7 · 1440×900");
  });

  it("waits honestly for the first frame while a browser runs", () => {
    renderPreview({ browser: running, executing: true });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("browser-empty")).toHaveAttribute("data-reason", "waiting_frame");
  });

  it("never shows an old frame after the browser was closed", () => {
    renderPreview({ browser: { ...INITIAL_BROWSER_STATE, sessionStatus: "CLOSED" }, frame: frame(2) });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("browser-empty")).toHaveAttribute("data-reason", "closed");
  });

  it("shows sign-in-required without offering to automate it", () => {
    renderPreview({
      browser: {
        ...running,
        sessionStatus: "AUTH_REQUIRED",
        notice: { kind: "authentication_required", message: "Please sign in to blinkit.com yourself.", at: "2026-11-05T10:00:00Z" },
      },
    });
    expect(screen.getByTestId("browser-notice")).toHaveAttribute("data-kind", "authentication_required");
    expect(screen.getByTestId("browser-notice")).toHaveTextContent(/never types passwords, otps or captchas/i);
    expect(screen.getByTestId("browser-status")).toHaveTextContent("Sign-in needed");
  });

  it("explains when execution is unavailable", () => {
    renderPreview({ executionAvailable: false, unavailableMessage: "Chromium is not installed." });
    expect(screen.getByTestId("browser-unavailable")).toHaveTextContent("Chromium is not installed.");
  });

  it("closing the browser needs a confirming second click and is hidden while executing", async () => {
    const onClose = vi.fn().mockResolvedValue({ ok: true });
    const { rerender } = renderPreview({ browser: running, onClose });
    await userEvent.click(screen.getByRole("button", { name: "Close browser" }));
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /confirm closing the browser/i }));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(
      <BrowserPreview preview={INITIAL_BROWSER_PREVIEW} browser={running} executing onReconnect={vi.fn()} onClose={onClose} />,
    );
    expect(screen.queryByRole("button", { name: /close browser/i })).not.toBeInTheDocument();
  });

  it("keeps the Phase 1 demo placeholder clearly labelled", () => {
    renderPreview({ preview: { ...INITIAL_BROWSER_PREVIEW, mode: "PLACEHOLDER", message: "Simulated", isDemo: true } });
    expect(screen.getByTestId("browser-empty")).toHaveAttribute("data-reason", "demo");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
