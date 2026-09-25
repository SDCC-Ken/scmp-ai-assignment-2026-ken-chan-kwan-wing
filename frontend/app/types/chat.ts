/** Types for the Phase 2 chat API (see docs/chat-api-contract.md). All data is fictional. */
/* Card payload types carry a "Data" suffix so they never shadow the Vue components of the same name. */

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

export type TraceStepKey = 'understand' | 'merge' | 'validate' | 'decide' | 'submit' | 'status' | 'respond'

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

export type MessageUi = ConfirmationCardData | StatusCardData | ResultCardData

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
