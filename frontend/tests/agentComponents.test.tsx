import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AgentStatus } from "@/components/agent/AgentStatus";
import { AgentThinkingIndicator } from "@/components/agent/AgentThinkingIndicator";
import { ClarificationPanel } from "@/components/agent/ClarificationPanel";
import { IntentBadge } from "@/components/agent/IntentBadge";
import { PlanPreview } from "@/components/agent/PlanPreview";
import { PlanRiskIndicator, overallRisk } from "@/components/agent/PlanRiskIndicator";
import { PlanStep } from "@/components/agent/PlanStep";
import { TaskStatusCard } from "@/components/dashboard/TaskStatusCard";

import { PLAN_ID, TASK, samplePlan } from "./fixtures";

import type { ClarificationRequest } from "@/types/agent";

describe("PlanPreview", () => {
  it("renders summary, intent, website, step count, confidence, assumptions and all steps", () => {
    render(<PlanPreview plan={samplePlan()} />);
    const preview = screen.getByTestId("plan-preview");
    expect(preview).toHaveTextContent("PLAN READY");
    expect(preview).toHaveTextContent("Prepare a shopping cart on Amazon with laptop.");
    expect(preview).toHaveTextContent("amazon.in");
    expect(preview).toHaveTextContent("95%");
    expect(preview).toHaveTextContent("Quantity for laptop not given");
    expect(screen.getByTestId("intent-badge")).toHaveAttribute("data-intent", "ECOMMERCE_SHOPPING");
    expect(screen.getAllByTestId("plan-step")).toHaveLength(5);
    expect(screen.getByTestId("plan-message")).toHaveTextContent("Haan bhai!");
  });

  it("states that nothing runs until Run Plan and never shows steps as done", () => {
    render(<PlanPreview plan={samplePlan()} />);
    expect(screen.getByTestId("execution-notice")).toHaveTextContent(/not executed\. nothing runs in a browser until you click run plan/i);
    for (const step of screen.getAllByTestId("plan-step")) {
      expect(step).toHaveAttribute("data-status", "planned");
      expect(step).toHaveTextContent("Planned");
    }
    expect(screen.queryByText(/completed|executing|done/i)).not.toBeInTheDocument();
  });

  it("shows approval checkpoints and the overall risk", () => {
    render(<PlanPreview plan={samplePlan()} />);
    expect(screen.getByText(/1 approval checkpoint planned/i)).toBeInTheDocument();
    expect(screen.getByText("Approval checkpoint")).toBeInTheDocument();
    expect(screen.getByText("Requires approval")).toBeInTheDocument();
    expect(within(screen.getByTestId("plan-risk")).getByTestId("risk-badge")).toHaveTextContent("CRITICAL");
  });

  it("labels mock plans", () => {
    render(<PlanPreview plan={samplePlan()} />);
    expect(screen.getByTitle(/offline mock planner/i)).toHaveTextContent("Mock plan");
  });

  it("renders a rejected plan without steps or execution notice", () => {
    render(<PlanPreview plan={samplePlan({ status: "REJECTED", intent: "UNSUPPORTED", steps: [], requires_human_approval: false, user_facing_message: "Sorry, I can't plan that." })} />);
    expect(screen.getByText(/NOT PLANNED/)).toBeInTheDocument();
    expect(screen.queryByTestId("execution-notice")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("plan-step")).toHaveLength(0);
  });

  it("renders general chat as a reply with no browser actions", () => {
    render(<PlanPreview plan={samplePlan({ intent: "GENERAL_CHAT", steps: [], requires_human_approval: false, assumptions: [] })} />);
    expect(screen.getByText(/no browser actions needed/i)).toBeInTheDocument();
  });
});

describe("PlanStep", () => {
  it("renders number, action detail, expected outcome and risk", () => {
    const step = samplePlan().steps[2]!;
    render(<ol><PlanStep step={step} /></ol>);
    expect(screen.getByLabelText("Step 3")).toHaveTextContent("03");
    expect(screen.getByText("Add laptop to the cart.")).toBeInTheDocument();
    expect(screen.getByText(/Laptop is in the cart/)).toBeInTheDocument();
    expect(screen.getByTestId("risk-badge")).toHaveTextContent("MEDIUM");
  });

  it("hides sensitive typed text", () => {
    const step = { ...samplePlan().steps[1]!, action: { type: "type" as const, target_description: "Field", text: "secret", clear_first: true, sensitive: true } };
    render(<ol><PlanStep step={step} /></ol>);
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
    expect(screen.getByText(/\[hidden\]/)).toBeInTheDocument();
  });
});

describe("IntentBadge and risk", () => {
  it.each([
    ["ECOMMERCE_SHOPPING", "E-commerce shopping"],
    ["MEDIA_SEARCH", "Media search"],
    ["EMAIL_DRAFT", "Email draft"],
    ["CALENDAR_MANAGEMENT", "Calendar"],
    ["GENERAL_CHAT", "General chat"],
  ] as const)("labels %s", (intent, label) => {
    render(<IntentBadge intent={intent} />);
    expect(screen.getByTestId("intent-badge")).toHaveTextContent(label);
    expect(screen.getByLabelText(`Intent: ${label}`)).toBeInTheDocument();
  });

  it("computes the overall risk as the highest step risk", () => {
    expect(overallRisk(samplePlan().steps)).toBe("CRITICAL");
    expect(overallRisk(samplePlan().steps.slice(0, 2))).toBe("LOW");
    render(<PlanRiskIndicator steps={samplePlan().steps.slice(0, 3)} />);
    expect(screen.getByTestId("risk-badge")).toHaveTextContent("MEDIUM");
  });
});

describe("AgentThinkingIndicator", () => {
  it("shows only stages reported by the backend", () => {
    render(<AgentThinkingIndicator progress={{ stage: "CLASSIFYING_INTENT", progress: 33, message: "Identifying the task…" }} />);
    expect(screen.getByText("Understanding your command…")).toBeInTheDocument();
    expect(screen.getByText("Identifying the task…")).toBeInTheDocument();
    expect(screen.queryByText("Building an action plan…")).not.toBeInTheDocument();
    expect(screen.queryByText("Finalizing the plan…")).not.toBeInTheDocument();
    expect(screen.getByText(/nothing is being done in a browser/i)).toBeInTheDocument();
  });

  it("waits honestly before the first stage arrives", () => {
    render(<AgentThinkingIndicator progress={null} />);
    expect(screen.getByText(/waiting for the planner/i)).toBeInTheDocument();
  });
});

describe("AgentStatus", () => {
  const info = { agent_name: "Kamlesh Bhai", provider: "mock", model: "taskpilot-mock-v1", status: "available" as const, planning_enabled: true, browser_execution_enabled: false, is_mock: true, provider_reachable: null };

  it("shows planning state and mock badge", () => {
    render(<AgentStatus status="PLANNING" info={info} connected />);
    expect(screen.getByTestId("agent-status")).toHaveTextContent("Kamlesh Bhai");
    expect(screen.getByTestId("agent-status")).toHaveTextContent("Planning…");
    expect(screen.getByText(/mock planner/i)).toBeInTheDocument();
  });

  it("shows offline and real provider details", () => {
    const { rerender } = render(<AgentStatus status="IDLE" info={info} connected={false} />);
    expect(screen.getByTestId("agent-status")).toHaveTextContent("Offline");
    rerender(<AgentStatus status="PLAN_READY" info={{ ...info, provider: "anthropic", model: "claude-opus-5-5", is_mock: false }} connected />);
    expect(screen.getByText("anthropic · claude-opus-5-5")).toBeInTheDocument();
    expect(screen.queryByText(/mock planner/i)).not.toBeInTheDocument();
  });
});

describe("ClarificationPanel", () => {
  const clarification: ClarificationRequest = {
    taskId: TASK,
    planId: PLAN_ID,
    question: "Bhai, milk ka kaunsa brand aur kitni quantity chahiye?",
    missingInformation: ["brand", "quantity"],
  };

  it("shows the question and missing information", () => {
    render(<ClarificationPanel clarification={clarification} onSubmit={vi.fn()} isSubmitting={false} />);
    expect(screen.getByTestId("clarification-question")).toHaveTextContent("kaunsa brand");
    expect(screen.getByLabelText("Missing information")).toHaveTextContent("brand");
  });

  it("submits the trimmed answer and clears the input", async () => {
    const onSubmit = vi.fn().mockResolvedValue({ ok: true });
    render(<ClarificationPanel clarification={clarification} onSubmit={onSubmit} isSubmitting={false} />);
    const box = screen.getByRole("textbox", { name: /your answer/i });
    const send = screen.getByRole("button", { name: /send answer/i });
    expect(send).toBeDisabled();
    await userEvent.type(box, "  Amul, 1 litre  ");
    await userEvent.click(send);
    expect(onSubmit).toHaveBeenCalledWith("Amul, 1 litre");
    expect(box).toHaveValue("");
  });

  it("shows a loading state and blocks resubmission", async () => {
    const onSubmit = vi.fn();
    render(<ClarificationPanel clarification={clarification} onSubmit={onSubmit} isSubmitting />);
    expect(screen.getByRole("button", { name: /sending/i })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: /your answer/i })).toBeDisabled();
  });

  it("shows backend errors and keeps the answer", async () => {
    const onSubmit = vi.fn().mockResolvedValue({ ok: false, error: "This task is PLANNED and is not waiting for a clarification." });
    render(<ClarificationPanel clarification={clarification} onSubmit={onSubmit} isSubmitting={false} />);
    await userEvent.type(screen.getByRole("textbox", { name: /your answer/i }), "Blinkit{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(/not waiting/i);
    expect(screen.getByRole("textbox", { name: /your answer/i })).toHaveValue("Blinkit");
  });
});

describe("TaskStatusCard (no false execution status)", () => {
  const task = {
    task_id: TASK, session_id: "s", command: "Amazon par laptop order karo", input_mode: "TEXT" as const,
    state: "PLANNED" as const, created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:01Z",
  };

  it("marks only visited states and labels execution as waiting for Run Plan", () => {
    render(<TaskStatusCard task={task} visitedStates={["IDLE", "PLANNING", "PLANNED"]} plan={samplePlan()} />);
    expect(screen.getByTestId("task-state-badge")).toHaveTextContent("Plan ready · not executed");
    const steps = within(screen.getByRole("list", { name: "Task lifecycle" })).getAllByRole("listitem");
    expect(steps.filter((s) => s.hasAttribute("data-reached"))).toHaveLength(3);
    expect(screen.getByText("Execute · Run Plan")).toBeInTheDocument();
    expect(screen.getByTestId("plan-summary")).toHaveTextContent("5 planned steps");
  });

  it("shows needs-input for clarification", () => {
    render(<TaskStatusCard task={{ ...task, state: "NEEDS_CLARIFICATION" }} visitedStates={["IDLE", "PLANNING", "NEEDS_CLARIFICATION"]} />);
    expect(screen.getByTestId("task-state-badge")).toHaveTextContent("Needs your input");
    expect(screen.getByText("Needs input")).toBeInTheDocument();
  });
});
