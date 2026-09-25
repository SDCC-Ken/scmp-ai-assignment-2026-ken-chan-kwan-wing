import { describe, expect, it } from 'vitest'
import { balanceLineView, normalizeInfoLines, traceStepLabel, validBalanceLines } from '../app/utils/chatExtras'
import { announcementFor } from '../app/utils/chat'
import type { Message } from '../app/types/chat'

describe('confirmation card info lines', () => {
  it('reads the design shape and keeps the tone', () => {
    const lines = normalizeInfoLines([
      { label: 'Annual leave balance 2026', value: '15 days, 3 used, 12 left', tone: 'info' },
      { label: 'Heads-up', value: 'Ben is also away', tone: 'warning' },
    ])
    expect(lines).toEqual([
      { label: 'Annual leave balance 2026', value: '15 days, 3 used, 12 left', tone: 'info' },
      { label: 'Heads-up', value: 'Ben is also away', tone: 'warning' },
    ])
  })

  it('tolerates plain strings and unknown tones, and drops blanks and junk', () => {
    const lines = normalizeInfoLines(['  9.5 left after this request  ', '', { label: 'X', value: 'Y', tone: 'loud' }, { label: 'no value' }, 42, null])
    expect(lines).toEqual([
      { label: '', value: '9.5 left after this request', tone: 'info' },
      { label: 'X', value: 'Y', tone: 'info' },
    ])
  })

  it('returns an empty list when there is no info', () => {
    expect(normalizeInfoLines(undefined)).toEqual([])
    expect(normalizeInfoLines(null)).toEqual([])
    expect(normalizeInfoLines('text')).toEqual([])
  })
})

describe('trace step labels', () => {
  it('uses the label from the API, then a known label, then a readable key', () => {
    expect(traceStepLabel({ step: 'documents', label: 'Read the certificate' })).toBe('Read the certificate')
    expect(traceStepLabel({ step: 'documents', label: '' })).toBe('Read attached documents')
    expect(traceStepLabel({ step: 'check_policy', label: '' })).toBe('Check policy')
    expect(traceStepLabel({ step: '', label: '' })).toBe('Processing step')
  })
})

describe('balance card', () => {
  const annual = { leave_type: 'annual', entitled_days: 15, approved_days: 3, pending_days: 2.5, remaining_days: 12 }

  it('summarises a line with numbers and bar segments', () => {
    const view = balanceLineView(annual)
    expect(view.label).toBe('Annual leave')
    expect(view.summary).toBe('12 days left of 15 days')
    expect(view.bar.approvedPct).toBe(20)
    expect(view.bar.pendingPct).toBe(16.7)
    expect(view.stats.map(s => s.value)).toEqual(['15 days', '3 days', '2.5 days', '12 days'])
  })

  it('ignores lines with non-numeric days', () => {
    const lines = validBalanceLines({ lines: [annual, { ...annual, leave_type: 'sick', remaining_days: 'lots' as unknown as number }] })
    expect(lines).toHaveLength(1)
    expect(validBalanceLines(undefined)).toEqual([])
  })

  it('is announced to screen readers', () => {
    const message: Message = {
      id: 1, sender_type: 'assistant', content: 'Here is your balance.', created_at: '2026-09-25T03:10:00Z', trace: null,
      ui: { type: 'balance_card', year: 2026, lines: [annual] },
    }
    expect(announcementFor(message)).toContain('Leave balance for 2026')
  })
})
