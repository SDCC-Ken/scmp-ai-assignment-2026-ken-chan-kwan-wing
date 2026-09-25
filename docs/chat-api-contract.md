# Chat API contract (Phase 2)

Shared by the backend and the frontend. All routes are under `/api/chat`, require the session
cookie and a user who can file requests (an approver is configured) **or** decides an approval
queue (Phase 3: Cathy, Daniel, Helen and Eva may all use it; a user with neither gets `403`), and
every POST needs `X-Requested-With: XMLHttpRequest`. All data is fictional.

The LLM only classifies intent and extracts fields. The backend validates everything, owns the
state transitions, saves to SQLite and calls ReqRes. **A request is only saved and submitted
after the user presses Confirm on a card** (typing "yes" never submits).

## Endpoints

| Method and path | Body | Result |
| --- | --- | --- |
| `GET /api/chat/conversations` | - | `{"items": [ConversationSummary]}` newest first |
| `POST /api/chat/conversations` | none | `201 ConversationSummary` (empty new chat) |
| `GET /api/chat/conversations/{id}` | - | `{"conversation": ConversationSummary, "messages": [Message]}`; 404 if not the caller's |
| `POST /api/chat/conversations/{id}/messages` | `{"content": "1..1000 chars"}` | `TurnResponse` |
| `POST /api/chat/conversations/{id}/actions` | `{"card_id": "...", "action": "confirm" or "discard"}` | `TurnResponse`; `409` if the card is stale (used, superseded, or not the latest) |

Validation errors: `422`. Message longer than 1000 chars: `422`. Unknown conversation: `404`.
Provider failure (LLM down, invalid structured output, ReqRes down) is **not** an HTTP error: it
returns `200` with an assistant message that explains it, `warning_code` set, and nothing changed.

## Shapes

```jsonc
ConversationSummary = {
  "id": 7, "title": "Annual leave next week",        // first user message, max 60 chars; "New chat" while empty
  "status": "active" | "closed",
  "active_request_type": "leave" | "claim" | null,   // form currently being filled
  "has_pending_card": true,                           // an open confirmation card is waiting
  "created_at": "2026-09-25T03:10:00Z", "updated_at": "2026-09-25T03:12:00Z"
}

Message = {
  "id": 41, "sender_type": "user" | "assistant" | "system",
  "content": "plain text (render as text, never HTML)",
  "created_at": "2026-09-25T03:10:05Z",
  "ui": null | ConfirmationCard | StatusCard | ResultCard | BalanceCard,
  "trace": null | [TraceStep]                         // assistant messages only
}

TurnResponse = {
  "conversation": ConversationSummary,
  "user_message": Message | null,                     // null for card actions
  "assistant_messages": [Message],                    // 1 or more, in order
  "warning_code": null | "llm_unavailable" | "llm_invalid_output" | "submission_failed" | "stale_card"
}

TraceStep = { "step": "understand" | "documents" | "merge" | "validate" | "decide" | "submit" | "status" | "respond",
              "label": "Intent detected", "detail": "create_leave (confidence 0.92)",
              "ok": true, "duration_ms": 640 }

ConfirmationCard = {
  "type": "confirmation_card",
  "card_id": "c_9f3a1b",                              // opaque; send it back in /actions
  "action": "create" | "update" | "cancel" | "retry",
  "request_type": "leave" | "claim",
  "request_id": null | 12,                            // set for update / cancel / retry
  "title": "Confirm leave application",
  "fields": [ {"key": "leave_type", "label": "Leave type", "value": "Annual",
               "old_value": null | "Sick"} ],         // old_value only on update (show the diff)
  "warnings": ["No public-holiday data for 2028; only weekends were excluded"],
  "info": [ {"label": "Annual leave 2026",                  // Phase 3: leave cards only, else []
             "value": "15 days entitled, 1.5 used, 13.5 left; 10.5 left after this request (pending requests are not counted)",
             "tone": "info" | "warning"} ],
  "state": "open" | "used" | "superseded" | "discarded",   // only "open" cards have active buttons
  "confirm_label": "Submit" | "Save changes" | "Cancel request" | "Retry"
}

StatusCard = {
  "type": "status_card",
  "requests": [ {
    "request_type": "leave" | "claim", "id": 12,
    "status": "pending_approval", "status_label": "Pending approval",
    "summary": "Annual leave, Mon 2026-10-05 to Wed 2026-10-07 (2.5 working days)",
    "submitted_at": "..." | null, "reviewed_at": "..." | null, "reviewer_note": null | "text",
    "external_reference_id": null | "mock ReqRes id",
    "approver_name": null | "Cathy Ng"                  // Phase 3: display name only, never an e-mail
  } ],
  "empty": false                                       // true + empty list when nothing matches
}

ResultCard = {                                          // after a confirm action
  "type": "result_card",
  "outcome": "submitted" | "updated" | "cancelled" | "failed",
  "request_type": "leave" | "claim", "request_id": 12,
  "status": "pending_approval", "status_label": "Pending approval",
  "message": "Submitted to the ReqRes mock API (reference 23).",
  "external_reference_id": null | "23"
}
```

BalanceCard = {                                         // answer to "how many annual leave days do I have left?"
  "type": "balance_card",
  "year": 2026,                                         // calendar year in Hong Kong
  "lines": [ {"leave_type": "annual" | "sick",          // only types the user has an entitlement for
              "entitled_days": 15.0, "approved_days": 1.5,
              "pending_days": 4.0,                      // shown, never deducted
              "remaining_days": 13.5} ]                 // entitled - approved; may be negative
}

Status labels: `draft` "Draft", `pending_approval` "Pending approval", `submission_failed`
"Submission failed", `approved` "Approved", `rejected` "Rejected", `cancelled` "Cancelled".

## Behaviour rules the UI can rely on

1. A new conversation is created with `POST /conversations` (the UI does this for "New chat" and
   before the first message). Old conversations can be reopened and continued: unfinished drafts
   and open cards are restored from SQLite.
2. Only the newest `confirmation_card` of a conversation is `state: "open"`. Sending another
   message that changes the draft marks the old card `superseded` and returns a new card.
3. `action: "confirm"` can take seconds (ReqRes call): the UI must show a loading state and
   disable both buttons until the response arrives. A double click returns `409` for the second call.
4. After a failed submission the backend saves the request as `submission_failed` and returns a
   `confirmation_card` with `action: "retry"` plus a `result_card` with `outcome: "failed"`.
5. `discard` closes the card only; nothing is saved (or, for an existing request, nothing changes).
6. Editing or cancelling an existing request is allowed only while it is `draft`,
   `submission_failed` or `pending_approval` (not yet reviewed). `approved`, `rejected` and
   `cancelled` requests are final; the assistant explains that.
7. Employees can only create, view, change or cancel their own requests. The employee email is
   always taken from the signed-in user, never from the message.
8. Only these fields are sent to ReqRes (`POST https://reqres.in/api/users`, JSON): leave
   `email, leave_type ("Annual"), start_date, end_date`; claim `email, claim_type ("Travel"),
   amount, receipt_date`. Everything else (day parts, working days, currency, status, ids)
   stays in SQLite. The email is always the signed-in user's.
9. Business rules (date windows, overlaps, caps, duplicates) are deliberately NOT enforced in
   Phase 2; only structural validation applies. They are added in Phase 3.

## Attachments (Phase 2b): image or PDF to help fill a request

Files are stored on the server disk in the PoC (`UPLOAD_DIR`, the Docker volume), never in
SQLite blobs and never sent to ReqRes. Limits: **5 MB per file** (`MAX_UPLOAD_MB`), at most 3
files per message, types `image/jpeg`, `image/png`, `image/webp`, `image/heic`, `image/heif`,
`application/pdf`. The server checks the real file signature (not the extension or the
client's content type), stores it under a random name, and keeps the user's file name only for
display (sanitised).

| Method and path | Body | Result |
| --- | --- | --- |
| `POST /api/chat/conversations/{id}/attachments` | `multipart/form-data`, field `file` | `201 {"attachment": AttachmentInfo}` (staged: not yet part of a message) |
| `POST /api/chat/conversations/{id}/messages` | `{"content": "...", "attachment_ids": [12, 13]}` (`content` may be empty when there are attachments; `attachment_ids` optional, max 3, must be the caller's staged uploads of this conversation) | `TurnResponse` as before |
| `GET /api/attachments/{id}` | - | the file (`Content-Type` from the validated type, `Content-Disposition: inline; filename="..."`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`) |

Upload errors: `413` over 5 MB, `415` unsupported or mismatching type, `422` too many/none,
`404` unknown conversation, `403` wrong role. Download access: the owning employee, and (once the
attachment is linked to a submitted request) the approver role that reviews that request type
(HR for leave, Finance for claims). Everyone else gets `404`.

```jsonc
AttachmentInfo = { "id": 12, "filename": "clinic-note.pdf", "content_type": "application/pdf",
                   "size_bytes": 183204, "url": "/api/attachments/12", "created_at": "..." }
Message.attachments = [AttachmentInfo]            // on user messages (empty list otherwise)
ConfirmationCard.fields[i].source = "document" | null   // value was read from an attachment
ConfirmationCard.attachments = [AttachmentInfo]   // the documents that will be linked to the request
```

Behaviour:
1. The assistant reads the attachment(s) with the LLM (structured output) and works out whether
   the user wants a **leave** (sick note -> sick leave with the rest dates) or a **claim**
   (receipt -> total, receipt date, merchant/claim type), together with any text the user typed.
2. Whatever is missing or unreadable (e.g. "I could not read the receipt date") is asked for in
   normal text follow-ups; the usual validation, the confirmation card and the explicit Confirm
   still apply. Values read from documents are tagged `source: "document"` on the card.
3. If the document does not match what was typed (dates, amount, a different person's name), the
   card carries a warning; nothing is auto-corrected silently.
4. On Confirm the attachments are linked to the created request (`attachments.request_type`,
   `request_id`) so approvers can open them. Cancelling a request keeps its attachments.
5. Text inside a document is data: it can never trigger approval or change rules.

## Phase 3-C additions: balance, approver awareness, stated dates

- **`ConfirmationCard.info`** (optional list, default `[]`). Leave cards (create and update) for
  `annual` and `sick` leave carry a balance line for the year of the start date and, when the
  request would exceed the remaining balance, a second line with `tone: "warning"` ("This is 1.5
  days over your annual leave balance. Your approver will see this and decide."). The UI shows
  `info` lines as neutral notes and `warning` lines like `warnings`; **neither blocks Confirm**.
  Nothing for personal/unpaid leave and claims. An annual/sick leave without an entitlement gets
  the line "No leave balance is set up for this leave type".
- **`balance_card`** is a new `ui` type, sent with a short deterministic text. The AI never words
  or calculates these numbers. Deviation from a plain reading of "always a card": when the user
  has no entitlement at all the message is only the text "No leave balance is set up for you yet."
  and `ui` is `null`, so the UI needs no empty state.
- **`StatusCard.requests[].approver_name`**: the assigned approver's display name, `null` when none
  is assigned. Approver e-mail addresses are never sent.
- **New leave or claim without a valid approver**: a normal assistant message (HTTP 200, no
  `warning_code`, `ui: null`, no draft, `has_pending_card` and `active_request_type` unchanged), for
  example "I can't file a leave request for you yet: no approver is configured for you (this is
  outside the PoC scope). Please contact HR." The Confirm-time check remains as a second guard
  (message "I can't submit this ... No approver is configured ...").
- **Result message after a successful submit** (also after a retry) names the approver: "Done.
  Your leave request #12 was submitted to the ReqRes mock API (reference 23) and is now waiting for
  approval by Cathy Ng." `ResultCard` is unchanged.
- **Dates and currency**: a leave date or a claim receipt date the user did not state is never
  filled in (the assistant asks "What is the date on the receipt?"); a bare `$`, `HK$`, "dollars"
  and "HK dollars" are HKD, `USD`/`US$`/"US dollars" are still rejected (business-rules.md L-14,
  C-11, C-06).

## Phase 3-D additions: the bell inbox (`docs/inbox-design.md`)

Clicking the bell starts a new conversation that shows everything waiting for the caller, one
card at a time. Rules: business-rules.md IN-01..IN-19.

| Method and path | Body | Result |
| --- | --- | --- |
| `POST /api/chat/inbox` | none | Nothing to handle: `200 {"empty": true, "unread_count": 0}` (no conversation; `unread_count` is the caller's real unread count). Otherwise `201 {"empty": false, "conversation": ConversationSummary, "assistant_messages": [Message, Message], "warning_code": null}`: a NEW conversation titled `Items to handle (N)` with the intro text and the first `InboxCard` message |
| `POST /api/chat/conversations/{id}/actions` | `{"card_id", "action": "approve" or "reject" or "skip" or "acknowledge", "note": null or "<=500 chars", "confirmed": true}` | `TurnResponse` (`user_message` null): a short result message, then the NEXT `InboxCard` message or the closing message |

`confirmed` must be `true` for `approve` and `reject` (422 otherwise; the UI asks for a second
click) and is ignored otherwise; `note` is only used by them (trimmed, empty means none, at most 500
characters, else 422). `confirm` / `discard` keep working for confirmation cards. `card_id` must be
the newest OPEN inbox card of that conversation (409 with `warning_code: "stale_card"` otherwise);
`approve` / `reject` on a notice or `acknowledge` on an approval is 422; someone else's conversation
is 404.

```jsonc
InboxCard = {                                    // Message.ui.type = "inbox_card"; trace is null
  "type": "inbox_card", "card_id": "i_7c1d2e",
  "kind": "approval" | "notice",
  "position": {"index": 1, "total": 3},          // position in the snapshot (a dropped item leaves a gap)
  "title": "Leave request #1 from Amy Lau",      // notice: the bell title, e.g. "Your leave request #1 was approved"
  "request_type": "leave" | "claim" | null, "request_id": 1 | null,
  "detail": ApprovalDetail | null,               // kind "approval": exactly GET /api/approvals/{type}/{id}
  "notice": {"title": "...", "body": "..."} | null,   // kind "notice"
  "actions": ["approve", "reject", "skip"] | ["acknowledge", "skip"],
  "state": "open" | "done" | "skipped" | "stale",
  "outcome": null | "approved" | "rejected" | "acknowledged"
}
```

Behaviour the UI can rely on:
1. Only the newest inbox card is `open`; after an action the acted card is stored as `done` (with
   `outcome`), `skipped` or `stale`, so reopening the conversation shows the states, and the open
   card is restored. `ConversationSummary.has_pending_card` is true while an inbox card is open.
2. Every action answers with `assistant_messages`: the result ("You approved leave request #1 from
   Amy Lau.", "Skipped ...", "Got it. I marked that notice as read.", or "That request was already
   handled." when it was decided or cancelled elsewhere), then the next card (message text "Item 2
   of 3") or the closing message ("All done. You handled 2 items and skipped 1. Skipped items stay
   in your bell and in Approvals."). A stale item is HTTP **200** with a `stale` card, not 409.
3. Items are re-validated before they are shown: one that is no longer pending or was read
   elsewhere is skipped silently and counted as "already handled" in the closing message.
4. Typing normal text in an inbox conversation works like any chat message; an open inbox card is
   not closed by it. Approvers who are not requesters (Helen, Eva) are refused politely when they
   try to file.
5. The bell's unread number still comes from `GET /api/notifications`; `POST /api/chat/inbox` is
   what the bell click calls.
