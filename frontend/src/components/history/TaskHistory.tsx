"use client";

import { History, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { getTaskHistory, type TaskHistoryItem } from "@/lib/systemApi";

const TONE: Record<string, "success" | "warning" | "destructive" | "secondary" | "violet"> = {
  COMPLETED: "success", FAILED: "destructive", CANCELLED: "warning", PLANNED: "violet", NEEDS_CLARIFICATION: "warning",
};

/**
 * Persistent task history (survives restarts). Opening an entry shows its stored summary only —
 * sensitive actions can never be resumed from here; a fresh plan and fresh approvals are always needed.
 */
export function TaskHistory({ sessionId }: { sessionId: string | null }) {
  const [items, setItems] = useState<TaskHistoryItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async (next: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const page = await getTaskHistory({ sessionId, cursor: next });
      setItems((prev) => (next ? [...prev, ...page.tasks] : page.tasks));
      setCursor(page.next_cursor);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load task history.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load(null);
  }, [load]);

  return (
    <Card aria-labelledby="history-title" data-testid="task-history">
      <CardHeader><CardTitle id="history-title"><History className="h-3.5 w-3.5" aria-hidden /> Task history</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-2">
        {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
        {!loading && items.length === 0 && !error && <p className="text-sm text-muted-foreground">No tasks yet.</p>}
        <ul className="flex flex-col gap-1.5">
          {items.map((t) => (
            <li key={t.task_id} className="rounded-md border border-white/[0.06]" data-testid="history-item">
              <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm"
                aria-expanded={open === t.task_id} onClick={() => setOpen(open === t.task_id ? null : t.task_id)}>
                <span className="truncate">{t.command}</span>
                <span className="flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
                  {new Date(t.created_at).toLocaleString()}
                  <Badge variant={TONE[t.state] ?? "secondary"}>{t.state.replace(/_/g, " ").toLowerCase()}</Badge>
                </span>
              </button>
              {open === t.task_id && (
                <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 border-t border-white/[0.06] px-3 py-2 text-xs" data-testid="history-details">
                  <dt className="text-muted-foreground">Status</dt><dd>{t.state}{t.execution_status ? ` · run ${t.execution_status.toLowerCase()}` : ""}</dd>
                  {t.error_message && (<><dt className="text-muted-foreground">Reason</dt><dd>{t.error_message}{t.error_code ? ` [${t.error_code}]` : ""}</dd></>)}
                  {t.recovery_note && (<><dt className="text-muted-foreground">Recovery</dt><dd>{t.recovery_note}</dd></>)}
                  <dt className="text-muted-foreground">Updated</dt><dd>{new Date(t.updated_at).toLocaleString()}</dd>
                  <dd className="col-span-2 text-muted-foreground">To act again, send a new command — sensitive steps always need a fresh plan and approval.</dd>
                </dl>
              )}
            </li>
          ))}
        </ul>
        {cursor && (
          <Button variant="outline" size="sm" onClick={() => void load(cursor)} disabled={loading}>
            {loading && <Loader2 className="animate-spin" aria-hidden />} Load more
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
