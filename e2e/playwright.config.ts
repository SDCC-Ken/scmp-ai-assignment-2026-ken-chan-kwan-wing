import { defineConfig } from '@playwright/test'
import { API_URL, WEB_URL } from './support/env.mjs'

export default defineConfig({
  testDir: './tests',
  testIgnore: 'screenshots.spec.ts', // documentation screenshots run only via `bun run screenshots`
  outputDir: './test-results',
  fullyParallel: false,
  workers: 1, // one shared API and database: tests run one after another
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: WEB_URL,
    // System Google Chrome. Fallback without Chrome: `bunx playwright install chromium`, then run with E2E_BROWSER=chromium.
    channel: process.env.E2E_BROWSER === 'chromium' ? undefined : 'chrome',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1280, height: 900 },
  },
  webServer: [
    {
      name: 'api',
      command: 'node support/start-api.mjs',
      url: `${API_URL}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      name: 'web',
      command: 'node support/start-web.mjs',
      url: `${WEB_URL}/login`,
      reuseExistingServer: false,
      timeout: 300_000, // includes the one-off frontend build
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
