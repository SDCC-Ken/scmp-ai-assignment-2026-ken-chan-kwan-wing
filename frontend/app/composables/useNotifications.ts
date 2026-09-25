/**
 * Unread count for the bell badge (kept in `useState`, cleared on sign-in / sign-out). It is fed by
 * `GET /api/notifications?limit=1` (only `unread_count` is used); the header polls it every 30 s, on focus,
 * and pauses while the tab is hidden. A failed background poll keeps the last number.
 */
export function useNotifications() {
  const api = useApi()
  const unread = useState<number>('notif-unread', () => 0)

  async function refresh() {
    try {
      const data = parseNotificationList(await api<unknown>(`/api/notifications?limit=${NOTIFICATION_LIMIT}`))
      unread.value = data.unread_count
    }
    catch { /* keep the last known count */ }
  }

  return { unread, refresh }
}
