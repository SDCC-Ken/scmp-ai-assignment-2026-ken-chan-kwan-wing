/** Polling rules shared by the bell and the approvals list (pure; tests/notifications.test.ts). */

export const POLL_INTERVAL_MS = 30_000
/** Focus and visibility events fire together; ignore a second refresh inside this window. */
export const POLL_MIN_GAP_MS = 5_000

export interface PollState {
  hidden: boolean
  inFlight: boolean
  lastRunAt: number | null
  now: number
}

/** The 30 s timer: skip while the tab is hidden or a refresh is already running. */
export function shouldTick(state: Pick<PollState, 'hidden' | 'inFlight'>): boolean {
  return !state.hidden && !state.inFlight
}

/** Focus / visibility return: refresh at once unless one just ran or is running. */
export function shouldRefreshOnFocus(state: PollState, minGapMs: number = POLL_MIN_GAP_MS): boolean {
  if (state.hidden || state.inFlight) return false
  return state.lastRunAt === null || state.now - state.lastRunAt >= minGapMs
}
