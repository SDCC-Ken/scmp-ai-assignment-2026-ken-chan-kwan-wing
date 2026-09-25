import { expect, type Locator, type Page } from '@playwright/test'
import { approvalQueue, type ApiClient } from './api'
import { sendMessage, startNewChat } from './chat'
import type { LeaveRange } from './dates'

/** Amy asks for annual leave in the chat and submits the confirmation card. Returns the new request id. */
export async function submitLeaveInChat(page: Page, range: Pick<LeaveRange, 'start' | 'end'>): Promise<number> {
  await startNewChat(page)
  await sendMessage(page, `I need annual leave from ${range.start} to ${range.end}`)
  const card = page.getByRole('region', { name: 'Confirm leave application' })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: 'Submit', exact: true }).click()
  const result = page.getByRole('region', { name: 'Submitted result' })
  await expect(result).toContainText('Pending approval')
  const id = Number(/#(\d+)/.exec(await result.innerText())?.[1])
  expect(id).toBeGreaterThan(0)
  return id
}

/** The bell button in the header (its accessible name carries the unread number). */
export const bell = (page: Page): Locator => page.getByRole('button', { name: /^Notifications,/ })

/** Asserts the bell shows exactly `count` (a visible number, or no badge for 0). */
export async function expectBell(page: Page, count: number): Promise<void> {
  const button = bell(page)
  await expect(button).toHaveAccessibleName(count === 0 ? 'Notifications, none unread' : `Notifications, ${count} unread`)
  if (count > 0) await expect(button).toContainText(String(count))
}

/** Ids of the pending leave requests in the approver's queue, oldest first. */
export async function pendingLeaveIds(api: ApiClient): Promise<number[]> {
  return (await approvalQueue(api)).filter(i => i.request_type === 'leave').map(i => i.id)
}
