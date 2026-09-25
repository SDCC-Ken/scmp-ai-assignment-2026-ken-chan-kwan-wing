/** Pure approval helpers: formatting, limit bars, decision bodies, flags, errors (tests/approvals.test.ts). */
import type {
  ApprovalDetail,
  ApprovalFlags,
  Decision,
  DecisionBody,
  DepartmentBudgetLimit,
  LeaveBalanceLimit,
} from '../types/approvals'
import type { IconName, Tone } from './chat'

export const NOTE_MAX = 500

export function isRequestTypeParam(value: unknown): value is 'leave' | 'claim' {
  return value === 'leave' || value === 'claim'
}

export function approvalPath(type: string, id: number | string): string {
  return `/approvals/${type}/${id}`
}

/* ---- Numbers and money ---- */

/** "3 days", "1 day", "2.5 days", "0 days", "-1.5 days". Non-numbers give an en dash. */
export function formatDays(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '–'
  const rounded = Math.round(value * 100) / 100
  return `${rounded} ${Math.abs(rounded) === 1 ? 'day' : 'days'}`
}

/** Decimal strings from the API ("60000.00") to numbers; anything unusable is 0. */
export function parseAmount(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''))
  return Number.isFinite(n) ? n : 0
}

/** "HKD 47,520.00" (always two decimals; negatives as "HKD -1,500.00"). */
export function formatMoney(value: string | number | null | undefined, currency = 'HKD'): string {
  const n = parseAmount(value)
  const text = new Intl.NumberFormat('en-HK', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n)
  return `${currency} ${text}`
}

export function leaveTypeLabel(type: string | null | undefined): string {
  const key = (type ?? '').trim().toLowerCase()
  if (!key) return 'Leave'
  return `${key.charAt(0).toUpperCase()}${key.slice(1)} leave`
}

/* ---- Limit bar ---- */

export interface BarInput {
  limit: number
  approved: number
  /** Other pending requests (shown, not deducted). */
  pending: number
  /** This request. */
  requested: number
}

export interface BarView {
  /** Percentages of the bar width (0..100), stacked in this order: approved, this request, other pending. */
  approvedPct: number
  requestedPct: number
  pendingPct: number
  /** Where the limit sits on the bar (100 when nothing exceeds it). */
  limitPct: number
  /** approved + requested is beyond the limit (pending by others is not deducted). */
  exceeds: boolean
}

const pct = (part: number, scale: number) => (scale > 0 ? Math.round(Math.max(0, part) / scale * 1000) / 10 : 0)

/**
 * Segment widths for the limit bar. The scale is the larger of the limit and everything shown, so an over-limit
 * bar stays inside its box and the limit marker moves left. A zero limit gives a marker at 0 and full-width bars.
 */
export function limitBar(input: BarInput): BarView {
  const limit = Math.max(0, input.limit)
  const approved = Math.max(0, input.approved)
  const requested = Math.max(0, input.requested)
  const pending = Math.max(0, input.pending)
  const total = approved + requested + pending
  const scale = Math.max(limit, total)
  return {
    approvedPct: pct(approved, scale),
    requestedPct: pct(requested, scale),
    pendingPct: pct(pending, scale),
    limitPct: scale > 0 ? pct(limit, scale) : 0,
    exceeds: approved + requested > limit,
  }
}

export function leaveBarInput(lb: Pick<LeaveBalanceLimit, 'entitled_days' | 'approved_days' | 'pending_other_days' | 'requested_days'>): BarInput {
  return { limit: lb.entitled_days, approved: lb.approved_days, pending: lb.pending_other_days, requested: lb.requested_days }
}

export function budgetBarInput(b: Pick<DepartmentBudgetLimit, 'limit_amount' | 'approved_amount' | 'pending_other_amount' | 'requested_amount'>): BarInput {
  return {
    limit: parseAmount(b.limit_amount),
    approved: parseAmount(b.approved_amount),
    pending: parseAmount(b.pending_other_amount),
    requested: parseAmount(b.requested_amount),
  }
}

export interface LimitRow {
  key: string
  label: string
  value: string
  /** The row that answers "what is left after this request". */
  emphasis?: boolean
}

export function leaveBalanceRows(lb: LeaveBalanceLimit): LimitRow[] {
  return [
    { key: 'entitled', label: `Entitled in ${lb.year}`, value: formatDays(lb.entitled_days) },
    { key: 'approved', label: 'Already approved', value: formatDays(lb.approved_days) },
    { key: 'pending', label: 'Pending (other requests)', value: formatDays(lb.pending_other_days) },
    { key: 'requested', label: 'This request', value: formatDays(lb.requested_days) },
    { key: 'remaining', label: 'Remaining after this request', value: formatDays(lb.remaining_after_days), emphasis: true },
  ]
}

export function budgetRows(b: DepartmentBudgetLimit): LimitRow[] {
  const money = (v: string) => formatMoney(v, b.currency)
  return [
    { key: 'limit', label: `${b.department} limit for ${b.year}`, value: money(b.limit_amount) },
    { key: 'approved', label: 'Already approved', value: money(b.approved_amount) },
    { key: 'pending', label: 'Pending (other requests)', value: money(b.pending_other_amount) },
    { key: 'requested', label: 'This request', value: money(b.requested_amount) },
    { key: 'remaining', label: 'Remaining after this request', value: money(b.remaining_after_amount), emphasis: true },
  ]
}

/** One sentence for the over-limit warning (also repeated in the confirmation dialog); null when within limits. */
export function overLimitSummary(limits: ApprovalDetail['limits'] | null | undefined): string | null {
  const lb = limits?.leave_balance
  if (lb?.over_limit) {
    const by = lb.remaining_after_days < 0 ? ` by ${formatDays(-lb.remaining_after_days)}` : ''
    return `Over the ${leaveTypeLabel(lb.leave_type).toLowerCase()} balance${by}.`
  }
  const budget = limits?.department_budget
  if (budget?.over_limit) {
    const left = parseAmount(budget.remaining_after_amount)
    const by = left < 0 ? ` by ${formatMoney(-left, budget.currency)}` : ''
    return `Over the ${budget.department} department claim limit${by}.`
  }
  return null
}

/** Accessible description of a bar: numbers, not colours. */
export function limitBarLabel(title: string, parts: { limit: string, approved: string, requested: string, pending: string, over: boolean }): string {
  return `${title}: limit ${parts.limit}, approved ${parts.approved}, this request ${parts.requested}, other pending ${parts.pending}.${parts.over ? ' This request goes over the limit.' : ''}`
}

/* ---- Decision ---- */

/** Characters typed (code points, like the backend's count); the counter and the textarea limit use this. */
export function noteLength(note: string): number {
  return Array.from(note).length
}

export function noteRemaining(note: string): number {
  return NOTE_MAX - noteLength(note)
}

export function noteTooLong(note: string): boolean {
  return noteLength(note) > NOTE_MAX
}

/** POST body of a decision: the note is trimmed and an empty note is sent as null. */
export function buildDecisionBody(decision: Decision, note: string | null | undefined): DecisionBody {
  const trimmed = (note ?? '').trim()
  return { decision, note: trimmed ? trimmed : null }
}

export interface DecisionLabels {
  button: string
  confirm: string
  busy: string
  past: string
  tone: Tone
}

export function decisionLabels(decision: Decision): DecisionLabels {
  return decision === 'approve'
    ? { button: 'Approve', confirm: 'Confirm approve', busy: 'Approving...', past: 'approved', tone: 'green' }
    : { button: 'Reject', confirm: 'Confirm reject', busy: 'Rejecting...', past: 'rejected', tone: 'red' }
}

export function decisionSuccessMessage(decision: Decision, type: string, id: number, employee: string): string {
  return `You ${decisionLabels(decision).past} ${type === 'claim' ? 'claim' : 'leave request'} #${id} from ${employee}.`
}

/* ---- List flags ---- */

export interface FlagBadge {
  key: 'over_limit' | 'team_overlap' | 'attachments'
  label: string
  tone: Tone
  icon: IconName | 'users' | 'paperclip'
}

/** Badges for a list row: only the flags that apply; each has an icon and text (colour is never the only cue). */
export function flagBadges(flags: ApprovalFlags | null | undefined): FlagBadge[] {
  const out: FlagBadge[] = []
  if (!flags) return out
  if (flags.over_limit) out.push({ key: 'over_limit', label: 'Over limit', tone: 'amber', icon: 'alert' })
  if (flags.team_overlap_count > 0) {
    out.push({ key: 'team_overlap', label: `${flags.team_overlap_count} on leave in the team`, tone: 'grey', icon: 'users' })
  }
  if (flags.has_attachments) out.push({ key: 'attachments', label: 'Has attachment', tone: 'grey', icon: 'paperclip' })
  return out
}

/* ---- Errors ---- */

export type ApprovalPhase = 'list' | 'detail' | 'decision'

/** User-facing message for an approvals API failure (never echoes server text). `status` undefined = network error. */
export function approvalErrorMessage(status: number | undefined, phase: ApprovalPhase): string {
  if (status === undefined) return 'Cannot reach the server. Check your connection and try again.'
  if (status === 409) return 'This request was already decided or changed.'
  if (status === 404) return phase === 'list' ? 'Approvals are not available.' : 'This request is no longer available.'
  if (status === 403) return 'You are not allowed to do that.'
  if (status === 422) return 'That decision was not accepted. Keep the note under 500 characters.'
  if (status === 429) return 'Too many requests. Please wait a moment and try again.'
  if (status >= 500) return 'The server had a problem. Please try again in a moment.'
  return 'Something went wrong. Please try again.'
}

/** Dates for the team list, "2026-10-06" or "2026-10-05 to 2026-10-07". */
export function dateRange(start: string, end: string): string {
  return start === end || !end ? start : `${start} to ${end}`
}
