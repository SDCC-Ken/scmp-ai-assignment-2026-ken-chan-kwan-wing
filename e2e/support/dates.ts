import fs from 'node:fs'
import path from 'node:path'
import { BACKEND_DIR } from './env.mjs'

/**
 * Today's date in Hong Kong as ISO (the backend judges "past" and "future" by the Hong Kong date).
 * Computed from the UTC+8 offset instead of `Intl`, whose output depends on the runtime's ICU data.
 */
export function hkToday(): string {
  return new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10)
}

let holidays: Set<string> | undefined
/** Hong Kong public holidays from the bundled 1823 calendar the backend seeds from. */
function publicHolidays(): Set<string> {
  if (!holidays) {
    const ics = fs.readFileSync(path.join(BACKEND_DIR, 'app', 'data', 'hk_public_holidays_1823.ics'), 'utf8')
    holidays = new Set(
      [...ics.matchAll(/DTSTART;VALUE=DATE:(\d{4})(\d{2})(\d{2})/g)].map(m => `${m[1]}-${m[2]}-${m[3]}`),
    )
  }
  return holidays
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const weekday = (iso: string) => new Date(`${iso}T00:00:00Z`).getUTCDay() // 0 Sun .. 6 Sat

export interface LeaveRange {
  start: string
  end: string
  /** Working days of the range (always 2: a Tuesday and the following Wednesday, neither a holiday). */
  workingDays: 2
}

/**
 * A two-working-day annual-leave range (Tuesday and Wednesday, so never a Fri-Sat-Sun range) that
 * starts at least `weeksAhead` weeks from today (Hong Kong) and is not a public holiday.
 * The seed puts its leave inside the next ~25 days, so `weeksAhead >= 6` never clashes with it;
 * different `weeksAhead` values give different, non-overlapping ranges.
 */
export function futureLeaveRange(weeksAhead = 6): LeaveRange {
  let day = addDays(hkToday(), weeksAhead * 7)
  for (let i = 0; i < 400; i++, day = addDays(day, 1)) {
    const next = addDays(day, 1)
    if (weekday(day) === 2 && !publicHolidays().has(day) && !publicHolidays().has(next)) {
      return { start: day, end: next, workingDays: 2 }
    }
  }
  throw new Error('No suitable leave range found in the bundled holiday calendar')
}

/** "Tue 2026-11-03" style label the UI uses for a date (English weekday abbreviation + ISO date). */
export function weekdayLabel(iso: string): string {
  const names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  return `${names[weekday(iso)]} ${iso}`
}
