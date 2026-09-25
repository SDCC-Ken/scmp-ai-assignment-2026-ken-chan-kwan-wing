import { test as base, expect } from '@playwright/test'
import { resetData } from './reset'

/**
 * Every test starts from the known seed (auto fixture) and reports uncaught page errors:
 * `unexpectedErrors()` returns the page errors and console errors that are not in `allowed`.
 */
export const test = base.extend<{
  seed: void
  unexpectedErrors: (allowed?: RegExp[]) => string[]
}>({
  seed: [async ({}, use) => { // eslint-disable-line no-empty-pattern
    await resetData()
    await use()
  }, { auto: true }],

  unexpectedErrors: async ({ page }, use) => {
    const seen: string[] = []
    page.on('pageerror', error => seen.push(`pageerror: ${error.message}`))
    page.on('console', (msg) => {
      if (msg.type() === 'error') seen.push(`console: ${msg.text()}`)
    })
    await use((allowed = []) => seen.filter(line => !allowed.some(re => re.test(line))))
  },
})

export { expect }
