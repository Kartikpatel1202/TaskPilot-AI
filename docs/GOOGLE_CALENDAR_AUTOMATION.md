# Google Calendar automation

Creates **one** event, only after the user approves that exact event. Never deletes or modifies other
events (`CALENDAR_ALLOW_AUTOMATIC_EVENT_DELETION` and `CALENDAR_REQUIRE_CREATION_APPROVAL=false` are
refused by settings validation).

## Time parsing (`calendar/datetime_parser.py`)

Deterministic Python with an injected "now" and IANA zones (no model arithmetic):

- dates: today/aaj, tomorrow/kal (assumption stated), parso/day after tomorrow, weekdays (next
  occurrence, stated), `10 Nov`, `November 10 2026`, ISO `2026-11-10`, `25/11`;
- times: `3pm`, `3:30 pm`, `15:00`, ranges `3-4pm`, `from 3:30pm to 5pm`, `noon`, `3 baje` with
  subah/shaam/raat or an explicit AM/PM;
- durations: `30 minutes`, `1 hour`, `1.5 hours`, `an hour`, `half an hour`, `1 ghanta`, `aadha ghanta`;
- timezones: IANA names or IST/PST/EST/GMT/UTC/… else `CALENDAR_DEFAULT_TIMEZONE` (stated).

It **asks** instead of guessing when: AM/PM is ambiguous, `10/11` could be either order, date/time is
missing, duration is missing (unless `CALENDAR_DEFAULT_DURATION_MINUTES > 0`, then stated), the time has
passed, or the wall time does not exist on that day (DST gap). A repeated DST hour uses the first
occurrence and says so.

## Flow

1. **Prepare:** labels (`Tuesday, November 10, 2026`, `3:00 PM – 3:30 PM`, `Asia/Kolkata (IST, UTC+05:30)`)
   and `event_hash` = SHA-256 over title, UTC start/end, timezone, description, location, sorted
   attendees, reminder and recurrence.
2. **Conflicts / duplicates (advisory):** read the day view's `[data-eventid]` labels. An identical event
   (same title, start, end) → `ALREADY_EXISTS`, nothing created. Overlaps → `CONFLICTS_FOUND`, shown in the
   approval. Unreadable calendar → `UNAVAILABLE` ("not assumed free").
3. **Prefill:** open the documented event template URL (`/calendar/r/eventedit?text&dates&ctz&details&location&add`)
   and re-read the form; any mismatch → `CALENDAR_FORM_MISMATCH`.
4. **Approve:** an `ApprovalRequest` (risk HIGH) with `calendar: CalendarApprovalDetails`. The dashboard shows
   `CalendarApprovalDialog` — "Reject Event Creation" / "Confirm This Exact Event", no autofocus on a
   decision, Enter never decides. Rejected → `CALENDAR_EVENT_REJECTED` (run cancelled); expired →
   `CALENDAR_APPROVAL_EXPIRED`.
5. **Re-check:** the approved hash, the live hash and the live form must all agree, and the approval must be
   unused → a single-use `CalendarAuthorization`. Otherwise `CALENDAR_APPROVAL_STALE` / `…_REUSED`.
6. **Save once:** the authorization is marked clicked *before* the click, so Save can never be pressed
   twice. The invitation dialog's **Send** is clicked only when the approved event lists attendees (the
   dialog said invitations will be sent); otherwise **Don't send**.
7. **Verify:** re-read the day view (up to 3 reads). Found → `CREATED` with the visible event id.
   Not found → `UNKNOWN` ("check Google Calendar before trying again, to avoid a duplicate") — never claimed.

## Events

`calendar.event_prepared`, `calendar.conflict_detected`, `calendar.approval_required`,
`calendar.approval_resolved`, `calendar.event_creation_started`, `calendar.event_created`,
`calendar.event_creation_failed`.

## Testing status

Verified on the local Calendar-like fixture (events in the browser's local storage), including reject →
approve, conflicts, duplicates, invitations and the silent-save UNKNOWN case. **Not tested against
calendar.google.com.**
