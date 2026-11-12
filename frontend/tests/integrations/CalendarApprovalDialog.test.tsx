import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalDialog } from "@/components/approval/ApprovalDialog";

import { uuidFor } from "../fixtures";
import { calendarApproval } from "./integrationFixtures";

const resolved = (status: "APPROVED" | "REJECTED") =>
  vi.fn().mockResolvedValue({ approval_id: uuidFor(700), decision: status === "APPROVED" ? "APPROVE" : "REJECT", status, resolved_at: "2026-11-09T10:00:05Z" });

describe("CalendarApprovalDialog", () => {
  it("shows exactly the event being approved", () => {
    render(<ApprovalDialog approval={calendarApproval()} open onOpenChange={vi.fn()} onDecide={vi.fn()} />);
    const dialog = screen.getByTestId("calendar-approval-dialog");
    expect(dialog).toHaveTextContent(/calendar event review/i);
    const details = screen.getByTestId("calendar-approval-details");
    expect(details).toHaveTextContent("Meeting with Rahul");
    expect(details).toHaveTextContent("Tuesday, November 10, 2026");
    expect(details).toHaveTextContent("3:00 PM – 3:30 PM");
    expect(details).toHaveTextContent("Asia/Kolkata (IST, UTC+05:30)");
    expect(screen.getByTestId("calendar-conflict-status")).toHaveTextContent("No overlapping events seen");
    expect(screen.getByTestId("calendar-invite-note")).toHaveTextContent(/no invitations/i);
    expect(screen.getByTestId("reject-event")).toHaveTextContent("Reject Event Creation");
    expect(screen.getByTestId("confirm-event")).toHaveTextContent("Confirm This Exact Event");
  });

  it("has no autofocus on a decision and Enter never approves", () => {
    const onDecide = vi.fn();
    render(<ApprovalDialog approval={calendarApproval()} open onOpenChange={vi.fn()} onDecide={onDecide} />);
    expect(document.activeElement).not.toBe(screen.getByTestId("confirm-event"));
    expect(document.activeElement).not.toBe(screen.getByTestId("reject-event"));
    fireEvent.keyDown(screen.getByTestId("calendar-approval-dialog"), { key: "Enter" });
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("an explicit click approves exactly once; reject is explicit too", async () => {
    const approve = resolved("APPROVED");
    const { unmount } = render(<ApprovalDialog approval={calendarApproval()} open onOpenChange={vi.fn()} onDecide={approve} />);
    await userEvent.click(screen.getByTestId("confirm-event"));
    expect(await screen.findByRole("status")).toHaveTextContent("approved");
    expect(screen.queryByTestId("confirm-event")).not.toBeInTheDocument(); // locked after one decision
    expect(approve).toHaveBeenCalledTimes(1);
    expect(approve).toHaveBeenCalledWith(uuidFor(700), "APPROVE");
    unmount();
    const reject = resolved("REJECTED");
    render(<ApprovalDialog approval={calendarApproval()} open onOpenChange={vi.fn()} onDecide={reject} />);
    await userEvent.click(screen.getByTestId("reject-event"));
    expect(reject).toHaveBeenCalledWith(uuidFor(700), "REJECT");
  });

  it("shows conflicts, unknown conflict state and invitations", () => {
    const base = calendarApproval();
    render(<ApprovalDialog approval={calendarApproval({ calendar: { ...base.calendar!, conflict_status: "CONFLICTS_FOUND", sends_invitations: true,
      attendee_emails: ["rahul@example.com"], conflicts: [{ title: "Design review", start_label: "3:00pm", end_label: "4:00pm", kind: "PARTIAL" }] } })}
      open onOpenChange={vi.fn()} onDecide={vi.fn()} />);
    expect(screen.getByText(/Overlaps “Design review”/)).toBeInTheDocument();
    expect(screen.getByTestId("calendar-invite-note")).toHaveTextContent("rahul@example.com");
  });

  it("expired reviews cannot be approved", () => {
    render(<ApprovalDialog approval={calendarApproval({ status: "EXPIRED", expires_at: "2026-01-01T00:00:00Z" })} open onOpenChange={vi.fn()} onDecide={vi.fn()} />);
    expect(screen.queryByTestId("confirm-event")).not.toBeInTheDocument();
    expect(screen.getByText(/No event was created/)).toBeInTheDocument();
  });
});
