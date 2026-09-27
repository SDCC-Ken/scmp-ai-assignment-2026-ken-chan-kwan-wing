<script setup lang="ts">
import type { ConversationSummary } from '~/types/chat'

defineProps<{
  conversations: ConversationSummary[]
  activeId: number | null
  loading: boolean
  /** A turn is in flight: switching or starting chats is paused. */
  busy: boolean
}>()
defineEmits<{
  select: [id: number]
  create: []
}>()

// Relative times refresh once a minute.
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  timer = setInterval(() => (now.value = Date.now()), 60_000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <div class="p-3">
      <button
        type="button"
        data-testid="new-chat-button"
        class="focus-ring inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-secondary px-3 py-2 text-sm font-semibold text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="busy || loading"
        @click="$emit('create')"
      >
        <IconGlyph name="plus" class="h-4 w-4" />
        New chat
      </button>
    </div>

    <p v-if="loading" class="flex items-center gap-2 px-4 py-2 text-sm" role="status">
      <IconGlyph name="spinner" class="h-4 w-4" />
      Loading chats...
    </p>
    <p v-else-if="!conversations.length" class="px-4 py-2 text-sm opacity-90">
      No chats yet.
    </p>
    <ul v-else class="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3">
      <li v-for="conversation in conversations" :key="conversation.id">
        <button
          type="button"
          class="focus-ring block w-full rounded-lg border px-3 py-2 text-left disabled:cursor-not-allowed"
          :class="conversation.id === activeId ? 'border-secondary/60 bg-secondary/10' : 'border-transparent hover:bg-secondary/10'"
          :aria-current="conversation.id === activeId ? 'true' : undefined"
          :disabled="busy && conversation.id !== activeId"
          @click="$emit('select', conversation.id)"
        >
          <span class="flex items-center gap-1.5">
            <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ conversation.title }}</span>
            <span
              v-if="isInboxConversation(conversation)"
              class="inline-flex shrink-0 items-center gap-1 rounded-full px-1.5 py-0.5 text-xs font-semibold"
              :class="toneClass('grey')"
            >
              <IconGlyph name="inbox" class="h-3 w-3" />
              Inbox
            </span>
          </span>
          <span class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span class="opacity-90">Updated {{ relativeTime(conversation.updated_at, now) }}</span>
            <span
              v-for="badge in conversationBadges(conversation)"
              :key="badge.kind"
              class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 font-semibold"
              :class="toneClass(badge.kind === 'card' ? 'amber' : 'grey')"
            >
              <IconGlyph :name="badge.kind === 'card' ? 'clock' : 'pencil'" class="h-3 w-3" />
              {{ badge.label }}
            </span>
          </span>
        </button>
      </li>
    </ul>
    <p class="mt-auto border-t border-secondary/30 px-4 py-2.5 text-xs opacity-90">
      Mock session: fictional demo data only.
    </p>
  </div>
</template>
