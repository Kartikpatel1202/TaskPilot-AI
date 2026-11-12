# Gmail draft automation

**TaskPilot never sends email.** It composes, saves and verifies a **draft**; the user presses Send in
Gmail. When the user asks to *send*, the plan still creates a draft, an assumption says so, and the
`gmail.send_blocked` event carries:

> Haan bhai, main email ka draft prepare kar sakta hoon. Final Send tum Gmail se manually kar sakte ho.

`GMAIL_AUTOMATED_SEND_ENABLED` and `GMAIL_ATTACHMENT_ENABLED` exist only as locks: the server refuses to
start if either is `true`.

## Content

- Recipients must be email addresses the user wrote (`EmailStr`, deduplicated, ≤ `GMAIL_MAX_RECIPIENTS`).
  Missing → clarification ("I won't guess it"). CC is not automated (`GMAIL_CC_UNSUPPORTED`).
- Subject/body come from fact-free templates (`gmail/composer.py`): the stated topic plus typed outputs of
  earlier steps (`{{youtube.title}}`, `{{youtube.video_url}}`, `{{file.name}}`, `{{file.size}}`). Unknown
  details stay visible placeholders (`[Your name]`). Body ≤ `GMAIL_MAX_DRAFT_LENGTH`; text that looks like a
  credential or card number is refused.
- Before Run Plan the draft can be edited (`PUT /tasks/{id}/gmail/draft`, only while `PLANNED`).

## Flow (`gmail/adapter.py`)

1. Open Gmail (guarded). A sign-in page/password field → `GMAIL_LOGIN_REQUIRED` (run cancelled; the user
   signs in personally; TaskPilot never types passwords, OTPs or 2-step codes).
2. Click **Compose** (`div[gh=cm]`) — the only allowed click besides **Save & close**.
3. Fill `To recipients`, press Tab, and verify the recipient chips equal the requested addresses exactly.
4. Fill `subjectbox` and the contenteditable `Message Body` (rich-text fill verifies the editor text).
5. Wait for "Draft saved", then click **Save & close**.
6. Open Drafts (guarded navigation + a fixed same-document `location.hash = 'drafts'`) and look for the
   subject. Found → `DRAFT_SAVED` (verified). Error shown → `DRAFT_SAVE_FAILED`. Neither →
   `SAVE_STATUS_UNKNOWN` (step fails; never claimed as saved).

`IntegrationPolicy` refuses Send / Schedule send / "bhejo" / Discard / Delete for every Gmail purpose.

## Privacy

Telemetry carries status messages only — never the body or full addresses. The REST draft view masks
recipients after saving (`h•••@example.com`). Agent memory never stores the body.

## Events

`gmail.draft_started`, `gmail.draft_composed`, `gmail.draft_saved`, `gmail.draft_verified`,
`gmail.draft_failed`, `gmail.send_blocked`.

## Testing status

Verified on the local Gmail-like fixture, whose fake **Send** button increments a counter the tests
assert stays 0. **Not tested against mail.google.com.**
