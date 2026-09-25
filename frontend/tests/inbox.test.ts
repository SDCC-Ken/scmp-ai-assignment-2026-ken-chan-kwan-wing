import { describe, expect, it } from 'vitest'
import {
  activeInboxCardId,
  applyInboxTurn,
  buildInboxActionBody,
  canActOnCard,
  inboxActionErrorMessage,
  inboxActionLabels,
  inboxFinished,
  inboxOpenErrorMessage,
  inboxStateMeta,
  initialInboxMessages,
  markInboxCard,
  needsConfirmation,
  parseInboxResponse,
  positionLabel,
  stateAfterAction,
} from '../app/utils/inbox'
import { announcementFor, conversationBadges, isInboxConversation } from '../app/utils/chat'
import { formatBadgeCount } from '../app/utils/notifications'
import type { ConversationSummary, InboxCardData, Message, TurnResponse } from '../app/types/chat'

const card = (id: string, index: number, total: number, over: Partial<InboxCardData> = {}): InboxCardData => ({
  type: 'inbox_card', card_id: id, kind: 'approval', position: { index, total }, title: `Leave request #${index} from Amy Lau`,
  request_type: 'leave', request_id: index, detail: null, notice: null, actions: ['approve', 'reject', 'skip'], state: 'open', outcome: null, ...over,
})

const msg = (id: number, ui: Message['ui'] = null, content = '', sender: Message['sender_type'] = 'assistant'): Message => ({
  id, sender_type: sender, content, created_at: `2026-09-25T03:10:${String(id).padStart(2, '0')}Z`, ui, trace: null,
})

const conv = (id: number, title: string): ConversationSummary => ({
  id, title, status: 'active', active_request_type: null, has_pending_card: true, created_at: '2026-09-25T03:10:00Z', updated_at: '2026-09-25T03:10:00Z',
})

describe('bell click result', () => {
  it('reads an empty answer as "all caught up" without a conversation', () => {
    expect(parseInboxResponse({ empty: true, unread_count: 0 })).toEqual({ kind: 'empty', unreadCount: 0 })
    expect(parseInboxResponse({ empty: true })).toEqual({ kind: 'empty', unreadCount: 0 })
  })

  it('reads a created conversation with its first messages', () => {
    const first = msg(1, null, 'You have 2 items.')
    const result = parseInboxResponse({ empty: false, conversation: conv(7, 'Items to handle (2)'), assistant_messages: [first, msg(2, card('i_1', 1, 2)), { junk: true }], warning_code: null })
    expect(result.kind).toBe('conversation')
    if (result.kind === 'conversation') {
      expect(result.conversation.id).toBe(7)
      expect(result.messages.map(m => m.id)).toEqual([1, 2])
    }
  })

  it('treats a payload without a usable conversation as invalid', () => {
    expect(parseInboxResponse(null)).toEqual({ kind: 'invalid' })
    expect(parseInboxResponse({ empty: false })).toEqual({ kind: 'invalid' })
    expect(parseInboxResponse({ empty: false, conversation: { id: 'x', title: 5 } })).toEqual({ kind: 'invalid' })
  })

  it('maps a failed click to a short message without echoing server text', () => {
    expect(inboxOpenErrorMessage(undefined)).toContain('Cannot reach the server')
    expect(inboxOpenErrorMessage(403)).toContain('not available')
    expect(inboxOpenErrorMessage(500)).toContain('server had a problem')
  })
})

describe('position label and inbox conversations', () => {
  it('labels the position "Item 2 of 3"', () => {
    expect(positionLabel({ index: 2, total: 3 })).toBe('Item 2 of 3')
    expect(positionLabel({ index: 1, total: 1 })).toBe('Item 1 of 1')
    expect(positionLabel({ index: 4, total: 3 })).toBe('Item 4 of 4')
    expect(positionLabel(null)).toBe('Item')
    expect(positionLabel({ index: 0, total: 3 })).toBe('Item')
  })

  it('recognises an inbox conversation by its title and tags it in the list', () => {
    expect(isInboxConversation(conv(1, 'Items to handle (3)'))).toBe(true)
    expect(isInboxConversation(conv(1, 'Annual leave next week'))).toBe(false)
    expect(isInboxConversation(null)).toBe(false)
    expect(conversationBadges(conv(1, 'Items to handle (3)'))[0]!.label).toBe('Items waiting')
    expect(conversationBadges(conv(1, 'Annual leave'))[0]!.label).toBe('Awaiting confirmation')
  })
})

describe('action body', () => {
  it('sends the trimmed note and confirmed:true for approve and reject', () => {
    expect(buildInboxActionBody('i_1', 'approve', '  Enjoy the break.  ')).toEqual({ card_id: 'i_1', action: 'approve', note: 'Enjoy the break.', confirmed: true })
    expect(buildInboxActionBody('i_1', 'reject', 'No cover that week')).toEqual({ card_id: 'i_1', action: 'reject', note: 'No cover that week', confirmed: true })
  })

  it('sends an empty or missing note as null', () => {
    expect(buildInboxActionBody('i_1', 'approve', '   ').note).toBeNull()
    expect(buildInboxActionBody('i_1', 'reject', null).note).toBeNull()
    expect(buildInboxActionBody('i_1', 'approve').note).toBeNull()
  })

  it('sends neither a note nor confirmed for skip and acknowledge', () => {
    expect(buildInboxActionBody('i_2', 'skip', 'ignored note')).toEqual({ card_id: 'i_2', action: 'skip' })
    expect(buildInboxActionBody('i_3', 'acknowledge', 'ignored note')).toEqual({ card_id: 'i_3', action: 'acknowledge' })
    expect(needsConfirmation('approve')).toBe(true)
    expect(needsConfirmation('reject')).toBe(true)
    expect(needsConfirmation('skip')).toBe(false)
    expect(needsConfirmation('acknowledge')).toBe(false)
  })
})

describe('card state transitions', () => {
  it('maps each action to the local state and outcome', () => {
    expect(stateAfterAction('approve')).toEqual({ state: 'done', outcome: 'approved' })
    expect(stateAfterAction('reject')).toEqual({ state: 'done', outcome: 'rejected' })
    expect(stateAfterAction('acknowledge')).toEqual({ state: 'done', outcome: 'acknowledged' })
    expect(stateAfterAction('skip')).toEqual({ state: 'skipped', outcome: null })
  })

  it('moves only the acted card and does not mutate the input', () => {
    const list = [msg(1, card('i_1', 1, 2)), msg(2, card('i_2', 2, 2, { state: 'skipped' }))]
    const next = markInboxCard(list, 'i_1', stateAfterAction('approve'))
    expect((next[0]!.ui as InboxCardData).state).toBe('done')
    expect((next[0]!.ui as InboxCardData).outcome).toBe('approved')
    expect((next[1]!.ui as InboxCardData).state).toBe('skipped')
    expect((list[0]!.ui as InboxCardData).state).toBe('open')
  })

  it('only the newest open card is active; older open cards are read-only', () => {
    const list = [msg(1, card('i_1', 1, 3)), msg(2, card('i_2', 2, 3, { state: 'done', outcome: 'approved' })), msg(3, card('i_3', 3, 3))]
    expect(activeInboxCardId(list)).toBe('i_3')
    expect(canActOnCard(card('i_3', 3, 3), 'i_3', 'approve')).toBe(true)
    expect(canActOnCard(card('i_1', 1, 3), 'i_3', 'approve')).toBe(false)
    expect(canActOnCard(card('i_3', 3, 3, { state: 'stale' }), 'i_3', 'skip')).toBe(false)
    expect(canActOnCard(card('i_3', 3, 3, { actions: ['acknowledge', 'skip'], kind: 'notice' }), 'i_3', 'approve')).toBe(false)
    expect(activeInboxCardId([msg(1, null, 'hello')])).toBeNull()
  })

  it('knows when the last card has been handled (the closing message is showing)', () => {
    const open = [msg(1, card('i_1', 1, 1))]
    expect(inboxFinished(open)).toBe(false)
    expect(inboxFinished(markInboxCard(open, 'i_1', stateAfterAction('skip')))).toBe(true)
    expect(inboxFinished([msg(1, null, 'not an inbox')])).toBe(false)
  })

  it('gives every state a labelled badge (colour is never the only cue)', () => {
    expect(inboxStateMeta(card('a', 1, 1))).toBeNull()
    expect(inboxStateMeta(card('a', 1, 1), false)!.label).toBe('Not the current item')
    expect(inboxStateMeta(card('a', 1, 1, { state: 'done', outcome: 'approved' }))).toMatchObject({ label: 'Approved', tone: 'green' })
    expect(inboxStateMeta(card('a', 1, 1, { state: 'done', outcome: 'rejected' }))).toMatchObject({ label: 'Rejected', tone: 'red' })
    expect(inboxStateMeta(card('a', 1, 1, { state: 'done', outcome: 'acknowledged' }))!.label).toBe('Got it')
    expect(inboxStateMeta(card('a', 1, 1, { state: 'skipped' }))!.label).toBe('Skipped')
    expect(inboxStateMeta(card('a', 1, 1, { state: 'stale' }))).toMatchObject({ label: 'Already handled elsewhere', tone: 'amber' })
  })
})

describe('merging the next card and the closing message', () => {
  const turn = (assistant: Message[]): TurnResponse => ({ conversation: conv(7, 'Items to handle (2)'), user_message: null, assistant_messages: assistant, warning_code: null })

  it('marks the acted card, then appends the result text and the next card in order', () => {
    const before = [msg(1, null, 'Intro'), msg(2, card('i_1', 1, 2))]
    const after = applyInboxTurn(before, 'i_1', 'approve', turn([msg(3, null, 'You approved leave request #1 from Amy Lau.'), msg(4, card('i_2', 2, 2))]))
    expect(after.map(m => m.id)).toEqual([1, 2, 3, 4])
    expect((after[1]!.ui as InboxCardData).outcome).toBe('approved')
    expect(activeInboxCardId(after)).toBe('i_2')
  })

  it('ends with the closing message and no open card after the last item', () => {
    const before = [msg(1, null, 'Intro'), msg(2, card('i_1', 1, 1))]
    const after = applyInboxTurn(before, 'i_1', 'skip', turn([msg(3, null, 'You handled 0 items and skipped 1.')]))
    expect(activeInboxCardId(after)).toBeNull()
    expect(inboxFinished(after)).toBe(true)
    expect(after[after.length - 1]!.content).toContain('skipped 1')
  })

  it('lets a card the server sends back win over the local guess', () => {
    const before = [msg(2, card('i_1', 1, 2))]
    const after = applyInboxTurn(before, 'i_1', 'approve', turn([msg(2, card('i_1', 1, 2, { state: 'stale' })), msg(3, card('i_2', 2, 2))]))
    expect((after[0]!.ui as InboxCardData).state).toBe('stale')
  })

  it('keeps the order of the handoff messages from the bell', () => {
    const list = initialInboxMessages([msg(2, card('i_1', 1, 2)), msg(1, null, 'Intro')])
    expect(list.map(m => m.id)).toEqual([1, 2])
  })
})

describe('screen reader text and labels', () => {
  it('announces the position, the title and the choices', () => {
    expect(announcementFor(msg(2, card('i_1', 2, 3)))).toBe('Item 2 of 3. Leave request #2 from Amy Lau. Choose Approve, Reject or Skip.')
    expect(announcementFor(msg(2, card('i_9', 3, 3, { kind: 'notice', actions: ['acknowledge', 'skip'], title: 'Your leave request #3 was approved' }))))
      .toBe('Item 3 of 3. Your leave request #3 was approved. Choose Got it or Skip.')
  })

  it('has the two-step button texts and readable error messages', () => {
    expect(inboxActionLabels('approve')).toMatchObject({ button: 'Approve', confirm: 'Confirm approve' })
    expect(inboxActionLabels('reject')).toMatchObject({ button: 'Reject', confirm: 'Confirm reject' })
    expect(inboxActionErrorMessage(undefined)).toContain('note is kept')
    expect(inboxActionErrorMessage(422)).toContain('500 characters')
    expect(inboxActionErrorMessage(409)).toBe('That card is out of date.')
  })

  it('caps the bell number at 99+ and hides zero', () => {
    expect(formatBadgeCount(99)).toBe('99')
    expect(formatBadgeCount(100)).toBe('99+')
    expect(formatBadgeCount(0)).toBe('')
  })
})
