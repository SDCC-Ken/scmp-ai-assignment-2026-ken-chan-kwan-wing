import type {
  AttachmentInfo,
  ConversationDetail,
  ConversationList,
  ConversationSummary,
  Message,
  TurnResponse,
} from '~/types/chat'

interface ChatError {
  text: string
  /** Set when the failed step can be repeated with the Retry button. */
  retry: (() => Promise<void>) | null
}

/**
 * Chat state and actions for the signed-in employee. Every call goes through `useApi` (session cookie, CSRF
 * header, 401 sign-out). Responses for a conversation the user has already left are ignored for the thread
 * but still update the sidebar summary.
 */
export function useChat() {
  const api = useApi()

  const conversations = ref<ConversationSummary[]>([])
  const activeId = ref<number | null>(null)
  const messages = ref<Message[]>([])
  const draft = ref('')

  const initialising = ref(true)
  const loadingThread = ref(false)
  /** A message turn is in flight (shows "Thinking..."). */
  const sending = ref(false)
  /** The card whose action is in flight, with the decision (shows the card's loading state). */
  const acting = ref<{ cardId: string, decision: 'confirm' | 'discard' } | null>(null)

  /** Files picked for the next message (uploaded as soon as they are added). */
  const staged = ref<StagedFile[]>([])
  /** Validation messages for files that were refused before uploading. */
  const attachmentErrors = ref<string[]>([])

  const error = ref<ChatError | null>(null)
  const warning = ref<string | null>(null)
  const notice = ref<string | null>(null)

  let tempSeq = 0
  let loadToken = 0
  let stagedSeq = 0

  const active = computed(() => conversations.value.find(c => c.id === activeId.value) ?? null)
  const busy = computed(() => sending.value || acting.value !== null)
  const uploading = computed(() => isUploading(staged.value))
  const sendable = computed(() => canSendMessage(draft.value, staged.value, busy.value))

  function clearFeedback() {
    error.value = null
    warning.value = null
    notice.value = null
  }

  function fail(cause: unknown, action: ChatAction, retry: (() => Promise<void>) | null = null) {
    error.value = { text: chatErrorMessage(extractStatus(cause), action), retry }
  }

  function upsert(summary: ConversationSummary) {
    conversations.value = upsertConversation(conversations.value, summary)
  }

  /** Loads a conversation's messages (restoring open cards) and makes it the active one. */
  async function openConversation(id: number) {
    const token = ++loadToken
    activeId.value = id
    loadingThread.value = true
    messages.value = []
    draft.value = ''
    discardStaged()
    clearFeedback()
    try {
      const detail = await api<ConversationDetail>(`/api/chat/conversations/${id}`)
      if (token !== loadToken) return
      messages.value = reconcileCards(mergeMessages([], detail.messages), { hasPendingCard: detail.conversation.has_pending_card })
      upsert(detail.conversation)
    }
    catch (cause) {
      if (token !== loadToken) return
      fail(cause, 'load', () => openConversation(id))
    }
    finally {
      if (token === loadToken) loadingThread.value = false
    }
  }

  async function createConversation() {
    const summary = await api<ConversationSummary>('/api/chat/conversations', { method: 'POST' })
    upsert(summary)
    return summary
  }

  /** Fetches the list, opens the most recent conversation or creates the first one. */
  async function init() {
    initialising.value = true
    error.value = null
    try {
      const list = await api<ConversationList>('/api/chat/conversations')
      conversations.value = sortConversations(list.items)
      const first = conversations.value[0] ?? await createConversation()
      await openConversation(first.id)
    }
    catch (cause) {
      fail(cause, 'load', init)
    }
    finally {
      initialising.value = false
    }
  }

  /** Starts a new chat; an untouched empty chat is reused instead of piling up blank conversations. */
  async function newChat() {
    if (busy.value) return
    if (isEmptyConversation(active.value ?? undefined, messages.value) && !loadingThread.value) {
      clearFeedback()
      return
    }
    clearFeedback()
    try {
      const summary = await createConversation()
      await openConversation(summary.id)
    }
    catch (cause) {
      fail(cause, 'load', newChat)
    }
  }

  async function select(id: number) {
    if (id === activeId.value || busy.value) return
    await openConversation(id)
  }

  function revokePreview(item: StagedFile) {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
  }

  /** Drops every staged file (leaving the conversation, or after a successful send). */
  function discardStaged() {
    for (const item of staged.value) revokePreview(item)
    staged.value = []
    attachmentErrors.value = []
  }

  function removeFile(localId: string) {
    const item = staged.value.find(f => f.localId === localId)
    if (item) revokePreview(item)
    staged.value = removeStaged(staged.value, localId)
  }

  function dismissAttachmentErrors() {
    attachmentErrors.value = []
  }

  /** Uploads one staged file to the active conversation; a stale result (chat switched, chip removed) is ignored. */
  async function uploadFile(localId: string, conversationId: number) {
    const item = staged.value.find(f => f.localId === localId)
    if (!item) return
    const form = new FormData() // no Content-Type header: the browser adds the multipart boundary
    form.append('file', item.file, item.name)
    try {
      const res = await api<{ attachment: AttachmentInfo }>(`/api/chat/conversations/${conversationId}/attachments`, {
        method: 'POST',
        body: form,
      })
      if (activeId.value === conversationId) staged.value = markUploaded(staged.value, localId, res.attachment)
    }
    catch (cause) {
      if (activeId.value === conversationId) staged.value = markUploadFailed(staged.value, localId, uploadErrorMessage(extractStatus(cause)))
    }
  }

  /** Validates picked, dropped or pasted files, stages the valid ones and uploads them. */
  async function addFiles(files: File[]) {
    if (!files.length || busy.value) return
    attachmentErrors.value = []
    const { accepted, errors } = validateSelection(files, staged.value.length)
    attachmentErrors.value = errors
    if (!accepted.length) return
    let conversationId = activeId.value
    if (conversationId === null) {
      try {
        conversationId = (await createConversation()).id
        activeId.value = conversationId
      }
      catch (cause) {
        fail(cause, 'load')
        return
      }
    }
    const added = accepted.map(({ file, mime }) => {
      // HEIC often has no browser type: give the upload the resolved one so the server sees a matching type.
      const normalised = file.type === mime ? file : new File([file], file.name, { type: mime })
      const previewUrl = mime.startsWith('image/') ? URL.createObjectURL(normalised) : null
      return newStagedFile(`f${++stagedSeq}`, normalised, file.name, mime, previewUrl)
    })
    staged.value = [...staged.value, ...added]
    const id = conversationId
    await Promise.all(added.map(item => uploadFile(item.localId, id)))
  }

  async function retryUpload(localId: string) {
    if (activeId.value === null) return
    staged.value = markRetrying(staged.value, localId)
    await uploadFile(localId, activeId.value)
  }

  async function send(text?: string) {
    const content = (text ?? draft.value).trim()
    const ready = staged.value
    if (!canSendMessage(content, ready, busy.value) || activeId.value === null) return
    const conversationId = activeId.value
    const tempId = -(++tempSeq)
    const attachmentIds = uploadedIds(ready)
    const attachments = ready.flatMap(f => (f.attachment ? [f.attachment] : []))
    clearFeedback()
    attachmentErrors.value = []
    messages.value = mergeMessages(messages.value, [optimisticMessage(tempId, content, new Date(), attachments)])
    draft.value = ''
    staged.value = [] // moved into the message; restored below if the send fails
    sending.value = true
    try {
      const turn = await api<TurnResponse>(`/api/chat/conversations/${conversationId}/messages`, {
        method: 'POST',
        body: attachmentIds.length ? { content, attachment_ids: attachmentIds } : { content },
      })
      for (const item of ready) revokePreview(item)
      upsert(turn.conversation)
      if (activeId.value !== conversationId) return
      messages.value = reconcileCards(applyTurn(messages.value, tempId, turn), { hasPendingCard: turn.conversation.has_pending_card })
      warning.value = warningMessage(turn.warning_code)
    }
    catch (cause) {
      if (activeId.value !== conversationId) {
        for (const item of ready) revokePreview(item)
        return
      }
      messages.value = messages.value.filter(m => m.id !== tempId)
      if (!draft.value) draft.value = content // keep the text so nothing is lost
      if (!staged.value.length) staged.value = ready // and the files
      else for (const item of ready) revokePreview(item)
      fail(cause, 'send', () => send())
    }
    finally {
      sending.value = false
    }
  }

  async function cardAction(cardId: string, decision: 'confirm' | 'discard') {
    if (busy.value || activeId.value === null) return
    const conversationId = activeId.value
    clearFeedback()
    acting.value = { cardId, decision }
    try {
      const turn = await api<TurnResponse>(`/api/chat/conversations/${conversationId}/actions`, {
        method: 'POST',
        body: { card_id: cardId, action: decision },
      })
      upsert(turn.conversation)
      if (activeId.value !== conversationId) return
      // A failed submission answers with a fresh (retry) card; the acted card is then used either way.
      messages.value = reconcileCards(applyTurn(messages.value, null, turn), {
        hasPendingCard: turn.conversation.has_pending_card,
        acted: { cardId, state: decision === 'confirm' ? 'used' : 'discarded' },
      })
      warning.value = warningMessage(turn.warning_code)
    }
    catch (cause) {
      if (activeId.value !== conversationId) return
      if (extractStatus(cause) === 409) {
        // Stale card: the server is the source of truth, so reload it and explain.
        acting.value = null
        await openConversation(conversationId)
        notice.value = chatErrorMessage(409, 'card')
        return
      }
      fail(cause, 'card', () => cardAction(cardId, decision))
    }
    finally {
      acting.value = null
    }
  }

  function dismissWarning() {
    warning.value = null
  }

  function dismissNotice() {
    notice.value = null
  }

  function dismissError() {
    error.value = null
  }

  /** Re-runs the failed step (send, card action or load). */
  async function retry() {
    const step = error.value?.retry
    if (!step) return
    error.value = null
    await step()
  }

  return {
    conversations,
    activeId,
    active,
    messages,
    draft,
    initialising,
    loadingThread,
    sending,
    acting,
    busy,
    staged,
    attachmentErrors,
    uploading,
    sendable,
    error,
    warning,
    notice,
    init,
    newChat,
    select,
    send,
    addFiles,
    removeFile,
    retryUpload,
    dismissAttachmentErrors,
    cardAction,
    retry,
    dismissWarning,
    dismissNotice,
    dismissError,
  }
}
