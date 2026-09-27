/**
 * Capture the real, isolated Robin/Mia bell flow for Presentation Scene 03.
 *
 * Each reset touches only the dedicated fixture, never the ordinary Scene 02 data.
 * Run after `docker compose up --build -d`:
 *   bun e2e/capture-approver-presentation.mjs
 */
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const output = resolve(root, 'frontend/public/presentation')
const resetScript = [
  'import os, urllib.request',
  'request = urllib.request.Request("http://127.0.0.1:9181/api/presentation/reset-approval-demo", method="POST", headers={"X-Requested-With":"XMLHttpRequest", "X-Presentation-Reset": os.environ["PRESENTATION_RESET_TOKEN"]})',
  'urllib.request.urlopen(request, timeout=5).read()',
].join('; ')

mkdirSync(output, { recursive: true })

function resetFixture() {
  console.log('Resetting isolated fixture')
  execFileSync('docker', ['compose', 'exec', '-T', 'api', 'python', '-c', resetScript], {
    cwd: root,
    stdio: 'inherit',
  })
}

const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

async function signIn(name) {
  console.log(`Signing in as ${name}`)
  await page.goto('http://localhost:9180/login')
  const dialog = page.getByRole('dialog', { name: /Sign in with Google/ })
  await dialog.getByRole('button', { name: new RegExp(name) }).click()
  await page.locator('header').getByText(name, { exact: true }).waitFor()
}

async function signOut() {
  console.log('Signing out')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByRole('dialog', { name: /Sign in with Google/ }).waitFor()
}

async function openRobinCard() {
  console.log('Opening Robin inbox')
  const bell = page.locator('button[title="Open your inbox"]')
  await bell.waitFor({ state: 'visible', timeout: 5000 })
  await bell.click({ noWaitAfter: true, timeout: 5000 })
  await page.waitForTimeout(350)
  console.log(`Robin inbox URL: ${page.url()}`)
  const card = page.getByRole('region', { name: /^Leave request #\d+ from Mia Chan/ })
  await card.waitFor({ timeout: 8000 })
  return card
}

// 03A: a bell opens the real isolated review conversation.
resetFixture()
await signIn('Robin Ho')
let card = await openRobinCard()
console.log('Capturing 03A')
await page.screenshot({ path: resolve(output, '03a-bell-inbox.png') })

// 03B: the approval confirmation, before any decision is written.
await card.getByLabel('Note for the employee (optional)').fill('Coverage confirmed for this period.')
await card.getByRole('button', { name: 'Approve', exact: true }).click()
await card.getByRole('button', { name: 'Confirm approve', exact: true }).waitFor()
console.log('Capturing 03B')
await page.screenshot({ path: resolve(output, '03b-approve-confirm.png') })
await signOut()

// 03C: the same real card at its separate reject-confirmation step.
resetFixture()
await signIn('Robin Ho')
card = await openRobinCard()
await card.getByLabel('Note for the employee (optional)').fill('Coverage is required for this period.')
await card.getByRole('button', { name: 'Reject', exact: true }).click()
await card.getByRole('button', { name: 'Confirm reject', exact: true }).waitFor()
console.log('Capturing 03C')
await page.screenshot({ path: resolve(output, '03c-reject-confirm.png') })
await signOut()

// 03D: complete a fresh approval, then capture Mia's real notification before "Got it" is used.
resetFixture()
await signIn('Robin Ho')
card = await openRobinCard()
await card.getByLabel('Note for the employee (optional)').fill('Coverage confirmed for this period.')
await card.getByRole('button', { name: 'Approve', exact: true }).click()
await card.getByRole('button', { name: 'Confirm approve', exact: true }).click()
await page.locator('p').filter({ hasText: /You approved leave request #\d+ from Mia Chan/ }).waitFor()
await signOut()
await signIn('Mia Chan')
await page.locator('button[title="Open your inbox"]').click({ noWaitAfter: true })
await page.getByRole('region', { name: /^Your leave request #\d+ was approved/ }).waitFor()
console.log('Capturing 03D')
await page.screenshot({ path: resolve(output, '03d-employee-notification.png') })

await context.close()
await browser.close()
// Leave the live fixture ready to start, not with a completed decision from capture 03D.
resetFixture()
console.log(`Saved Scene 03 screenshots to ${output}`)
