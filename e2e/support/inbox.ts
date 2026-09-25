import { expect } from '@playwright/test'
import type { ApiClient } from './api'

/** An inbox card as the API returns it (only the fields the tests look at). */
export interface InboxCardJson {
  card_id: string
  kind: 'approval' | 'notice'
  title: string
  request_type: 'leave' | 'claim' | null
  request_id: number | null
  position: { index: number, total: number }
  notice: { title: string, body: string } | null
}

interface Turn {
  conversation: { id: number, title: string }
  assistant_messages: { content: string, ui: (InboxCardJson & { type: string }) | null }[]
}

const cardsOf = (turn: Turn): InboxCardJson[] =>
  turn.assistant_messages.flatMap(m => (m.ui?.type === 'inbox_card' ? [m.ui] : []))

export interface InboxSweep {
  /** Nothing to handle (no conversation was created). */
  empty: boolean
  conversationId: number | null
  title: string | null
  /** Every card in order (each one skipped after it was read, so nothing is decided or marked read). */
  cards: InboxCardJson[]
}

/** Opens the caller's inbox through the API and walks all cards with "skip" (read-only in effect). */
export async function sweepInbox(api: ApiClient): Promise<InboxSweep> {
  const res = await api.post('/api/chat/inbox')
  expect(res.ok(), `POST /api/chat/inbox as ${api.user}: ${res.status()}`).toBe(true)
  const body = await res.json()
  if (body.empty) return { empty: true, conversationId: null, title: null, cards: [] }
  expect(res.status()).toBe(201)
  const conversationId: number = body.conversation.id
  const cards = cardsOf(body)
  for (let i = 0; i < 20; i++) {
    const last = cards[cards.length - 1]
    if (!last) break
    const skip = await api.post(`/api/chat/conversations/${conversationId}/actions`, { card_id: last.card_id, action: 'skip' })
    expect(skip.status()).toBe(200)
    const next = cardsOf(await skip.json())
    if (!next.length) break
    cards.push(...next)
  }
  return { empty: false, conversationId, title: body.conversation.title, cards }
}

/** Opens the inbox and returns the first card without acting on it. */
export async function openInbox(api: ApiClient): Promise<{ conversationId: number, card: InboxCardJson }> {
  const res = await api.post('/api/chat/inbox')
  expect(res.status()).toBe(201)
  const body = await res.json() as Turn & { conversation: { id: number } }
  const card = cardsOf(body)[0]
  if (!card) throw new Error(`inbox of ${api.user} has no card`)
  return { conversationId: body.conversation.id, card }
}
