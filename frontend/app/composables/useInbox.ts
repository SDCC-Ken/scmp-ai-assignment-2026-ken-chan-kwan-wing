import type { ConversationSummary, InboxResponse, Message } from '~/types/chat'

/** What the bell hands to the chat page: the new inbox conversation and its first assistant messages. */
export interface InboxHandoff {
  conversation: ConversationSummary
  messages: Message[]
}

export type InboxOpenOutcome = 'empty' | 'opened' | 'error'

/**
 * The bell click: `POST /api/chat/inbox` (CSRF header via `useApi`). An empty answer creates nothing. Otherwise the new
 * conversation is stored in shared state for `useChat` to pick up and the user is taken to the chat (`/`), where that
 * conversation opens with the returned messages. Afterwards the badge count is refreshed.
 */
export function useInbox() {
  const api = useApi()
  const { user, withContext } = useAuth()
  const notifications = useNotifications()
  const handoff = useState<InboxHandoff | null>('inbox-handoff', () => null)
  const opening = ref(false)
  const errorText = ref<string | null>(null)

  async function open(): Promise<InboxOpenOutcome> {
    if (opening.value) return 'error'
    opening.value = true
    errorText.value = null
    try {
      const result = parseInboxResponse(await api<InboxResponse>('/api/chat/inbox', { method: 'POST' }))
      if (result.kind === 'empty') {
        await notifications.refresh()
        return 'empty'
      }
      if (result.kind === 'invalid') {
        errorText.value = inboxOpenErrorMessage(500)
        return 'error'
      }
      handoff.value = { conversation: result.conversation, messages: result.messages }
      if (canUseChat(user.value)) await withContext(() => navigateTo('/'))
      await notifications.refresh()
      return 'opened'
    }
    catch (cause) {
      errorText.value = inboxOpenErrorMessage(extractStatus(cause))
      return 'error'
    }
    finally {
      opening.value = false
    }
  }

  return { opening, errorText, open }
}
