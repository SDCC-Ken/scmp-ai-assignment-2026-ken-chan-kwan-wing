import { defineConfig } from '@playwright/test'
import base from './playwright.config'

/**
 * Documentation screenshots (`bun run screenshots`): same offline stack and servers as the tests, but only
 * `tests/screenshots.spec.ts`, at a fixed 1280x800 viewport in the light theme. Writes into `docs/screenshots/`.
 */
export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: 'screenshots.spec.ts',
  outputDir: './test-results-screenshots',
  reporter: [['list']],
  use: {
    ...base.use,
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    colorScheme: 'light',
    locale: 'en-GB',
    timezoneId: 'Asia/Hong_Kong',
    screenshot: 'off',
    trace: 'off',
  },
})
