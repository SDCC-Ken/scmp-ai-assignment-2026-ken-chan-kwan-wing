import { test, expect } from '../support/fixtures'
import { signInAs } from '../support/auth'
import { composer, sendMessage, startNewChat } from '../support/chat'
import { futureLeaveRange, weekdayLabel } from '../support/dates'

/**
 * E2E test 3: safe failure states in the chat. Nothing crashes, nothing typed is lost where the UI
 * promises it, and normal use resumes afterwards.
 */
const MESSAGES = '**/api/chat/conversations/*/messages'
// The one console line the browser prints for an aborted request; anything else is a real error.
const EXPECTED_ABORT = [/Failed to load resource: net::ERR_FAILED/]

test('network failure on send: inline error, text kept, Retry recovers', async ({ page, unexpectedErrors }) => {
  const { start, end } = futureLeaveRange(6)
  const text = `I need annual leave from ${start} to ${end}`

  await signInAs(page, 'Amy Lau')
  await startNewChat(page)

  // The message POST fails at network level (the connection is dropped), once.
  let aborted = 0
  await page.route(MESSAGES, (route) => {
    aborted++
    return route.abort('failed')
  })
  await sendMessage(page, text)

  const alert = page.getByRole('alert').filter({ hasText: 'Cannot reach the server' })
  await expect(alert).toBeVisible()
  await expect(alert).toContainText('Check your connection and try again.')
  await expect(alert.getByRole('button', { name: 'Retry' })).toBeVisible()
  expect(aborted).toBe(1)
  // The typed text is kept in the composer, the failed message is not shown as sent, no card appeared.
  await expect(composer(page)).toHaveValue(text)
  await expect(page.getByRole('heading', { name: 'How can I help today?' })).toBeVisible() // still an empty thread
  await expect(page.getByText(text, { exact: true })).toHaveCount(0) // (only the composer holds it: it is a value, not text)
  await expect(page.getByRole('region', { name: 'Confirm leave application' })).toHaveCount(0)

  // Connection is back: Retry sends the same text and the normal reply appears.
  await page.unroute(MESSAGES)
  await alert.getByRole('button', { name: 'Retry' }).click()
  const card = page.getByRole('region', { name: 'Confirm leave application' })
  await expect(card).toBeVisible()
  await expect(card).toContainText(weekdayLabel(start))
  await expect(alert).toHaveCount(0)
  await expect(composer(page)).toHaveValue('')
  await expect(composer(page)).toBeEnabled()
  expect(aborted).toBe(1)

  // The page never crashed: no uncaught errors, and only the expected failed request in the console.
  expect(unexpectedErrors(EXPECTED_ABORT)).toEqual([])
})

test('server error on send: inline error with Retry (HTTP 500)', async ({ page, unexpectedErrors }) => {
  await signInAs(page, 'Amy Lau')
  await startNewChat(page)
  await page.route(MESSAGES, route => route.fulfill({
    status: 500,
    contentType: 'application/json',
    headers: { 'access-control-allow-origin': 'http://localhost:9280', 'access-control-allow-credentials': 'true' },
    body: JSON.stringify({ detail: 'boom' }),
  }))
  await sendMessage(page, 'what is the status of my requests?')
  const alert = page.getByRole('alert').filter({ hasText: 'The server had a problem' })
  await expect(alert).toBeVisible()
  await expect(alert).not.toContainText('boom') // server text is never echoed
  await expect(composer(page)).toHaveValue('what is the status of my requests?')

  await page.unroute(MESSAGES)
  await alert.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByRole('region', { name: 'Your requests' })).toBeVisible()
  await expect(alert).toHaveCount(0)
  expect(unexpectedErrors([/Failed to load resource: the server responded with a status of 500/])).toEqual([])
})

test('LLM outage: banner, conversation and draft intact, chat keeps working', async ({ page, unexpectedErrors }) => {
  const { start, end } = futureLeaveRange(9)

  await signInAs(page, 'Amy Lau')
  await startNewChat(page)

  // An earlier draft: a leave confirmation card that is waiting for Submit.
  await sendMessage(page, `annual leave from ${start} to ${end}`)
  const card = page.getByRole('region', { name: 'Confirm leave application' })
  await expect(card.getByRole('button', { name: 'Submit', exact: true })).toBeVisible()

  // Test-only trigger of the fake LLM: it raises LLMError("Simulated outage") for this marker.
  await sendMessage(page, 'please help [[llm-down]]')

  const banner = page.getByRole('status').filter({ hasText: 'The AI service is unavailable, please try again.' })
  await expect(banner).toBeVisible()
  const messages = page.getByRole('list', { name: 'Messages' })
  await expect(messages.getByText("I couldn't reach the AI service just now, so nothing was changed.")).toBeVisible()
  // Nothing was lost: the earlier user message and the draft's card are still there and still open.
  await expect(messages.getByText(`annual leave from ${start} to ${end}`)).toBeVisible()
  await expect(card).toBeVisible()
  await expect(card.getByRole('button', { name: 'Submit', exact: true })).toBeEnabled()
  // The composer stays usable.
  await expect(composer(page)).toBeEnabled()

  // GAP (reported): the banner has only "Dismiss warning"; there is no "Try again" button and the
  // message that hit the outage is not put back in the composer, so the user has to retype it.
  await expect(banner.getByRole('button', { name: /retry|try again/i })).toHaveCount(0)
  await expect(composer(page)).toHaveValue('')

  // Sending a normal message works again (the fake LLM is only down for the marker).
  await sendMessage(page, 'what is the status of my requests?')
  await expect(page.getByRole('region', { name: 'Your requests' })).toBeVisible()
  await expect(banner).toHaveCount(0)

  // And the original draft survived the outage: Submit still files exactly that request.
  await card.getByRole('button', { name: 'Submit', exact: true }).click()
  const result = page.getByRole('region', { name: 'Submitted result' })
  await expect(result).toContainText('Pending approval')

  expect(unexpectedErrors()).toEqual([])
})
