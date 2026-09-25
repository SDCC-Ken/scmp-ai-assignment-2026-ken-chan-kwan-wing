/** Pure, framework-free chat helpers (unit-tested offline in tests/chat.test.ts). */
import type {
  AttachmentInfo,
  CardAction,
  CardField,
  CardState,
  ConfirmationCardData,
  ConversationSummary,
  Message,
  RequestStatus,
  ResultOutcome,
  TurnResponse,
  WarningCode,
} from '../types/chat'

export const MAX_MESSAGE_LENGTH = 1000

/** The backend titles an inbox conversation "Items to handle (N)"; the sidebar tags it by this prefix. */
export const INBOX_TITLE_PREFIX = 'Items to handle'

export function isInboxConversation(summary: Pick<ConversationSummary, 'title'> | null | undefined): boolean {
  return !!summary && typeof summary.title === 'string' && summary.title.startsWith(INBOX_TITLE_PREFIX)
}

/** Suggestion chips of the empty state; picking one sends it as a message. */
export const CHAT_SUGGESTIONS: readonly string[] = [
  'I need annual leave next Monday and Tuesday',
  'Half day sick leave tomorrow afternoon',
  'Claim HKD 180 for a taxi yesterday',
  'What is the status of my requests?',
]

/* ---- Status badges: colour is never the only cue (each tone has an icon and a text label) ---- */

export type Tone = 'amber' | 'green' | 'red' | 'grey'
export type IconName = 'clock' | 'check' | 'x' | 'alert' | 'ban' | 'pencil'

export interface StatusMeta {
  label: string
  tone: Tone
  icon: IconName
}

const STATUS_META: Readonly<Record<RequestStatus, StatusMeta>> = {
  draft: { label: 'Draft', tone: 'grey', icon: 'pencil' },
  pending_approval: { label: 'Pending approval', tone: 'amber', icon: 'clock' },
  submission_failed: { label: 'Submission failed', tone: 'red', icon: 'alert' },
  approved: { label: 'Approved', tone: 'green', icon: 'check' },
  rejected: { label: 'Rejected', tone: 'red', icon: 'x' },
  cancelled: { label: 'Cancelled', tone: 'grey', icon: 'ban' },
}

/** Label, tone and icon for a request status; unknown statuses fall back to a neutral badge. */
export function statusMeta(status: string, fallbackLabel?: string): StatusMeta {
  const known = (STATUS_META as Record<string, StatusMeta | undefined>)[status]
  if (known) return known
  return { label: fallbackLabel || 'Unknown status', tone: 'grey', icon: 'clock' }
}

/** CSS class for a tone (palette defined in main.css, contrast >= 4.5:1 in both themes). */
export function toneClass(tone: Tone): string {
  return `tone tone-${tone}`
}

const OUTCOME_META: Readonly<Record<ResultOutcome, { label: string, tone: Tone, icon: IconName }>> = {
  submitted: { label: 'Submitted', tone: 'green', icon: 'check' },
  updated: { label: 'Updated', tone: 'green', icon: 'check' },
  cancelled: { label: 'Cancelled', tone: 'grey', icon: 'ban' },
  failed: { label: 'Submission failed', tone: 'red', icon: 'alert' },
}

export function outcomeMeta(outcome: string) {
  return (OUTCOME_META as Record<string, (typeof OUTCOME_META)[ResultOutcome] | undefined>)[outcome]
    ?? { label: 'Done', tone: 'grey' as Tone, icon: 'check' as IconName }
}

const CARD_STATE_META: Readonly<Record<Exclude<CardState, 'open'>, { label: string, tone: Tone, icon: IconName }>> = {
  used: { label: 'Confirmed', tone: 'green', icon: 'check' },
  superseded: { label: 'Replaced by a newer card', tone: 'grey', icon: 'ban' },
  discarded: { label: 'Discarded', tone: 'grey', icon: 'x' },
}

export function cardStateMeta(state: string) {
  return (CARD_STATE_META as Record<string, (typeof CARD_STATE_META)[keyof typeof CARD_STATE_META] | undefined>)[state]
    ?? { label: 'Closed', tone: 'grey' as Tone, icon: 'ban' as IconName }
}

/** Text of the loading state while a card action runs (the required "API loading state"). */
export function cardBusyLabel(action: CardAction, decision: 'confirm' | 'discard'): string {
  if (decision === 'discard') return 'Discarding...'
  return action === 'cancel' ? 'Cancelling request...' : 'Submitting to ReqRes...'
}

/* ---- Time ---- */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** "just now", "5 min ago", "3 h ago", "yesterday", "4 d ago", then the ISO date. Bad input gives "". */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const diff = now - then
  if (diff < MINUTE) return 'just now' // includes small clock skew into the future
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} min ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)} h ago`
  if (diff < 2 * DAY) return 'yesterday'
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)} d ago`
  return new Date(then).toISOString().slice(0, 10)
}

/** Clock time of a message, e.g. "11:05". `timeZone` is only passed by tests. */
export function formatClock(iso: string, timeZone?: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone })
}

/** Date and time for cards, e.g. "25 Sep 2026, 11:05". */
export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone,
  })
}

/** "640 ms" or "1.2 s". */
export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

/* ---- Card fields ---- */

/** Value to show for a card field; blank values become an en dash. */
export function fieldValue(value: string | null | undefined): string {
  const text = (value ?? '').trim()
  return text || '–'
}

/** True when a field carries a real change (an old value that differs from the new one). */
export function fieldHasDiff(field: CardField): boolean {
  return field.old_value !== null && field.old_value !== undefined && field.old_value !== field.value
}

/* ---- Conversations ---- */

export function sortConversations(list: readonly ConversationSummary[]): ConversationSummary[] {
  return [...list].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at) || b.id - a.id)
}

/** Inserts or replaces a summary and keeps the list newest-first. */
export function upsertConversation(list: readonly ConversationSummary[], summary: ConversationSummary): ConversationSummary[] {
  return sortConversations([...list.filter(c => c.id !== summary.id), summary])
}

export interface ConversationBadge {
  kind: 'card' | 'form'
  label: string
}

/** Badges for the sidebar: an open card and/or the form type being filled. */
export function conversationBadges(summary: ConversationSummary): ConversationBadge[] {
  const badges: ConversationBadge[] = []
  if (summary.has_pending_card) {
    // An inbox conversation waits for a decision on its open item, not for a form confirmation.
    badges.push({ kind: 'card', label: isInboxConversation(summary) ? 'Items waiting' : 'Awaiting confirmation' })
  }
  if (summary.active_request_type) {
    badges.push({ kind: 'form', label: summary.active_request_type === 'leave' ? 'Leave form' : 'Claim form' })
  }
  return badges
}

/** A conversation the user has not typed into yet (safe to reuse instead of creating another). */
export function isEmptyConversation(summary: ConversationSummary | undefined, messages: readonly Message[]): boolean {
  return !!summary && messages.length === 0 && !summary.has_pending_card && !summary.active_request_type
}

/* ---- Messages ---- */

function byTime(a: Message, b: Message): number {
  return Date.parse(a.created_at) - Date.parse(b.created_at) || a.id - b.id
}

/** Merges messages by id (incoming wins) and orders them oldest-first. Optimistic (negative-id) messages stay last on ties. */
export function mergeMessages(existing: readonly Message[], incoming: readonly Message[]): Message[] {
  const byId = new Map<number, Message>()
  for (const message of [...existing, ...incoming]) byId.set(message.id, message)
  return [...byId.values()].sort(byTime)
}

/** Placeholder for the user's message while the request is in flight (negative id = not yet saved). */
export function optimisticMessage(tempId: number, content: string, now: Date = new Date(), attachments: AttachmentInfo[] = []): Message {
  return { id: tempId, sender_type: 'user', content, created_at: now.toISOString(), ui: null, trace: null, attachments }
}

export function isOptimistic(message: Message): boolean {
  return message.id < 0
}

/** Applies a TurnResponse: drops the optimistic message, merges the saved ones (user message first). */
export function applyTurn(messages: readonly Message[], tempId: number | null, turn: TurnResponse): Message[] {
  const kept = tempId === null ? messages : messages.filter(m => m.id !== tempId)
  const incoming = [...(turn.user_message ? [turn.user_message] : []), ...turn.assistant_messages]
  return mergeMessages(kept, incoming)
}

function isOpenCard(message: Message): boolean {
  return message.ui?.type === 'confirmation_card' && message.ui.state === 'open'
}

function withCardState(message: Message, state: CardState): Message {
  if (message.ui?.type !== 'confirmation_card') return message
  const ui: ConfirmationCardData = { ...message.ui, state }
  return { ...message, ui }
}

/**
 * Keeps card states consistent with the contract: only the newest confirmation card can be open, and no card
 * is open when the conversation has no pending card. `acted` records the decision the user just took.
 */
export function reconcileCards(
  messages: readonly Message[],
  opts: { hasPendingCard: boolean, acted?: { cardId: string, state: CardState } },
): Message[] {
  let next = messages.map(m =>
    opts.acted && m.ui?.type === 'confirmation_card' && m.ui.card_id === opts.acted.cardId
      ? withCardState(m, opts.acted.state)
      : m,
  )
  const openIndexes = next.flatMap((m, i) => (isOpenCard(m) ? [i] : []))
  const last = openIndexes[openIndexes.length - 1]
  next = next.map((m, i) => {
    if (!isOpenCard(m)) return m
    return i === last && opts.hasPendingCard ? m : withCardState(m, 'superseded')
  })
  return next
}

/** True when the newest message is one the user has not seen the answer to (used to decide auto-scroll). */
export function lastMessageIsUser(messages: readonly Message[]): boolean {
  return messages[messages.length - 1]?.sender_type === 'user'
}

/** Text spoken by the aria-live region for a new assistant message. */
export function announcementFor(message: Message): string {
  const parts = [message.content.trim()]
  if (message.ui?.type === 'confirmation_card' && message.ui.state === 'open') {
    parts.push(`${message.ui.title}. Use the ${message.ui.confirm_label} button or Discard.`)
  }
  else if (message.ui?.type === 'status_card') {
    parts.push(message.ui.requests.length ? `${message.ui.requests.length} request(s) listed.` : 'No matching requests.')
  }
  else if (message.ui?.type === 'result_card') {
    parts.push(message.ui.message)
  }
  else if (message.ui?.type === 'balance_card') {
    parts.push(`Leave balance for ${message.ui.year}: ${message.ui.lines.length} leave type(s) shown.`)
  }
  else if (message.ui?.type === 'inbox_card') {
    const { position, title, kind, state } = message.ui
    const head = position && position.index >= 1 && position.total >= 1 ? `Item ${position.index} of ${position.total}. ${title}.` : `${title}.`
    parts.push(state !== 'open' ? head : `${head} ${kind === 'approval' ? 'Choose Approve, Reject or Skip.' : 'Choose Got it or Skip.'}`)
  }
  return parts.filter(Boolean).join(' ')
}

/* ---- Composer ---- */

/** True when the trimmed text is 1..1000 characters (the backend counts the trimmed text) and no turn is in flight. */
export function canSend(text: string, busy: boolean): boolean {
  const length = text.trim().length
  return !busy && length > 0 && length <= MAX_MESSAGE_LENGTH
}

/** Characters left, counting the trimmed text like the backend does (negative = over the limit). */
export function remainingChars(text: string): number {
  return MAX_MESSAGE_LENGTH - text.trim().length
}

/** True when the scroll position is within `threshold` px of the bottom (so auto-scroll may follow new messages). */
export function isNearBottom(metrics: { scrollTop: number, scrollHeight: number, clientHeight: number }, threshold = 80): boolean {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold
}

/* ---- Errors ---- */

export type ChatAction = 'load' | 'send' | 'card'

/** User-facing message for a chat API failure (never echoes server text). `status` undefined = network error. */
export function chatErrorMessage(status: number | undefined, action: ChatAction): string {
  if (status === undefined) return 'Cannot reach the server. Check your connection and try again.'
  if (status === 403) return 'The chat is available to employees only.'
  if (status === 404) return 'That conversation could not be found.'
  if (status === 409) return 'That card is out of date.'
  if (status === 422) return action === 'send' ? 'That message could not be sent. Keep it between 1 and 1000 characters.' : 'That request was not accepted.'
  if (status === 429) return 'Too many requests. Please wait a moment and try again.'
  if (status >= 500) return 'The server had a problem. Please try again in a moment.'
  return 'Something went wrong. Please try again.'
}

const WARNING_MESSAGES: Readonly<Record<WarningCode, string>> = {
  llm_unavailable: 'The AI service is unavailable, please try again.',
  llm_invalid_output: 'The AI gave an answer I could not use. Please rephrase and try again.',
  submission_failed: 'The submission to ReqRes failed. Your request is saved; use Retry on the card to try again.',
  stale_card: 'That card is out of date.',
}

/** Banner text for a `warning_code`; null when there is nothing to show (or an unknown code). */
export function warningMessage(code: string | null | undefined): string | null {
  if (!code) return null
  return (WARNING_MESSAGES as Record<string, string | undefined>)[code] ?? 'Something needs your attention. Please try again.'
}

/** Warning codes where the AI could not answer this message, so sending it again is meaningful. */
export function isRetryableWarning(code: string | null | undefined): boolean {
  return code === 'llm_unavailable' || code === 'llm_invalid_output'
}

/**
 * The draft after "Try again": the failed message goes back into the composer, unless the user has already typed
 * something new there (never overwrite their text).
 */
export function restoreDraft(currentDraft: string, failedText: string | null): string {
  if (failedText === null || currentDraft.trim() !== '') return currentDraft
  return failedText
}
