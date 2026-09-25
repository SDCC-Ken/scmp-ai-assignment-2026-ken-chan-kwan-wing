import { test, expect } from '../support/fixtures'
import { signInAs, signOut } from '../support/auth'
import { apiAs, approvalQueue } from '../support/api'
import { sendMessage, startNewChat } from '../support/chat'
import { auditEvents } from '../support/db'
import { futureLeaveRange, weekdayLabel } from '../support/dates'
import { bell, expectBell, submitLeaveInChat } from '../support/flows'

/**
 * E2E test 1: an employee files leave in the chat, the assigned HR approver approves it, and the
 * employee sees the decision. Two variants of the approver's step: through the bell inbox (the
 * primary flow) and through the Approvals page. Fake LLM and fake submission adapter: fully offline.
 */
test('employee files leave, HR approver approves it in the bell inbox, employee sees the notice', async ({ page, unexpectedErrors }) => {
  const { start, end } = futureLeaveRange(6)
  const note = 'Approved through the inbox. Please hand over your open items.'

  // --- Amy files the request ------------------------------------------------------------------
  await signInAs(page, 'Amy Lau')
  const requestId = await submitLeaveInChat(page, { start, end })
  await signOut(page)

  // --- Cathy: the bell shows the queue size and opens a new "Items to handle" conversation -----
  const cathyApi = await apiAs('Cathy Ng')
  const queue = await approvalQueue(cathyApi)
  const seedLeaveId = queue.map(i => i.id).find(id => id !== requestId)! // the older seed item comes first
  expect(queue.map(i => i.id)).toEqual([seedLeaveId, requestId])
  await cathyApi.dispose()

  await signInAs(page, 'Cathy Ng')
  await expectBell(page, queue.length) // 1 seed item + the new request
  await bell(page).click()

  await expect(page.getByRole('heading', { name: `Items to handle (${queue.length})`, level: 1 })).toBeVisible()
  const messages = page.getByRole('list', { name: 'Messages' })
  await expect(messages.getByText(`You have ${queue.length} items to handle.`)).toBeVisible()

  // Card 1 of 2 is the older seed request: skip it (it stays unread), then card 2 is the new one.
  const first = page.getByRole('region', { name: new RegExp(`^Leave request #${seedLeaveId} from Amy Lau`) })
  await expect(first).toBeVisible()
  await expect(first).toContainText('Item 1 of 2')
  await first.getByRole('button', { name: 'Skip', exact: true }).click()
  await expect(messages.getByText(/Skipped leave request #\d+ from Amy Lau\./i)).toBeVisible()

  const card = page.getByRole('region', { name: new RegExp(`^Leave request #${requestId} from Amy Lau`) })
  await expect(card).toBeVisible()
  await expect(card).toContainText('Item 2 of 2')
  await expect(card.getByRole('region', { name: 'Limits' })).toContainText('Annual leave balance')
  await expect(card.getByRole('region', { name: 'Request details' })).toContainText(weekdayLabel(start))
  await card.getByLabel('Note for the employee (optional)').fill(note)
  await card.getByRole('button', { name: 'Approve', exact: true }).click()
  // Second explicit step; nothing was decided yet.
  await expect(card.getByRole('button', { name: 'Confirm approve' })).toBeVisible()
  await expect(card.getByRole('button', { name: 'Back' })).toBeVisible()
  expect(auditEvents('leave_request', requestId).some(e => e.event_type === 'request.approved')).toBe(false)
  await card.getByRole('button', { name: 'Confirm approve' }).click()

  await expect(messages.getByText(`You approved leave request #${requestId} from Amy Lau.`)).toBeVisible()
  await expect(messages.getByText('All done. You handled 1 item and skipped 1.')).toBeVisible()
  // The number drops by one: the skipped seed item is still unread.
  await expectBell(page, queue.length - 1)

  // Audit: one approval, recorded as made through the inbox.
  const approved = auditEvents('leave_request', requestId).filter(e => e.event_type === 'request.approved')
  expect(approved).toHaveLength(1)
  expect([approved[0]!.from_status, approved[0]!.to_status]).toEqual(['pending_approval', 'approved'])
  expect(approved[0]!.metadata.via).toBe('inbox')
  await signOut(page)

  // --- Amy: her bell shows 1; the inbox holds one notice with the approval and the note --------
  await signInAs(page, 'Amy Lau')
  await expectBell(page, 1)
  await bell(page).click()
  await expect(page.getByRole('heading', { name: 'Items to handle (1)', level: 1 })).toBeVisible()
  const notice = page.getByRole('region', { name: `Your leave request #${requestId} was approved` })
  await expect(notice).toBeVisible()
  await expect(notice).toContainText('Item 1 of 1')
  await expect(notice).toContainText('Approved by Cathy Ng.')
  await expect(notice).toContainText(note)
  await notice.getByRole('button', { name: 'Got it', exact: true }).click()
  await expect(messages.getByText('Got it. I marked that notice as read.')).toBeVisible()
  await expect(messages.getByText('All done. You handled 1 item.')).toBeVisible()
  await expectBell(page, 0)

  // A second click: nothing left, no new conversation.
  const conversations = page.getByRole('navigation', { name: 'Conversations' })
  const before = await conversations.getByRole('button').count()
  await bell(page).click()
  await expect(page.getByRole('status').filter({ hasText: 'You are all caught up' })).toBeVisible()
  await expect(conversations.getByRole('button')).toHaveCount(before)

  expect(unexpectedErrors()).toEqual([])
})

test('employee files leave, HR approver approves it on the Approvals page, employee sees the decision', async ({ page, unexpectedErrors }) => {
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
  expect(approved.metadata.via).not.toBe('inbox') // decided on the Approvals page, not in the inbox

  expect(unexpectedErrors()).toEqual([])
})
