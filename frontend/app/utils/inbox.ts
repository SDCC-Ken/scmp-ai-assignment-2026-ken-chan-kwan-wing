/** Pure helpers for the bell inbox (docs/inbox-design.md; tests/inbox.test.ts). All text is rendered as plain text. */
import type {
  ConversationSummary,
  InboxAction,
  InboxActionBody,
  InboxCardData,
  InboxCardState,
  InboxOutcome,
  Message,
  TurnResponse,
} from '../types/chat'
import { applyTurn, mergeMessages } from './chat'
import type { IconName, Tone } from './chat'

/* ---- Bell click result ---- */

export type InboxOpenResult =
  | { kind: 'empty', unreadCount: number }
  | { kind: 'conversation', conversation: ConversationSummary, messages: Message[] }
  | { kind: 'invalid' }

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Tolerant reading of `POST /api/chat/inbox`: `{empty:true}` means nothing to do, anything without a usable conversation is invalid. */
export function parseInboxResponse(payload: unknown): InboxOpenResult {
  if (!isRecord(payload)) return { kind: 'invalid' }
  if (payload.empty === true) {
    const unread = typeof payload.unread_count === 'number' && payload.unread_count >= 0 ? payload.unread_count : 0
    return { kind: 'empty', unreadCount: unread }
  }
  const conversation = payload.conversation
  if (!isRecord(conversation) || typeof conversation.id !== 'number' || typeof conversation.title !== 'string') return { kind: 'invalid' }
  const list = Array.isArray(payload.assistant_messages) ? payload.assistant_messages : []
  const messages = list.filter((m): m is Message => isRecord(m) && typeof m.id === 'number' && typeof m.content === 'string')
  return { kind: 'conversation', conversation: conversation as unknown as ConversationSummary, messages }
}

/** Mapping of a failed bell click to a short message (never echoes server text). `status` undefined = network error. */
export function inboxOpenErrorMessage(status: number | undefined): string {
  if (status === undefined) return 'Cannot reach the server. Check your connection and try again.'
  if (status === 403) return 'The inbox is not available for this account.'
  if (status === 429) return 'Too many requests. Please wait a moment and try again.'
  if (status >= 500) return 'The server had a problem. Please try again in a moment.'
  return 'Could not open your inbox. Please try again.'
}

/* ---- Cards ---- */

export function inboxCardOf(message: Pick<Message, 'ui'>): InboxCardData | null {
  return message.ui?.type === 'inbox_card' ? message.ui : null
}

/** "Item 2 of 3"; a missing or broken position gives "Item". */
export function positionLabel(position: InboxCardData['position'] | null | undefined): string {
  const index = position?.index
  const total = position?.total
  if (typeof index !== 'number' || typeof total !== 'number' || index < 1 || total < 1) return 'Item'
  return `Item ${index} of ${Math.max(index, total)}`
}

/** card_id of the newest open inbox card: the only one with active buttons. */
export function activeInboxCardId(messages: readonly Message[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const card = inboxCardOf(messages[i]!)
    if (card && card.state === 'open') return card.card_id
  }
  return null
}

/** True when the conversation has an inbox card and none of them is still open (the closing message is showing). */
export function inboxFinished(messages: readonly Message[]): boolean {
  return messages.some(m => inboxCardOf(m)) && activeInboxCardId(messages) === null
}

export function needsConfirmation(action: InboxAction): boolean {
  return action === 'approve' || action === 'reject'
}

/**
 * POST body for an inbox action. Only approve and reject carry a note (trimmed, null when empty) and
 * `confirmed: true`; skip and acknowledge send just the card id and the action.
 */
export function buildInboxActionBody(cardId: string, action: InboxAction, note?: string | null): InboxActionBody {
  if (!needsConfirmation(action)) return { card_id: cardId, action }
  const trimmed = (note ?? '').trim()
  return { card_id: cardId, action, note: trimmed ? trimmed : null, confirmed: true }
}

/** Local state of a card after the server accepted the action. */
export function stateAfterAction(action: InboxAction): { state: InboxCardState, outcome: InboxOutcome | null } {
  switch (action) {
    case 'approve': return { state: 'done', outcome: 'approved' }
    case 'reject': return { state: 'done', outcome: 'rejected' }
    case 'acknowledge': return { state: 'done', outcome: 'acknowledged' }
    default: return { state: 'skipped', outcome: null }
  }
}

/** Returns the messages with the card moved to its new state (other messages are untouched). */
export function markInboxCard(messages: readonly Message[], cardId: string, next: { state: InboxCardState, outcome: InboxOutcome | null }): Message[] {
  return messages.map((m) => {
    const card = inboxCardOf(m)
    if (!card || card.card_id !== cardId) return m
    return { ...m, ui: { ...card, state: next.state, outcome: next.outcome } }
  })
}

/**
 * Applies a successful inbox action: the acted card gets its new state, then the returned messages (result text,
 * the next card or the closing message) are merged in. Anything the server sends for a card wins over the local guess.
 */
export function applyInboxTurn(messages: readonly Message[], cardId: string, action: InboxAction, turn: Pick<TurnResponse, 'assistant_messages' | 'user_message'>): Message[] {
  return applyTurn(markInboxCard(messages, cardId, stateAfterAction(action)), null, turn as TurnResponse)
}

/** Handoff from the bell to the chat: merge into an empty list and keep the server order. */
export function initialInboxMessages(messages: readonly Message[]): Message[] {
  return mergeMessages([], messages)
}

/** May this card's buttons be used? Only the newest open card, and only the actions the card offers. */
export function canActOnCard(card: InboxCardData, activeId: string | null, action: InboxAction): boolean {
  return card.state === 'open' && card.card_id === activeId && card.actions.includes(action)
}

export interface InboxBadgeMeta {
  label: string
  tone: Tone
  icon: IconName
}

/** Status badge of a card that is no longer open; `null` while it is open. `active` is false for an open card that is not the newest. */
export function inboxStateMeta(card: Pick<InboxCardData, 'state' | 'outcome'>, active = true): InboxBadgeMeta | null {
  if (card.state === 'open') return active ? null : { label: 'Not the current item', tone: 'grey', icon: 'ban' }
  if (card.state === 'skipped') return { label: 'Skipped', tone: 'grey', icon: 'ban' }
  if (card.state === 'stale') return { label: 'Already handled elsewhere', tone: 'amber', icon: 'alert' }
  if (card.outcome === 'approved') return { label: 'Approved', tone: 'green', icon: 'check' }
  if (card.outcome === 'rejected') return { label: 'Rejected', tone: 'red', icon: 'x' }
  if (card.outcome === 'acknowledged') return { label: 'Got it', tone: 'green', icon: 'check' }
  return { label: 'Done', tone: 'green', icon: 'check' }
}

/** Button text and the busy text of the second step ("Confirm approve") for approve and reject. */
export function inboxActionLabels(action: InboxAction): { button: string, confirm: string, busy: string } {
  switch (action) {
    case 'approve': return { button: 'Approve', confirm: 'Confirm approve', busy: 'Approving...' }
    case 'reject': return { button: 'Reject', confirm: 'Confirm reject', busy: 'Rejecting...' }
    case 'acknowledge': return { button: 'Got it', confirm: 'Got it', busy: 'Saving...' }
    default: return { button: 'Skip', confirm: 'Skip', busy: 'Skipping...' }
  }
}

/** Inline error of a failed card action (never echoes server text). `status` undefined = network error. */
export function inboxActionErrorMessage(status: number | undefined): string {
  if (status === undefined) return 'Cannot reach the server. Your note is kept; check your connection and try again.'
  if (status === 409) return 'That card is out of date.'
  if (status === 422) return 'That action was not accepted. Keep the note under 500 characters and confirm the decision.'
  if (status === 403 || status === 404) return 'This item is no longer available to you.'
  if (status === 429) return 'Too many requests. Please wait a moment and try again.'
  if (status >= 500) return 'The server had a problem. Your note is kept; please try again in a moment.'
  return 'Something went wrong. Please try again.'
}
