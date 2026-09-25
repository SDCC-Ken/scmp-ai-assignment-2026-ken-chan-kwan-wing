/** Pure helpers for the bell's unread badge (tests/notifications.test.ts). The bell polls `GET /api/notifications?limit=1` only for the count. */
import type { AppNotification, NotificationList } from '../types/notifications'

/** The bell only needs the unread count, so it asks for a single item. */
export const NOTIFICATION_LIMIT = 1

export function isUnread(n: Pick<AppNotification, 'read_at'>): boolean {
  return !n.read_at
}

/** Badge text: nothing for 0, the number up to 99, then "99+". */
export function formatBadgeCount(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return ''
  return count > 99 ? '99+' : String(Math.floor(count))
}

/** Accessible name of the bell button, including the count. */
export function bellLabel(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return 'Notifications, none unread'
  const shown = count > 99 ? 'more than 99' : String(Math.floor(count))
  return `Notifications, ${shown} unread`
}

/** Accessible name of the bell while the inbox request is running. */
export function bellBusyLabel(count: number): string {
  return `${bellLabel(count)}. Opening your inbox...`
}

/** Text for the polite live region when the count changes. */
export function unreadAnnouncement(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return 'No unread notifications'
  return count === 1 ? '1 unread notification' : `${count > 99 ? 'More than 99' : count} unread notifications`
}

function toNotification(value: unknown): AppNotification | null {
  if (typeof value !== 'object' || value === null) return null
  const v = value as Record<string, unknown>
  if (typeof v.id !== 'number' || typeof v.title !== 'string') return null
  return {
    id: v.id,
    event_type: typeof v.event_type === 'string' ? v.event_type : '',
    title: v.title,
    body: typeof v.body === 'string' ? v.body : '',
    request_type: v.request_type === 'leave' || v.request_type === 'claim' ? v.request_type : null,
    request_id: typeof v.request_id === 'number' ? v.request_id : null,
    read_at: typeof v.read_at === 'string' ? v.read_at : null,
    created_at: typeof v.created_at === 'string' ? v.created_at : '',
    link: typeof v.link === 'string' ? v.link : null,
  }
}

/** Tolerant parse of GET /api/notifications: malformed rows are dropped, the count falls back to the unread rows. */
export function parseNotificationList(payload: unknown): NotificationList {
  const v = (typeof payload === 'object' && payload !== null ? payload : {}) as Record<string, unknown>
  const items = (Array.isArray(v.items) ? v.items : []).map(toNotification).filter((n): n is AppNotification => n !== null)
  const unread = typeof v.unread_count === 'number' && v.unread_count >= 0 ? v.unread_count : items.filter(isUnread).length
  return { items, unread_count: unread }
}
