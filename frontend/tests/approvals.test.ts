import { describe, expect, it } from 'vitest'
import {
  approvalErrorMessage,
  buildDecisionBody,
  budgetBarInput,
  budgetRows,
  dateRange,
  decisionLabels,
  decisionSuccessMessage,
  flagBadges,
  formatDays,
  formatMoney,
  leaveBalanceRows,
  leaveBarInput,
  leaveTypeLabel,
  limitBar,
  NOTE_MAX,
  noteRemaining,
  noteTooLong,
  overLimitSummary,
  parseAmount,
} from '../app/utils/approvals'
import type { DepartmentBudgetLimit, LeaveBalanceLimit } from '../app/types/approvals'

const leave: LeaveBalanceLimit = {
  leave_type: 'annual', year: 2026, entitled_days: 15, approved_days: 12, pending_other_days: 0,
  requested_days: 5, remaining_after_days: -2, over_limit: true,
}
const budget: DepartmentBudgetLimit = {
  department: 'IT', year: 2026, limit_amount: '60000.00', approved_amount: '59900.00', pending_other_amount: '300.00',
  requested_amount: '246.50', remaining_after_amount: '-146.50', over_limit: true, currency: 'HKD',
}

describe('days and money formatting', () => {
  it('formats days with the right unit and half days', () => {
    expect(formatDays(1)).toBe('1 day')
    expect(formatDays(0)).toBe('0 days')
    expect(formatDays(2.5)).toBe('2.5 days')
    expect(formatDays(-1.5)).toBe('-1.5 days')
    expect(formatDays(Number.NaN)).toBe('–')
    expect(formatDays(undefined)).toBe('–')
  })

  it('formats currency with grouping and two decimals, including negatives', () => {
    expect(formatMoney('47520.00', 'HKD')).toBe('HKD 47,520.00')
    expect(formatMoney('180', 'HKD')).toBe('HKD 180.00')
    expect(formatMoney('-146.5', 'HKD')).toBe('HKD -146.50')
    expect(formatMoney('nonsense')).toBe('HKD 0.00')
  })

  it('parses decimal strings safely', () => {
    expect(parseAmount('60000.00')).toBe(60000)
    expect(parseAmount(null)).toBe(0)
    expect(parseAmount('x')).toBe(0)
  })

  it('names leave types', () => {
    expect(leaveTypeLabel('annual')).toBe('Annual leave')
    expect(leaveTypeLabel('SICK')).toBe('Sick leave')
    expect(leaveTypeLabel('')).toBe('Leave')
  })
})

describe('limit bar percentages', () => {
  it('splits a normal balance into approved, this request and pending, marking the limit at the end', () => {
    const bar = limitBar({ limit: 15, approved: 3, pending: 2.5, requested: 2.5 })
    expect(bar.approvedPct).toBe(20)
    expect(bar.requestedPct).toBe(16.7)
    expect(bar.pendingPct).toBe(16.7)
    expect(bar.limitPct).toBe(100)
    expect(bar.exceeds).toBe(false)
  })

  it('scales to what is shown when over the limit and moves the limit marker left', () => {
    const bar = limitBar(leaveBarInput(leave))
    expect(bar.exceeds).toBe(true)
    expect(bar.approvedPct + bar.requestedPct + bar.pendingPct).toBeCloseTo(100, 0)
    expect(bar.limitPct).toBeCloseTo(88.2, 1)
  })

  it('handles a zero limit without dividing by zero', () => {
    const none = limitBar({ limit: 0, approved: 0, pending: 0, requested: 0 })
    expect(none).toEqual({ approvedPct: 0, requestedPct: 0, pendingPct: 0, limitPct: 0, exceeds: false })
    const over = limitBar({ limit: 0, approved: 0, pending: 0, requested: 100 })
    expect(over.requestedPct).toBe(100)
    expect(over.limitPct).toBe(0)
    expect(over.exceeds).toBe(true)
  })

  it('never returns negative or NaN percentages for odd input', () => {
    const bar = limitBar({ limit: 10, approved: -5, pending: Number.NaN as number, requested: 3 })
    for (const value of [bar.approvedPct, bar.requestedPct, bar.pendingPct, bar.limitPct]) {
      expect(Number.isFinite(value)).toBe(true)
      expect(value).toBeGreaterThanOrEqual(0)
    }
  })

  it('reads budget money strings for the bar', () => {
    const bar = limitBar(budgetBarInput(budget))
    expect(bar.exceeds).toBe(true)
    expect(bar.approvedPct).toBeGreaterThan(95)
  })
})

describe('limit rows and over-limit wording', () => {
  it('lists the leave balance lines in the agreed order', () => {
    const rows = leaveBalanceRows(leave)
    expect(rows.map(r => r.key)).toEqual(['entitled', 'approved', 'pending', 'requested', 'remaining'])
    expect(rows.at(-1)).toMatchObject({ value: '-2 days', emphasis: true })
    expect(rows[0]!.label).toBe('Entitled in 2026')
  })

  it('lists the department budget lines with currency formatting', () => {
    const rows = budgetRows(budget)
    expect(rows[0]).toMatchObject({ label: 'IT limit for 2026', value: 'HKD 60,000.00' })
    expect(rows.at(-1)!.value).toBe('HKD -146.50')
  })

  it('writes the over-limit sentence for leave and claims, and nothing when within limits', () => {
    expect(overLimitSummary({ leave_balance: leave, department_budget: null })).toBe('Over the annual leave balance by 2 days.')
    expect(overLimitSummary({ leave_balance: null, department_budget: budget })).toBe('Over the IT department claim limit by HKD 146.50.')
    expect(overLimitSummary({ leave_balance: { ...leave, over_limit: false }, department_budget: null })).toBeNull()
    expect(overLimitSummary({ leave_balance: null, department_budget: null })).toBeNull()
    expect(overLimitSummary(null)).toBeNull()
  })
})

describe('decision body and note', () => {
  it('trims the note and sends an empty note as null', () => {
    expect(buildDecisionBody('approve', '  Enjoy the trip.  ')).toEqual({ decision: 'approve', note: 'Enjoy the trip.' })
    expect(buildDecisionBody('reject', '   ')).toEqual({ decision: 'reject', note: null })
    expect(buildDecisionBody('reject', '')).toEqual({ decision: 'reject', note: null })
    expect(buildDecisionBody('approve', null)).toEqual({ decision: 'approve', note: null })
  })

  it('counts the 500-character note limit', () => {
    expect(NOTE_MAX).toBe(500)
    expect(noteRemaining('')).toBe(500)
    expect(noteRemaining('a'.repeat(120))).toBe(380)
    expect(noteTooLong('a'.repeat(500))).toBe(false)
    expect(noteTooLong('a'.repeat(501))).toBe(true)
  })

  it('labels the two decisions and their confirmation buttons', () => {
    expect(decisionLabels('approve')).toMatchObject({ button: 'Approve', confirm: 'Confirm approve', busy: 'Approving...' })
    expect(decisionLabels('reject')).toMatchObject({ button: 'Reject', confirm: 'Confirm reject', busy: 'Rejecting...' })
    expect(decisionSuccessMessage('approve', 'leave', 12, 'Amy Lau')).toBe('You approved leave request #12 from Amy Lau.')
    expect(decisionSuccessMessage('reject', 'claim', 9, 'Amy Lau')).toBe('You rejected claim #9 from Amy Lau.')
  })
})

describe('list flags and errors', () => {
  it('shows only the flags that apply, each with text', () => {
    expect(flagBadges({ over_limit: false, team_overlap_count: 0, has_attachments: false })).toEqual([])
    const all = flagBadges({ over_limit: true, team_overlap_count: 2, has_attachments: true })
    expect(all.map(b => b.label)).toEqual(['Over limit', '2 on leave in the team', 'Has attachment'])
    expect(all[0]).toMatchObject({ tone: 'amber', icon: 'alert' })
    expect(flagBadges(null)).toEqual([])
  })

  it('maps API failures to friendly text without echoing the server', () => {
    expect(approvalErrorMessage(409, 'decision')).toBe('This request was already decided or changed.')
    expect(approvalErrorMessage(404, 'decision')).toBe('This request is no longer available.')
    expect(approvalErrorMessage(undefined, 'list')).toMatch(/Cannot reach/)
    expect(approvalErrorMessage(500, 'detail')).toMatch(/server had a problem/)
    expect(approvalErrorMessage(422, 'decision')).toMatch(/500/)
  })

  it('formats date ranges', () => {
    expect(dateRange('2026-10-06', '2026-10-06')).toBe('2026-10-06')
    expect(dateRange('2026-10-05', '2026-10-07')).toBe('2026-10-05 to 2026-10-07')
  })
})
