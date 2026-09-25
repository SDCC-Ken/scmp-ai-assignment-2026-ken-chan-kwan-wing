import { test, expect } from '../support/fixtures'
import { signInAs, signOut } from '../support/auth'
import { sendMessage, startNewChat } from '../support/chat'
import { auditEvents } from '../support/db'
import { futureLeaveRange, weekdayLabel } from '../support/dates'

/**
 * E2E test 1: an employee files leave in the chat, the assigned HR approver approves it, and the
 * employee sees the decision. Fake LLM and fake submission adapter: fully offline.
 */
test('employee files leave, HR approver approves, employee sees the decision', async ({ page, unexpectedErrors }) => {
  const { start, end, workingDays } = futureLeaveRange(6)
  const dates = `${weekdayLabel(start)} to ${weekdayLabel(end)}` // as the UI words it
  const note = 'Approved. Enjoy the break and please hand over your open items.'

  // --- Amy (IT employee): ask for leave in the chat -------------------------------------------
  await signInAs(page, 'Amy Lau')
  await startNewChat(page)
  await sendMessage(page, `I need annual leave from ${start} to ${end}`)

  // The confirmation card shows what will be submitted; nothing is saved before Submit.
  const card = page.getByRole('region', { name: 'Confirm leave application' })
  await expect(card).toBeVisible()
  await expect(card.getByRole('term').filter({ hasText: 'Leave type' })).toBeVisible()
  await expect(card).toContainText('Annual')
  await expect(card).toContainText(weekdayLabel(start))
  await expect(card).toContainText(weekdayLabel(end))
  await expect(card.getByText('Working days')).toBeVisible()
  await expect(card.locator('dd', { hasText: /^2$/ })).toHaveCount(workingDays === 2 ? 1 : 0)
  // Balance info line (seed: 15 days entitled, 1.5 approved; this request is 2 days).
  await expect(card.getByRole('list', { name: 'More information' })).toContainText('15 days entitled')
  await expect(card.getByRole('list', { name: 'More information' })).toContainText('11.5 left after this request')

  await card.getByRole('button', { name: 'Submit', exact: true }).click()

  // Result card: pending approval, and it must be honest that this is NOT the ReqRes integration.
  const result = page.getByRole('region', { name: 'Submitted result' })
  await expect(result).toBeVisible()
  await expect(result).toContainText('Pending approval')
  await expect(result).toContainText('offline "fake" adapter (not ReqRes)')
  await expect(page.getByRole('list', { name: 'Messages' }).getByText(/is now waiting for approval by Cathy Ng/)).toBeVisible()
  const requestId = Number(/#(\d+)/.exec(await result.innerText())?.[1])
  expect(requestId).toBeGreaterThan(0)

  await signOut(page)

  // --- Cathy (assigned HR approver for IT leave): decide it -----------------------------------
  await signInAs(page, 'Cathy Ng')
  await page.getByRole('link', { name: /^Approvals/ }).click()
  await expect(page.getByRole('heading', { name: 'Leave approvals' })).toBeVisible()

  // Amy's seed data also has an older pending leave: pick the new request by its dates.
  const queue = page.getByRole('list', { name: 'Pending requests' })
  const rows = queue.locator(':scope > li') // (each row has a nested Flags list)
  await expect(rows).toHaveCount(2)
  const row = rows.filter({ hasText: dates })
  await expect(row).toHaveCount(1)
  await row.getByRole('link', { name: /Amy Lau/ }).click()

  await expect(page.getByRole('heading', { name: `Leave request #${requestId}`, level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Limits' })).toContainText('Annual leave balance')
  await expect(page.getByRole('region', { name: 'Team on leave at the same time' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Request details' })).toContainText(weekdayLabel(start))

  await page.getByLabel('Note for the employee (optional)').fill(note)
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('alertdialog', { name: `Approve leave request #${requestId}?` })
  await expect(dialog).toContainText(note)
  await dialog.getByRole('button', { name: 'Confirm approve' }).click()

  // Success notice on the list, and the decided item has left it (the older seed item stays).
  await expect(page).toHaveURL(/\/approvals$/)
  await expect(page.getByRole('status').filter({ hasText: `You approved leave request #${requestId} from Amy Lau.` })).toBeVisible()
  await expect(rows.filter({ hasText: dates })).toHaveCount(0)
  await expect(rows).toHaveCount(1)

  // TODO(bell-inbox): after the bell inbox is redone, add here the steps for Amy's notification
  // ("Your leave request #<id> was approved" with the note) and for Cathy's "new request" one.

  await signOut(page)

  // --- Amy again: the status card shows Approved with the reviewer's note ---------------------
  await signInAs(page, 'Amy Lau')
  await startNewChat(page)
  await sendMessage(page, 'what is the status of my requests?')
  const status = page.getByRole('region', { name: 'Your requests' })
  await expect(status).toBeVisible()
  const item = status.getByRole('listitem').filter({ hasText: `Leave application #${requestId}` })
  await expect(item).toHaveCount(1)
  await expect(item).toContainText('Approved')
  await expect(item).toContainText('Reviewer note')
  await expect(item).toContainText(note)
  await expect(item).toContainText(dates)

  // --- Audit trail: exactly one approval event for this request --------------------------------
  const events = auditEvents('leave_request', requestId)
  expect(events.filter(e => e.event_type === 'request.approved')).toHaveLength(1)
  expect(events.map(e => e.event_type)).toEqual([
    'request.created',
    'request.confirmed',
    'submission.succeeded',
    'request.approved',
  ])
  const approved = events.find(e => e.event_type === 'request.approved')!
  expect([approved.from_status, approved.to_status]).toEqual(['pending_approval', 'approved'])

  expect(unexpectedErrors()).toEqual([])
})
