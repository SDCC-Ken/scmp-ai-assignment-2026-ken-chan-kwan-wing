import { expect, type Locator, type Page } from '@playwright/test'

export const composer = (page: Page): Locator => page.getByLabel('Message', { exact: true })
export const sendButton = (page: Page): Locator => page.getByRole('button', { name: 'Send', exact: true })

/**
 * Clicks "New chat" and waits until the new conversation is really active. The page moves focus to
 * the composer only after it has created and selected the conversation, so anything typed earlier
 * could be wiped: wait for that focus before typing.
 */
export async function startNewChat(page: Page): Promise<void> {
  const created = page.waitForResponse(r => r.url().endsWith('/api/chat/conversations') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'New chat' }).click()
  expect((await created).status()).toBe(201)
  await expect(composer(page)).toBeFocused()
}

/** Types a message and sends it with the Send button. */
export async function sendMessage(page: Page, text: string): Promise<void> {
  await composer(page).fill(text)
  await sendButton(page).click()
}
