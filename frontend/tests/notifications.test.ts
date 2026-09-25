import { describe, expect, it } from 'vitest'
import {
  bellBusyLabel,
  bellLabel,
  formatBadgeCount,
  NOTIFICATION_LIMIT,
  parseNotificationList,
  unreadAnnouncement,
} from '../app/utils/notifications'
import { POLL_INTERVAL_MS, shouldRefreshOnFocus, shouldTick } from '../app/utils/polling'
import type { AppNotification } from '../app/types/notifications'

const n = (id: number, read: string | null = null, link: string | null = null): AppNotification => ({
  id, event_type: 'request.submitted', title: `Title ${id}`, body: 'Body', request_type: 'leave', request_id: 12,
  read_at: read, created_at: '2026-09-25T03:10:00Z', link,
})

describe('unread badge', () => {
  it('shows nothing for zero, the number up to 99, and 99+ above', () => {
    expect(formatBadgeCount(0)).toBe('')
    expect(formatBadgeCount(-3)).toBe('')
    expect(formatBadgeCount(7)).toBe('7')
    expect(formatBadgeCount(99)).toBe('99')
    expect(formatBadgeCount(100)).toBe('99+')
    expect(formatBadgeCount(5000)).toBe('99+')
  })

  it('puts the count in the button name and the live announcement', () => {
    expect(bellLabel(3)).toBe('Notifications, 3 unread')
    expect(bellLabel(0)).toBe('Notifications, none unread')
    expect(bellLabel(250)).toBe('Notifications, more than 99 unread')
    expect(unreadAnnouncement(1)).toBe('1 unread notification')
    expect(unreadAnnouncement(4)).toBe('4 unread notifications')
    expect(unreadAnnouncement(0)).toBe('No unread notifications')
  })
})

describe('bell while the inbox opens', () => {
  it('adds the busy text to the accessible name and keeps the count', () => {
    expect(bellBusyLabel(3)).toBe('Notifications, 3 unread. Opening your inbox...')
    expect(bellBusyLabel(0)).toBe('Notifications, none unread. Opening your inbox...')
  })

  it('polls the count with a single item', () => {
    expect(NOTIFICATION_LIMIT).toBe(1)
  })
})

describe('payload parsing', () => {
  it('drops malformed rows and falls back to counting unread rows', () => {
    const list = parseNotificationList({ items: [n(1), { nope: true }, n(2, 'x')] })
    expect(list.items).toHaveLength(2)
    expect(list.unread_count).toBe(1)
  })

  it('keeps the server unread count (it can exceed the rows returned)', () => {
    expect(parseNotificationList({ items: [n(1)], unread_count: 120 }).unread_count).toBe(120)
    expect(parseNotificationList(null)).toEqual({ items: [], unread_count: 0 })
  })

  it('keeps titles and bodies as plain strings (they are rendered as text)', () => {
    const [item] = parseNotificationList({ items: [{ ...n(1), title: '<img src=x onerror=alert(1)>' }] }).items
    expect(item!.title).toBe('<img src=x onerror=alert(1)>')
  })
})

describe('polling rules', () => {
  it('ticks every 30 seconds, but not while hidden or still running', () => {
    expect(POLL_INTERVAL_MS).toBe(30_000)
    expect(shouldTick({ hidden: false, inFlight: false })).toBe(true)
    expect(shouldTick({ hidden: true, inFlight: false })).toBe(false)
    expect(shouldTick({ hidden: false, inFlight: true })).toBe(false)
  })

  it('refreshes on focus unless hidden, running, or one ran a moment ago', () => {
    const base = { hidden: false, inFlight: false, lastRunAt: null, now: 100_000 }
    expect(shouldRefreshOnFocus(base)).toBe(true)
    expect(shouldRefreshOnFocus({ ...base, hidden: true })).toBe(false)
    expect(shouldRefreshOnFocus({ ...base, inFlight: true })).toBe(false)
    expect(shouldRefreshOnFocus({ ...base, lastRunAt: 98_000 })).toBe(false)
    expect(shouldRefreshOnFocus({ ...base, lastRunAt: 90_000 })).toBe(true)
  })
})
