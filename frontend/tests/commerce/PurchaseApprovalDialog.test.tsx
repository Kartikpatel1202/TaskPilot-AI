import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalDialog } from "@/components/approval/ApprovalDialog";
import { initialTaskPilotState, mapEventToActions, taskPilotReducer, type TaskPilotState } from "@/context/taskPilotReducer";
import { parseServerMessage } from "@/lib/validators";

import { SESSION, TASK, uuidFor } from "../fixtures";
import { purchaseApproval } from "./commerceFixtures";

import type { AnyTelemetryEvent } from "@/types/telemetry";

function setup(onDecide = vi.fn().mockResolvedValue({ approval_id: uuidFor(600), decision: "APPROVE", status: "APPROVED", resolved_at: "2026-11-06T10:00:05Z" })) {
  render(<ApprovalDialog approval={purchaseApproval()} open onOpenChange={vi.fn()} onDecide={onDecide} />);
  return onDecide;
}

describe("PurchaseApprovalDialog", () => {
  it("shows the exact order being approved instead of a generic dialog", () => {
    setup();
    const dialog = screen.getByTestId("purchase-approval-dialog");
    expect(dialog).toHaveTextContent(/final purchase review/i);
    expect(screen.getByTestId("purchase-items")).toHaveTextContent("1. Amul Taaza Toned Fresh Milk — 2 × 1 ltr");
    expect(dialog.querySelector('[data-field="total"]')).toHaveTextContent("₹212.00");
    expect(screen.getByTestId("purchase-address")).toHaveTextContent("Home: •••, Gurugram 122•••");
    expect(screen.getByTestId("purchase-payment")).toHaveTextContent("Cash on Delivery");
    expect(screen.getByTestId("purchase-warning")).toHaveTextContent(/may place a real cash-on-delivery order/i);
    expect(screen.getByText(/expires in/i)).toBeInTheDocument();
    expect(screen.getByTestId("confirm-purchase")).toHaveTextContent("Confirm This Exact Order");
    expect(screen.getByTestId("reject-purchase")).toHaveTextContent("Reject Purchase");
  });

  it("Enter never approves; focus is not on a decision button", () => {
    const onDecide = setup();
    expect(document.activeElement).not.toBe(screen.getByTestId("confirm-purchase"));
    fireEvent.keyDown(screen.getByTestId("purchase-approval-dialog"), { key: "Enter" });
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("an explicit click approves exactly once", async () => {
    const onDecide = setup();
    await userEvent.click(screen.getByTestId("confirm-purchase"));
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith(uuidFor(600), "APPROVE");
    expect(await screen.findByRole("status")).toHaveTextContent("approved");
  });

  it("reject is explicit too", async () => {
    const onDecide = setup(vi.fn().mockResolvedValue({ approval_id: uuidFor(600), decision: "REJECT", status: "REJECTED", resolved_at: "2026-11-06T10:00:05Z" }));
    await userEvent.click(screen.getByTestId("reject-purchase"));
    expect(onDecide).toHaveBeenCalledWith(uuidFor(600), "REJECT");
  });

  it("expired reviews cannot be approved", () => {
    render(<ApprovalDialog approval={purchaseApproval({ status: "EXPIRED", expires_at: "2026-01-01T00:00:00Z" })} open onOpenChange={vi.fn()} onDecide={vi.fn()} />);
    expect(screen.queryByTestId("confirm-purchase")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/expired/i);
  });
});

// ------------------------------------------------------------------ commerce telemetry -> reducer

let seq = 0;
function event(type: string, data: Record<string, unknown>): AnyTelemetryEvent {
  seq += 1;
  const parsed = parseServerMessage(JSON.stringify({ event_id: uuidFor(9000 + seq), session_id: SESSION, task_id: TASK, sequence: seq,
    occurred_at: "2026-11-06T10:00:05.000000+00:00", type, data }));
  if (!parsed.ok || parsed.message.kind !== "event") throw new Error(`invalid ${type}`);
  return parsed.message.event;
}

function active(): TaskPilotState {
  return taskPilotReducer(initialTaskPilotState, { type: "TASK_ACCEPTED", task: {
    task_id: TASK, session_id: SESSION, command: "c", input_mode: "TEXT", state: "EXECUTING", created_at: "2026-11-06T10:00:00Z", updated_at: "2026-11-06T10:00:00Z" } });
}

describe("commerce telemetry", () => {
  it("validates purchase approvals with their exact-order details", () => {
    const parsed = parseServerMessage(JSON.stringify({ event_id: uuidFor(9500), session_id: SESSION, task_id: TASK, sequence: 1,
      occurred_at: "2026-11-06T10:00:05Z", type: "approval.required", data: purchaseApproval() }));
    expect(parsed.ok && parsed.message.kind === "event" && parsed.message.event.type === "approval.required"
      && parsed.message.event.data.purchase?.final_total).toBe("212.00");
  });

  it("logs commerce events and bumps the summary revision", () => {
    let state = active();
    for (const e of [
      event("commerce.products_found", { platform: "BLINKIT", requirement_id: uuidFor(300), query: "Amul taaza milk", candidate_count: 4, exact_match_count: 1 }),
      event("commerce.payment_handoff", { platform: "AMAZON_IN", status: "USER_ACTION_REQUIRED", message: "Please complete payment manually on the merchant website." }),
    ]) {
      for (const a of mapEventToActions(e)) state = taskPilotReducer(state, a);
    }
    expect(state.commerce?.revision).toBe(2);
    expect(state.commerce?.lastEvent?.type).toBe("commerce.payment_handoff");
    expect(state.logs.map((l) => l.message)).toEqual(expect.arrayContaining([
      'Read 4 product(s) for "Amul taaza milk" · 1 exact match(es).',
      "Please complete payment manually on the merchant website.",
    ]));
  });

  it("rejects malformed commerce payloads", () => {
    const bad = parseServerMessage(JSON.stringify({ event_id: uuidFor(9600), session_id: SESSION, task_id: TASK, sequence: 1,
      occurred_at: "2026-11-06T10:00:05Z", type: "commerce.price_changed", data: { difference: "forty rupees" } }));
    expect(bad.ok).toBe(false);
  });
});
