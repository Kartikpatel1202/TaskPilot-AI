import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmailDraftPreview } from "@/components/gmail/EmailDraftPreview";

import { draftView } from "./integrationFixtures";

describe("EmailDraftPreview", () => {
  it("says the email has NOT been sent and has no Send button", () => {
    render(<EmailDraftPreview view={draftView()} onSave={vi.fn()} />);
    expect(screen.getByTestId("draft-not-sent")).toHaveTextContent("Draft prepared. Email has NOT been sent.");
    expect(screen.queryByRole("button", { name: /send/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("draft-recipients")).toHaveTextContent("hr@example.com");
    expect(screen.getByTestId("draft-body")).toHaveTextContent("[Your name]");
  });

  it("can be edited before the plan runs", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    render(<EmailDraftPreview view={draftView()} onSave={onSave} />);
    await userEvent.click(screen.getByTestId("edit-draft"));
    const subject = screen.getByLabelText("Draft subject");
    await userEvent.clear(subject);
    await userEvent.type(subject, "Winter internships");
    await userEvent.click(screen.getByTestId("save-draft-edits"));
    expect(onSave).toHaveBeenCalledWith("Winter internships", expect.stringContaining("internship opportunities"));
  });

  it("is read-only after saving and shows the verified status", () => {
    const view = draftView({ editable: false, recipients: undefined, draft: { ...draftView().draft, status: "DRAFT_SAVED", verified: true,
      message: "Draft saved and found in Gmail Drafts. The email has NOT been sent.", send_blocked: true } });
    render(<EmailDraftPreview view={view} onSave={vi.fn()} />);
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Saved in Drafts");
    expect(screen.queryByTestId("edit-draft")).not.toBeInTheDocument();
    expect(screen.getByTestId("draft-recipients")).toHaveTextContent("h•••@example.com");
    expect(screen.getByTestId("send-blocked-note")).toHaveTextContent("Final Send tum Gmail se manually kar sakte ho");
  });

  it("reports failed or unknown saves honestly", () => {
    render(<EmailDraftPreview view={draftView({ editable: false, draft: { ...draftView().draft, status: "SAVE_STATUS_UNKNOWN" } })} />);
    expect(screen.getByTestId("draft-status")).toHaveTextContent("Save status unknown");
    expect(screen.getByTestId("draft-not-sent")).toBeInTheDocument();
  });
});
