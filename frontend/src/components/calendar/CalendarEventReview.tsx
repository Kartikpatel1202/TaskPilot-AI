"use client";

import { AlertTriangle, CalendarClock } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { CONFLICT_LABEL, EVENT_STATUS_LABEL, type CalendarEventReview as Review } from "@/types/calendar";

/** The exact event (planned → approval → created and verified). Nothing is created without approval. */
export function CalendarEventReview({ review }: { review: Review }) {
  const done = review.status === "CREATED" || review.status === "ALREADY_EXISTS";
  const bad = ["REJECTED", "EXPIRED", "UNKNOWN", "FAILED"].includes(review.status);
  return (
    <section className="flex flex-col gap-2" aria-label="Calendar event" data-testid="calendar-event-review">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          <CalendarClock className="h-3 w-3" aria-hidden /> Calendar event
        </p>
        <Badge variant={done ? "success" : bad ? "warning" : "secondary"} data-testid="calendar-status">{EVENT_STATUS_LABEL[review.status]}</Badge>
      </div>
      <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Title</dt><dd>{review.event.title}</dd>
        <dt className="text-muted-foreground">Date</dt><dd data-testid="calendar-date">{review.date_label}</dd>
        <dt className="text-muted-foreground">Time</dt><dd data-testid="calendar-time">{review.time_label} ({review.duration_minutes} min)</dd>
        <dt className="text-muted-foreground">Timezone</dt><dd>{review.timezone_label}</dd>
        {review.event.attendee_emails.length > 0 && (<><dt className="text-muted-foreground">Guests</dt><dd>{review.event.attendee_emails.join(", ")}</dd></>)}
        <dt className="text-muted-foreground">Conflicts</dt><dd>{CONFLICT_LABEL[review.conflict_status]}</dd>
      </dl>
      {review.conflicts.map((c) => (
        <p key={`${c.title}-${c.start_label}`} className="flex items-center gap-1.5 text-xs text-level-warning">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {c.title} · {c.start_label}–{c.end_label}
        </p>
      ))}
      {review.assumptions.map((a) => <p key={a} className="text-[11px] text-muted-foreground">• {a}</p>)}
      {review.message && <p className="text-xs" data-testid="calendar-message">{review.message}</p>}
    </section>
  );
}
