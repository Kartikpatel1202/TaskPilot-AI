"use client";

import { Loader2, MailCheck, MailWarning, Pencil } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { DRAFT_STATUS_LABEL, type EmailDraftView } from "@/types/gmail";

export interface EmailDraftPreviewProps {
  view: EmailDraftView;
  saving?: boolean;
  onSave?: (subject: string, body: string) => Promise<{ ok: boolean; error?: string }>;
}

/**
 * The email draft. There is deliberately NO Send button anywhere: TaskPilot only saves drafts;
 * the user sends from Gmail themselves. Editing is possible only before the plan runs.
 */
export function EmailDraftPreview({ view, saving = false, onSave }: EmailDraftPreviewProps) {
  const { draft } = view;
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(view.body ?? "");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!editing) {
      setSubject(draft.subject);
      setBody(view.body ?? "");
    }
  }, [draft.subject, view.body, editing]);

  const saved = draft.status === "DRAFT_SAVED" && draft.verified;
  const problem = draft.status === "DRAFT_SAVE_FAILED" || draft.status === "SAVE_STATUS_UNKNOWN" || draft.status === "LOGIN_REQUIRED";
  const submit = async () => {
    if (!onSave) return;
    setError(null);
    const result = await onSave(subject.trim(), body);
    if (result.ok) setEditing(false);
    else setError(result.error ?? "The draft could not be updated.");
  };

  return (
    <section className="flex flex-col gap-2" aria-label="Email draft" data-testid="email-draft-preview">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {problem ? <MailWarning className="h-3 w-3" aria-hidden /> : <MailCheck className="h-3 w-3" aria-hidden />} Gmail draft
        </p>
        <Badge variant={saved ? "success" : problem ? "warning" : "secondary"} data-testid="draft-status">{DRAFT_STATUS_LABEL[draft.status]}</Badge>
      </div>
      <p role="note" className="rounded-md border border-level-warning/30 bg-level-warning/[0.06] px-3 py-1.5 text-xs font-medium text-level-warning"
        data-testid="draft-not-sent">
        Draft prepared. Email has NOT been sent.
      </p>
      {draft.send_blocked && (
        <p className="text-xs text-muted-foreground" data-testid="send-blocked-note">
          Haan bhai, main email ka draft prepare kar sakta hoon. Final Send tum Gmail se manually kar sakte ho.
        </p>
      )}
      <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">To</dt>
        <dd data-testid="draft-recipients">{(view.recipients ?? draft.recipients_masked).join(", ")}</dd>
        <dt className="text-muted-foreground">Subject</dt>
        <dd>
          {editing ? (
            <input aria-label="Draft subject" className="w-full rounded border border-border bg-transparent px-2 py-1 text-sm" value={subject}
              maxLength={200} onChange={(e) => setSubject(e.target.value)} />
          ) : draft.subject}
        </dd>
      </dl>
      {editing ? (
        <Textarea aria-label="Draft body" rows={8} maxLength={12_000} value={body} onChange={(e) => setBody(e.target.value)} />
      ) : (
        view.body && <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-white/[0.06] bg-white/[0.02] p-2 text-xs" data-testid="draft-body">{view.body}</pre>
      )}
      <p className="text-[11px] text-muted-foreground">{draft.message}</p>
      {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
      {view.editable && onSave && (
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>Cancel</Button>
              <Button size="sm" onClick={() => void submit()} disabled={saving || !subject.trim() || !body.trim()} data-testid="save-draft-edits">
                {saving && <Loader2 className="animate-spin" aria-hidden />} Save draft text
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)} data-testid="edit-draft">
              <Pencil aria-hidden /> Edit before running
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
