# Frontend (Nuxt 4 + TypeScript + Tailwind CSS 4)

Runs on port 9180 (`WEB_PORT`). Env is read from the repo-root `../.env` if present; theme values use `NUXT_PUBLIC_THEME_*`.

- `bun install` - install dependencies
- `bun run dev` - dev server at http://localhost:9180
- `bun run lint` / `bun run lint:fix` - ESLint (`@nuxt/eslint`)
- `bun run typecheck` - `nuxt typecheck` (vue-tsc)
- `bun run test` - Vitest (theme, auth, access, approvals, notifications, chat and attachment utils, offline)
- `bun run build` then `bun run preview` (or `node .output/server/index.mjs` with `NITRO_PORT=9180`)

## Mock Google sign-in (Phase 1)

`/login` shows a Google One Tap-style card, **automatically on load**, fixed at the top-right of the viewport
(16px from the edges, 360px wide). Full-width MOCK warning banner on the page, plus a "MOCK" chip and the short
warning text inside the card. No Google scripts or requests: the "G" is an inline SVG. The card lists the fictional seed
users (`GET /api/auth/mock-users`) grouped by role; each row is a button ("Continue as <first name>") that calls
`POST /api/auth/mock-google/login`. Nothing is authenticated by Google.

- **Card behaviour:** not a modal (no backdrop, no focus trap, focus is never stolen on load). It is early in the tab
  order (after the theme toggle). Escape or the X collapses it; the page then shows a "Sign in with Google" button that
  re-opens it (and moves focus to the card). While a sign-in is in flight the clicked row shows a spinner, the other rows
  are disabled and Escape/X are ignored. Under 640px it flows in at the top of the page with 8px side margins; from 768px
  the page copy is shifted left so the card never covers it (640-767px it overlays).
- **Session = httpOnly cookie set by the API.** The API answers login with `Set-Cookie: scmp_session=<jwt>; HttpOnly;
  SameSite=Lax; Path=/; Max-Age=3600` and no token in the body, so **page scripts cannot read the session**
  (`document.cookie` never shows it; nothing is in localStorage/sessionStorage). The frontend never touches the token
  and sends no `Authorization` header. Auth state is only the non-secret user object in `useState` (fine in the SSR payload).
- **Cross-origin calls:** the browser calls the API on another port (web :9180 -> API :9181, same host), so every browser
  request uses `credentials: 'include'` and the API must allow the explicit origin with
  `Access-Control-Allow-Credentials: true` and the `X-Requested-With` header. Every unsafe request (POST/PUT/PATCH/DELETE)
  carries `X-Requested-With: XMLHttpRequest` (CSRF marker; otherwise the API returns 403 `CSRF check failed`).
- **SSR:** the Nuxt server forwards the incoming request's `cookie` header to `GET /api/auth/me` (using the private
  `apiBaseServer`), so a hard reload renders the signed-in page directly. Set-Cookie from API responses is never copied
  into the Nuxt response. Server-side, no cookies at all means no API call.
- **Guarding:** global middleware `app/middleware/auth.global.ts` validates the session once per server render, redirects
  unauthenticated users to `/login` and signed-in users away from it. A 401/403 clears the user; `/login?reason=expired`
  shows "session expired" only when a session cookie was actually present. `useApi()` (any API call) does the same on a 401.
- **Sign out:** `POST /api/auth/logout` (best effort; the API clears the cookie), then local state is always cleared.
- **API base URLs:** browser uses `NUXT_PUBLIC_API_BASE` (default `http://localhost:9181`); SSR uses the private
  `NUXT_API_BASE_SERVER` when set (docker-compose sets `http://api:9181`, because `localhost` inside the web
  container is the container itself). It is a runtime env var, not baked into the build. Use the same hostname for web and API
  (e.g. both `localhost`) so the host-scoped cookie is sent to both ports.

## Dev aid: API stub

`scripts/mock-api-stub.ts` is a throwaway implementation of the cookie auth contract for developing the UI without the
backend (not used by tests, Docker or production): login sets an HttpOnly `scmp_session` cookie and returns no token,
`/me` reads the cookie, logout clears it, the CSRF header is enforced, and CORS allows the explicit origin with credentials.

```bash
bun scripts/mock-api-stub.ts                       # listens on 9181 (API_PORT), CORS for http://localhost:9180
API_PORT=9191 STUB_ALLOWED_ORIGIN=http://127.0.0.1:9190 bun scripts/mock-api-stub.ts   # e.g. beside a build on 9190
curl -X POST localhost:9181/__stub/expire          # make /api/auth/me return 401 (session-expiry check)
curl -X POST localhost:9181/__stub/reset
```

## Employee chat (Phase 2)

Route `/` for users with `can_request` is one chat workspace (`ChatWorkspace`): conversation list on the left (a slide-over
drawer below 768px), message thread and composer on the right. Users without `can_request` (Helen, Eva) never see the chat: the
route rules send them to `/approvals` (the chat API would answer 403). Contract: `../docs/chat-api-contract.md`.

- **State and calls:** `app/composables/useChat.ts` (all requests go through `useApi`: cookie, `X-Requested-With` on POSTs, 401 sign-out).
  Pure helpers (status badges, relative time, message merge, card-state reconciliation, `canSend`, error mapping) live in
  `app/utils/chat.ts`; contract types in `app/types/chat.ts`; tests in `tests/chat.test.ts`.
- **Rendering:** every message is plain text (no `v-html`). Cards come from `message.ui`: `ConfirmationCard` (Submit/Discard, diff for
  `old_value`, amber warnings, read-only with a state badge once it is not `open`), `StatusCard`, `ResultCard`. Each assistant message
  with a `trace` has a native `<details>` "How I understood this".
- **Loading states:** "Thinking..." while a message is in flight; the confirming card shows "Submitting to ReqRes..." with both buttons disabled.
- **Errors:** network failure keeps the text in the composer and shows an inline error with Retry; `warning_code` shows a dismissible
  banner; a 409 on a card action reloads the conversation and shows "That card is out of date".
- **Keyboard:** Enter sends (not while an IME is composing), Shift+Enter adds a line, Escape closes the drawer, all controls have focus rings.

### Trying the chat without the backend

```bash
API_PORT=9191 STUB_ALLOWED_ORIGIN=http://127.0.0.1:9190 bun scripts/mock-api-stub.ts      # scripted chat API (in memory)
NUXT_PUBLIC_API_BASE=http://127.0.0.1:9191 NITRO_PORT=9190 NITRO_HOST=127.0.0.1 node .output/server/index.mjs   # after bun run build
```

Stub script (see the header of `scripts/mock-api-stub.ts`): "leave" asks once for the end date, then shows a confirmation card;
"claim"/"taxi" shows a claim card; "change"/"update" shows a diff card; "cancel" a cancel card; "status" a status card with 3 requests;
"fail" returns `warning_code: llm_unavailable`; "stale" makes the next confirm answer 409. `STUB_TURN_DELAY_MS` (default 900) slows message turns.

## Attachments (Phase 2b)

Employees can attach a medical certificate or a receipt to a message (contract: "Attachments (Phase 2b)" in `../docs/chat-api-contract.md`).

- **Adding files:** the paperclip button (labelled, keyboard operable), drag-and-drop onto the composer, or pasting an image (a pasted
  `image.png` is renamed `pasted-image-<time>.png`). Allowed: JPEG, PNG, WebP, HEIC, HEIF, PDF; **5 MB per file, 3 per message**. The client
  checks this first with plain messages (for example "clinic-note.pdf is 7.2 MB; the limit is 5 MB.", "notes.txt is not a supported file type...",
  "You can attach up to 3 files to one message."); the server re-validates. HEIC often has no browser MIME type, so the extension is used
  only when the browser gives none, and the upload is re-typed to match.
- **Staging:** each valid file appears as a removable chip above the input (image thumbnail from an object URL that is revoked when the
  chip goes away, or a PDF icon; name, size, spinner while uploading, Retry and Remove on error). Files upload immediately with
  `POST /api/chat/conversations/{id}/attachments` (multipart field `file`, cookie and `X-Requested-With` via `useApi`; no `Content-Type` is set by hand;
  the conversation is created first when needed). Upload errors 413/415/422/404/5xx are mapped to friendly text (server text is never echoed).
- **Sending:** `POST /messages` with `{content, attachment_ids}`; the text may be empty when a file is ready. Send is disabled while an upload is
  running or failed (retry or remove it, so no file is dropped silently). If the send fails, the text and the chips come back.
- **Message length** is counted on the trimmed text (the backend does the same); the counter shows it.
- **Thread:** user bubbles show image thumbnails (click for a preview dialog: `role="dialog"`, Escape closes, focus returns to the thumbnail) and PDF
  chips (open in a new tab). Files are loaded with `fetch` + credentials into a Blob and an object URL (`useAttachmentBlobs`, one download shared by
  every thumbnail of the same file, revoked when the last one unmounts), never with a plain `<img src>`. A 404 shows "File unavailable".
- **Card:** fields with `source: "document"` get a "from document" tag (icon and text), and `card.attachments` are listed as small thumbnails or
  chips under "Attached documents that will be sent to your approver with the request".
- **Code:** helpers in `app/utils/attachments.ts` (validation, sizes, MIME mapping, staged-file state machine), tests in `tests/attachments.test.ts`.

### Stub behaviour for attachments

`scripts/mock-api-stub.ts` stores uploads in memory (5 MB and type checks, owner-only download at `GET /api/attachments/{id}`) and reads them by
file name: "sick" or "medical" asks once for the last day of rest, then shows a leave card with `source: "document"` fields and the attachment;
"receipt" shows a claim card with a name-mismatch warning; "blurry" asks the user to type the details; any other file asks what to do with it.
A name containing "flaky" fails once with 500 (exercise Retry), "reject" answers 415. `STUB_UPLOAD_DELAY_MS` (default 700) and
`STUB_TURN_DELAY_MS` (default 900) keep the spinners visible.


## Phase 3: role-aware screens, approvals and the notification bell

Contract: `../docs/phase3-approval-design.md` (sections 1 to 5). The user object now carries `department {id,name}|null`,
`job_title|null`, `can_request` and `approves` (`"leave"|"claim"|null`); a missing field (older API) is read as null / false
(`normalizeUser` in `app/utils/auth.ts`).

### Who sees what

| Account (stub) | Role | `can_request` | `approves` | Header tabs | Lands on |
| --- | --- | --- | --- | --- | --- |
| Amy Lau, Ben Chow (IT), Daniel Wong (HR) | employee | yes | - | My requests | `/` (chat) |
| Cathy Ng (HR) | hr_approver | yes | leave | My requests, Approvals | `/` |
| Helen Yeung (HR manager) | hr_approver | no | leave | Approvals | `/approvals` |
| Eva Cheung (Finance) | finance_approver | no | claim | Approvals | `/approvals` |

Route rules are pure functions in `app/utils/access.ts` (`routeRedirect`, `homePath`, `navTabs`), used by the global middleware
`app/middleware/auth.global.ts`: `/` needs `can_request` (else redirect to `/approvals`), `/approvals*` needs `approves` (else
back to `/`), and a user with neither capability lands on `/no-access` (a friendly page with the header, so they can sign out; it
is used instead of `/login` because `/login` sends signed-in users home and would loop). The mock account chooser shows job title
and department under each name and scrolls inside the viewport (max height) so six accounts stay tidy, also at 360px.

### Screens

- **`/approvals`** - heading by scope ("Leave approvals" / "Claim approvals"); cards from `GET /api/approvals` (oldest first): employee,
  department, summary, submitted time, and flags "Over limit" (amber, icon), "N on leave in the team", "Has attachment". Empty state
  "Nothing waiting for you", loading, error with Retry, manual Refresh. Each card is one link to the detail (stretched link).
- **`/approvals/[type]/[id]`** - header (employee, department, status), amber `warnings`, request fields, attachments (reuses
  `AttachmentItem`/`AttachmentPreview`: image thumbnails and preview dialog, PDF opens in a new tab), a **Limits** panel
  (`ApprovalLimits`: leave balance lines or department budget with currency formatting, a labelled stacked bar (`LimitBar`,
  role="img" with the numbers in its label) and an over-limit notice; "No balance applies to personal or unpaid leave" when
  `leave_balance` is null), "Team on leave at the same time" (or "Nobody else in the team is on leave then"), and a **Reviewer note**
  textarea (max 500 characters with a counter, "Note for the employee (optional)"). **Approve** / **Reject** open a native-`<dialog>`
  confirmation (`role="alertdialog"`, focus starts on Cancel, Escape cancels, focus returns to the button) that summarises employee,
  request, decision and note and repeats the over-limit warning; while posting everything is disabled ("Approving..."). Body:
  `{"decision","note"}` with the note trimmed and empty sent as `null`. Success -> back to the list with a success notice (the item is
  gone); 409 -> "This request was already decided or changed. The list was reloaded."; 404 -> "This request is no longer available";
  other errors inline with Retry.
- **Notification bell** (`NotificationBell`, every signed-in user) - button with an unread badge (99+ cap), a polite live region with
  the count, and an accessible name that includes it. The popover is a non-modal `role="dialog"` (focus moves in, Escape and click
  outside close it and Escape returns focus to the bell, a route change closes it). Items show title, body (2 lines), relative time
  and an unread dot with visually-hidden "Unread". Clicking marks the item read (optimistic, rolled back on error) and either
  navigates to `link` (approvers) or opens a small dialog with the full title, body and time (requesters). "Mark all as read" calls
  `POST /api/notifications/read-all`. Everything is rendered as text, never HTML, and only in-app `link` paths are followed.
- **Polling** - one poll in `AppHeader` (`usePolling`): every 30 s and when the window regains focus, paused while the tab is hidden,
  never overlapping and never twice within 5 s. It refreshes the bell and, for approvers, the queue that feeds the Approvals tab
  badge and the list page (`useApprovalQueue`). A failed background poll keeps what is on screen. User-scoped state is cleared on
  sign-in and sign-out (`USER_SCOPED_STATE_KEYS`).
- **Chat additions** - `balance_card` messages (`BalanceCard`: leave type, entitled, approved, pending, remaining, with a bar), optional
  `info: [{label, value, tone}]` lines on confirmation cards above the buttons (plain strings are tolerated; `warning` is amber with an
  icon), the trace label for the `documents` step ("Read attached documents") with a readable fallback for unknown step names.

Code: pure helpers in `app/utils/{access,approvals,notifications,polling,chatExtras}.ts`, types in `app/types/{approvals,notifications}.ts`,
tests in `tests/{access,approvals,notifications,chat-additions}.test.ts`.

### Stub scenarios (Phase 3)

`scripts/mock-api-stub.ts` (ports 9190/9191 in the commands above) now serves the six users, `GET /api/approvals`,
`GET/POST /api/approvals/{type}/{id}[/decision]`, `GET /api/notifications`, `POST /api/notifications/{id}/read`,
`POST /api/notifications/read-all` and `GET /api/me/balances`, with the design's 403/404/409 rules.

- **Cathy** (leave, IT staff): leave #12 from Amy, annual, 5 days, **over the balance by 2 days**, team overlap with Ben (one approved, one pending).
- **Helen** (leave, HR staff): sick leave #14 from Daniel with a **PDF certificate**, within balance, nobody else away.
- **Eva** (claims): claim #9 from Amy, HKD 246.50, **over the IT budget**, with a receipt **image**.
- 20 s after an approver first looks (list or bell), one more item appears for them with a notification (Cathy: leave #15 from Ben; Helen: leave
  #16 from Cathy; Eva: claim #10 from Daniel). `STUB_NEW_ITEM_AFTER_MS` changes the delay.
- A decision moves the item out of the list and gives the requester a notification that includes the note; a second decision answers 409. To
  see the 409 path in the UI: open a detail, then `curl -X POST "localhost:9191/__stub/decide?type=leave&id=12&decision=approve"`, then press Approve.
- Notifications: Amy 1 unread (a rejection with a note), Ben 1 unread, Cathy 2 unread (one approver link, one requester message), Helen 1,
  Eva 1, Daniel none (empty bell). `POST /__stub/reset` re-seeds everything.
- Chat: "how many annual leave days do I have left?" -> `balance_card`; the leave card carries an info line and a warning line.
