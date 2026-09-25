# Bell inbox: "handle everything waiting for me, one by one"

Ken: "when clicking the bell create a new conversation and show all the items that need handling
one by one; also a small number on the bell." All data is fictional.

## Behaviour

- The bell (every signed-in user) keeps its **small unread number**. Clicking the bell creates a
  **new conversation** (a chat) called "Items to handle (N)" and opens it in the chat page. If there
  is nothing to handle, no conversation is created and the bell shows "You are all caught up".
- The conversation opens with a short intro and then shows the items **one card at a time**. After
  the person acts on (or skips) a card, the next card appears; at the end there is a closing message
  with a summary. Skipped items stay unread and come back the next time the bell is clicked.
- Items, in this order:
  1. **Approvals** (approvers): every request that is `pending_approval` and assigned to the caller
     (oldest first), with the same context as the approvals screen: fields, attachments, limit or
     budget with over-limit flag, team overlap, warnings, optional note. Actions: Approve, Reject,
     Skip.
  2. **Notices** (everyone): the caller's other unread notifications (a decision on their own request,
     or a change or cancellation of a request that is no longer pending). Actions: Got it, Skip.
     Unread `request.submitted` / `request.updated` notifications of a still-pending request are
     covered by its approval card (not a separate notice); they are marked read when that card is
     handled.
- Approve and Reject need a **second explicit click** ("Confirm approve") in the card; the API also
  requires `confirmed: true`. The decision uses exactly the same rules, audit and notifications as
  the approvals screen (assigned approver, still pending, one winner, optional note up to 500
  characters); its audit metadata gets `"via": "inbox"`.
- Chat access: users who can file requests **or** approve something may use the chat (so Helen and
  Eva can use the inbox). Filing requests still needs an approver, so Helen and Eva still cannot file.
- The old bell dropdown is replaced by this flow. `GET /api/notifications` and the approvals screens
  remain.

## API

| Method and path | Result |
| --- | --- |
| `POST /api/chat/inbox` (no body) | Nothing to handle: `200 {"empty": true, "unread_count": 0}`. Otherwise `201 {"empty": false, "conversation": ConversationSummary, "assistant_messages": [Message], "warning_code": null}` (intro message, then the first card) |
| `POST /api/chat/conversations/{id}/actions` | Existing endpoint; body gains inbox actions: `{"card_id": "...", "action": "approve" \| "reject" \| "skip" \| "acknowledge", "note": null \| "<=500 chars", "confirmed": true}` (`confirmed` required for approve and reject, ignored otherwise; `note` only for approve and reject). Returns `TurnResponse` with the result message(s) and the NEXT card (or the closing message) |

Errors: 409 for a stale card, an item already decided elsewhere (the card becomes `stale` and the
next item is shown), or a card that is not the newest open one; 422 for a missing `confirmed`, a bad
action for the card kind, or a note over 500 characters; 404 for someone else's conversation; 403
for users who neither file nor approve (the existing rule).

```jsonc
InboxCard = {                                    // Message.ui.type = "inbox_card"
  "type": "inbox_card", "card_id": "i_7c1d2e",
  "kind": "approval" | "notice",
  "position": {"index": 1, "total": 3},
  "title": "Leave request #1 from Amy Lau",
  "request_type": "leave" | "claim" | null, "request_id": 1 | null,
  "detail": ApprovalDetail | null,               // kind "approval": exactly the shape of GET /api/approvals/{type}/{id}
  "notice": {"title": "...", "body": "..."} | null,   // kind "notice"
  "actions": ["approve", "reject", "skip"] | ["acknowledge", "skip"],
  "state": "open" | "done" | "skipped" | "stale",
  "outcome": null | "approved" | "rejected" | "acknowledged"
}
```

The closing message text summarises "You handled 2 items and skipped 1" and says skipped items stay
in the bell and in Approvals. Conversation state (the item queue, the position, counts) is stored
with the conversation so reopening it restores the open card.

## Not in scope

Editing a decision after the fact, bulk approve, reordering the queue, push or e-mail notifications.
