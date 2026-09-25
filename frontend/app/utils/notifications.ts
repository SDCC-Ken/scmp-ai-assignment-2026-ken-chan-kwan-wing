/** Pure notification helpers (tests/notifications.test.ts). Titles and bodies are always rendered as text. */
import type { AppNotification, NotificationList } from '../types/notifications'

export const NOTIFICATION_LIMIT = 20

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

/** Text for the polite live region when the count changes. */
export function unreadAnnouncement(count: number): string {
  if (!Number.isFinite(count) || count <= 0) return 'No unread notifications'
  return count === 1 ? '1 unread notification' : `${count > 99 ? 'More than 99' : count} unread notifications`
}

/** Only in-app paths are followed (no protocol-relative or absolute URLs from the API). */
export function safeInternalLink(link: string | null | undefined): string | null {
  if (typeof link !== 'string') return null
  const value = link.trim()
  return value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') ? value : null
}

export type NotificationTarget = { kind: 'link', to: string } | { kind: 'dialog' }

/** Approvers follow the link; requesters (no link) get the detail dialog. */
export function notificationTarget(n: Pick<AppNotification, 'link'>): NotificationTarget {
  const to = safeInternalLink(n.link)
  return to ? { kind: 'link', to } : { kind: 'dialog' }
}

export interface ReadUpdate {
  items: AppNotification[]
  unread: number
  /** False when the notification was missing or already read (no request is needed). */
  changed: boolean
}

/** Optimistic "mark one as read"; the count drops by one only when the item really was unread. */
export function applyRead(items: readonly AppNotification[], unread: number, id: number, now: string): ReadUpdate {
  const target = items.find(n => n.id === id)
  if (!target || !isUnread(target)) return { items: [...items], unread, changed: false }
  return {
    items: items.map(n => (n.id === id ? { ...n, read_at: now } : n)),
    unread: Math.max(0, unread - 1),
    changed: true,
  }
}

/** Optimistic "mark all as read". The unread count becomes 0. */
export function applyReadAll(items: readonly AppNotification[], now: string): ReadUpdate {
  const changed = items.some(isUnread)
  return { items: items.map(n => (isUnread(n) ? { ...n, read_at: now } : n)), unread: 0, changed }
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
