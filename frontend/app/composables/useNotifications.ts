import type { AppNotification } from '~/types/notifications'

/**
 * Shared notification state for the bell (kept in `useState`, cleared on sign-in / sign-out). Reads and writes go
 * through `useApi`. Marking as read is optimistic and rolls back when the API refuses. A poll that started before a
 * local change is discarded, so an old response never brings back a dot the user just cleared.
 */
export function useNotifications() {
  const api = useApi()
  const items = useState<AppNotification[]>('notif-items', () => [])
  const unread = useState<number>('notif-unread', () => 0)
  const loaded = useState<boolean>('notif-loaded', () => false)
  const error = useState<string | null>('notif-error', () => null)
  const actionError = ref<string | null>(null)
  const loading = ref(false)
  let mutations = 0

  async function refresh() {
    const startedAt = mutations
    loading.value = true
    try {
      const data = parseNotificationList(await api<unknown>(`/api/notifications?limit=${NOTIFICATION_LIMIT}`))
      if (startedAt !== mutations) return
      items.value = data.items
      unread.value = data.unread_count
      error.value = null
      loaded.value = true
    }
    catch {
      // A failed background poll keeps what is shown; only a list that never loaded reports an error.
      if (!loaded.value) error.value = 'Notifications could not be loaded.'
    }
    finally {
      loading.value = false
    }
  }

  async function markRead(id: number) {
    const update = applyRead(items.value, unread.value, id, new Date().toISOString())
    if (!update.changed) return
    const snapshot = { items: items.value, unread: unread.value }
    mutations++
    items.value = update.items
    unread.value = update.unread
    try {
      await api(`/api/notifications/${id}/read`, { method: 'POST' })
    }
    catch {
      mutations++
      items.value = snapshot.items
      unread.value = snapshot.unread
      actionError.value = 'Could not mark that notification as read. Please try again.'
    }
  }

  async function markAllRead() {
    const update = applyReadAll(items.value, new Date().toISOString())
    if (!update.changed && unread.value === 0) return
    const snapshot = { items: items.value, unread: unread.value }
    mutations++
    items.value = update.items
    unread.value = update.unread
    try {
      await api('/api/notifications/read-all', { method: 'POST' })
    }
    catch {
      mutations++
      items.value = snapshot.items
      unread.value = snapshot.unread
      actionError.value = 'Could not mark all as read. Please try again.'
    }
  }

  return { items, unread, loaded, loading, error, actionError, refresh, markRead, markAllRead }
}
