"use client";

import { Activity, ChevronRight, Loader2, RefreshCw, Search, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { getActivity, getTaskActivity, type ActivityEvent, type ActivityKind, type TaskActivity } from "@/lib/activityApi";

const KINDS: { value: ActivityKind | "all"; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "task", label: "Tasks" },
  { value: "step", label: "Browser steps" },
  { value: "approval", label: "Approvals" },
  { value: "browser", label: "Browser" },
  { value: "purchase", label: "Orders" },
  { value: "integration", label: "Gmail / Calendar / Files" },
  { value: "security", label: "Sign-in & security" },
];
const STATUSES = ["", "COMPLETED", "FAILED", "CANCELLED", "PLANNED", "SUCCEEDED", "BLOCKED", "UNKNOWN", "SUCCESS", "FAILURE"];

type Tone = "success" | "warning" | "destructive" | "secondary" | "violet";
function tone(status: string): Tone {
  if (/COMPLETED|SUCCEEDED|SUCCESS|APPROVED/.test(status)) return "success";
  if (/FAILED|FAILURE|REJECTED|UNKNOWN/.test(status)) return "destructive";
  if (/BLOCKED|CANCELLED|EXPIRED|WITHDRAWN|PENDING|NEEDS/.test(status)) return "warning";
  if (/PLANNED|RUNNING|EXECUTING/.test(status)) return "violet";
  return "secondary";
}

const time = (iso: string) => new Date(iso).toLocaleString();

/** Activity Logs: real persisted events (tasks, browser steps, approvals, audit) with filters and task details. */
export function ActivityLog() {
  const [kind, setKind] = useState<ActivityKind | "all">("all");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [before, setBefore] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async (cursor: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const page = await getActivity({ kind, status: status || undefined, q: appliedQuery || undefined, before: cursor });
      setEvents((prev) => (cursor ? [...prev, ...page.events] : page.events));
      setBefore(page.next_before);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load activity.");
    } finally {
      setLoading(false);
    }
  }, [kind, status, appliedQuery]);

  useEffect(() => {
    void load(null);
  }, [load]);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
      <Card aria-labelledby="activity-title" data-testid="activity-log">
        <CardHeader className="flex-wrap gap-2">
          <CardTitle id="activity-title"><Activity className="h-3.5 w-3.5" aria-hidden /> Activity logs</CardTitle>
          <Button size="sm" variant="ghost" onClick={() => void load(null)} aria-label="Refresh activity"><RefreshCw aria-hidden /></Button>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setAppliedQuery(query.trim()); }}>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Type
              <select value={kind} onChange={(e) => setKind(e.target.value as ActivityKind | "all")} data-testid="activity-kind"
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
                {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
              Status
              <select value={status} onChange={(e) => setStatus(e.target.value)} data-testid="activity-status"
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
                {STATUSES.map((s) => <option key={s} value={s}>{s ? s.toLowerCase() : "Any"}</option>)}
              </select>
            </label>
            <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-[11px] text-muted-foreground">
              Search commands
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. blinkit milk" data-testid="activity-search"
                className="rounded-md border border-border bg-transparent px-2 py-1.5 text-sm text-foreground" />
            </label>
            <Button type="submit" size="sm" variant="outline"><Search aria-hidden /> Filter</Button>
          </form>

          {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
          {!loading && !error && events.length === 0 && <p className="text-sm text-muted-foreground">No activity recorded yet.</p>}

          <ol className="flex flex-col gap-1.5">
            {events.map((e) => (
              <li key={e.id} data-testid="activity-item">
                <button type="button" disabled={!e.task_id} onClick={() => setDetailId(e.task_id)}
                  className="flex w-full items-start gap-3 rounded-md border border-white/[0.06] px-3 py-2 text-left text-sm enabled:hover:bg-white/[0.03] disabled:cursor-default">
                  <span className="w-36 shrink-0 text-[11px] tabular-nums text-muted-foreground">{time(e.occurred_at)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{e.title}</span>
                      <Badge variant={tone(e.status)}>{e.status.toLowerCase().replace(/_/g, " ")}</Badge>
                      {e.error_code && <span className="font-mono text-[10px] text-level-error">{e.error_code}</span>}
                      {e.duration_ms !== null && <span className="text-[10px] text-muted-foreground">{(e.duration_ms / 1000).toFixed(1)} s</span>}
                    </span>
                    {e.command && <span className="block truncate text-xs text-muted-foreground">“{e.command}”</span>}
                    {e.detail && <span className="block text-xs text-muted-foreground">{e.detail}</span>}
                  </span>
                  {e.task_id && <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />}
                </button>
              </li>
            ))}
          </ol>
          {loading && <Loader2 className="mx-auto h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading" />}
          {before && !loading && (
            <Button variant="outline" size="sm" onClick={() => void load(before)}>Load older</Button>
          )}
        </CardContent>
      </Card>

      {detailId && <TaskDetail taskId={detailId} onClose={() => setDetailId(null)} />}
    </div>
  );
}

function TaskDetail({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<TaskActivity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setError(null);
    getTaskActivity(taskId)
      .then((d) => alive && setDetail(d))
      .catch((err) => alive && setError(err instanceof ApiError ? err.message : "Could not load this task."));
    return () => {
      alive = false;
    };
  }, [taskId]);

  return (
    <Card aria-label="Task details" data-testid="activity-detail" className="h-fit xl:sticky xl:top-4">
      <CardHeader className="flex-wrap gap-2">
        <CardTitle>Task details</CardTitle>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close details"><X aria-hidden /></Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
        {!detail && !error && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-label="Loading" />}
        {detail && (
          <>
            <p className="font-medium">“{detail.command}”</p>
            <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted-foreground">Status</dt>
              <dd><Badge variant={tone(detail.state)}>{detail.state.toLowerCase().replace(/_/g, " ")}</Badge></dd>
              <dt className="text-muted-foreground">Input</dt><dd>{detail.input_mode.toLowerCase()}</dd>
              {detail.intent && (<><dt className="text-muted-foreground">Intent</dt><dd>{detail.intent.toLowerCase().replace(/_/g, " ")}</dd></>)}
              {detail.planner && (<><dt className="text-muted-foreground">Planner</dt><dd>{detail.planner}</dd></>)}
              {detail.plan_summary && (<><dt className="text-muted-foreground">Plan</dt><dd>{detail.plan_summary}</dd></>)}
              {detail.error_message && (<><dt className="text-muted-foreground">Error</dt><dd className="text-level-error">{detail.error_message}{detail.error_code ? ` [${detail.error_code}]` : ""}</dd></>)}
              {detail.recovery_note && (<><dt className="text-muted-foreground">Recovery</dt><dd>{detail.recovery_note}</dd></>)}
              <dt className="text-muted-foreground">Created</dt><dd>{time(detail.created_at)}</dd>
              <dt className="text-muted-foreground">Updated</dt><dd>{time(detail.updated_at)}</dd>
            </dl>

            <div>
              <h3 className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Browser steps</h3>
              {detail.steps.length === 0 ? <p className="text-xs text-muted-foreground">No browser steps ran for this task.</p> : (
                <ol className="flex flex-col gap-1" data-testid="activity-steps">
                  {detail.steps.map((s) => (
                    <li key={`${s.order}-${s.attempt}`} className="rounded border border-white/[0.06] px-2 py-1.5 text-xs">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{s.order}. {s.action_type}</span>
                        <Badge variant={tone(s.lifecycle)}>{s.lifecycle.toLowerCase()}</Badge>
                        {s.attempt > 1 && <span className="text-muted-foreground">attempt {s.attempt}</span>}
                        {s.duration_ms !== null && <span className="text-muted-foreground">{(s.duration_ms / 1000).toFixed(1)} s</span>}
                      </span>
                      {s.message && <span className="block text-muted-foreground">{s.message}</span>}
                      {s.error_code && <span className="block font-mono text-level-error">{s.error_code}</span>}
                    </li>
                  ))}
                </ol>
              )}
            </div>

            {detail.events.length > 0 && (
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Events</h3>
                <ul className="flex flex-col gap-1 text-xs">
                  {detail.events.map((e) => (
                    <li key={e.id} className="flex flex-wrap gap-2">
                      <span className="tabular-nums text-muted-foreground">{new Date(e.occurred_at).toLocaleTimeString()}</span>
                      <span>{e.title}</span>
                      <Badge variant={tone(e.status)}>{e.status.toLowerCase()}</Badge>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.conversation.length > 0 && (
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Conversation</h3>
                <ul className="flex flex-col gap-1 text-xs">
                  {detail.conversation.map((c, i) => (
                    <li key={i}><span className="font-medium">{c.role === "user" ? "You" : "Kamlesh Bhai"}:</span> {c.content}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
