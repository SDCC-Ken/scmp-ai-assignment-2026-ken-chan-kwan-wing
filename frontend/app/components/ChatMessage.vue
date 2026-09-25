<script setup lang="ts">
import type { Message } from '~/types/chat'

defineProps<{
  message: Message
  /** Decision in flight for a card of this message (only ever set for that card). */
  pending: { cardId: string, decision: 'confirm' | 'discard' } | null
  /** A turn or card action is running: card buttons are disabled. */
  locked: boolean
}>()
defineEmits<{ action: [cardId: string, decision: 'confirm' | 'discard'] }>()
</script>

<template>
  <li v-if="message.sender_type === 'system'" class="flex justify-center">
    <p class="chat-text rounded-full border border-secondary/30 px-3 py-1 text-center text-xs">
      {{ message.content }}
    </p>
  </li>

  <li v-else-if="message.sender_type === 'user'" class="flex flex-col items-end">
    <ul v-if="message.attachments?.length" class="mb-1 flex max-w-[85%] flex-wrap justify-end gap-2" aria-label="Attached files">
      <li v-for="attachment in message.attachments" :key="attachment.id" class="max-w-full">
        <AttachmentItem :attachment="attachment" />
      </li>
    </ul>
    <p
      v-if="message.content.trim()"
      class="chat-text max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-sm text-background"
      :class="isOptimistic(message) ? 'opacity-80' : ''"
    >
      {{ message.content }}
    </p>
    <p class="mt-0.5 px-1 text-xs opacity-80">
      <span v-if="isOptimistic(message)">Sending...</span>
      <time v-else :datetime="message.created_at">{{ formatClock(message.created_at) }}</time>
    </p>
  </li>

  <li v-else class="flex flex-col items-start">
    <p
      v-if="message.content.trim()"
      class="chat-text max-w-[85%] rounded-2xl rounded-bl-md border border-secondary/30 bg-secondary/5 px-3.5 py-2 text-sm"
    >
      <span class="sr-only">Assistant: </span>{{ message.content }}
    </p>
    <div v-if="message.ui" class="mt-2 w-full max-w-[min(100%,34rem)]">
      <ConfirmationCard
        v-if="message.ui.type === 'confirmation_card'"
        :card="message.ui"
        :pending="pending && pending.cardId === message.ui.card_id ? pending.decision : null"
        :locked="locked"
        @action="(id, decision) => $emit('action', id, decision)"
      />
      <StatusCard v-else-if="message.ui.type === 'status_card'" :card="message.ui" />
      <ResultCard v-else-if="message.ui.type === 'result_card'" :card="message.ui" />
      <BalanceCard v-else-if="message.ui.type === 'balance_card'" :card="message.ui" />
    </div>
    <TraceDisclosure v-if="message.trace && message.trace.length" :steps="message.trace" />
    <p class="mt-0.5 px-1 text-xs opacity-80">
      <time :datetime="message.created_at">{{ formatClock(message.created_at) }}</time>
    </p>
  </li>
</template>
