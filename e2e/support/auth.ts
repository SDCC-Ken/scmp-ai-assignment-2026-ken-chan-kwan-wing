import { expect, type Page } from '@playwright/test'
import type { UserName } from './users'

/**
 * Signs in through the mock Google One Tap card on /login: picks the account row by its
 * accessible name and waits until the header shows that user.
 */
export async function signInAs(page: Page, name: UserName): Promise<void> {
  await page.goto('/login')
  const card = page.getByRole('dialog', { name: /Sign in with Google/ })
  await card.getByRole('button', { name: new RegExp(name) }).click()
  await expect(page).not.toHaveURL(/\/login/)
  await expect(page.locator('header').getByText(name, { exact: true })).toBeVisible()
}

export async function signOut(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('dialog', { name: /Sign in with Google/ })).toBeVisible()
}
