import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DomainStatusCard } from "@/components/integrations/DomainStatusCard";
import { WorkflowSummary } from "@/components/integrations/WorkflowSummary";

import { TASK, uuidFor } from "../fixtures";
import { workflowState } from "./integrationFixtures";

describe("WorkflowSummary", () => {
  it("lists ordered steps with their real status and hand-offs", () => {
    render(<WorkflowSummary workflow={workflowState()} />);
    expect(screen.getByTestId("workflow-summary")).toHaveTextContent("Workflow · YouTube → Gmail");
    expect(screen.getByTestId("workflow-status")).toHaveTextContent("Running…");
    const steps = screen.getAllByTestId("workflow-step");
    expect(steps.map((s) => s.dataset.status)).toEqual(["COMPLETED", "NOT_STARTED"]);
    expect(steps[1]).toHaveTextContent("Uses the result of an earlier step.");
  });

  it("shows partial results honestly", () => {
    render(<WorkflowSummary workflow={workflowState({ status: "PARTIAL", final_result: "1 of 2 step(s) finished. Step 2 (Save Gmail draft): skipped" })} />);
    expect(screen.getByTestId("workflow-status")).toHaveTextContent("Partly done");
    expect(screen.getByTestId("workflow-result")).toHaveTextContent("1 of 2 step(s) finished");
  });

  it("sends the chosen option (or a skip) for a pending choice", async () => {
    const onChoose = vi.fn().mockResolvedValue({ ok: true });
    const choice = { choice_id: uuidFor(850), task_id: TASK, step_id: uuidFor(801), domain: "YOUTUBE" as const, question: "Several videos match. Which one should I use?",
      options: [{ option_id: "v1", label: "Python Tutorial", detail: "Code Fixture Academy" }, { option_id: "v2", label: "Learn Python in 1 Hour" }],
      expires_at: "2099-01-01T00:00:00Z" };
    render(<WorkflowSummary workflow={workflowState({ status: "WAITING_USER", pending_choice: choice })} onChoose={onChoose} />);
    await userEvent.click(screen.getAllByTestId("choice-option")[1]!);
    expect(onChoose).toHaveBeenCalledWith(uuidFor(850), "v2");
    await userEvent.click(screen.getByRole("button", { name: /skip/i }));
    expect(onChoose).toHaveBeenLastCalledWith(uuidFor(850), null);
  });

  it("domain cards show the observed status", () => {
    render(<DomainStatusCard entry={{ domain: "GMAIL", label: "Gmail", status: "AUTHENTICATION_REQUIRED", message: "Please sign in yourself.", capabilities: ["GMAIL_CREATE_DRAFT"] }} />);
    const card = screen.getByTestId("domain-status-card");
    expect(card).toHaveAttribute("data-status", "AUTHENTICATION_REQUIRED");
    expect(card).toHaveTextContent("Sign in yourself");
  });
});
