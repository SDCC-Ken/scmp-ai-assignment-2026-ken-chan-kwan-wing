/** Phase 3 chat additions: card info lines, balance card lines, trace step labels (tests/chat-additions.test.ts). */
import type { BalanceCardData, BalanceLine, ConfirmationCardData, InfoLine, TraceStep } from '../types/chat'
import { formatDays, leaveTypeLabel, limitBar } from './approvals'
import type { BarView } from './approvals'

/**
 * Info lines of a confirmation card. The design shape is `{label, value, tone}`; a plain string (no label) is
 * tolerated and shown as an info line. Blank or malformed entries are dropped; an unknown tone becomes "info".
 */
export function normalizeInfoLines(raw: ConfirmationCardData['info'] | unknown): InfoLine[] {
  if (!Array.isArray(raw)) return []
  const out: InfoLine[] = []
  for (const entry of raw as unknown[]) {
    if (typeof entry === 'string') {
      const value = entry.trim()
      if (value) out.push({ label: '', value, tone: 'info' })
    }
    else if (typeof entry === 'object' && entry !== null) {
      const e = entry as Record<string, unknown>
      const value = typeof e.value === 'string' ? e.value.trim() : ''
      if (!value) continue
      out.push({
        label: typeof e.label === 'string' ? e.label.trim() : '',
        value,
        tone: e.tone === 'warning' ? 'warning' : 'info',
      })
    }
  }
  return out
}

const TRACE_LABELS: Readonly<Record<string, string>> = {
  understand: 'Understood your message',
  documents: 'Read attached documents',
  merge: 'Merged with earlier details',
  validate: 'Validated the details',
  decide: 'Decided the next step',
  submit: 'Submitted the request',
  status: 'Looked up your requests',
  respond: 'Wrote the answer',
}

/** "documents" -> "Read attached documents"; unknown step names fall back to a readable form of the key. */
export function traceStepLabel(step: Pick<TraceStep, 'step' | 'label'>): string {
  const own = (step.label ?? '').trim()
  if (own) return own
  const key = String(step.step ?? '').trim()
  if (TRACE_LABELS[key]) return TRACE_LABELS[key]
  const words = key.replace(/[_-]+/g, ' ').trim()
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : 'Processing step'
}

/** Only balance lines with numeric days are drawn; anything else from the API is ignored. */
export function validBalanceLines(card: Pick<BalanceCardData, 'lines'> | null | undefined): BalanceLine[] {
  const lines = Array.isArray(card?.lines) ? card.lines : []
  return lines.filter(l => l && typeof l.leave_type === 'string'
    && [l.entitled_days, l.approved_days, l.pending_days, l.remaining_days].every(n => typeof n === 'number' && Number.isFinite(n)))
}

export interface BalanceLineView {
  label: string
  bar: BarView
  summary: string
  stats: { key: string, label: string, value: string }[]
}

/** Numbers and bar segments of one balance line (pending is shown on the bar but not deducted). */
export function balanceLineView(line: BalanceLine): BalanceLineView {
  return {
    label: leaveTypeLabel(line.leave_type),
    bar: limitBar({ limit: line.entitled_days, approved: line.approved_days, pending: line.pending_days, requested: 0 }),
    summary: `${formatDays(line.remaining_days)} left of ${formatDays(line.entitled_days)}`,
    stats: [
      { key: 'entitled', label: 'Entitled', value: formatDays(line.entitled_days) },
      { key: 'approved', label: 'Approved', value: formatDays(line.approved_days) },
      { key: 'pending', label: 'Pending', value: formatDays(line.pending_days) },
      { key: 'remaining', label: 'Remaining', value: formatDays(line.remaining_days) },
    ],
  }
}
