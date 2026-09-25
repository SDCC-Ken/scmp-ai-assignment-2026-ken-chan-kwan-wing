import { test, expect } from '../support/fixtures'
import { apiAs, approvalQueue, type ApiClient } from '../support/api'
import { signInAs } from '../support/auth'
import { auditEvents } from '../support/db'
import { bell, expectBell } from '../support/flows'
import { openInbox, sweepInbox } from '../support/inbox'

/**
 * E2E test 2: role and assignment boundaries, in the UI and in the API.
 *
 * What the backend really answers (asserted below, see docs/phase3-approval-design.md section 5):
 *   - a request the caller may not decide (other request type, or not assigned to them):
 *     404 {"detail":"Request not found"} on both GET and the decision POST (deliberately the same
 *     as "does not exist", so nothing leaks). The request stays pending_approval.
 *   - a user who is not an approver at all (employee): 403 on the queue.
 */
const NOT_FOUND = 'Request not found'

/** Ids are looked up as an allowed user, never hard-coded. */
async function pendingLeaveOf(approver: ApiClient, employee: string): Promise<number> {
  const item = (await approvalQueue(approver)).find(i => i.request_type === 'leave' && i.employee.display_name === employee)
  if (!item) throw new Error(`no pending leave of ${employee} in the queue of ${approver.user}`)
  return item.id
}

async function assertStillPending(approver: ApiClient, type: 'leave' | 'claim', id: number): Promise<void> {
  const detail = await approver.json(`/api/approvals/${type}/${id}`)
  expect(detail.request.status).toBe('pending_approval')
}

test.describe('role and assignment boundaries', () => {
  test('finance approver cannot open or decide an assigned leave request', async ({ page }) => {
    const cathy = await apiAs('Cathy Ng')
    const eva = await apiAs('Eva Cheung')
    const leaveId = await pendingLeaveOf(cathy, 'Amy Lau')

    // UI: navigating straight to the leave approval shows the not-available state and no details.
    await signInAs(page, 'Eva Cheung')
    await page.goto(`/approvals/leave/${leaveId}`)
    await expect(page.getByRole('heading', { name: 'This request is no longer available' })).toBeVisible()
    const main = page.getByRole('main')
    await expect(main).not.toContainText('Amy Lau')
    await expect(main).not.toContainText(/\d{4}-\d{2}-\d{2}/) // no dates
    await expect(main).not.toContainText('Annual')
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Reject' })).toHaveCount(0)

    // API with Eva's session: 404 (not 403), identical to "does not exist".
    const detail = await eva.get(`/api/approvals/leave/${leaveId}`)
    expect(detail.status()).toBe(404)
    expect((await detail.json()).detail).toBe(NOT_FOUND)
    const missing = await eva.get('/api/approvals/leave/999999')
    expect(missing.status()).toBe(404)
    expect((await missing.json()).detail).toBe((await detail.json()).detail)

    for (const decision of ['approve', 'reject'] as const) {
      const res = await eva.post(`/api/approvals/leave/${leaveId}/decision`, { decision, note: 'should not work' })
      expect(res.status()).toBe(404)
      expect((await res.json()).detail).toBe(NOT_FOUND)
    }

    // Her queue holds claims only, and the leave request is still pending for its real approver.
    const queue = await approvalQueue(eva)
    expect(queue.length).toBeGreaterThan(0)
    expect(queue.every(i => i.request_type === 'claim')).toBe(true)
    await assertStillPending(cathy, 'leave', leaveId)
    expect(auditEvents('leave_request', leaveId).filter(e => /^request\.(approved|rejected)$/.test(e.event_type))).toEqual([])

    await Promise.all([cathy.dispose(), eva.dispose()])
  })

  test('HR approver cannot open or decide a claim', async ({ page }) => {
    const cathy = await apiAs('Cathy Ng')
    const eva = await apiAs('Eva Cheung')
    const claim = (await approvalQueue(eva)).find(i => i.request_type === 'claim')
    if (!claim) throw new Error('the seed has no pending claim')

    await signInAs(page, 'Cathy Ng')
    await page.goto(`/approvals/claim/${claim.id}`)
    await expect(page.getByRole('heading', { name: 'This request is no longer available' })).toBeVisible()
    const main = page.getByRole('main')
    await expect(main).not.toContainText(claim.employee.display_name)
    await expect(main).not.toContainText('HKD')
    await expect(main).not.toContainText(/\d{4}-\d{2}-\d{2}/)
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)

    const detail = await cathy.get(`/api/approvals/claim/${claim.id}`)
    expect(detail.status()).toBe(404)
    expect((await detail.json()).detail).toBe(NOT_FOUND)
    for (const decision of ['approve', 'reject'] as const) {
      const res = await cathy.post(`/api/approvals/claim/${claim.id}/decision`, { decision, note: 'should not work' })
      expect(res.status()).toBe(404)
      expect((await res.json()).detail).toBe(NOT_FOUND)
    }

    // Her queue holds leave only; the claim is untouched for Eva.
    expect((await approvalQueue(cathy)).every(i => i.request_type === 'leave')).toBe(true)
    await assertStillPending(eva, 'claim', claim.id)
    expect(auditEvents('claim_request', claim.id).filter(e => /^request\.(approved|rejected)$/.test(e.event_type))).toEqual([])

    await Promise.all([cathy.dispose(), eva.dispose()])
  })

  test('employee has no approvals access, and an unassigned HR manager cannot see the leave', async ({ page }) => {
    const cathy = await apiAs('Cathy Ng')
    const leaveId = await pendingLeaveOf(cathy, 'Amy Lau')

    // Amy (employee): /approvals and a detail URL bounce back to the chat; the API answers 403.
    await signInAs(page, 'Amy Lau')
    for (const path of ['/approvals', `/approvals/leave/${leaveId}`]) {
      await page.goto(path)
      await expect(page).toHaveURL(/localhost:\d+\/$/)
      await expect(page.getByRole('link', { name: /^Approvals/ })).toHaveCount(0)
      await expect(page.getByRole('heading', { name: 'Leave approvals' })).toHaveCount(0)
    }
    const amy = await apiAs('Amy Lau')
    const list = await amy.get('/api/approvals')
    expect(list.status()).toBe(403)
    expect((await amy.get(`/api/approvals/leave/${leaveId}`)).status()).toBe(403)
    expect((await amy.post(`/api/approvals/leave/${leaveId}/decision`, { decision: 'approve' })).status()).toBe(403)

    // Helen (HR manager, approves HR leave only): Amy's IT leave is not assigned to her.
    const helen = await apiAs('Helen Yeung')
    const detail = await helen.get(`/api/approvals/leave/${leaveId}`)
    expect(detail.status()).toBe(404)
    expect((await detail.json()).detail).toBe(NOT_FOUND)
    expect((await helen.post(`/api/approvals/leave/${leaveId}/decision`, { decision: 'approve' })).status()).toBe(404)
    expect((await approvalQueue(helen)).some(i => i.id === leaveId)).toBe(false)
    await assertStillPending(cathy, 'leave', leaveId)

    await Promise.all([cathy.dispose(), amy.dispose(), helen.dispose()])
  })

  test('bell inbox: each role sees only what belongs to them', async ({ page }) => {
    // Helen (HR manager): only Daniel's leave. Eva (finance): only claims. No cross-over of data.
    const eva = await apiAs('Eva Cheung')
    const helen = await apiAs('Helen Yeung')
    const cathy = await apiAs('Cathy Ng')

    const evaQueue = await approvalQueue(eva)
    const evaInbox = await sweepInbox(eva)
    expect(evaInbox.title).toBe(`Items to handle (${evaQueue.length})`)
    expect(evaInbox.cards).toHaveLength(evaQueue.length)
    expect(evaInbox.cards.every(c => c.kind === 'approval' && c.request_type === 'claim')).toBe(true)
    expect(evaInbox.cards.map(c => c.request_id).sort()).toEqual(evaQueue.map(i => i.id).sort())
    expect(evaInbox.cards.some(c => /leave/i.test(c.title))).toBe(false)

    const helenInbox = await sweepInbox(helen)
    expect(helenInbox.cards).toHaveLength(1)
    const [helenCard] = helenInbox.cards
    expect(helenCard).toMatchObject({ kind: 'approval', request_type: 'leave' })
    expect(helenCard!.title).toContain('Daniel Wong')
    expect(helenCard!.title).not.toContain('Amy Lau')
    expect(helenInbox.title).toBe('Items to handle (1)')

    // Cathy (assigned to IT leave): Amy's leave only. Her own approved requests are already read: no notice.
    const cathyInbox = await sweepInbox(cathy)
    expect(cathyInbox.cards).toHaveLength(1)
    expect(cathyInbox.cards[0]).toMatchObject({ kind: 'approval', request_type: 'leave' })
    expect(cathyInbox.cards[0]!.title).toContain('Amy Lau')

    // Seed truth for the requesters: Amy and Daniel have no unread notification (empty inbox, no conversation);
    // Ben has exactly two notices (his rejected leave and his rejected claim).
    for (const name of ['Amy Lau', 'Daniel Wong'] as const) {
      const api = await apiAs(name)
      const res = await api.post('/api/chat/inbox')
      expect(res.status()).toBe(200)
      expect(await res.json()).toMatchObject({ empty: true, unread_count: 0 })
      expect((await api.json<{ items: unknown[] }>('/api/chat/conversations')).items.some(
        (c: any) => String(c.title).startsWith('Items to handle'), // eslint-disable-line @typescript-eslint/no-explicit-any
      )).toBe(false)
      await api.dispose()
    }
    const ben = await apiAs('Ben Chow')
    const benInbox = await sweepInbox(ben)
    expect(benInbox.cards).toHaveLength(2)
    expect(benInbox.cards.every(c => c.kind === 'notice')).toBe(true)
    expect(benInbox.cards.map(c => c.title).sort()).toEqual([
      expect.stringMatching(/^Your claim #\d+ was rejected$/),
      expect.stringMatching(/^Your leave request #\d+ was rejected$/),
    ])
    await ben.dispose()

    // UI: Eva's bell shows her two claims and the conversation contains no leave item; Amy's bell is empty.
    await signInAs(page, 'Eva Cheung')
    await expectBell(page, evaQueue.length)
    await bell(page).click()
    await expect(page.getByRole('heading', { name: `Items to handle (${evaQueue.length})`, level: 1 })).toBeVisible()
    await expect(page.getByRole('region', { name: /^Claim #\d+ from /i })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Messages' })).not.toContainText(/leave request/i)

    await Promise.all([eva.dispose(), helen.dispose(), cathy.dispose()])
  })

  test('bell inbox: a card from another user\'s conversation cannot be acted on', async () => {
    const cathy = await apiAs('Cathy Ng')
    const eva = await apiAs('Eva Cheung')
    const leaveId = await pendingLeaveOf(cathy, 'Amy Lau')
    const { conversationId, card } = await openInbox(cathy)
    expect(card).toMatchObject({ kind: 'approval', request_type: 'leave', request_id: leaveId })

    // Eva presents Cathy's conversation and card: 404 (the same answer as "does not exist"), for every action.
    const readOther = await eva.get(`/api/chat/conversations/${conversationId}`)
    expect(readOther.status()).toBe(404)
    for (const body of [
      { card_id: card.card_id, action: 'skip' },
      { card_id: card.card_id, action: 'approve', note: 'not mine', confirmed: true },
      { card_id: card.card_id, action: 'reject', note: 'not mine', confirmed: true },
    ]) {
      const res = await eva.post(`/api/chat/conversations/${conversationId}/actions`, body)
      expect(res.status(), JSON.stringify(body)).toBe(404)
    }
    // Nothing changed: the request is still pending and no decision was audited.
    await assertStillPending(cathy, 'leave', leaveId)
    expect(auditEvents('leave_request', leaveId).filter(e => /^request\.(approved|rejected)$/.test(e.event_type))).toEqual([])
    // Cathy's own card is still open and works.
    const skip = await cathy.post(`/api/chat/conversations/${conversationId}/actions`, { card_id: card.card_id, action: 'skip' })
    expect(skip.status()).toBe(200)

    await Promise.all([cathy.dispose(), eva.dispose()])
  })
})
