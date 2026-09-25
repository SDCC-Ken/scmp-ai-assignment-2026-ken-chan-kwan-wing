# Frontend (Nuxt 4 + TypeScript + Tailwind CSS 4)

Runs on port 9180 (`WEB_PORT`). Env is read from the repo-root `../.env` if present; theme values use `NUXT_PUBLIC_THEME_*`.

- `bun install` - install dependencies
- `bun run dev` - dev server at http://localhost:9180
- `bun run lint` / `bun run lint:fix` - ESLint (`@nuxt/eslint`)
- `bun run typecheck` - `nuxt typecheck` (vue-tsc)
- `bun run test` - Vitest (theme, auth, access, approvals, notifications, inbox, chat and attachment utils, offline)
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
drawer below 768px), message thread and composer on the right. Since the bell inbox the chat is open to users who file requests **or**
approve something (`can_request` or `approves`); only a user with neither is sent away (`/no-access`). Helen and Eva (approve-only) see it as
an "Inbox" tab with a lighter empty state (no filing chips, "Use the bell to see what needs your attention", the composer stays for status
questions). Contract: `../docs/chat-api-contract.md`.

- **State and calls:** `app/composables/useChat.ts` (all requests go through `useApi`: cookie, `X-Requested-With` on POSTs, 401 sign-out).
  Pure helpers (status badges, relative time, message merge, card-state reconciliation, `canSend`, error mapping) live in
  `app/utils/chat.ts`; contract types in `app/types/chat.ts`; tests in `tests/chat.test.ts`.
- **Rendering:** every message is plain text (no `v-html`). Cards come from `message.ui`: `ConfirmationCard` (Submit/Discard, diff for
  `old_value`, amber warnings, read-only with a state badge once it is not `open`), `StatusCard`, `ResultCard` (its reference line reads a neutral "Reference: ...", since the offline fake adapter also returns one). Each assistant message
  with a `trace` has a native `<details>` "How I understood this".
- **Loading states:** "Thinking..." while a message is in flight; the confirming card shows "Submitting to ReqRes..." with both buttons disabled.
- **Errors:** network failure keeps the text in the composer and shows an inline error with Retry; `warning_code` shows a dismissible
  banner (for `llm_unavailable` / `llm_invalid_output` it also has **Try again**, which puts the failed message back in the composer and focuses it; the backend already stored it, so a real re-send would duplicate the bubble); a 409 on a card action reloads the conversation and shows "That card is out of date".
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
| Helen Yeung (HR manager) | hr_approver | no | leave | Inbox, Approvals | `/approvals` |
| Eva Cheung (Finance) | finance_approver | no | claim | Inbox, Approvals | `/approvals` |

Route rules are pure functions in `app/utils/access.ts` (`routeRedirect`, `homePath`, `navTabs`), used by the global middleware
`app/middleware/auth.global.ts`: `/` needs `can_request` or `approves` (`canUseChat`; the tab reads "My requests" for requesters and "Inbox" for
approve-only users), `/approvals*` needs `approves` (else
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
- **Notification bell** - see "Bell inbox" below (the old dropdown list, "Mark all as read" and the requester detail dialog are gone).
- **Polling** - one poll in `AppHeader` (`usePolling`): every 30 s and when the window regains focus, paused while the tab is hidden,
  never overlapping and never twice within 5 s. It refreshes the bell's unread number (`GET /api/notifications?limit=1`, only `unread_count` is used) and, for approvers, the queue that feeds the Approvals tab
  badge and the list page (`useApprovalQueue`). A failed background poll keeps what is on screen. User-scoped state is cleared on
  sign-in and sign-out (`USER_SCOPED_STATE_KEYS`).
- **Chat additions** - `balance_card` messages (`BalanceCard`: leave type, entitled, approved, pending, remaining, with a bar), optional
  `info: [{label, value, tone}]` lines on confirmation cards above the buttons (plain strings are tolerated; `warning` is amber with an
  icon), the trace label for the `documents` step ("Read attached documents") with a readable fallback for unknown step names.

Code: pure helpers in `app/utils/{access,approvals,notifications,polling,chatExtras,inbox}.ts`, types in `app/types/{approvals,notifications}.ts`,
tests in `tests/{access,approvals,notifications,chat-additions,inbox}.test.ts`.

## Bell inbox (handle everything waiting, one card at a time)

Spec: `../docs/inbox-design.md`. The bell (`NotificationBell`, every signed-in user) keeps its small unread number (99+ cap, polite live
region, the count in the accessible name) and now **creates a new conversation** when clicked:

- **Click:** `POST /api/chat/inbox` (CSRF header via `useApi`, `useInbox`). While it runs the bell is disabled with a spinner.
  `{"empty": true}` creates nothing: a small anchored notice "You are all caught up" (`role="status"`) closes after about 3 s, on Escape or on a
  click outside, with no navigation. Otherwise the conversation and its first assistant messages are handed to the chat (`useState('inbox-handoff')`,
  cleared on sign-in/sign-out), the app goes to `/` (from any page, also for approve-only users) and opens THAT conversation without another
  request; focus moves to the first card's heading. The badge is refreshed afterwards and after every handled card.
- **`inbox_card` messages** (`InboxCard`, types in `app/types/chat.ts`, helpers in `app/utils/inbox.ts`): header "Item 2 of 3", the title, then
  - kind `approval`: the same detail as the approvals screen through the shared `ApprovalDetailPanel` (also used by `/approvals/[type]/[id]`): warnings,
    limits (leave balance or department budget with the over-limit notice), fields, attachments with the existing preview, team overlap. Then a
    "Note for the employee (optional)" textarea (500 characters, counter) and **Approve / Reject / Skip**. Approve and Reject use an inline second step:
    the buttons become **Confirm approve** (or **Confirm reject**) and **Back**, repeating the over-limit warning; focus moves to Confirm and back to the
    button on Back. Only Confirm posts `{card_id, action, note, confirmed: true}` to `POST /api/chat/conversations/{id}/actions` (note trimmed, empty is
    `null`); Skip posts `{card_id, action: "skip"}`.
  - kind `notice`: title and body, **Got it** (`acknowledge`) and **Skip**.
  - While posting, that card shows a spinner, all its controls and the composer are disabled. On success the returned messages (result text, the next card
    or the closing summary) are appended, the acted card becomes `done` (badge Approved / Rejected / Got it) or `skipped`, `stale` shows "Already handled
    elsewhere", and focus moves to the next card's heading (or the composer after the closing message). Only the newest open inbox card is active; older
    cards are read-only (collapsed, "Show details" expands them).
  - Errors: 409 -> "That card is out of date" and a quiet reload of the conversation (the stored states, incl. a stale card and the next card, are shown);
    422 and 5xx inline with a fixed message; a network error keeps the note and offers Retry. Everything is plain text (no `v-html`).
- **Reopening:** an old inbox conversation loads with its cards in their stored states (the open card is active). The conversation list marks conversations whose
  title starts with "Items to handle" with an "Inbox" tag (and "Items waiting" instead of "Awaiting confirmation" while a card is open).
- **Code:** `app/composables/{useInbox,useChat,useNotifications}.ts`, `app/components/{NotificationBell,InboxCard,ApprovalDetailPanel}.vue`, tests in `tests/inbox.test.ts`.

### Stub scenarios: bell inbox

`POST /api/chat/inbox`, the inbox actions (`approve` / `reject` need `confirmed: true` else 422, `skip`, `acknowledge`) and per-conversation state live in the stub
(the chat API is open to approvers too; the scripted assistant refuses to file for Helen and Eva). The seed now has extra items so each user has something to see:

| User | Bell number | Inbox |
| --- | --- | --- |
| Cathy | 3 | 2 approvals: leave #12 (over the balance by 2 days, team overlap, PDF booking) and leave #13 (Ben, plain) + 1 notice (her own request approved) |
| Helen | 1 | 1 approval: sick leave #14 with a PDF |
| Eva | 2 | 2 claims: #9 (over the IT budget, receipt image) and #11 (Daniel, within the HR budget) |
| Amy | 1 | 1 notice (her leave #5 was rejected, with the note) |
| Ben, Daniel | 0 | empty: "You are all caught up" |

Deciding or acknowledging marks the related notifications read, so the number drops; skipped items stay unread and return on the next bell click. After the last
item the closing message reads "You handled N items and skipped M ...". **Stale path:** click the bell as Cathy, run
`curl -X POST "localhost:9191/__stub/decide?type=leave&id=12&decision=approve"`, then Approve and Confirm on the first card: the stub answers 409, marks the card
`stale`, and the next card is already in the conversation (the UI reloads it). `POST /__stub/reset` re-seeds everything; `STUB_NEW_ITEM_AFTER_MS` still injects one more
approval after 20 s (it appears at the next bell click).

### Stub scenarios (Phase 3)

`scripts/mock-api-stub.ts` (ports 9190/9191 in the commands above) now serves the six users, `GET /api/approvals`,
`GET/POST /api/approvals/{type}/{id}[/decision]`, `GET /api/notifications`, `POST /api/notifications/{id}/read`,
`POST /api/notifications/read-all` and `GET /api/me/balances`, with the design's 403/404/409 rules.

- **Cathy** (leave, IT staff): leave #12 from Amy, annual, 5 days, **over the balance by 2 days**, team overlap with Ben (one approved, one pending), a PDF booking;
  leave #13 from Ben, annual, 2 days, within the balance.
- **Helen** (leave, HR staff): sick leave #14 from Daniel with a **PDF certificate**, within balance, nobody else away.
- **Eva** (claims): claim #9 from Amy, HKD 246.50, **over the IT budget**, with a receipt **image**; claim #11 from Daniel, HKD 420.00, within the HR budget.
- 20 s after an approver first looks (list or bell), one more item appears for them with a notification (Cathy: leave #15 from Ben; Helen: leave
  #16 from Cathy; Eva: claim #10 from Daniel). `STUB_NEW_ITEM_AFTER_MS` changes the delay.
- A decision moves the item out of the list and gives the requester a notification that includes the note; a second decision answers 409. To
  see the 409 path in the UI: open a detail, then `curl -X POST "localhost:9191/__stub/decide?type=leave&id=12&decision=approve"`, then press Approve.
- Notifications: see the bell-inbox table above (Amy 1, Ben 0, Cathy 3, Helen 1, Eva 2, Daniel 0). `POST /__stub/reset` re-seeds everything.
- Chat: "how many annual leave days do I have left?" -> `balance_card`; the leave card carries an info line and a warning line.

## Dates and times

All dates and times are formatted by our own functions in `app/utils/chat.ts` (`formatDateTime`,
`formatClock`, `formatIsoDate`, `relativeTime`), never with `toLocaleString` or `Intl`. Output is
fixed, for example `25 Sep 2026, 11:05` (three-letter month, 24 hour clock, midnight is `00:05`) and is
always in Hong Kong time (UTC+8, no daylight saving), the zone the backend uses for "today". This keeps
the server render and the browser identical whatever the runtime's ICU data or time zone. Tests in
`tests/chat.test.ts` check every month, midnight, year and leap-day rollover, and four machine time zones.
