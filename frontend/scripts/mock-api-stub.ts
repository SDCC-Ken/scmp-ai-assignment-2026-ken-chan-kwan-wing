/**
 * DEV AID ONLY - a tiny stand-in for the backend auth contract on port 9181.
 * Run:  bun scripts/mock-api-stub.ts
 * Not used by tests, Docker or production; the real FastAPI backend replaces it.
 *
 * Contract (same as the FastAPI backend):
 *   POST /api/auth/mock-google/login {email} -> 200 {expires_in, user} + Set-Cookie scmp_session (HttpOnly, no token in body)
 *   GET  /api/auth/me                        -> user, authenticated from the cookie (401 otherwise)
 *   POST /api/auth/logout                    -> 204 and clears the cookie
 *   Every POST/PUT/PATCH/DELETE needs `X-Requested-With: XMLHttpRequest` (else 403 "CSRF check failed").
 *   CORS: explicit allowed origin + Access-Control-Allow-Credentials: true (credentials are used, so no "*").
 *
 * Chat endpoints (Phase 2, see docs/chat-api-contract.md; users who can_request OR approve, others get 403). A SCRIPTED flow, no LLM:
 *   text with "leave"   -> asks once for the end date; the next text -> confirmation_card (+ trace)
 *   text with "claim"/"taxi" -> confirmation_card for a claim;  "change"/"update" -> update card with a diff
 *   text with "cancel"  -> cancel card;  "yes"/"ok" while a card is open -> reminder to press the button
 *   text with "status"  -> status_card with 3 requests;  "fail" -> warning_code llm_unavailable
 *   text with "stale"   -> a leave card whose next confirm answers 409
 * Attachments (Phase 2b): POST /api/chat/conversations/{id}/attachments (multipart field "file", 5 MB, images or PDF; kept in memory),
 *   GET /api/attachments/{id} (owner only, returns the stored bytes), `attachment_ids` on messages.
 *   Attachment names drive the scripted reading: "sick"/"medical" -> asks once for the last day of rest, then a leave card with
 *   `source: "document"` fields and attachments; "receipt" -> claim card with a name-mismatch warning; "blurry" -> asks the user to
 *   type the details; any other file -> asks what to do with it. Upload names containing "flaky" fail once with 500 (Retry works),
 *   "reject" answers 415. STUB_UPLOAD_DELAY_MS (default 700) slows uploads so the spinner is visible.
 *   Message turns take STUB_TURN_DELAY_MS (default 900) and POST /actions confirm 1.5 s, so the loading states are visible.
 *   Data lives in memory only (reset by /__stub/reset or a restart).
 *
 * Phase 3 (see docs/phase3-approval-design.md, section 5). Six users: Amy Lau, Ben Chow (IT employees), Cathy Ng (HR approver for
 *   leave AND a requester), Daniel Wong (HR employee), Helen Yeung (HR manager, approves leave, cannot file), Eva Cheung (Finance,
 *   approves claims, cannot file). The chat needs `can_request` or `approves` (Helen and Eva can use it for the inbox); /api/approvals* needs `approves` (else 403); the request must be assigned
 *   to the caller and pending (else 404; a second decision answers 409).
 *   GET  /api/approvals, GET /api/approvals/{type}/{id}, POST /api/approvals/{type}/{id}/decision {decision, note}
 *   GET  /api/notifications?limit=20, POST /api/notifications/{id}/read, POST /api/notifications/read-all, GET /api/me/balances
 *   Seeded pending items: leave #12 (Amy, over the annual balance, team overlap with Ben) -> Cathy; sick leave #14 (Daniel, PDF
 *   certificate) -> Helen; claim #9 (Amy, over the IT budget, receipt image) -> Eva. 20 s after an approver's first list or
 *   notification call one more item appears for them (with a notification). A decision creates a notification for the requester.
 *   Chat: "how many annual leave days do I have left?" -> balance_card; leave cards carry `info` lines (one with tone warning).
 *
 * Bell inbox (see docs/inbox-design.md): the chat API is open to users who file OR approve (Helen and Eva can use it, but the scripted
 *   assistant refuses to file for them). POST /api/chat/inbox creates a conversation "Items to handle (N)" with an intro and the first
 *   inbox_card, or answers {empty:true, unread_count:0}. Per user: Cathy = 2 approvals (leave #12 over the balance, team overlap, PDF;
 *   leave #13 plain) + 1 notice; Helen = 1 approval; Eva = 2 claims (#9 over the IT budget, #11 within the HR budget); Amy = 1 notice;
 *   Ben and Daniel = empty. POST /actions takes {card_id, action: approve|reject|skip|acknowledge, note, confirmed}: approve/reject need
 *   confirmed:true (else 422), a card that is not the newest open one answers 409, a request decided elsewhere (see /__stub/decide below)
 *   marks the card `stale`, answers 409 and the next card is already in the conversation. Deciding marks the approver's notifications for
 *   that request read, so the bell number drops; skipped items stay unread.
 *
 * Extra dev endpoints (no CSRF header needed, so they work with plain curl):
 *   POST /__stub/expire  -> every later /api/auth/me returns 401 (cookie stays in the browser)
 *   POST /__stub/reset   -> clears that flag, the logout counter, all chat data, and re-seeds requests and notifications
 *   POST /__stub/decide?type=leave&id=12&decision=approve -> decide a request "elsewhere" (to see the 409 path in the UI)
 *   GET  /__stub/state   -> { expired, logouts }
 */
import { Buffer } from 'node:buffer'
import { createServer } from 'node:http'
import { deflateSync } from 'node:zlib'
import { setTimeout as sleep } from 'node:timers/promises'
import type { IncomingMessage } from 'node:http'
import process from 'node:process'

const PORT = Number(process.env.API_PORT) || 9181
const ORIGIN = process.env.STUB_ALLOWED_ORIGIN || 'http://localhost:9180'
const COOKIE_NAME = 'scmp_session'
const MAX_AGE = 3600
const TURN_DELAY_MS = Number(process.env.STUB_TURN_DELAY_MS ?? 900)
const UPLOAD_DELAY_MS = Number(process.env.STUB_UPLOAD_DELAY_MS ?? 700)
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'application/pdf']

type Role = 'employee' | 'hr_approver' | 'finance_approver'
interface StubUser {
  id: number
  email: string
  display_name: string
  role: Role
  department: { id: number, name: string }
  job_title: string
  can_request: boolean
  approves: 'leave' | 'claim' | null
}

const IT = { id: 1, name: 'IT' }
const HR = { id: 2, name: 'HR' }
const FINANCE = { id: 3, name: 'Finance' }

const USERS: StubUser[] = [
  { id: 1, email: 'amy.lau@example.com', display_name: 'Amy Lau', role: 'employee', department: IT, job_title: 'Senior Software Engineer', can_request: true, approves: null },
  { id: 2, email: 'ben.chow@example.com', display_name: 'Ben Chow', role: 'employee', department: IT, job_title: 'Frontend Developer', can_request: true, approves: null },
  { id: 3, email: 'cathy.ng@example.com', display_name: 'Cathy Ng', role: 'hr_approver', department: HR, job_title: 'HR Business Partner (IT)', can_request: true, approves: 'leave' },
  { id: 4, email: 'daniel.wong@example.com', display_name: 'Daniel Wong', role: 'employee', department: HR, job_title: 'HR Coordinator', can_request: true, approves: null },
  { id: 5, email: 'helen.yeung@example.com', display_name: 'Helen Yeung', role: 'hr_approver', department: HR, job_title: 'HR Manager', can_request: false, approves: 'leave' },
  { id: 6, email: 'eva.cheung@example.com', display_name: 'Eva Cheung', role: 'finance_approver', department: FINANCE, job_title: 'Finance Manager', can_request: false, approves: 'claim' },
]

let expired = false
let logouts = 0

function userFromCookie(header: string | undefined) {
  const pair = (header ?? '').split(';').map(p => p.trim()).find(p => p.startsWith(`${COOKIE_NAME}=`))
  const value = pair?.slice(COOKIE_NAME.length + 1) ?? ''
  if (!value.startsWith('stub.')) return undefined
  const email = Buffer.from(value.slice('stub.'.length), 'base64url').toString()
  return USERS.find(u => u.email === email)
}

/* ---- Chat (scripted, in memory) ------------------------------------------------------------------ */

type Json = Record<string, unknown>
type Send = (status: number, body?: unknown, extraHeaders?: Record<string, string>) => void

interface StubConversation {
  id: number
  owner: string
  title: string
  active_request_type: 'leave' | 'claim' | null
  has_pending_card: boolean
  created_at: string
  updated_at: string
  messages: Json[]
  awaitingEnd: boolean
  awaitingDocEnd: Json[] | null
  stale: boolean
  inFlight: Set<string>
  inbox: InboxState | null
}

interface InboxItem {
  kind: 'approval' | 'notice'
  type?: 'leave' | 'claim'
  requestId?: number
  notificationId?: number
  cardId: string
}

interface InboxState {
  items: InboxItem[]
  /** Index of the item whose card is open; equal to items.length once everything is handled. */
  index: number
  handled: number
  skipped: number
}

const conversations: StubConversation[] = []
let conversationSeq = 0
let messageSeq = 0
let cardSeq = 0
let requestSeq = 20

interface StoredAttachment {
  id: number
  owner: string
  conversationId: number
  filename: string
  content_type: string
  bytes: Buffer
  created_at: string
  used: boolean
}

const attachmentStore: StoredAttachment[] = []
let attachmentSeq = 0
const flakySeen = new Set<string>()

const attachmentInfo = (a: StoredAttachment) => ({
  id: a.id,
  filename: a.filename,
  content_type: a.content_type,
  size_bytes: a.bytes.length,
  url: `/api/attachments/${a.id}`,
  created_at: a.created_at,
})

const iso = () => new Date().toISOString()
const summary = (c: StubConversation) => ({
  id: c.id,
  title: c.title,
  status: 'active',
  active_request_type: c.active_request_type,
  has_pending_card: c.has_pending_card,
  created_at: c.created_at,
  updated_at: c.updated_at,
})

function step(key: string, label: string, detail: string, ok = true, duration_ms = 80 + Math.round(Math.random() * 500)) {
  return { step: key, label, detail, ok, duration_ms }
}

function push(c: StubConversation, sender: 'user' | 'assistant', content: string, ui: Json | null = null, trace: Json[] | null = null, attachments: Json[] = []): Json {
  const message = { id: ++messageSeq, sender_type: sender, content, created_at: iso(), ui, trace, attachments }
  c.messages.push(message)
  c.updated_at = message.created_at
  return message
}

function supersedeOpenCards(c: StubConversation) {
  for (const m of c.messages) {
    const ui = m.ui as Json | null
    if (ui?.type === 'confirmation_card' && ui.state === 'open') ui.state = 'superseded'
  }
}

function makeCard(c: StubConversation, kind: 'leave' | 'claim' | 'update' | 'cancel' | 'docleave' | 'docclaim', attachments: Json[] = []): Json {
  supersedeOpenCards(c)
  const base = { type: 'confirmation_card', card_id: `c_${(++cardSeq).toString(16).padStart(4, '0')}`, warnings: [] as string[], state: 'open', attachments }
  c.has_pending_card = true
  c.active_request_type = kind === 'claim' || kind === 'docclaim' ? 'claim' : 'leave'
  if (kind === 'docleave') {
    return { ...base, action: 'create', request_type: 'leave', request_id: null, title: 'Confirm leave application', confirm_label: 'Submit',
      info: [{ label: 'Sick leave balance 2026', value: '10 days, 1 used, 9 left; 6 left after this request (pending requests not counted)', tone: 'info' }],
      fields: [
      { key: 'employee_email', label: 'Employee', value: c.owner, old_value: null },
      { key: 'leave_type', label: 'Leave type', value: 'Sick', old_value: null, source: 'document' },
      { key: 'start_date', label: 'Start date', value: 'Mon 2026-09-21', old_value: null, source: 'document' },
      { key: 'end_date', label: 'End date', value: 'Wed 2026-09-23 (3 working days)', old_value: null },
    ] }
  }
  if (kind === 'docclaim') {
    return { ...base, action: 'create', request_type: 'claim', request_id: null, title: 'Confirm staff claim', confirm_label: 'Submit',
      warnings: ['The name on the receipt (Alex Chan) does not match your name (Amy Lau). Please check it is your receipt.'],
      fields: [
        { key: 'claim_type', label: 'Claim type', value: 'Meals', old_value: null, source: 'document' },
        { key: 'amount', label: 'Amount', value: 'HKD 246.50', old_value: null, source: 'document' },
        { key: 'receipt_date', label: 'Receipt date', value: 'Wed 2026-09-23', old_value: null, source: 'document' },
      ] }
  }
  if (kind === 'claim') {
    return { ...base, action: 'create', request_type: 'claim', request_id: null, title: 'Confirm staff claim', confirm_label: 'Submit', fields: [
      { key: 'claim_type', label: 'Claim type', value: 'Transport', old_value: null },
      { key: 'amount', label: 'Amount', value: 'HKD 180.00', old_value: null },
      { key: 'receipt_date', label: 'Receipt date', value: 'Thu 2026-09-24', old_value: null },
    ] }
  }
  if (kind === 'update') {
    return { ...base, action: 'update', request_type: 'leave', request_id: 12, title: 'Confirm changes to leave request #12', confirm_label: 'Save changes', fields: [
      { key: 'leave_type', label: 'Leave type', value: 'Sick', old_value: 'Annual' },
      { key: 'start_date', label: 'Start date', value: 'Mon 2026-10-05', old_value: 'Mon 2026-10-05' },
      { key: 'end_date', label: 'End date', value: 'Wed 2026-10-07', old_value: 'Tue 2026-10-06' },
    ], warnings: ['No public-holiday data for 2028; only weekends were excluded'] }
  }
  if (kind === 'cancel') {
    return { ...base, action: 'cancel', request_type: 'leave', request_id: 12, title: 'Cancel leave request #12?', confirm_label: 'Cancel request', fields: [
      { key: 'summary', label: 'Request', value: 'Annual leave, Mon 2026-10-05 to Wed 2026-10-07', old_value: null },
    ] }
  }
  return { ...base, action: 'create', request_type: 'leave', request_id: null, title: 'Confirm leave application', confirm_label: 'Submit',
    info: [
      { label: 'Annual leave balance 2026', value: '15 days, 3 used, 12 left; 10 left after this request (pending requests not counted)', tone: 'info' },
      { label: 'Heads-up', value: 'Ben Chow is also on leave on Tue 2026-10-06. Your approver will decide.', tone: 'warning' },
    ],
    fields: [
    { key: 'employee_email', label: 'Employee', value: c.owner, old_value: null },
    { key: 'leave_type', label: 'Leave type', value: 'Annual', old_value: null },
    { key: 'start_date', label: 'Start date', value: 'Mon 2026-10-05', old_value: null },
    { key: 'end_date', label: 'End date', value: 'Tue 2026-10-06 (2 working days)', old_value: null },
  ] }
}

const STATUS_REQUESTS = [
  { request_type: 'leave', id: 12, status: 'pending_approval', status_label: 'Pending approval', summary: 'Annual leave, Mon 2026-10-05 to Wed 2026-10-07 (2.5 working days)', submitted_at: '2026-09-24T03:10:00Z', reviewed_at: null, reviewer_note: null, external_reference_id: '23' },
  { request_type: 'claim', id: 8, status: 'approved', status_label: 'Approved', summary: 'Transport claim, HKD 95.00, receipt 2026-09-18', submitted_at: '2026-09-19T02:00:00Z', reviewed_at: '2026-09-21T08:30:00Z', reviewer_note: 'Approved. Thanks for the receipt.', external_reference_id: '17' },
  { request_type: 'leave', id: 5, status: 'rejected', status_label: 'Rejected', summary: 'Sick leave, 2026-09-08', submitted_at: '2026-09-08T01:00:00Z', reviewed_at: '2026-09-09T02:00:00Z', reviewer_note: 'Please attach a medical certificate and resubmit.', external_reference_id: '9' },
]

function handleText(c: StubConversation, text: string, attachments: Json[] = []): string | null {
  const lower = text.toLowerCase()
  const names = attachments.map(a => String(a.filename).toLowerCase()).join(' ')
  const has = (...words: string[]) => words.some(w => lower.includes(w))
  const trace = (...steps: Json[]) => steps
  const warning: string | null = null

  if (has('fail')) {
    push(c, 'assistant', 'Sorry, the AI service is not responding right now. Nothing was changed. Please try again.', null,
      trace(step('understand', 'Intent detection', 'Gemini request timed out', false, 8000)))
    return 'llm_unavailable'
  }
  if (has('status')) {
    push(c, 'assistant', 'Here are your requests.', { type: 'status_card', requests: STATUS_REQUESTS, empty: false },
      trace(step('understand', 'Intent detected', 'check_status (confidence 0.97)'), step('status', 'Looked up your requests', '3 found'), step('respond', 'Wrote the answer', 'status card')))
    return warning
  }
  const owner = USERS.find(u => u.email === c.owner)
  if (owner && !owner.can_request && has('leave', 'claim', 'taxi', 'change', 'update', 'cancel', 'balance', 'how many')) {
    push(c, 'assistant', 'I cannot file or change requests for you: no approver is set up for you, and your role is to approve. Use the bell to see what needs your attention, or ask me about the status of a request.', null,
      trace(step('understand', 'Intent detected', 'create_request (not allowed for this user)'), step('decide', 'Next step', 'explain and stop')))
    return warning
  }
  if (!attachments.length && !c.awaitingEnd && !c.awaitingDocEnd && (has('balance', 'how many') || (has('left') && has('leave')))) {
    push(c, 'assistant', 'Here is your leave balance for 2026.', {
      type: 'balance_card', year: 2026,
      lines: [
        { leave_type: 'annual', entitled_days: 15, approved_days: 3, pending_days: 2.5, remaining_days: 12 },
        { leave_type: 'sick', entitled_days: 10, approved_days: 1, pending_days: 0, remaining_days: 9 },
      ],
    }, trace(step('understand', 'Intent detected', 'check_balance (confidence 0.96)'), step('status', 'Looked up your balance', 'annual, sick'), step('respond', 'Wrote the answer', 'balance card')))
    return warning
  }
  if (attachments.length) {
    if (names.includes('blurry')) {
      push(c, 'assistant', 'I could not read that document clearly. Could you type the details instead, for example the type of leave and the dates, or the claim type, amount and receipt date?', null,
        trace(step('documents', 'Read attached documents', 'blurry-scan: text not legible', false, 2100), step('decide', 'Next step', 'ask the user to type the details')))
      return warning
    }
    if (names.includes('sick') || names.includes('medical')) {
      c.awaitingDocEnd = attachments
      c.active_request_type = 'leave'
      push(c, 'assistant', 'I read your medical certificate: sick leave starting Monday 2026-09-21. I could not find the last day of rest on the certificate. What is the last day of your leave?', null,
        trace(step('documents', 'Read attached documents', 'medical certificate (confidence 0.9)', true, 1900), step('merge', 'Collected from the document', 'leave_type, start_date'), step('validate', 'Missing fields', 'end_date', false), step('decide', 'Next step', 'ask a follow-up question')))
      return warning
    }
    if (names.includes('receipt')) {
      push(c, 'assistant', 'I read your receipt. Please check the details below and confirm.', makeCard(c, 'docclaim', attachments),
        trace(step('documents', 'Read attached documents', 'receipt: total, date, merchant', true, 1700), step('validate', 'Compared with your name', 'name on the receipt differs', false), step('decide', 'Next step', 'ask for confirmation')))
      return warning
    }
    push(c, 'assistant', 'I received the file. What would you like to do with it: apply for leave or submit a staff claim?', null,
      trace(step('understand', 'Read the attachment', 'unclear purpose', true, 900), step('decide', 'Next step', 'ask a follow-up question')))
    return warning
  }
  if (c.awaitingDocEnd) {
    const docs = c.awaitingDocEnd
    c.awaitingDocEnd = null
    push(c, 'assistant', 'Thanks. Here is the leave application, with the dates read from your certificate. Please check it and confirm.', makeCard(c, 'docleave', docs),
      trace(step('understand', 'Read your answer', 'end_date'), step('merge', 'Merged with the document', 'leave_type, start_date, end_date'), step('validate', 'Validated the fields', '3 working days, no overlap'), step('decide', 'Next step', 'ask for confirmation')))
    return warning
  }
  if (c.awaitingEnd) {
    c.awaitingEnd = false
    const card = makeCard(c, 'leave')
    push(c, 'assistant', 'Thanks. Please check the details below and confirm.', card,
      trace(step('understand', 'Intent detected', 'create_leave (confidence 0.92)'), step('merge', 'Merged with your earlier message', 'leave_type, start_date, end_date'), step('validate', 'Validated the fields', '2 working days, no overlap'), step('decide', 'Next step', 'ask for confirmation')))
    return warning
  }
  if (has('stale')) {
    c.stale = true
    push(c, 'assistant', 'I prepared this leave application. (Stub: confirming it will answer 409.)', makeCard(c, 'leave'),
      trace(step('understand', 'Intent detected', 'create_leave (confidence 0.9)'), step('decide', 'Next step', 'ask for confirmation')))
    return warning
  }
  const cardOpen = c.messages.some(m => (m.ui as Json | null)?.type === 'confirmation_card' && (m.ui as Json).state === 'open')
  if (cardOpen && /^\s*(yes|y|ok|okay|sure|confirm|submit)\b/.test(lower)) {
    push(c, 'assistant', 'Typing "yes" does not submit anything. Please press the Submit button on the card, or keep typing to change something.', null,
      trace(step('understand', 'Intent detected', 'confirm_by_text (ignored)'), step('decide', 'Next step', 'wait for the card button')))
    return warning
  }
  if (has('change', 'update')) {
    push(c, 'assistant', 'I can change request #12. Please review the highlighted differences.', makeCard(c, 'update'),
      trace(step('understand', 'Intent detected', 'update_request (confidence 0.88)'), step('validate', 'Checked request #12', 'still pending approval'), step('decide', 'Next step', 'ask for confirmation')))
    return warning
  }
  if (has('cancel')) {
    push(c, 'assistant', 'Do you want to cancel request #12?', makeCard(c, 'cancel'),
      trace(step('understand', 'Intent detected', 'cancel_request (confidence 0.9)'), step('decide', 'Next step', 'ask for confirmation')))
    return warning
  }
  if (has('claim', 'taxi')) {
    push(c, 'assistant', 'I have everything for this claim. Please check it and confirm.', makeCard(c, 'claim'),
      trace(step('understand', 'Intent detected', 'create_claim (confidence 0.95)'), step('validate', 'Validated the fields', 'amount 180.00, date in the past'), step('decide', 'Next step', 'ask for confirmation')))
    return warning
  }
  if (has('leave')) {
    c.awaitingEnd = true
    c.active_request_type = 'leave'
    push(c, 'assistant', 'Sure. What is the last day of your leave?', null,
      trace(step('understand', 'Intent detected', 'create_leave (confidence 0.92)'), step('merge', 'Collected so far', 'leave_type, start_date'), step('validate', 'Missing fields', 'end_date', false), step('decide', 'Next step', 'ask a follow-up question')))
    return warning
  }
  push(c, 'assistant', 'I can help you apply for leave, submit a staff claim, or check the status of your requests. What would you like to do?', null,
    trace(step('understand', 'Intent detected', 'unknown (confidence 0.4)'), step('respond', 'Wrote the answer', 'general help')))
  return warning
}

async function readJson(req: IncomingMessage): Promise<Json | null> {
  let raw = ''
  for await (const chunk of req) raw += chunk
  try {
    const parsed = JSON.parse(raw || 'null')
    return typeof parsed === 'object' && parsed !== null ? parsed as Json : null
  }
  catch {
    return null
  }
}

/** Reads the raw body, giving up (and draining) above `limit` bytes. */
async function readBuffer(req: IncomingMessage, limit: number): Promise<Buffer | null> {
  const chunks: Buffer[] = []
  let total = 0
  for await (const chunk of req) {
    total += chunk.length
    if (total > limit) continue // keep draining so the client gets our answer
    chunks.push(chunk as Buffer)
  }
  return total > limit ? null : Buffer.concat(chunks)
}

/** Minimal multipart parser: returns the `file` part (name, type, bytes) or null. */
function parseFilePart(body: Buffer, contentType: string): { filename: string, type: string, bytes: Buffer } | null {
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(contentType)
  const token = boundary?.[1] ?? boundary?.[2]
  if (!token) return null
  const delimiter = Buffer.from(`--${token}`)
  let start = body.indexOf(delimiter)
  while (start !== -1) {
    const headEnd = body.indexOf('\r\n\r\n', start)
    if (headEnd === -1) return null
    const head = body.subarray(start + delimiter.length, headEnd).toString('utf8')
    const next = body.indexOf(delimiter, headEnd)
    if (/name="file"/i.test(head) && next !== -1) {
      const filename = /filename="([^"]*)"/i.exec(head)?.[1] ?? ''
      const type = /content-type:\s*([^\r\n]+)/i.exec(head)?.[1]?.trim() ?? ''
      return { filename, type, bytes: body.subarray(headEnd + 4, next - 2) } // strip the CRLF before the next boundary
    }
    start = next
  }
  return null
}

async function handleUpload(req: IncomingMessage, c: StubConversation, owner: string, send: Send) {
  const body = await readBuffer(req, MAX_UPLOAD_BYTES + 64 * 1024)
  await sleep(UPLOAD_DELAY_MS)
  if (!body) return send(413, { detail: 'File too large' })
  const part = parseFilePart(body, String(req.headers['content-type'] ?? ''))
  if (!part || part.bytes.length === 0) return send(422, { detail: 'No file provided' })
  if (part.bytes.length > MAX_UPLOAD_BYTES) return send(413, { detail: 'File too large' })
  const name = part.filename.replace(/[\\/\r\n"]/g, '_').slice(0, 120) || 'file'
  if (!ALLOWED_TYPES.includes(part.type) || name.toLowerCase().includes('reject')) return send(415, { detail: 'Unsupported file type' })
  if (name.toLowerCase().includes('flaky') && !flakySeen.has(name)) {
    flakySeen.add(name) // fails once, so Retry can be exercised
    return send(500, { detail: 'Internal error' })
  }
  const stored: StoredAttachment = { id: ++attachmentSeq, owner, conversationId: c.id, filename: name, content_type: part.type, bytes: part.bytes, created_at: iso(), used: false }
  attachmentStore.push(stored)
  return send(201, { attachment: attachmentInfo(stored) })
}

/** Returns true when the request belonged to the chat API (and was answered). */
function handleChat(req: IncomingMessage, path: string, send: Send): boolean {
  const download = /^\/api\/attachments\/(\d+)$/.exec(path)
  if (!path.startsWith('/api/chat/') && !download) return false
  const user = expired ? undefined : userFromCookie(req.headers.cookie)
  if (!user) return send(401, { detail: 'Not authenticated' }), true
  if (download) {
    const file = attachmentStore.find(a => a.id === Number(download[1]) && (a.owner === user.email || approverMaySee(user, a.id)))
    if (!file || req.method !== 'GET') return send(404, { detail: 'Not found' }), true
    return send(200, file.bytes, {
      'content-type': file.content_type,
      'content-disposition': `inline; filename="${file.filename}"`,
      'x-content-type-options': 'nosniff',
      'cache-control': 'private, no-store',
    }), true
  }
  if (!user.can_request && !user.approves) return send(403, { detail: 'Forbidden' }), true

  const own = () => conversations.filter(c => c.owner === user.email).sort((a, b) => b.id - a.id)
  const method = req.method

  if (path === '/api/chat/inbox') {
    if (method !== 'POST') return send(405, { detail: 'Method not allowed' }), true
    void openInbox(user, send)
    return true
  }

  if (path === '/api/chat/conversations') {
    if (method === 'GET') return send(200, { items: own().sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id).map(summary) }), true
    if (method === 'POST') {
      const now = iso()
      const c: StubConversation = { id: ++conversationSeq, owner: user.email, title: 'New chat', active_request_type: null, has_pending_card: false, created_at: now, updated_at: now, messages: [], awaitingEnd: false, awaitingDocEnd: null, stale: false, inFlight: new Set(), inbox: null }
      conversations.push(c)
      return send(201, summary(c)), true
    }
    return send(405, { detail: 'Method not allowed' }), true
  }

  const match = /^\/api\/chat\/conversations\/(\d+)(\/messages|\/actions|\/attachments)?$/.exec(path)
  if (!match) return send(404, { detail: 'Not found' }), true
  const c = own().find(x => x.id === Number(match[1]))
  if (!c) return send(404, { detail: 'Conversation not found' }), true

  if (!match[2] && method === 'GET') return send(200, { conversation: summary(c), messages: c.messages }), true

  if (match[2] === '/attachments' && method === 'POST') {
    void handleUpload(req, c, user.email, send)
    return true
  }

  if (match[2] === '/messages' && method === 'POST') {
    void readJson(req).then(async (body) => {
      await sleep(TURN_DELAY_MS) // makes the "Thinking..." indicator visible
      const content = typeof body?.content === 'string' ? body.content.trim() : ''
      const ids = Array.isArray(body?.attachment_ids) ? body.attachment_ids as unknown[] : []
      const files = ids.map(id => attachmentStore.find(a => a.id === id && a.owner === user.email && a.conversationId === c.id && !a.used))
      if (ids.length > 3 || files.some(f => !f)) return send(422, { detail: 'invalid attachment_ids' })
      if ((!content && !files.length) || content.length > 1000) return send(422, { detail: 'content must be 1 to 1000 characters' })
      const stored = files as StoredAttachment[]
      for (const f of stored) f.used = true
      const infos = stored.map(attachmentInfo)
      const before = c.messages.length
      const userMessage = push(c, 'user', content, null, null, infos)
      if (before === 0) c.title = (content || `Attachment: ${infos[0]?.filename ?? 'file'}`).slice(0, 60)
      const warning = handleText(c, content, infos)
      return send(200, { conversation: summary(c), user_message: userMessage, assistant_messages: c.messages.slice(before + 1), warning_code: warning })
    })
    return true
  }

  if (match[2] === '/actions' && method === 'POST') {
    void readJson(req).then(async (body) => {
      const cardId = typeof body?.card_id === 'string' ? body.card_id : ''
      const action = body?.action
      if (typeof action === 'string' && INBOX_ACTIONS.includes(action)) {
        await sleep(600) // keeps the card's loading state visible
        return handleInboxAction(c, user, cardId, action, body ?? {}, send)
      }
      if (!cardId || (action !== 'confirm' && action !== 'discard')) return send(422, { detail: 'invalid action' })
      const holder = c.messages.find(m => (m.ui as Json | null)?.card_id === cardId)
      const card = holder?.ui as Json | undefined
      if (!card) return send(404, { detail: 'Card not found' })
      if (c.stale && card.state === 'open') {
        c.stale = false
        card.state = 'superseded'
        c.has_pending_card = false
        c.active_request_type = null
        return send(409, { detail: 'Card is no longer open' })
      }
      if (card.state !== 'open' || c.inFlight.has(cardId)) return send(409, { detail: 'Card is no longer open' })
      if (action === 'discard') {
        card.state = 'discarded'
        c.has_pending_card = false
        c.active_request_type = null
        push(c, 'assistant', 'Okay, I discarded that. Nothing was submitted.')
        return send(200, { conversation: summary(c), user_message: null, assistant_messages: c.messages.slice(-1), warning_code: null })
      }
      c.inFlight.add(cardId)
      await sleep(1500) // stands in for the ReqRes call
      c.inFlight.delete(cardId)
      card.state = 'used'
      c.has_pending_card = false
      c.active_request_type = null
      const requestType = card.request_type as string
      const outcome = card.action === 'cancel' ? 'cancelled' : card.action === 'update' ? 'updated' : 'submitted'
      const id = card.request_id ?? ++requestSeq
      const message = outcome === 'submitted'
        ? `Submitted to the ReqRes mock API (reference ${100 + id}).`
        : outcome === 'updated' ? 'Your changes were saved.' : 'The request was cancelled.'
      push(c, 'assistant', outcome === 'cancelled' ? 'Done, the request is cancelled.' : 'Done. Your request is with the approver now.', {
        type: 'result_card', outcome, request_type: requestType, request_id: id,
        status: outcome === 'cancelled' ? 'cancelled' : 'pending_approval', status_label: outcome === 'cancelled' ? 'Cancelled' : 'Pending approval',
        message, external_reference_id: outcome === 'submitted' ? String(100 + id) : null,
      }, [step('submit', 'Sent to ReqRes', 'POST /api/users 201', true, 1480), step('respond', 'Wrote the answer', 'result card')])
      return send(200, { conversation: summary(c), user_message: null, assistant_messages: c.messages.slice(-1), warning_code: null })
    })
    return true
  }

  return send(405, { detail: 'Method not allowed' }), true
}

/* ---- Phase 3: approvals, notifications, balances (in memory, re-seeded by /__stub/reset) -------------------------- */

interface StubRequest {
  type: 'leave' | 'claim'
  id: number
  employeeId: number
  approverId: number
  status: 'pending_approval' | 'approved' | 'rejected'
  submitted_at: string
  summary: string
  fields: { key: string, label: string, value: string }[]
  attachmentIds: number[]
  external_reference_id: string
  limits: Json
  team_overlap: Json[]
  warnings: string[]
  over_limit: boolean
  reviewer_note: string | null
  reviewed_at: string | null
}

interface StubNotification {
  id: number
  userId: number
  event_type: string
  title: string
  body: string
  request_type: 'leave' | 'claim' | null
  request_id: number | null
  read_at: string | null
  created_at: string
  link: string | null
}

const requests: StubRequest[] = []
const notifications: StubNotification[] = []
const firstSeen = new Map<string, number>()
const injected = new Set<string>()
let notificationSeq = 0
const NEW_ITEM_AFTER_MS = Number(process.env.STUB_NEW_ITEM_AFTER_MS ?? 20_000)

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString()
const userById = (id: number) => USERS.find(u => u.id === id)!
const employeeOf = (r: StubRequest) => {
  const u = userById(r.employeeId)
  return { id: u.id, display_name: u.display_name, department: u.department.name }
}

/** A tiny PNG "receipt" (drawn with zlib + a hand-made CRC) and a one-page PDF certificate, so thumbnails and the PDF tab work. */
function crc32(buf: Buffer): number {
  let c = ~0
  for (const byte of buf) {
    c ^= byte
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xEDB88320 : c >>> 1
  }
  return ~c >>> 0
}

function makePng(width: number, height: number): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const head = Buffer.alloc(4)
    head.writeUInt32BE(data.length)
    const body = Buffer.concat([Buffer.from(type), data])
    const tail = Buffer.alloc(4)
    tail.writeUInt32BE(crc32(body))
    return Buffer.concat([head, body, tail])
  }
  const rows: Buffer[] = []
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3, 0xFF)
    row[0] = 0
    const line = y > 24 && y < height - 16 && y % 14 < 3
    const banner = y < 20
    for (let x = 0; x < width; x++) {
      const inside = x > 16 && x < width - 16
      const value = banner ? [30, 64, 175] : line && inside ? [148, 163, 184] : [255, 255, 255]
      row[1 + x * 3] = value[0]!
      row[2 + x * 3] = value[1]!
      row[3 + x * 3] = value[2]!
    }
    rows.push(row)
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 2
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(Buffer.concat(rows))), chunk('IEND', Buffer.alloc(0))])
}

function makePdf(text: string): Buffer {
  const stream = `BT /F1 16 Tf 30 130 Td (${text}) Tj 0 -24 Td (Fictional demo document) Tj ET`
  const objects = [
    '<</Type/Catalog/Pages 2 0 R>>',
    '<</Type/Pages/Kids[3 0 R]/Count 1>>',
    '<</Type/Page/Parent 2 0 R/MediaBox[0 0 320 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>',
    `<</Length ${stream.length}>>\nstream\n${stream}\nendstream`,
    '<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>',
  ]
  let out = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, i) => {
    offsets.push(out.length)
    out += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = out.length
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map(o => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
  out += `trailer\n<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out)
}

const SEED_PDF_ID = 901
const SEED_PNG_ID = 902
const SEED_BOOKING_ID = 903

function seedAttachments() {
  const seeds: [number, string, string, string, Buffer][] = [
    [SEED_PDF_ID, 'daniel.wong@example.com', 'clinic-medical-certificate.pdf', 'application/pdf', makePdf('Medical certificate: 2 days rest')],
    [SEED_PNG_ID, 'amy.lau@example.com', 'team-dinner-receipt.png', 'image/png', makePng(240, 160)],
    [SEED_BOOKING_ID, 'amy.lau@example.com', 'flight-booking.pdf', 'application/pdf', makePdf('Flight booking: 12 to 16 Oct')],
  ]
  for (const [id, owner, filename, type, bytes] of seeds) {
    if (!attachmentStore.some(a => a.id === id)) {
      attachmentStore.push({ id, owner, conversationId: 0, filename, content_type: type, bytes, created_at: ago(60), used: true })
    }
  }
}

function approverMaySee(user: StubUser, attachmentId: number): boolean {
  return requests.some(r => r.approverId === user.id && r.attachmentIds.includes(attachmentId))
}

function notify(userId: number, eventType: string, title: string, body: string, request: StubRequest | null, link: string | null, read = false, createdAgo = 0) {
  notifications.push({
    id: ++notificationSeq, userId, event_type: eventType, title, body,
    request_type: request?.type ?? null, request_id: request?.id ?? null,
    read_at: read ? ago(createdAgo) : null, created_at: ago(createdAgo), link,
  })
}

function seedRequests() {
  requests.length = 0
  notifications.length = 0
  notificationSeq = 0
  firstSeen.clear()
  injected.clear()

  const leave12: StubRequest = {
    type: 'leave', id: 12, employeeId: 1, approverId: 3, status: 'pending_approval', submitted_at: ago(2 * 24 * 60),
    summary: 'Annual leave, Mon 2026-10-12 to Fri 2026-10-16 (5 working days)',
    fields: [
      { key: 'leave_type', label: 'Leave type', value: 'Annual' },
      { key: 'start_date', label: 'Start date', value: 'Mon 2026-10-12' },
      { key: 'end_date', label: 'End date', value: 'Fri 2026-10-16' },
      { key: 'working_days', label: 'Working days', value: '5' },
    ],
    attachmentIds: [SEED_BOOKING_ID], external_reference_id: '531',
    limits: { leave_balance: { leave_type: 'annual', year: 2026, entitled_days: 15, approved_days: 12, pending_other_days: 0, requested_days: 5, remaining_after_days: -2, over_limit: true }, department_budget: null },
    team_overlap: [
      { employee: 'Ben Chow', leave_type: 'annual', start_date: '2026-10-14', end_date: '2026-10-15', status: 'approved', working_days: 2 },
      { employee: 'Ben Chow', leave_type: 'personal', start_date: '2026-10-16', end_date: '2026-10-16', status: 'pending_approval', working_days: 1 },
    ],
    warnings: ['Over the annual leave balance by 2 days. You decide.'],
    over_limit: true, reviewer_note: null, reviewed_at: null,
  }
  const leave14: StubRequest = {
    type: 'leave', id: 14, employeeId: 4, approverId: 5, status: 'pending_approval', submitted_at: ago(6 * 60),
    summary: 'Sick leave, Thu 2026-09-24 to Fri 2026-09-25 (2 working days)',
    fields: [
      { key: 'leave_type', label: 'Leave type', value: 'Sick' },
      { key: 'start_date', label: 'Start date', value: 'Thu 2026-09-24' },
      { key: 'end_date', label: 'End date', value: 'Fri 2026-09-25' },
      { key: 'working_days', label: 'Working days', value: '2' },
    ],
    attachmentIds: [SEED_PDF_ID], external_reference_id: '540',
    limits: { leave_balance: { leave_type: 'sick', year: 2026, entitled_days: 10, approved_days: 1, pending_other_days: 0, requested_days: 2, remaining_after_days: 7, over_limit: false }, department_budget: null },
    team_overlap: [], warnings: [], over_limit: false, reviewer_note: null, reviewed_at: null,
  }
  const claim9: StubRequest = {
    type: 'claim', id: 9, employeeId: 1, approverId: 6, status: 'pending_approval', submitted_at: ago(26 * 60),
    summary: 'Meals claim, HKD 246.50, receipt 2026-09-23',
    fields: [
      { key: 'claim_type', label: 'Claim type', value: 'Meals' },
      { key: 'amount', label: 'Amount', value: 'HKD 246.50' },
      { key: 'receipt_date', label: 'Receipt date', value: 'Wed 2026-09-23' },
    ],
    attachmentIds: [SEED_PNG_ID], external_reference_id: '533',
    limits: { leave_balance: null, department_budget: { department: 'IT', year: 2026, limit_amount: '60000.00', approved_amount: '59900.00', pending_other_amount: '300.00', requested_amount: '246.50', remaining_after_amount: '-146.50', over_limit: true, currency: 'HKD' } },
    team_overlap: [], warnings: ['Over the IT department claim limit by HKD 146.50. You decide.'],
    over_limit: true, reviewer_note: null, reviewed_at: null,
  }
  const leave13: StubRequest = {
    type: 'leave', id: 13, employeeId: 2, approverId: 3, status: 'pending_approval', submitted_at: ago(3 * 60),
    summary: 'Annual leave, Tue 2026-10-27 to Wed 2026-10-28 (2 working days)',
    fields: leaveFields('Annual', 'Tue 2026-10-27', 'Wed 2026-10-28', 2),
    attachmentIds: [], external_reference_id: '545',
    limits: { leave_balance: { leave_type: 'annual', year: 2026, entitled_days: 15, approved_days: 4, pending_other_days: 0, requested_days: 2, remaining_after_days: 9, over_limit: false }, department_budget: null },
    team_overlap: [], warnings: [], over_limit: false, reviewer_note: null, reviewed_at: null,
  }
  const claim11: StubRequest = {
    type: 'claim', id: 11, employeeId: 4, approverId: 6, status: 'pending_approval', submitted_at: ago(4 * 60),
    summary: 'Training claim, HKD 420.00, receipt 2026-09-22',
    fields: [{ key: 'claim_type', label: 'Claim type', value: 'Training' }, { key: 'amount', label: 'Amount', value: 'HKD 420.00' }, { key: 'receipt_date', label: 'Receipt date', value: 'Tue 2026-09-22' }],
    attachmentIds: [], external_reference_id: '546',
    limits: { leave_balance: null, department_budget: { department: 'HR', year: 2026, limit_amount: '30000.00', approved_amount: '12000.00', pending_other_amount: '0.00', requested_amount: '420.00', remaining_after_amount: '17580.00', over_limit: false, currency: 'HKD' } },
    team_overlap: [], warnings: [], over_limit: false, reviewer_note: null, reviewed_at: null,
  }
  requests.push(leave12, leave13, leave14, claim9, claim11)

  notify(3, 'request.submitted', 'New leave request from Amy Lau', leave12.summary, leave12, '/approvals/leave/12', false, 2 * 24 * 60)
  notify(3, 'request.approved', 'Your leave request #3 was approved', 'Annual leave, Mon 2026-08-03 to Tue 2026-08-04. Note from Helen Yeung: "Enjoy the break."', null, null, false, 5 * 60)
  notify(3, 'request.submitted', 'New leave request from Ben Chow', leave13.summary, leave13, '/approvals/leave/13', false, 3 * 60)
  notify(5, 'request.submitted', 'New leave request from Daniel Wong', leave14.summary, leave14, '/approvals/leave/14', false, 6 * 60)
  notify(6, 'request.submitted', 'New claim from Amy Lau', claim9.summary, claim9, '/approvals/claim/9', false, 26 * 60)
  notify(6, 'request.submitted', 'New claim from Daniel Wong', claim11.summary, claim11, '/approvals/claim/11', false, 4 * 60)
  notify(6, 'request.submitted', 'New claim from Ben Chow', 'Transport claim, HKD 95.00, receipt 2026-09-18', null, null, true, 5 * 24 * 60)
  notify(1, 'request.rejected', 'Your leave request #5 was rejected', 'Sick leave, 2026-09-08. Note from Cathy Ng: "Please attach a medical certificate and resubmit."', null, null, false, 90)
  notify(1, 'request.approved', 'Your claim #8 was approved', 'Transport claim, HKD 95.00, receipt 2026-09-18', null, null, true, 3 * 24 * 60)
  notify(2, 'request.approved', 'Your leave request #7 was approved', 'Annual leave, Mon 2026-09-14 to Tue 2026-09-15. Note from Cathy Ng: "Approved, have a good trip."', null, null, true, 30)
  // Ben (2) and Daniel (4) have nothing unread on purpose: the bell's "all caught up" state.
}

const leaveFields = (type: string, start: string, end: string, days: number) => [
  { key: 'leave_type', label: 'Leave type', value: type },
  { key: 'start_date', label: 'Start date', value: start },
  { key: 'end_date', label: 'End date', value: end },
  { key: 'working_days', label: 'Working days', value: String(days) },
]

/** 20 s after an approver first looks, one more request lands in their queue (with a notification). */
function tick(user: StubUser) {
  if (!user.approves) return
  if (!firstSeen.has(user.email)) firstSeen.set(user.email, Date.now())
  if (injected.has(user.email) || Date.now() - firstSeen.get(user.email)! < NEW_ITEM_AFTER_MS) return
  injected.add(user.email)
  const now = iso()
  const none = { attachmentIds: [] as number[], reviewer_note: null, reviewed_at: null, team_overlap: [] as Json[], warnings: [] as string[], over_limit: false, status: 'pending_approval' as const, submitted_at: now }
  const balance = (approved: number, requested: number) => ({ leave_balance: { leave_type: 'annual', year: 2026, entitled_days: 15, approved_days: approved, pending_other_days: 0, requested_days: requested, remaining_after_days: 15 - approved - requested, over_limit: false }, department_budget: null })
  let item: StubRequest | undefined
  if (user.id === 3) {
    item = { ...none, type: 'leave', id: 15, employeeId: 2, approverId: 3, summary: 'Annual leave, Mon 2026-11-02 to Tue 2026-11-03 (2 working days)', fields: leaveFields('Annual', 'Mon 2026-11-02', 'Tue 2026-11-03', 2), external_reference_id: '551', limits: balance(4, 2) }
  }
  else if (user.id === 5) {
    item = { ...none, type: 'leave', id: 16, employeeId: 3, approverId: 5, summary: 'Annual leave, Mon 2026-10-19 to Tue 2026-10-20 (2 working days)', fields: leaveFields('Annual', 'Mon 2026-10-19', 'Tue 2026-10-20', 2), external_reference_id: '552', limits: balance(6, 2) }
  }
  else if (user.id === 6) {
    item = {
      ...none, type: 'claim', id: 10, employeeId: 4, approverId: 6, summary: 'Transport claim, HKD 180.00, receipt 2026-09-24', external_reference_id: '553',
      fields: [{ key: 'claim_type', label: 'Claim type', value: 'Transport' }, { key: 'amount', label: 'Amount', value: 'HKD 180.00' }, { key: 'receipt_date', label: 'Receipt date', value: 'Thu 2026-09-24' }],
      limits: { leave_balance: null, department_budget: { department: 'HR', year: 2026, limit_amount: '30000.00', approved_amount: '12000.00', pending_other_amount: '0.00', requested_amount: '180.00', remaining_after_amount: '17820.00', over_limit: false, currency: 'HKD' } },
    }
  }
  if (!item) return
  requests.push(item)
  const who = userById(item.employeeId).display_name
  notify(user.id, 'request.submitted', item.type === 'leave' ? `New leave request from ${who}` : `New claim from ${who}`, item.summary, item, `/approvals/${item.type}/${item.id}`)
}

const listItem = (r: StubRequest) => ({
  request_type: r.type, id: r.id, employee: employeeOf(r), summary: r.summary, submitted_at: r.submitted_at,
  flags: { over_limit: r.over_limit, team_overlap_count: r.team_overlap.length, has_attachments: r.attachmentIds.length > 0 },
})

const detailOf = (r: StubRequest) => ({
  request: {
    request_type: r.type, id: r.id, status: r.status, submitted_at: r.submitted_at, employee: employeeOf(r), fields: r.fields,
    attachments: r.attachmentIds.map(id => attachmentInfo(attachmentStore.find(a => a.id === id)!)), external_reference_id: r.external_reference_id,
  },
  limits: r.limits, team_overlap: r.team_overlap, warnings: r.warnings,
})

/** The approver's own notifications about this request are handled once it is decided (the bell number drops). */
function markRequestRead(user: StubUser, r: StubRequest) {
  for (const n of notifications) {
    if (n.userId === user.id && n.request_type === r.type && n.request_id === r.id) n.read_at ??= iso()
  }
}

function decide(r: StubRequest, decision: 'approve' | 'reject', note: string | null, by: StubUser) {
  markRequestRead(by, r)
  r.status = decision === 'approve' ? 'approved' : 'rejected'
  r.reviewed_at = iso()
  r.reviewer_note = note
  const noun = r.type === 'leave' ? 'leave request' : 'claim'
  notify(r.employeeId, `request.${r.status}`, `Your ${noun} #${r.id} was ${r.status}`,
    `${r.summary}.${note ? ` Note from ${by.display_name}: "${note}"` : ''}`, null, null)
}

/** Returns true when the request belonged to the Phase 3 API (and was answered). */
function handleApprovals(req: IncomingMessage, path: string, query: URLSearchParams, send: Send): boolean {
  const isApprovals = path === '/api/approvals' || path.startsWith('/api/approvals/')
  const isNotifications = path === '/api/notifications' || path.startsWith('/api/notifications/')
  const isBalances = path === '/api/me/balances'
  if (!isApprovals && !isNotifications && !isBalances) return false
  const user = expired ? undefined : userFromCookie(req.headers.cookie)
  if (!user) return send(401, { detail: 'Not authenticated' }), true
  const method = req.method

  if (isBalances) {
    if (!user.can_request) return send(403, { detail: 'Forbidden' }), true
    return send(200, { year: 2026, leave: [
      { leave_type: 'annual', entitled_days: 15, approved_days: 3, pending_days: 2.5, remaining_days: 12 },
      { leave_type: 'sick', entitled_days: 10, approved_days: 1, pending_days: 0, remaining_days: 9 },
    ] }), true
  }

  if (isNotifications) {
    tick(user)
    const mine = notifications.filter(n => n.userId === user.id).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id)
    if (path === '/api/notifications' && method === 'GET') {
      const limit = Math.min(100, Math.max(1, Number(query.get('limit')) || 20))
      const view = (n: StubNotification) => ({ id: n.id, event_type: n.event_type, title: n.title, body: n.body, request_type: n.request_type, request_id: n.request_id, read_at: n.read_at, created_at: n.created_at, link: n.link })
      return send(200, { items: mine.slice(0, limit).map(view), unread_count: mine.filter(n => !n.read_at).length }), true
    }
    if (path === '/api/notifications/read-all' && method === 'POST') {
      for (const n of mine) n.read_at ??= iso()
      return send(204), true
    }
    const one = /^\/api\/notifications\/(\d+)\/read$/.exec(path)
    if (one && method === 'POST') {
      const n = mine.find(x => x.id === Number(one[1]))
      if (!n) return send(404, { detail: 'Not found' }), true
      n.read_at ??= iso()
      return send(204), true
    }
    return send(404, { detail: 'Not found' }), true
  }

  if (!user.approves) return send(403, { detail: 'Forbidden' }), true
  tick(user)
  if (path === '/api/approvals' && method === 'GET') {
    const queue = requests.filter(r => r.approverId === user.id && r.type === user.approves && r.status === 'pending_approval')
      .sort((a, b) => Date.parse(a.submitted_at) - Date.parse(b.submitted_at) || a.id - b.id)
    return send(200, { items: queue.map(listItem), count: queue.length }), true
  }
  const match = /^\/api\/approvals\/(leave|claim)\/(\d+)(\/decision)?$/.exec(path)
  if (!match) return send(404, { detail: 'Not found' }), true
  const found = requests.find(r => r.type === match[1] && r.id === Number(match[2]) && r.approverId === user.id && r.type === user.approves)
  if (!found) return send(404, { detail: 'Not found' }), true

  if (!match[3] && method === 'GET') {
    return found.status === 'pending_approval' ? send(200, detailOf(found)) : send(404, { detail: 'Not found' }), true
  }
  if (match[3] && method === 'POST') {
    void readJson(req).then(async (body) => {
      await sleep(600) // keeps the "posting" state visible
      const decision = body?.decision
      const note = body?.note ?? null
      if ((decision !== 'approve' && decision !== 'reject') || (note !== null && (typeof note !== 'string' || note.length > 500))) {
        return send(422, { detail: 'invalid decision' })
      }
      if (found.status !== 'pending_approval') return send(409, { detail: 'Request is no longer pending' })
      decide(found, decision, note, user)
      return send(200, { request_type: found.type, id: found.id, status: found.status, reviewed_at: found.reviewed_at })
    })
    return true
  }
  return send(405, { detail: 'Method not allowed' }), true
}


/* ---- Bell inbox (docs/inbox-design.md) ------------------------------------------------------------------------------ */

const INBOX_ACTIONS = ['approve', 'reject', 'skip', 'acknowledge']

const unreadOf = (user: StubUser) => notifications.filter(n => n.userId === user.id && !n.read_at).length

/** Approvals first (oldest first), then the other unread notifications; a still-pending request's "submitted" notice is covered by its card. */
function buildInboxItems(user: StubUser): InboxItem[] {
  const queue = user.approves
    ? requests.filter(r => r.approverId === user.id && r.type === user.approves && r.status === 'pending_approval')
        .sort((a, b) => Date.parse(a.submitted_at) - Date.parse(b.submitted_at) || a.id - b.id)
    : []
  const covered = new Set(queue.map(r => `${r.type}:${r.id}`))
  const notices = notifications
    .filter(n => n.userId === user.id && !n.read_at
      && !(['request.submitted', 'request.updated'].includes(n.event_type) && n.request_type && covered.has(`${n.request_type}:${n.request_id}`)))
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id)
  return [
    ...queue.map((r): InboxItem => ({ kind: 'approval', type: r.type, requestId: r.id, cardId: `i_${(++cardSeq).toString(16).padStart(4, '0')}` })),
    ...notices.map((n): InboxItem => ({ kind: 'notice', notificationId: n.id, cardId: `i_${(++cardSeq).toString(16).padStart(4, '0')}` })),
  ]
}

function inboxCardUi(item: InboxItem, index: number, total: number): Json {
  const base = { type: 'inbox_card', card_id: item.cardId, position: { index: index + 1, total }, state: 'open', outcome: null }
  if (item.kind === 'approval') {
    const r = requests.find(x => x.type === item.type && x.id === item.requestId)!
    const who = userById(r.employeeId).display_name
    return { ...base, kind: 'approval', title: `${r.type === 'leave' ? 'Leave request' : 'Claim'} #${r.id} from ${who}`, request_type: r.type, request_id: r.id,
      detail: detailOf(r), notice: null, actions: ['approve', 'reject', 'skip'] }
  }
  const n = notifications.find(x => x.id === item.notificationId)!
  return { ...base, kind: 'notice', title: n.title, request_type: n.request_type, request_id: n.request_id,
    detail: null, notice: { title: n.title, body: n.body }, actions: ['acknowledge', 'skip'] }
}

async function openInbox(user: StubUser, send: Send) {
  await sleep(700) // keeps the bell's spinner visible
  const items = buildInboxItems(user)
  if (!items.length) return send(200, { empty: true, unread_count: unreadOf(user) })
  const now = iso()
  const c: StubConversation = { id: ++conversationSeq, owner: user.email, title: `Items to handle (${items.length})`, active_request_type: null, has_pending_card: true, created_at: now, updated_at: now, messages: [], awaitingEnd: false, awaitingDocEnd: null, stale: false, inFlight: new Set(), inbox: { items, index: 0, handled: 0, skipped: 0 } }
  conversations.push(c)
  push(c, 'assistant', `You have ${items.length} ${items.length === 1 ? 'item' : 'items'} waiting for you. I will show them one at a time. Skipped items stay in your bell.`)
  push(c, 'assistant', '', inboxCardUi(items[0]!, 0, items.length))
  return send(201, { empty: false, conversation: summary(c), assistant_messages: c.messages, warning_code: null })
}

const plural = (n: number) => `${n} ${n === 1 ? 'item' : 'items'}`

/** Adds the result text, then the next card or the closing message; returns the messages added. */
function advanceInbox(c: StubConversation, resultText: string | null): Json[] {
  const inbox = c.inbox!
  const before = c.messages.length
  if (resultText) push(c, 'assistant', resultText)
  inbox.index++
  if (inbox.index < inbox.items.length) {
    push(c, 'assistant', '', inboxCardUi(inbox.items[inbox.index]!, inbox.index, inbox.items.length))
  }
  else {
    c.has_pending_card = false
    push(c, 'assistant', `You handled ${plural(inbox.handled)} and skipped ${inbox.skipped}. Skipped items stay in the bell and in Approvals.`)
  }
  return c.messages.slice(before)
}

function handleInboxAction(c: StubConversation, user: StubUser, cardId: string, action: string, body: Json, send: Send) {
  const holder = c.messages.find(m => (m.ui as Json | null)?.type === 'inbox_card' && (m.ui as Json).card_id === cardId)
  const ui = holder?.ui as Json | undefined
  const inbox = c.inbox
  if (!ui || !inbox) return send(404, { detail: 'Card not found' })
  const current = inbox.items[inbox.index]
  if (ui.state !== 'open' || !current || current.cardId !== cardId) return send(409, { detail: 'Card is no longer open' })
  if (!(ui.actions as string[]).includes(action)) return send(422, { detail: 'action not allowed for this card' })
  const decides = action === 'approve' || action === 'reject'
  const note = decides ? (body.note ?? null) : null
  if (decides && body.confirmed !== true) return send(422, { detail: 'confirmed must be true' })
  if (decides && note !== null && (typeof note !== 'string' || note.length > 500)) return send(422, { detail: 'note must be at most 500 characters' })

  const done = (state: string, outcome: string | null, text: string | null) => {
    ui.state = state
    ui.outcome = outcome
    const added = advanceInbox(c, text)
    return send(200, { conversation: summary(c), user_message: null, assistant_messages: added, warning_code: null })
  }

  if (action === 'skip') {
    inbox.skipped++
    return done('skipped', null, 'Skipped. It stays in your bell.')
  }
  if (action === 'acknowledge') {
    const n = notifications.find(x => x.id === current.notificationId)
    if (n) n.read_at ??= iso()
    inbox.handled++
    return done('done', 'acknowledged', 'Marked as read.')
  }
  const r = requests.find(x => x.type === current.type && x.id === current.requestId)!
  if (r.status !== 'pending_approval') {
    // Decided elsewhere in the meantime: the card becomes stale, the next item is already shown, and the caller must reload.
    markRequestRead(user, r)
    ui.state = 'stale'
    ui.outcome = null
    advanceInbox(c, `${r.type === 'leave' ? 'Leave request' : 'Claim'} #${r.id} was already handled elsewhere, so nothing was changed.`)
    return send(409, { detail: 'Request is no longer pending' })
  }
  decide(r, action as 'approve' | 'reject', note as string | null, user)
  inbox.handled++
  const who = userById(r.employeeId).display_name
  return done('done', action === 'approve' ? 'approved' : 'rejected', `You ${action === 'approve' ? 'approved' : 'rejected'} ${r.type === 'leave' ? 'leave request' : 'claim'} #${r.id} from ${who}.${note ? ` Your note was sent to ${who}.` : ''}`)
}

seedAttachments()
seedRequests()

const sessionCookie = (value: string, maxAge: number) =>
  `${COOKIE_NAME}=${value}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${maxAge}`

createServer((req, res) => {
  const send = (status: number, body?: unknown, extraHeaders: Record<string, string> = {}) => {
    res.writeHead(status, {
      'access-control-allow-origin': ORIGIN,
      'access-control-allow-credentials': 'true',
      'access-control-allow-headers': 'content-type, x-requested-with',
      'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      vary: 'Origin',
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
      ...extraHeaders,
    })
    res.end(body === undefined ? undefined : Buffer.isBuffer(body) ? body : JSON.stringify(body))
  }
  const [path = '', queryString = ''] = (req.url || '').split('?')
  const query = new URLSearchParams(queryString)
  if (req.method === 'OPTIONS') return send(204)

  if (req.method === 'POST' && path === '/__stub/expire') {
    expired = true
    return send(200, { expired })
  }
  if (req.method === 'POST' && path === '/__stub/reset') {
    expired = false
    logouts = 0
    conversations.length = 0
    attachmentStore.length = 0
    flakySeen.clear()
    seedAttachments()
    seedRequests()
    return send(200, { expired, logouts })
  }
  if (req.method === 'POST' && path === '/__stub/decide') {
    // Decide a request "elsewhere" (as its approver), so the UI's 409 path can be tried.
    const found = requests.find(r => r.type === query.get('type') && r.id === Number(query.get('id')))
    if (!found) return send(404, { detail: 'Not found' })
    decide(found, query.get('decision') === 'reject' ? 'reject' : 'approve', 'Decided elsewhere (stub)', userById(found.approverId))
    return send(200, { status: found.status })
  }
  if (req.method === 'GET' && path === '/__stub/state') return send(200, { expired, logouts })

  // CSRF: unsafe methods must carry the marker header (a cross-site form post cannot set it).
  const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(req.method || 'GET')
  if (unsafe && req.headers['x-requested-with'] !== 'XMLHttpRequest') {
    return send(403, { detail: 'CSRF check failed' })
  }

  if (handleApprovals(req, path, query, send)) return
  if (handleChat(req, path, send)) return

  if (req.method === 'GET' && path === '/api/auth/mock-users') return send(200, USERS)

  if (req.method === 'POST' && path === '/api/auth/mock-google/login') {
    let raw = ''
    req.on('data', chunk => (raw += chunk))
    req.on('end', () => {
      let email = ''
      try {
        email = JSON.parse(raw).email
      }
      catch { /* falls through to 401 */ }
      const user = USERS.find(u => u.email === email)
      if (!user) return send(401, { detail: 'Invalid credentials' })
      expired = false
      return send(200, { expires_in: MAX_AGE, user }, {
        'set-cookie': sessionCookie(`stub.${Buffer.from(user.email).toString('base64url')}`, MAX_AGE),
      })
    })
    return
  }

  if (req.method === 'GET' && path === '/api/auth/me') {
    const user = expired ? undefined : userFromCookie(req.headers.cookie)
    return user ? send(200, user) : send(401, { detail: 'Not authenticated' })
  }

  if (req.method === 'POST' && path === '/api/auth/logout') {
    logouts++
    return send(204, undefined, { 'set-cookie': sessionCookie('', 0) })
  }

  return send(404, { detail: 'Not found' })
}).listen(PORT, () => console.log(`mock-api-stub listening on http://localhost:${PORT} (CORS origin ${ORIGIN})`))
