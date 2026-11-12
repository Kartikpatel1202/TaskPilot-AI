import { describe, expect, it } from "vitest";

import { initialTaskPilotState, mapEventToActions, taskPilotReducer, type TaskPilotState } from "@/context/taskPilotReducer";
import { parseTaskPlan } from "@/lib/planValidators";
import { parseServerMessage } from "@/lib/validators";

import { samplePlan, SESSION, TASK, uuidFor } from "../fixtures";
import { calendarApproval } from "./integrationFixtures";

import { INTEGRATION_EVENT_TYPES } from "@/types/integration";
import type { AnyTelemetryEvent } from "@/types/telemetry";

let seq = 0;
function frame(type: string, data: Record<string, unknown>): string {
  seq += 1;
  return JSON.stringify({ event_id: uuidFor(9700 + seq), session_id: SESSION, task_id: TASK, sequence: seq,
    occurred_at: "2026-11-09T10:00:05.000000+00:00", type, data });
}

function event(type: string, data: Record<string, unknown>): AnyTelemetryEvent {
  const parsed = parseServerMessage(frame(type, data));
  if (!parsed.ok || parsed.message.kind !== "event") throw new Error(`invalid ${type}`);
  return parsed.message.event;
}

function active(): TaskPilotState {
  return taskPilotReducer(initialTaskPilotState, { type: "TASK_ACCEPTED", task: {
    task_id: TASK, session_id: SESSION, command: "c", input_mode: "TEXT", state: "EXECUTING", created_at: "2026-11-09T10:00:00Z", updated_at: "2026-11-09T10:00:00Z" } });
}

describe("integration telemetry", () => {
  it("accepts every Phase 5 event type with the bounded payload", () => {
    for (const type of INTEGRATION_EVENT_TYPES) {
      const parsed = parseServerMessage(frame(type, { domain: "GMAIL", message: "ok" }));
      expect(parsed.ok, type).toBe(true);
    }
    expect(INTEGRATION_EVENT_TYPES).toHaveLength(36);
  });

  it("rejects malformed integration payloads", () => {
    expect(parseServerMessage(frame("gmail.draft_saved", { domain: "OUTLOOK", message: "x" })).ok).toBe(false);
    expect(parseServerMessage(frame("file.download_progress", { message: "x", bytes_received: -5 })).ok).toBe(false);
    expect(parseServerMessage(frame("youtube.search_started", {})).ok).toBe(false);
  });

  it("validates calendar approvals with the exact event", () => {
    const parsed = parseServerMessage(frame("approval.required", calendarApproval() as unknown as Record<string, unknown>));
    expect(parsed.ok && parsed.message.kind === "event" && parsed.message.event.type === "approval.required"
      && parsed.message.event.data.calendar?.event_hash).toBe("a".repeat(64));
  });

  it("logs integration events and bumps the revision (bodies are never part of events)", () => {
    let state = active();
    for (const e of [
      event("gmail.draft_started", { domain: "GMAIL", message: "Opening Gmail to prepare a draft." }),
      event("gmail.send_blocked", { domain: "GMAIL", message: "Haan bhai, main email ka draft prepare kar sakta hoon.", code: "GMAIL_SEND_BLOCKED" }),
      event("workflow.partial_success", { message: "1 of 2 step(s) finished.", status: "PARTIAL", completed_steps: 1, total_steps: 2 }),
    ]) {
      for (const a of mapEventToActions(e)) state = taskPilotReducer(state, a);
    }
    expect(state.integrations?.revision).toBe(3);
    expect(state.integrations?.activity.map((a) => a.type)).toEqual(["gmail.draft_started", "gmail.send_blocked", "workflow.partial_success"]);
    const levels = Object.fromEntries(state.logs.map((l) => [l.message, l.level]));
    expect(levels["Haan bhai, main email ka draft prepare kar sakta hoon. [GMAIL_SEND_BLOCKED]"]).toBe("WARNING");
    expect(levels["1 of 2 step(s) finished."]).toBe("WARNING");
  });

  it("parses plans with integration steps and rejects unsafe ones", () => {
    const step = (action: Record<string, unknown>, order = 1) => ({ step_id: uuidFor(950 + order), order, action, description: "d",
      expected_outcome: "o", risk_level: "LOW", requires_approval: false, depends_on: [] });
    const plan = samplePlan({ intent: "MULTI_DOMAIN_WORKFLOW" }) as unknown as Record<string, unknown>;
    const ok = parseTaskPlan({ ...plan, steps: [
      step({ type: "youtube_search", query: "python", max_results: 10, select: true, site_key: "youtube", continue_on_failure: true }),
      step({ type: "gmail_create_draft", recipient_emails: ["a@example.com"], cc_emails: [], subject: "s", body: "b", insert_outputs: ["youtube.video_reference"],
        send_requested: false, site_key: "gmail", continue_on_failure: true }, 2),
    ] });
    expect(ok?.steps.map((s) => s.action.type)).toEqual(["youtube_search", "gmail_create_draft"]);
    const bad = parseTaskPlan({ ...plan, steps: [step({ type: "youtube_play", video_reference: "https://evil.example/watch?v=abcdefgh", site_key: "youtube", continue_on_failure: false })] });
    expect(bad).toBeNull();
    const notEmail = parseTaskPlan({ ...plan, steps: [step({ type: "gmail_create_draft", recipient_emails: ["nobody"], cc_emails: [], subject: "s", body: "b",
      insert_outputs: [], send_requested: false, site_key: "gmail", continue_on_failure: false })] });
    expect(notEmail).toBeNull();
  });
});
