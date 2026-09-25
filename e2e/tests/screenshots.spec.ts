import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '../support/fixtures'
import { apiAs, approvalQueue } from '../support/api'
import { signInAs } from '../support/auth'
import { sendMessage, startNewChat } from '../support/chat'
import { SCREENSHOT_DIR, WEB_URL } from '../support/env.mjs'
import { futureLeaveRange } from '../support/dates'
import { bell, expectBell } from '../support/flows'
import type { Page } from '@playwright/test'

/**
 * Documentation screenshots (`bun run screenshots`, never part of `bun run test`): 1280x800, light theme,
 * fictional seed data only, offline fake LLM. Each run overwrites the same five PNG files in docs/screenshots/.
 */
test.beforeEach(async ({ context, page }) => {
  // Deterministic light theme: the theme cookie the app reads on the server, plus a light colour scheme (config).
  await context.addCookies([{ name: 'theme-mode', value: 'light', url: WEB_URL }])
  await page.setViewportSize({ width: 1280, height: 800 })
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true })
})

/** Waits until nothing is loading or animating, then writes the PNG (overwriting). */
async function shoot(page: Page, file: string, clip?: { x: number, y: number, width: number, height: number }): Promise<void> {
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0)
  await expect(page.getByText(/Thinking|Loading/)).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.mouse.move(0, 0)
  await page.waitForTimeout(400) // let transitions finish
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, file),
    animations: 'disabled',
    caret: 'hide',
    clip,
  })
}

/** Scrolls the chat thread (the scrollable ancestor of the message list) to its top or bottom. */
async function scrollThread(page: Page, where: 'top' | 'bottom'): Promise<void> {
  await page.getByRole('list', { name: 'Messages' }).evaluate((list, to) => {
    let el: HTMLElement | null = list as HTMLElement
    while (el && el.scrollHeight <= el.clientHeight) el = el.parentElement
    el?.scrollTo(0, to === 'top' ? 0 : el.scrollHeight)
  }, where)
}

test('01 mock sign-in', async ({ page }) => {
  await page.goto('/login')
  const card = page.getByRole('dialog', { name: /Sign in with Google/ })
  await expect(card).toBeVisible()
  await expect(card.getByRole('button', { name: /Continue as|Amy Lau|Ben Chow|Cathy Ng|Daniel Wong|Helen Yeung|Eva Cheung/ })).toHaveCount(6)
  await expect(page.getByText(/mock/i).first()).toBeVisible()
  await shoot(page, '01-mock-sign-in.png')
})

test('02 employee confirmation card', async ({ page }) => {
  await signInAs(page, 'Amy Lau')
  await startNewChat(page)
  const { start, end } = futureLeaveRange(6)
  await sendMessage(page, `I need annual leave from ${start} to ${end}`)
  const card = page.getByRole('region', { name: 'Confirm leave application' })
  await expect(card).toBeVisible()
  await expect(card.getByRole('list', { name: 'More information' })).toContainText('days entitled')
  await scrollThread(page, 'top') // the first bubble fully visible
  await shoot(page, '02-employee-confirmation.png')
})

test('03 HR approval with limits and team overlap', async ({ page }) => {
  const cathy = await apiAs('Cathy Ng')
  const leave = (await approvalQueue(cathy)).find(i => i.request_type === 'leave' && i.employee.display_name === 'Amy Lau')!
  await cathy.dispose()
  await signInAs(page, 'Cathy Ng')
  await page.goto(`/approvals/leave/${leave.id}`)
  await expect(page.getByRole('heading', { name: `Leave request #${leave.id}`, level: 1 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Limits' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Team on leave at the same time' })).toBeVisible()
  await page.getByLabel('Note for the employee (optional)').fill('Approved. Please hand over your open items before you go.')
  await shoot(page, '03-hr-approval.png')
})

test('04 notification bell and inbox conversation', async ({ page }) => {
  // Ben has two unread notices (his rejected leave and claim): short cards that fit the screen.
  await signInAs(page, 'Ben Chow')
  await expectBell(page, 2)
  await bell(page).click()
  await expect(page.getByRole('heading', { name: 'Items to handle (2)', level: 1 })).toBeVisible()
  await expect(page.getByText('Item 1 of 2', { exact: true })).toBeVisible()
  await expectBell(page, 2)
  await shoot(page, '04-notification-bell.png')
})

test('05 AI processing trace', async ({ page }) => {
  await signInAs(page, 'Amy Lau')
  await startNewChat(page)
  await sendMessage(page, 'I would like to take some annual leave')
  await expect(page.getByRole('list', { name: 'Messages' }).getByText(/What is the first day of your leave/).first()).toBeVisible()
  await page.getByText('How I understood this').last().click()
  await expect(page.getByRole('list', { name: 'AI processing steps' }).last()).toBeVisible()
  await scrollThread(page, 'bottom')
  await shoot(page, '05-ai-trace.png')
})
