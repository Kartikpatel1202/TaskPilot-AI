import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalDialog } from "@/components/approval/ApprovalDialog";
import { ApiError } from "@/lib/api";

import type { ApprovalDecision, ApprovalRequest, ApprovalResponse } from "@/types/approval";

function makeApproval(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    approval_id: "6a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    task_id: "1f2e3d4c-5b6a-4978-8a6b-5c4d3e2f1a0b",
    session_id: "0a9b8c7d-6e5f-4d3c-9b2a-1f0e9d8c7b6a",
    action_summary: "Place grocery order (simulated)",
    domain: "example-grocer.test",
    reason: "Placing an order may result in a purchase.",
    risk_level: "HIGH",
    status: "PENDING",
    estimated_impact: "Illustrative only: ₹850 across 4 items.",
    expires_at: new Date(Date.now() + 120_000).toISOString(),
    is_demo: true,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const ok = (decision: ApprovalDecision): ApprovalResponse => ({
  approval_id: makeApproval().approval_id,
  decision,
  status: decision === "APPROVE" ? "APPROVED" : "REJECTED",
  resolved_at: new Date().toISOString(),
});

function setup(approval = makeApproval(), onDecide = vi.fn(async (_id: string, d: ApprovalDecision) => ok(d))) {
  const onOpenChange = vi.fn();
  render(<ApprovalDialog approval={approval} open onOpenChange={onOpenChange} onDecide={onDecide} />);
  return { onDecide, onOpenChange };
}

describe("ApprovalDialog", () => {
  it("displays the approval details and demo banner", () => {
    setup();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Place grocery order (simulated)");
    expect(dialog).toHaveTextContent("example-grocer.test");
    expect(dialog).toHaveTextContent("Placing an order may result in a purchase.");
    expect(dialog).toHaveTextContent("₹850");
    expect(screen.getByTestId("demo-banner")).toHaveTextContent("DEMO APPROVAL — NO REAL ACTION");
  });

  it("displays the risk level", () => {
    setup(makeApproval({ risk_level: "CRITICAL" }));
    expect(screen.getByTestId("risk-badge")).toHaveTextContent("CRITICAL");
    expect(screen.getByLabelText("Risk level: Critical risk")).toBeInTheDocument();
  });

  it("does not auto-focus a decision button (no Enter-to-approve)", async () => {
    const { onDecide } = setup();
    expect(screen.getByRole("button", { name: /approve action/i })).not.toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("submits APPROVE when Approve is clicked", async () => {
    const { onDecide } = setup();
    await userEvent.click(screen.getByRole("button", { name: /approve action/i }));
    expect(onDecide).toHaveBeenCalledWith(makeApproval().approval_id, "APPROVE");
    expect(await screen.findByRole("status")).toHaveTextContent(/decision recorded: approved/i);
  });

  it("submits REJECT when Reject is clicked", async () => {
    const { onDecide } = setup();
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onDecide).toHaveBeenCalledWith(makeApproval().approval_id, "REJECT");
  });

  it("shows a loading state and prevents duplicate submissions", async () => {
    const pending = deferred<ApprovalResponse>();
    const onDecide = vi.fn(() => pending.promise);
    setup(makeApproval(), onDecide);
    const approve = screen.getByRole("button", { name: /approve action/i });
    await userEvent.click(approve);
    expect(screen.getByRole("button", { name: /submitting/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /submitting/i }));
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onDecide).toHaveBeenCalledTimes(1);
    pending.resolve(ok("APPROVE"));
    await screen.findByText(/decision recorded/i);
    expect(screen.queryByRole("button", { name: /approve action/i })).not.toBeInTheDocument();
  });

  it("shows a backend failure and allows a deliberate retry", async () => {
    const onDecide = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("Unable to reach the TaskPilot backend.", 0, "NETWORK_ERROR"))
      .mockResolvedValueOnce(ok("REJECT"));
    setup(makeApproval(), onDecide);
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be recorded/i);
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/decision recorded: rejected/i)).toBeInTheDocument();
  });

  it("handles an expired approval: approve is unavailable", () => {
    setup(makeApproval({ expires_at: new Date(Date.now() - 1_000).toISOString() }));
    expect(screen.queryByRole("button", { name: /approve action/i })).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/expired/i);
  });

  it("marks the request expired when the backend reports APPROVAL_EXPIRED", async () => {
    const onDecide = vi.fn().mockRejectedValue(new ApiError("expired", 410, "APPROVAL_EXPIRED"));
    setup(makeApproval(), onDecide);
    await userEvent.click(screen.getByRole("button", { name: /approve action/i }));
    expect(await screen.findByText(/can no longer be approved/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve action/i })).not.toBeInTheDocument();
  });

  it("locks decisions after a conflict (already resolved elsewhere)", async () => {
    const onDecide = vi.fn().mockRejectedValue(new ApiError("dup", 409, "APPROVAL_ALREADY_RESOLVED"));
    setup(makeApproval(), onDecide);
    await userEvent.click(screen.getByRole("button", { name: /approve action/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already decided/i);
    expect(screen.queryByRole("button", { name: /approve action/i })).not.toBeInTheDocument();
  });

  it("omits the demo banner for non-demo approvals", () => {
    setup(makeApproval({ is_demo: false }));
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
  });
});
