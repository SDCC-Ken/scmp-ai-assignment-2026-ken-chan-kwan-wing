# Chat API contract (Phase 2)

Shared by the backend and the frontend. All routes are under `/api/chat`, require the session
cookie and the `employee` role (other roles get `403 {"detail":"Forbidden"}`), and every POST
needs `X-Requested-With: XMLHttpRequest`. All data is fictional.

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
  "ui": null | ConfirmationCard | StatusCard | ResultCard,
  "trace": null | [TraceStep]                         // assistant messages only
}

TurnResponse = {
  "conversation": ConversationSummary,
  "user_message": Message | null,                     // null for card actions
  "assistant_messages": [Message],                    // 1 or more, in order
  "warning_code": null | "llm_unavailable" | "llm_invalid_output" | "submission_failed" | "stale_card"
}

TraceStep = { "step": "understand" | "merge" | "validate" | "decide" | "submit" | "status" | "respond",
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
    "external_reference_id": null | "mock ReqRes id"
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
