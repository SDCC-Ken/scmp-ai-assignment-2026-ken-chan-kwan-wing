# Phase 3: approval workflow (design and API contract)

Source: Ken's Phase 3 brief (13 points). All data is fictional. This file is the contract the
backend and frontend agents build against. Where Ken did not specify a value, the default chosen
here is marked **(assumption)** so it can be changed.

## 1. People, departments and who approves whom

| User | Department | Role | Files own requests | Approves |
| --- | --- | --- | --- | --- |
| Amy Lau | IT | employee | yes | - |
| Ben Chow | IT | employee | yes | - |
| Cathy Ng | HR | hr_approver | yes | Leave of the **IT** department (she is responsible for IT) |
| Daniel Wong | HR | employee | yes | - (was the HR approver before; now an HR staff member) |
| Helen Yeung (new, HR manager) | HR | hr_approver | no | Leave of the **HR** department (Cathy and Daniel) |
| Eva Cheung | Finance | finance_approver | no | **All claims** (Ken: "not the base rules, just to keep the PoC simple") |

- Routing is stored per department: `departments.leave_approver_user_id` and
  `departments.claim_approver_user_id`. IT leave -> Cathy, HR leave -> Helen, every claim -> Eva.
  The approver is resolved when the request is submitted and stored on the request
  (`approver_user_id`).
- An approver can never review their own request. If no approver can be resolved (or it would be the
  requester) the assistant refuses to create the request and explains why.
- `users.can_request` says who may use the chat to file requests (Amy, Ben, Cathy, Daniel = true;
  Helen, Eva = false). An approver may also file requests (Cathy), which is a change from the
  earlier product scope where approvers only approved.
- HR approvers see and decide **Leave only**; the Finance approver **Claims only**, and only the
  requests assigned to them.

## 2. Limits (shown, never blocking)

- **Leave balance (points 4, 5):** per user, per calendar year, for `annual` and `sick` only
  (`leave_entitlements`: user, year, leave_type, entitled_days). **(assumption)** Seed: annual 15
  days and sick 10 days for 2026 and 2027, with small variations. `personal` and `unpaid` have no
  balance. Used = working days of **approved** requests, counted in the year of the start date
  **(assumption)**. Pending requests are shown separately and are not deducted.
  `remaining = entitled - approved`. The request may exceed the balance.
- **Department claim limit (points 6, 7):** per department, per calendar year, in HKD
  (`departments.claim_limit_amount`) **(assumption)** Seed: IT 60,000.00, HR 30,000.00,
  Finance 30,000.00. Used = amount of **approved** claims of the department, by receipt-date year
  **(assumption)**; pending shown separately. A claim may exceed the limit.
- The employee sees their own leave balance (chat answer and on the leave card). The approver sees
  the balance or the department budget **and** an "over the limit" warning before deciding; the
  approver decides.

## 3. Approver experience (points 8 to 11, 13)

- List: only requests with status `pending_approval` assigned to the caller (Leave for HR
  approvers, Claims for the Finance approver). Inspect: the same restriction; anything else is 404.
  After a decision the request leaves the approver's list **(as specified: pending only)**.
- Detail shows: who, department, all request fields (including half-day parts and working days),
  attachments (Phase 2b), the **limit context** (leave balance or department budget, with the
  amount after this request and an over-limit flag), and the **team overlap** (colleagues of the
  same department whose approved or pending leave overlaps the requested dates).
- Decision: Approve or Reject with an **optional** reviewer note (max 500 characters) for both. The
  previous rule "reject needs a note" is removed (schema change, see section 7). The UI asks for a
  confirmation before sending. State change: `pending_approval` -> `approved` / `rejected`, sets
  `reviewed_by_user_id`, `reviewed_at`, `reviewer_note`.
- Audit (point 13): one `audit_events` row per decision (`request.approved` / `request.rejected`)
  with actor, entity, from/to status and metadata: note present, over-limit flags and the numbers
  the approver saw (balance or budget snapshot, team-overlap count).

## 4. Notifications and the bell (point 12)

Every signed-in user has a bell with an unread count. Clicking it lists recent notifications.

| Event | Recipient | Title example |
| --- | --- | --- |
| `request.submitted` | the assigned approver | "New leave request from Amy Lau" |
| `request.updated` | the assigned approver | "Amy Lau changed leave request #12" |
| `request.cancelled` | the assigned approver | "Amy Lau cancelled leave request #12" |
| `request.approved` | the requester | "Your leave request #12 was approved" (+ note) |
| `request.rejected` | the requester | "Your leave request #12 was rejected" (+ note) |

The frontend polls every 30 seconds and when the tab regains focus. Clicking a notification marks
it read and navigates: approvers to the request, requesters to a small detail dialog showing the
decision and note. Notifications never contain attachments or the full request.

## 5. API contract

All routes need the session cookie; POSTs need `X-Requested-With: XMLHttpRequest`. Errors: 401
unauthenticated, 403 wrong role, 404 not found or not visible to the caller, 409 wrong state,
422 validation.

```jsonc
UserPublic (extended; /api/auth/me, /api/auth/mock-users, login response) = {
  "id": 3, "email": "...", "display_name": "Cathy Ng", "role": "hr_approver",
  "department": {"id": 2, "name": "HR"},
  "job_title": "HR Business Partner (IT)",                       // display only
  "can_request": true,                                            // may use the chat
  "approves": "leave" | "claim" | null                            // which queue they decide
}
```

| Method and path | Who | Result |
| --- | --- | --- |
| `GET /api/me/balances` | any user with `can_request` | `{"year": 2026, "leave": [BalanceLine]}` |
| `GET /api/approvals` | hr_approver, finance_approver | `{"items": [ApprovalListItem], "count": 2}` (own queue, pending only, oldest first) |
| `GET /api/approvals/{request_type}/{id}` | the assigned approver | `ApprovalDetail` (404 unless pending and assigned to the caller) |
| `POST /api/approvals/{request_type}/{id}/decision` | the assigned approver | body `{"decision": "approve" or "reject", "note": null or "<=500 chars"}` -> `200 {"request_type","id","status","reviewed_at"}`; 409 if no longer pending |
| `GET /api/notifications?limit=20` | everyone | `{"items": [Notification], "unread_count": 3}` newest first |
| `POST /api/notifications/{id}/read` | owner | 204 |
| `POST /api/notifications/read-all` | owner | 204 |

```jsonc
BalanceLine = {"leave_type": "annual", "entitled_days": 15.0, "approved_days": 3.0,
               "pending_days": 2.5, "remaining_days": 12.0}       // days in 0.5 steps

ApprovalListItem = {
  "request_type": "leave", "id": 12,
  "employee": {"id": 1, "display_name": "Amy Lau", "department": "IT"},
  "summary": "Annual leave, Mon 2026-10-05 to Wed 2026-10-07 (2.5 working days)",
  "submitted_at": "2026-09-25T03:10:00Z",
  "flags": {"over_limit": false, "team_overlap_count": 1, "has_attachments": true}
}

ApprovalDetail = {
  "request": {
    "request_type": "leave", "id": 12, "status": "pending_approval",
    "submitted_at": "...", "employee": {"id": 1, "display_name": "Amy Lau", "department": "IT"},
    "fields": [{"key": "leave_type", "label": "Leave type", "value": "Annual"}, ...],
    "attachments": [AttachmentInfo],                // see docs/chat-api-contract.md
    "external_reference_id": "531" | null
  },
  "limits": {                                       // exactly one of the two, by request type
    "leave_balance": {"leave_type": "annual", "year": 2026, "entitled_days": 15.0,
                      "approved_days": 3.0, "pending_other_days": 0.0, "requested_days": 2.5,
                      "remaining_after_days": 9.5, "over_limit": false} | null,
    "department_budget": {"department": "IT", "year": 2026, "limit_amount": "60000.00",
                          "approved_amount": "12000.00", "pending_other_amount": "300.00",
                          "requested_amount": "180.00", "remaining_after_amount": "47520.00",
                          "over_limit": false, "currency": "HKD"} | null
  },                                                // no balance for personal/unpaid: leave_balance null
  "team_overlap": [{"employee": "Ben Chow", "leave_type": "annual", "start_date": "2026-10-06",
                    "end_date": "2026-10-06", "status": "approved", "working_days": 1.0}],
  "warnings": ["Over the annual leave balance by 1.5 days. You decide."]
}

Notification = {"id": 5, "event_type": "request.submitted", "title": "New leave request from Amy Lau",
                "body": "Annual leave, Mon 2026-10-05 to Wed 2026-10-07", "request_type": "leave",
                "request_id": 12, "read_at": null, "created_at": "...",
                "link": "/approvals/leave/12" | null}   // null for requesters (dialog instead)
```

Chat additions (`docs/chat-api-contract.md` still applies):
- Leave confirmation cards gain `info` lines such as "Annual leave balance 2026: 15 days, 3 used,
  12 left; 9.5 left after this request (pending requests not counted)". Over the balance the card
  shows a warning that the approver will decide; it does not block.
- New intent `check_balance` ("how many annual leave days do I have left?") answers with a
  `balance_card` UI: `{"type": "balance_card", "year": 2026, "lines": [BalanceLine]}`.
- If no approver can be resolved the assistant refuses with an explanation and no card.

## 6. Seed data (replaces the Phase 1 seed)

6 users as in section 1 (all `@example.com`), 3 departments (IT, HR, Finance) with the routing and
limits above, entitlements for 2026 and 2027, and leave/claim history re-assigned so every reviewed
row was reviewed by its correct approver (IT leave by Cathy, HR leave by Helen, claims by Eva).
Keep the counts from Phase 1 (10 leave, 10 claims, 2 pending of each) and make the pending ones show
the new features: at least one pending leave that overlaps a colleague's leave in the same
department, one over the annual balance, one pending claim that pushes a department over its limit.
Notifications match the pending items. Audit events keep the same variety.

## 7. Schema changes (need a database reset)

New: `departments`, `leave_entitlements`; `users.department_id`, `users.job_title`,
`users.can_request`; `leave_requests.approver_user_id`, `claim_requests.approver_user_id`;
`notifications` gets a nullable short `payload_json` if needed. Removed: the CHECK constraint
"rejected requests need a reviewer note" (the note is optional now) and the domain rule that
enforces it. SQLite cannot drop a CHECK constraint in place, so **existing databases must be
recreated**: `docker compose down -v` (or `python -m app.cli seed --reset --yes`). The API must
detect an older schema at startup and log a clear instruction instead of failing obscurely.

## 8. Not in Phase 3

Multi-level approval chains, delegation, entitlement accrual/carry-over, cross-year splitting of a
leave, editing limits from the UI, email notifications, websockets (polling is used).
