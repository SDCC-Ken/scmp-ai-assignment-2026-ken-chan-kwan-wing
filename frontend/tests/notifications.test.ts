import { describe, expect, it } from 'vitest'
import {
  applyRead,
  applyReadAll,
  bellLabel,
  formatBadgeCount,
  isUnread,
  notificationTarget,
  parseNotificationList,
  safeInternalLink,
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

describe('what a click does', () => {
  it('approvers follow the link, requesters get the dialog', () => {
    expect(notificationTarget(n(1, null, '/approvals/leave/12'))).toEqual({ kind: 'link', to: '/approvals/leave/12' })
    expect(notificationTarget(n(2, null, null))).toEqual({ kind: 'dialog' })
  })

  it('never follows an external or protocol-relative link', () => {
    expect(safeInternalLink('https://evil.example/x')).toBeNull()
    expect(safeInternalLink('//evil.example/x')).toBeNull()
    expect(safeInternalLink('/\\evil')).toBeNull()
    expect(safeInternalLink('javascript:alert(1)')).toBeNull()
    expect(safeInternalLink(' /approvals/leave/1 ')).toBe('/approvals/leave/1')
    expect(notificationTarget(n(3, null, 'https://evil.example'))).toEqual({ kind: 'dialog' })
  })
})

describe('optimistic read handling', () => {
  const list = [n(1), n(2, '2026-09-25T04:00:00Z'), n(3)]

  it('marks one unread item read and lowers the count once', () => {
    const update = applyRead(list, 2, 1, '2026-09-25T05:00:00Z')
    expect(update.changed).toBe(true)
    expect(update.unread).toBe(1)
    expect(isUnread(update.items[0]!)).toBe(false)
    expect(isUnread(update.items[2]!)).toBe(true)
    expect(list[0]!.read_at).toBeNull() // the input is not mutated (rollback needs it)
  })

  it('does nothing for an already-read or unknown item', () => {
    expect(applyRead(list, 2, 2, 'now')).toMatchObject({ changed: false, unread: 2 })
    expect(applyRead(list, 2, 99, 'now')).toMatchObject({ changed: false, unread: 2 })
  })

  it('never lets the count go below zero', () => {
    expect(applyRead([n(1)], 0, 1, 'now').unread).toBe(0)
  })

  it('marks everything read and zeroes the count', () => {
    const update = applyReadAll(list, 'now')
    expect(update.unread).toBe(0)
    expect(update.items.every(i => !isUnread(i))).toBe(true)
    expect(update.changed).toBe(true)
    expect(applyReadAll([n(2, 'x')], 'now').changed).toBe(false)
  })
})

describe('payload parsing', () => {
  it('drops malformed rows and falls back to counting unread rows', () => {
    const list = parseNotificationList({ items: [n(1), { nope: true }, n(2, 'x')] })
    expect(list.items).toHaveLength(2)
    expect(list.unread_count).toBe(1)
  })

  it('keeps the server unread count (it can exceed the 20 rows shown)', () => {
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
