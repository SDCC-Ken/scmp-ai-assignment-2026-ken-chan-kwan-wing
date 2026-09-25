import { describe, expect, it } from 'vitest'
import {
  announcementFor,
  applyTurn,
  canSend,
  cardBusyLabel,
  chatErrorMessage,
  conversationBadges,
  fieldHasDiff,
  fieldValue,
  formatClock,
  formatDateTime,
  formatIsoDate,
  formatDuration,
  isEmptyConversation,
  isNearBottom,
  isRetryableWarning,
  MAX_MESSAGE_LENGTH,
  mergeMessages,
  optimisticMessage,
  remainingChars,
  reconcileCards,
  relativeTime,
  restoreDraft,
  statusMeta,
  upsertConversation,
  warningMessage,
} from '../app/utils/chat'
import type { ConfirmationCardData, ConversationSummary, Message, TurnResponse } from '../app/types/chat'

const conv = (id: number, updated: string, extra: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id,
  title: `Chat ${id}`,
  status: 'active',
  active_request_type: null,
  has_pending_card: false,
  created_at: '2026-09-25T03:00:00Z',
  updated_at: updated,
  ...extra,
})

const msg = (id: number, at: string, extra: Partial<Message> = {}): Message => ({
  id,
  sender_type: 'assistant',
  content: `m${id}`,
  created_at: at,
  ui: null,
  trace: null,
  ...extra,
})

const card = (id: string, state: ConfirmationCardData['state'] = 'open'): ConfirmationCardData => ({
  type: 'confirmation_card',
  card_id: id,
  action: 'create',
  request_type: 'leave',
  request_id: null,
  title: 'Confirm leave application',
  fields: [],
  warnings: [],
  state,
  confirm_label: 'Submit',
})

const cardState = (m: Message) => (m.ui?.type === 'confirmation_card' ? m.ui.state : undefined)

describe('status badges', () => {
  it('maps every contract status to a label, tone and icon (colour is never the only cue)', () => {
    expect(statusMeta('pending_approval')).toEqual({ label: 'Pending approval', tone: 'amber', icon: 'clock' })
    expect(statusMeta('approved').tone).toBe('green')
    expect(statusMeta('rejected').tone).toBe('red')
    expect(statusMeta('submission_failed')).toMatchObject({ label: 'Submission failed', tone: 'red' })
    expect(statusMeta('cancelled').tone).toBe('grey')
    expect(statusMeta('draft').tone).toBe('grey')
    const icons = ['draft', 'pending_approval', 'submission_failed', 'approved', 'rejected', 'cancelled'].map(s => statusMeta(s).icon)
    expect(new Set(icons).size).toBe(6)
  })

  it('falls back to a neutral badge using the API label for unknown statuses', () => {
    expect(statusMeta('on_hold', 'On hold')).toMatchObject({ label: 'On hold', tone: 'grey' })
    expect(statusMeta('on_hold').label).toBe('Unknown status')
  })
})

describe('time formatting', () => {
  const now = Date.parse('2026-09-25T12:00:00Z')

  it('formats relative time in coarse steps', () => {
    expect(relativeTime('2026-09-25T11:59:40Z', now)).toBe('just now')
    expect(relativeTime('2026-09-25T11:55:00Z', now)).toBe('5 min ago')
    expect(relativeTime('2026-09-25T09:00:00Z', now)).toBe('3 h ago')
    expect(relativeTime('2026-09-24T09:00:00Z', now)).toBe('yesterday')
    expect(relativeTime('2026-09-21T12:00:00Z', now)).toBe('4 d ago')
    expect(relativeTime('2026-09-01T12:00:00Z', now)).toBe('2026-09-01')
  })

  it('treats clock skew into the future and bad input safely', () => {
    expect(relativeTime('2026-09-25T12:05:00Z', now)).toBe('just now')
    expect(relativeTime('not a date', now)).toBe('')
  })

  it('formats clock time, date-time and durations', () => {
    // Hong Kong time (UTC+8) is the default; an explicit offset in minutes is used by tests
    expect(formatClock('2026-09-25T03:05:00Z')).toBe('11:05')
    expect(formatClock('2026-09-25T03:05:00Z', 0)).toBe('03:05')
    expect(formatClock('nope')).toBe('')
    expect(formatDateTime('2026-09-25T03:05:00Z')).toBe('25 Sep 2026, 11:05')
    expect(formatDateTime('2026-09-25T03:05:00Z', 0)).toBe('25 Sep 2026, 03:05')
    expect(formatDateTime(null)).toBe('')
    expect(formatDateTime('not a date')).toBe('')
    expect(formatDuration(640)).toBe('640 ms')
    expect(formatDuration(1240)).toBe('1.2 s')
    expect(formatDuration(-1)).toBe('')
  })
})

describe('card fields', () => {
  it('shows a diff only when the old value really differs', () => {
    expect(fieldHasDiff({ key: 'a', label: 'A', value: 'Annual', old_value: 'Sick' })).toBe(true)
    expect(fieldHasDiff({ key: 'a', label: 'A', value: 'Annual', old_value: 'Annual' })).toBe(false)
    expect(fieldHasDiff({ key: 'a', label: 'A', value: 'Annual', old_value: null })).toBe(false)
  })

  it('replaces blank values with an en dash', () => {
    expect(fieldValue('  ')).toBe('–')
    expect(fieldValue(null)).toBe('–')
    expect(fieldValue(' HKD 180 ')).toBe('HKD 180')
  })

  it('words the loading state per action', () => {
    expect(cardBusyLabel('create', 'confirm')).toBe('Submitting to ReqRes...')
    expect(cardBusyLabel('retry', 'confirm')).toBe('Submitting to ReqRes...')
    expect(cardBusyLabel('cancel', 'confirm')).toBe('Cancelling request...')
    expect(cardBusyLabel('create', 'discard')).toBe('Discarding...')
  })
})

describe('conversations', () => {
  it('upserts a summary and keeps the list newest-first', () => {
    const list = [conv(1, '2026-09-25T03:00:00Z'), conv(2, '2026-09-25T02:00:00Z')]
    const next = upsertConversation(list, conv(2, '2026-09-25T04:00:00Z', { title: 'Renamed' }))
    expect(next.map(c => c.id)).toEqual([2, 1])
    expect(next[0]!.title).toBe('Renamed')
    expect(next).toHaveLength(2)
    expect(list[0]!.id).toBe(1) // input not mutated
  })

  it('derives sidebar badges from the open card and the active form', () => {
    expect(conversationBadges(conv(1, '2026-09-25T03:00:00Z'))).toEqual([])
    expect(conversationBadges(conv(1, '2026-09-25T03:00:00Z', { has_pending_card: true, active_request_type: 'leave' })))
      .toEqual([{ kind: 'card', label: 'Awaiting confirmation' }, { kind: 'form', label: 'Leave form' }])
    expect(conversationBadges(conv(1, '2026-09-25T03:00:00Z', { active_request_type: 'claim' }))[0]!.label).toBe('Claim form')
  })

  it('only reuses a conversation that is really empty', () => {
    expect(isEmptyConversation(conv(1, '2026-09-25T03:00:00Z'), [])).toBe(true)
    expect(isEmptyConversation(conv(1, '2026-09-25T03:00:00Z'), [msg(1, '2026-09-25T03:00:00Z')])).toBe(false)
    expect(isEmptyConversation(conv(1, '2026-09-25T03:00:00Z', { has_pending_card: true }), [])).toBe(false)
    expect(isEmptyConversation(undefined, [])).toBe(false)
  })
})

describe('message merging and ordering', () => {
  it('merges by id (incoming wins) and orders oldest-first', () => {
    const existing = [msg(2, '2026-09-25T03:02:00Z'), msg(1, '2026-09-25T03:01:00Z')]
    const merged = mergeMessages(existing, [msg(2, '2026-09-25T03:02:00Z', { content: 'updated' }), msg(3, '2026-09-25T03:03:00Z')])
    expect(merged.map(m => m.id)).toEqual([1, 2, 3])
    expect(merged[1]!.content).toBe('updated')
  })

  it('breaks timestamp ties by id', () => {
    const merged = mergeMessages([msg(5, '2026-09-25T03:00:00Z')], [msg(4, '2026-09-25T03:00:00Z')])
    expect(merged.map(m => m.id)).toEqual([4, 5])
  })

  it('replaces the optimistic message with the saved one and appends the assistant reply', () => {
    const temp = optimisticMessage(-1, 'hello', new Date('2026-09-25T03:00:00Z'))
    const turn: TurnResponse = {
      conversation: conv(1, '2026-09-25T03:00:05Z'),
      user_message: msg(10, '2026-09-25T03:00:01Z', { sender_type: 'user', content: 'hello' }),
      assistant_messages: [msg(11, '2026-09-25T03:00:03Z'), msg(12, '2026-09-25T03:00:04Z')],
      warning_code: null,
    }
    const result = applyTurn([temp], -1, turn)
    expect(result.map(m => m.id)).toEqual([10, 11, 12])
    expect(result.some(m => m.id < 0)).toBe(false)
  })

  it('handles a card action turn without a user message', () => {
    const turn: TurnResponse = { conversation: conv(1, '2026-09-25T03:00:05Z'), user_message: null, assistant_messages: [msg(9, '2026-09-25T03:00:03Z')], warning_code: null }
    expect(applyTurn([msg(8, '2026-09-25T03:00:00Z')], null, turn).map(m => m.id)).toEqual([8, 9])
  })
})

describe('card state reconciliation', () => {
  const open1 = msg(1, '2026-09-25T03:00:00Z', { ui: card('c1') })
  const open2 = msg(2, '2026-09-25T03:01:00Z', { ui: card('c2') })

  it('keeps only the newest open card open', () => {
    const result = reconcileCards([open1, open2], { hasPendingCard: true })
    expect(result.map(cardState)).toEqual(['superseded', 'open'])
  })

  it('closes every card when the conversation has no pending card', () => {
    expect(reconcileCards([open1, open2], { hasPendingCard: false }).map(cardState)).toEqual(['superseded', 'superseded'])
  })

  it('marks the acted card as used or discarded and does not touch the input', () => {
    const result = reconcileCards([open2], { hasPendingCard: false, acted: { cardId: 'c2', state: 'used' } })
    expect(cardState(result[0]!)).toBe('used')
    expect(cardState(open2)).toBe('open')
  })

  it('leaves non-card messages alone', () => {
    const plain = msg(3, '2026-09-25T03:02:00Z')
    expect(reconcileCards([plain], { hasPendingCard: true })[0]).toBe(plain)
  })
})

describe('composer rules', () => {
  it('blocks empty, whitespace-only and over-limit text and any send while busy', () => {
    expect(canSend('hello', false)).toBe(true)
    expect(canSend('', false)).toBe(false)
    expect(canSend('   \n ', false)).toBe(false)
    expect(canSend('hello', true)).toBe(false)
    expect(canSend('a'.repeat(MAX_MESSAGE_LENGTH), false)).toBe(true)
    expect(canSend('a'.repeat(MAX_MESSAGE_LENGTH + 1), false)).toBe(false)
    // the backend counts the trimmed text, so surrounding whitespace does not count against the limit
    expect(canSend(`  ${'a'.repeat(MAX_MESSAGE_LENGTH)}\n`, false)).toBe(true)
    expect(remainingChars(`${'a'.repeat(998)}  `)).toBe(2)
  })

  it('only follows new messages when the user is near the bottom', () => {
    expect(isNearBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 })).toBe(true)
    expect(isNearBottom({ scrollTop: 300, scrollHeight: 1000, clientHeight: 100 })).toBe(false)
  })
})

describe('error and warning messages', () => {
  it('maps HTTP statuses and network errors to plain messages', () => {
    expect(chatErrorMessage(undefined, 'send')).toMatch(/Cannot reach the server/)
    expect(chatErrorMessage(403, 'load')).toMatch(/employees only/)
    expect(chatErrorMessage(409, 'card')).toBe('That card is out of date.')
    expect(chatErrorMessage(422, 'send')).toMatch(/1 and 1000/)
    expect(chatErrorMessage(500, 'send')).toMatch(/server had a problem/)
    expect(chatErrorMessage(418, 'send')).toMatch(/Something went wrong/)
  })

  it('maps warning codes to banner text', () => {
    expect(warningMessage('llm_unavailable')).toBe('The AI service is unavailable, please try again.')
    expect(warningMessage('stale_card')).toBe('That card is out of date.')
    expect(warningMessage(null)).toBeNull()
    expect(warningMessage('something_new')).toMatch(/needs your attention/)
  })
})

describe('Try again after an AI warning', () => {
  it('offers a retry only for warnings where the AI could not answer', () => {
    expect(isRetryableWarning('llm_unavailable')).toBe(true)
    expect(isRetryableWarning('llm_invalid_output')).toBe(true)
    expect(isRetryableWarning('submission_failed')).toBe(false)
    expect(isRetryableWarning('stale_card')).toBe(false)
    expect(isRetryableWarning(null)).toBe(false)
    expect(isRetryableWarning(undefined)).toBe(false)
  })

  it('puts the failed message back into an empty composer', () => {
    expect(restoreDraft('', 'annual leave next week')).toBe('annual leave next week')
    expect(restoreDraft('   ', 'annual leave next week')).toBe('annual leave next week')
  })

  it('never overwrites text the user typed since, or restores nothing', () => {
    expect(restoreDraft('something else', 'annual leave next week')).toBe('something else')
    expect(restoreDraft('', null)).toBe('')
    expect(restoreDraft('typed', null)).toBe('typed')
  })
})

describe('screen-reader announcements', () => {
  it('describes an open card and a result', () => {
    const text = announcementFor(msg(1, '2026-09-25T03:00:00Z', { content: 'Please confirm.', ui: card('c1') }))
    expect(text).toContain('Please confirm.')
    expect(text).toContain('Submit')
    const result = announcementFor(msg(2, '2026-09-25T03:00:00Z', {
      content: '',
      ui: { type: 'result_card', outcome: 'submitted', request_type: 'leave', request_id: 1, status: 'pending_approval', status_label: 'Pending approval', message: 'Submitted.', external_reference_id: '23' },
    }))
    expect(result).toBe('Submitted.')
  })
})


describe('deterministic date and time formatting', () => {
  it('always writes a three-letter month, never "Sept"', () => {
    for (let month = 1; month <= 12; month++) {
      const iso = `2026-${String(month).padStart(2, '0')}-15T04:00:00Z`
      expect(formatDateTime(iso)).toMatch(/^15 (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) 2026, 12:00$/)
    }
    expect(formatDateTime('2026-09-15T04:00:00Z')).toBe('15 Sep 2026, 12:00')
  })

  it('uses a 24 hour clock and never prints 24:xx for midnight', () => {
    expect(formatClock('2026-09-25T16:05:00Z')).toBe('00:05') // 00:05 on 26 Sep in Hong Kong
    expect(formatDateTime('2026-09-25T16:05:00Z')).toBe('26 Sep 2026, 00:05')
    expect(formatClock('2026-09-25T15:59:00Z')).toBe('23:59')
  })

  it('rolls the calendar date over with the zone offset (year and leap day)', () => {
    expect(formatDateTime('2026-12-31T16:30:00Z')).toBe('1 Jan 2027, 00:30')
    expect(formatDateTime('2028-02-28T16:00:00Z')).toBe('29 Feb 2028, 00:00')
    expect(formatDateTime('2026-09-25T03:05:00Z', -300)).toBe('24 Sep 2026, 22:05')
  })

  it('does not depend on the machine time zone or the runtime locale data', () => {
    const before = process.env.TZ
    try {
      for (const tz of ['UTC', 'Asia/Tokyo', 'America/Los_Angeles', 'Pacific/Kiritimati']) {
        process.env.TZ = tz
        expect(formatDateTime('2026-09-25T03:05:00Z')).toBe('25 Sep 2026, 11:05')
        expect(formatIsoDate('2026-09-25T20:00:00Z')).toBe('2026-09-26')
      }
    }
    finally {
      if (before === undefined) delete process.env.TZ
      else process.env.TZ = before
    }
  })

  it('gives the Hong Kong calendar date for relativeTime older than a week', () => {
    const now = Date.parse('2026-10-20T12:00:00Z')
    expect(relativeTime('2026-09-30T17:00:00Z', now)).toBe('2026-10-01') // 01:00 on 1 Oct in Hong Kong
  })

  it('returns an empty string for bad input', () => {
    expect(formatIsoDate('')).toBe('')
    expect(formatIsoDate(null)).toBe('')
    expect(formatClock('')).toBe('')
  })
})
