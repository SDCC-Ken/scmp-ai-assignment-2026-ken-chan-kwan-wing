<script setup lang="ts">
import type { InboxAction, Message } from '~/types/chat'

const props = defineProps<{
  conversationId: number | null
  messages: Message[]
  loading: boolean
  sending: boolean
  acting: { cardId: string, decision: 'confirm' | 'discard' } | null
  busy: boolean
  /** The user may file requests: show the filing suggestions in the empty state. Otherwise a lighter inbox hint. */
  canRequest: boolean
  activeInboxId: string | null
  inboxActing: { cardId: string, action: InboxAction } | null
  inboxError: { cardId: string, action: InboxAction, text: string } | null
}>()
const emit = defineEmits<{
  action: [cardId: string, decision: 'confirm' | 'discard']
  inbox: [cardId: string, action: InboxAction, note: string | null]
  suggest: [text: string]
}>()

const scroller = ref<HTMLElement | null>(null)
/** True while the view follows new messages; turns false as soon as the user scrolls up. */
const following = ref(true)
const announcement = ref('')

// Instant (not smooth) on purpose: a smooth scroll fires scroll events that would look like the user scrolling up.
function scrollToBottom() {
  const el = scroller.value
  if (el) el.scrollTop = el.scrollHeight
}

function onScroll() {
  const el = scroller.value
  if (el) following.value = isNearBottom(el)
}

function jumpToLatest() {
  following.value = true
  scrollToBottom()
}

// A different conversation: start at the bottom and stay silent (only NEW assistant messages are announced).
watch(() => props.conversationId, () => {
  following.value = true
  announcement.value = ''
})

// Messages that are on screen when a conversation finishes loading are not "new".
let announcedUpTo = 0
watch(() => props.loading, (loading) => {
  if (!loading) announcedUpTo = props.messages.reduce((max, m) => Math.max(max, m.id), 0)
}, { immediate: true })

watch(() => props.messages, async (list, previous) => {
  if (props.loading) return
  const fresh = list.filter(m => m.sender_type === 'assistant' && m.id > announcedUpTo)
  if (fresh.length && previous.length) {
    announcement.value = fresh.map(announcementFor).join(' ')
  }
  announcedUpTo = Math.max(announcedUpTo, ...list.map(m => m.id))
  // Own message: always show it. Otherwise only follow when the user has not scrolled up.
  if (lastMessageIsUser(list)) following.value = true
  await nextTick()
  if (following.value) scrollToBottom()
})

watch(() => [props.loading, props.sending, props.acting], async () => {
  await nextTick()
  if (following.value) scrollToBottom()
})

const isEmpty = computed(() => !props.loading && props.messages.length === 0)
</script>

<template>
  <div class="relative min-h-0 flex-1">
    <div
      ref="scroller"
      class="h-full overflow-y-auto overscroll-contain px-3 py-4 sm:px-5"
      tabindex="0"
      role="region"
      aria-label="Conversation messages"
      @scroll.passive="onScroll"
    >
      <div v-if="loading" class="flex h-full items-center justify-center gap-2 text-sm" role="status">
        <IconGlyph name="spinner" class="h-4 w-4" />
        Loading conversation...
      </div>

      <div v-else-if="isEmpty && !canRequest" class="mx-auto flex h-full max-w-xl flex-col items-center justify-center gap-3 py-6 text-center">
        <span class="flex h-12 w-12 items-center justify-center rounded-full border border-secondary/40" aria-hidden="true">
          <IconGlyph name="inbox" class="h-6 w-6" />
        </span>
        <h2 class="text-lg font-semibold">
          Nothing here yet
        </h2>
        <p class="text-sm opacity-90">
          Use the bell to see what needs your attention. You can also ask me a question below, for example about the status of a request.
        </p>
      </div>

      <div v-else-if="isEmpty" class="mx-auto flex h-full max-w-xl flex-col items-center justify-center gap-4 py-6 text-center">
        <span class="flex h-12 w-12 items-center justify-center rounded-full border border-secondary/40" aria-hidden="true">
          <IconGlyph name="chat" class="h-6 w-6" />
        </span>
        <div>
          <h2 class="text-lg font-semibold">
            How can I help today?
          </h2>
          <p class="mt-1 text-sm opacity-90">
            Tell me in your own words about a leave application or a staff claim. I will ask for anything missing
            and show a card to confirm before anything is submitted.
          </p>
        </div>
        <SuggestionChips :disabled="busy" @pick="text => emit('suggest', text)" />
      </div>

      <ol v-else class="mx-auto flex max-w-3xl flex-col gap-4" aria-label="Messages">
        <ChatMessage
          v-for="message in messages"
          :key="message.id"
          :message="message"
          :pending="acting"
          :locked="busy"
          :active-inbox-id="activeInboxId"
          :inbox-acting="inboxActing"
          :inbox-error="inboxError"
          @action="(id, decision) => emit('action', id, decision)"
          @inbox="(id, action, note) => emit('inbox', id, action, note)"
        />
        <li v-if="sending" class="flex items-start" role="status">
          <span class="inline-flex items-center gap-2 rounded-2xl rounded-bl-md border border-secondary/30 bg-secondary/5 px-3.5 py-2 text-sm">
            <span class="flex items-center gap-1" aria-hidden="true"><span class="chat-dot" /><span class="chat-dot" /><span class="chat-dot" /></span>
            Thinking...
          </span>
        </li>
      </ol>
    </div>

    <button
      v-if="!following && messages.length"
      type="button"
      class="focus-ring absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full bg-secondary px-3 py-1.5 text-xs font-semibold text-background shadow-md hover:opacity-90"
      @click="jumpToLatest"
    >
      <IconGlyph name="down" class="h-3.5 w-3.5" />
      Jump to latest
    </button>

    <div class="sr-only" aria-live="polite" aria-atomic="true">
      {{ announcement }}
    </div>
  </div>
</template>
