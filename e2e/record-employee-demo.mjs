/**
 * Creates the reusable Section 02 recording against the locally running Docker app.
 * It deliberately uses the configured Ollama provider, never a Gemini key.
 *
 * Run after `docker compose up --build -d`:
 *   bun e2e/record-employee-demo.mjs
 */
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdirSync, renameSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const recordings = resolve(root, 'e2e/.tmp/employee-recording')
const output = resolve(root, 'frontend/public/demo/employee-journey.webm')

mkdirSync(recordings, { recursive: true })
mkdirSync(resolve(root, 'frontend/public/demo'), { recursive: true })
// Scope is exactly the fictional Docker demo database and uploaded sample files.
execFileSync('docker', ['compose', 'exec', '-T', 'api', 'python', '-m', 'app.cli', 'reset-demo', '--yes'], { cwd: root, stdio: 'inherit' })

// Do not inherit the desktop VPN/proxy when the recording calls localhost Docker services.
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--no-proxy-server'] })
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: recordings, size: { width: 1280, height: 720 } },
})
const page = await context.newPage()
const wait = ms => page.waitForTimeout(ms)

async function newChat() {
  const created = page.waitForResponse(response => response.url().includes('/api/chat/conversations') && response.request().method() === 'POST', { timeout: 30_000 })
  await page.getByRole('button', { name: 'New chat' }).click()
  await created
  await page.getByLabel('Message', { exact: true }).waitFor({ state: 'visible' })
  await page.waitForTimeout(150)
}

async function send(text) {
  await page.getByLabel('Message', { exact: true }).fill(text)
  await page.getByRole('button', { name: 'Send', exact: true }).waitFor({ state: 'visible' })
  try {
    await page.waitForFunction(() => [...document.querySelectorAll('button')]
      .some(button => button.textContent?.trim() === 'Send' && !button.hasAttribute('disabled')), undefined, { timeout: 5_000 })
  } catch {
    console.log(`Composer value: ${await page.getByLabel('Message', { exact: true }).inputValue()}`)
    console.log(`Send disabled: ${await page.getByRole('button', { name: 'Send', exact: true }).isDisabled()}`)
    throw new Error('Send did not unlock after text entry')
  }
  await page.getByRole('button', { name: 'Send', exact: true }).click({ noWaitAfter: true, timeout: 5_000 })
}

async function finish() {
  const videoPath = await page.video()?.path()
  await context.close()
  await browser.close()
  if (!videoPath) throw new Error('Playwright did not create a recording')
  renameSync(videoPath, output)
  console.log(`Saved ${output}`)
}

await page.goto('http://localhost:9180/login')
console.log('Recording: mock login')
await page.getByRole('dialog', { name: /Sign in with Google/ }).getByRole('button', { name: /Amy Lau/ }).click()
await page.getByRole('button', { name: 'New chat' }).waitFor({ state: 'visible' })
await wait(900)

// A: show the mock account and B: show the holiday validation followed by a valid request.
await newChat()
console.log('Recording: holiday validation')
await send('Annual leave on 2026-10-01')
// Let the spoken error remain visible, but do not make the recorder depend on a wording detail.
await wait(2500)

await newChat()
console.log('Recording: leave create')
await send('Annual leave from 2026-09-30 to 2026-10-05')
const createCard = page.getByRole('region', { name: 'Confirm leave application' })
await createCard.waitFor({ state: 'visible', timeout: 90_000 })
await wait(1200)
await createCard.getByRole('button', { name: 'Submit', exact: true }).click()
const submitted = page.getByRole('region', { name: 'Submitted result' })
await submitted.waitFor({ state: 'visible', timeout: 30_000 })
const requestId = /#(\d+)/.exec(await submitted.innerText())?.[1]
if (!requestId) throw new Error('Could not read created leave request id')
await wait(1100)

if (process.env.RECORD_CHAPTERS === 'leave') {
  await finish()
  process.exit(0)
}

// C: owner changes the still-pending request; the changed fields stay visible on the confirmation card.
await newChat()
console.log('Recording: leave change')
await send(`Change leave request #${requestId} so it ends on 2026-10-06`)
const updateCard = page.getByRole('region', { name: 'Confirm changes to leave application' })
await updateCard.waitFor({ state: 'visible', timeout: 90_000 })
await wait(1100)
await updateCard.getByRole('button', { name: 'Save changes', exact: true }).click()
await page.getByRole('region', { name: 'Updated result' }).waitFor({ state: 'visible', timeout: 30_000 })
await wait(900)

// D: the same owner withdraws the same pending request.
await newChat()
console.log('Recording: leave cancel')
await send(`Cancel leave request #${requestId}`)
const cancelCard = page.getByRole('region', { name: `Confirm cancellation of Leave request #${requestId}` })
await cancelCard.waitFor({ state: 'visible', timeout: 90_000 })
await wait(900)
await cancelCard.getByRole('button', { name: 'Cancel request', exact: true }).click()
await page.getByRole('region', { name: 'Cancelled result' }).waitFor({ state: 'visible', timeout: 30_000 })
await wait(900)

// E: a fictional PNG receipt exercises the image/document path using Gemma locally.
await newChat()
console.log('Recording: receipt claim')
await page.locator('input[type=file]').setInputFiles(resolve(root, 'backend/samples/receipt-sample.png'))
await send('Create a staff claim from this receipt')
await page.getByText(/Confirm staff claim|I could not read|What date/i).first().waitFor({ state: 'visible', timeout: 90_000 })
await wait(1800)

await finish()
