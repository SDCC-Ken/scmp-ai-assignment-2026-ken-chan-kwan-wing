/** Types for the Phase 2 chat API (see docs/chat-api-contract.md). All data is fictional. */
/* Card payload types carry a "Data" suffix so they never shadow the Vue components of the same name. */

import type { ApprovalDetail } from './approvals'

export type RequestType = 'leave' | 'claim'

export interface ConversationSummary {
  id: number
  /** First user message (max 60 chars); "New chat" while empty. */
  title: string
  status: 'active' | 'closed'
  /** Form currently being filled. */
  active_request_type: RequestType | null
  /** An open confirmation card is waiting. */
  has_pending_card: boolean
  created_at: string
  updated_at: string
}

/** `(string & {})` keeps autocomplete for the known steps while tolerating names added by a newer backend. */
export type TraceStepKey = 'understand' | 'documents' | 'merge' | 'validate' | 'decide' | 'submit' | 'status' | 'respond' | (string & {})

export interface TraceStep {
  step: TraceStepKey
  label: string
  detail: string
  ok: boolean
  duration_ms: number
}

export type CardState = 'open' | 'used' | 'superseded' | 'discarded'
export type CardAction = 'create' | 'update' | 'cancel' | 'retry'

/** A staged or sent file (Phase 2b). `url` is relative to the API base; fetch it with credentials. */
export interface AttachmentInfo {
  id: number
  filename: string
  content_type: string
  size_bytes: number
  url: string
  created_at: string
}

export interface CardField {
  key: string
  label: string
  value: string
  /** Only on updates: the previous value, shown as a struck-through diff. */
  old_value: string | null
  /** "document" when the value was read from an attachment. */
  source?: 'document' | null
}

/** A line of context on a confirmation card (Phase 3), for example the leave balance. A plain string is tolerated. */
export type InfoTone = 'info' | 'warning'
export interface InfoLine {
  label: string
  value: string
  tone: InfoTone
}

export interface ConfirmationCardData {
  type: 'confirmation_card'
  card_id: string
  action: CardAction
  request_type: RequestType
  request_id: number | null
  title: string
  fields: CardField[]
  warnings: string[]
  state: CardState
  confirm_label: string
  /** Extra context lines (Phase 3): shown above the buttons. Objects per the design doc; plain strings are tolerated. */
  info?: (InfoLine | string)[] | null
  /** Documents that will be linked to the request (Phase 2b). */
  attachments?: AttachmentInfo[]
}

export type RequestStatus = 'draft' | 'pending_approval' | 'submission_failed' | 'approved' | 'rejected' | 'cancelled'

export interface StatusRequest {
  request_type: RequestType
  id: number
  status: RequestStatus
  status_label: string
  summary: string
  submitted_at: string | null
  reviewed_at: string | null
  reviewer_note: string | null
  external_reference_id: string | null
}

export interface StatusCardData {
  type: 'status_card'
  requests: StatusRequest[]
  empty: boolean
}

export type ResultOutcome = 'submitted' | 'updated' | 'cancelled' | 'failed'

export interface ResultCardData {
  type: 'result_card'
  outcome: ResultOutcome
  request_type: RequestType
  request_id: number
  status: RequestStatus
  status_label: string
  message: string
  external_reference_id: string | null
}

/** One leave type's balance for a year (days in 0.5 steps). */
export interface BalanceLine {
  leave_type: string
  entitled_days: number
  approved_days: number
  pending_days: number
  remaining_days: number
}

export interface BalanceCardData {
  type: 'balance_card'
  year: number
  lines: BalanceLine[]
}

/** Bell inbox card (see docs/inbox-design.md): one item waiting for the person, shown one card at a time. */
export type InboxKind = 'approval' | 'notice'
export type InboxCardState = 'open' | 'done' | 'skipped' | 'stale'
export type InboxOutcome = 'approved' | 'rejected' | 'acknowledged'
export type InboxAction = 'approve' | 'reject' | 'skip' | 'acknowledge'

export interface InboxCardData {
  type: 'inbox_card'
  card_id: string
  kind: InboxKind
  position: { index: number, total: number }
  title: string
  request_type: RequestType | null
  request_id: number | null
  /** kind "approval": exactly the shape of GET /api/approvals/{type}/{id}. */
  detail: ApprovalDetail | null
  /** kind "notice": plain text. */
  notice: { title: string, body: string } | null
  actions: InboxAction[]
  state: InboxCardState
  outcome: InboxOutcome | null
}

export type MessageUi = ConfirmationCardData | StatusCardData | ResultCardData | BalanceCardData | InboxCardData

export interface Message {
  id: number
  sender_type: 'user' | 'assistant' | 'system'
  /** Plain text: always render as text, never as HTML. */
  content: string
  created_at: string
  ui: MessageUi | null
  trace: TraceStep[] | null
  /** Files on a user message (Phase 2b); may be absent on older payloads. */
  attachments?: AttachmentInfo[]
}

export type WarningCode = 'llm_unavailable' | 'llm_invalid_output' | 'submission_failed' | 'stale_card'

export interface TurnResponse {
  conversation: ConversationSummary
  user_message: Message | null
  assistant_messages: Message[]
  warning_code: WarningCode | null
}

export interface ConversationDetail {
  conversation: ConversationSummary
  messages: Message[]
}

export interface ConversationList {
  items: ConversationSummary[]
}

/** Body of `POST /api/chat/conversations/{id}/actions` for an inbox card. */
export interface InboxActionBody {
  card_id: string
  action: InboxAction
  /** Only for approve and reject: trimmed, null when empty. */
  note?: string | null
  /** Only for approve and reject: always true (the second, explicit click). */
  confirmed?: boolean
}

/** `POST /api/chat/inbox`: nothing waiting, or a new conversation with its first messages. */
export type InboxResponse =
  | { empty: true, unread_count: number }
  | { empty: false, conversation: ConversationSummary, assistant_messages: Message[] }
