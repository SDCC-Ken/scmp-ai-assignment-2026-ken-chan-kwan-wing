import { test, expect } from '../support/fixtures'
import { apiAs, approvalQueue, type ApiClient } from '../support/api'
import { signInAs } from '../support/auth'
import { auditEvents } from '../support/db'

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
})
