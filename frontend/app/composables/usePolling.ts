/**
 * Runs `task` every 30 s while the tab is visible, and again when the tab becomes visible or the window regains
 * focus (never twice within a few seconds, never while a run is still in flight). Call it in `setup`; timers and
 * listeners are removed on unmount. `task` must catch its own errors.
 */
export function usePolling(task: () => Promise<unknown>, options: { intervalMs?: number, immediate?: boolean } = {}) {
  const intervalMs = options.intervalMs ?? POLL_INTERVAL_MS
  let timer: ReturnType<typeof setInterval> | undefined
  let inFlight = false
  let lastRunAt: number | null = null

  async function run() {
    inFlight = true
    lastRunAt = Date.now()
    try {
      await task()
    }
    finally {
      inFlight = false
    }
  }

  function onTick() {
    if (shouldTick({ hidden: document.hidden, inFlight })) void run()
  }

  function onFocusOrVisible() {
    if (shouldRefreshOnFocus({ hidden: document.hidden, inFlight, lastRunAt, now: Date.now() })) void run()
  }

  onMounted(() => {
    if (options.immediate !== false) void run()
    timer = setInterval(onTick, intervalMs)
    document.addEventListener('visibilitychange', onFocusOrVisible)
    window.addEventListener('focus', onFocusOrVisible)
  })

  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
    document.removeEventListener('visibilitychange', onFocusOrVisible)
    window.removeEventListener('focus', onFocusOrVisible)
  })

  return { refresh: run }
}
