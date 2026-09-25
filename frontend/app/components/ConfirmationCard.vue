<script setup lang="ts">
import type { ConfirmationCardData } from '~/types/chat'

const props = defineProps<{
  card: ConfirmationCardData
  /** The action in flight for THIS card, if any. */
  pending: 'confirm' | 'discard' | null
  /** Any turn or card action is running elsewhere: buttons stay disabled. */
  locked: boolean
}>()
defineEmits<{ action: [cardId: string, decision: 'confirm' | 'discard'] }>()

const isOpen = computed(() => props.card.state === 'open')
const stateMeta = computed(() => cardStateMeta(props.card.state))
const disabled = computed(() => props.locked || props.pending !== null)
const infoLines = computed(() => normalizeInfoLines(props.card.info))
const titleId = computed(() => `card-title-${props.card.card_id}`)
</script>

<template>
  <section
    class="rounded-xl border p-3"
    :class="isOpen ? 'border-secondary/60 bg-background shadow-sm' : 'border-dashed border-secondary/30 bg-secondary/5'"
    :aria-labelledby="titleId"
    :aria-busy="pending !== null"
  >
    <div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
      <h3 :id="titleId" class="text-sm font-semibold">
        {{ card.title }}
      </h3>
      <span
        v-if="!isOpen"
        class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold"
        :class="toneClass(stateMeta.tone)"
      >
        <IconGlyph :name="stateMeta.icon" class="h-3.5 w-3.5 shrink-0" />
        {{ stateMeta.label }}
      </span>
    </div>

    <dl class="mt-2 divide-y divide-secondary/15 text-sm">
      <div v-for="field in card.fields" :key="field.key" class="grid grid-cols-[minmax(0,7rem)_1fr] gap-x-3 py-1.5">
        <dt class="font-medium opacity-90">
          {{ field.label }}
        </dt>
        <dd class="chat-text min-w-0">
          <template v-if="fieldHasDiff(field)">
            <del class="opacity-80">{{ fieldValue(field.old_value) }}</del>
            <span class="sr-only"> changed to </span>
            <span aria-hidden="true"> &rarr; </span>
            <ins class="font-semibold no-underline">{{ fieldValue(field.value) }}</ins>
          </template>
          <template v-else>
            {{ fieldValue(field.value) }}
          </template>
          <span
            v-if="field.source === 'document'"
            class="ml-1.5 inline-flex items-center gap-1 whitespace-nowrap rounded-full px-1.5 py-0.5 align-middle text-xs font-semibold"
            :class="toneClass('grey')"
          >
            <IconGlyph name="file" class="h-3 w-3 shrink-0" />
            from document
          </span>
        </dd>
      </div>
    </dl>

    <div v-if="card.attachments?.length" class="mt-2 border-t border-secondary/15 pt-2">
      <p class="text-xs font-medium">
        Attached documents that will be sent to your approver with the request
      </p>
      <ul class="mt-1.5 flex flex-wrap gap-2" aria-label="Attached documents">
        <li v-for="attachment in card.attachments" :key="attachment.id" class="max-w-full">
          <AttachmentItem :attachment="attachment" size="small" />
        </li>
      </ul>
    </div>

    <div
      v-for="(warning, index) in card.warnings"
      :key="index"
      class="mt-2 flex items-start gap-2 rounded-lg px-2.5 py-2 text-xs"
      :class="toneClass('amber')"
      role="note"
    >
      <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
      <span class="chat-text"><span class="font-semibold">Note: </span>{{ warning }}</span>
    </div>

    <ul v-if="infoLines.length" class="mt-2 space-y-1.5" aria-label="More information">
      <li
        v-for="(line, index) in infoLines"
        :key="index"
        class="flex items-start gap-2 rounded-lg px-2.5 py-2 text-xs"
        :class="toneClass(line.tone === 'warning' ? 'amber' : 'grey')"
      >
        <IconGlyph :name="line.tone === 'warning' ? 'alert' : 'info'" class="mt-0.5 h-4 w-4 shrink-0" />
        <span class="chat-text"><span v-if="line.label" class="font-semibold">{{ line.label }}: </span>{{ line.value }}</span>
      </li>
    </ul>

    <template v-if="isOpen">
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="disabled"
          @click="$emit('action', card.card_id, 'confirm')"
        >
          <IconGlyph v-if="pending === 'confirm'" name="spinner" class="h-4 w-4" />
          {{ pending === 'confirm' ? cardBusyLabel(card.action, 'confirm') : card.confirm_label }}
        </button>
        <button
          type="button"
          class="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border border-secondary/50 px-4 py-2 text-sm font-medium hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="disabled"
          @click="$emit('action', card.card_id, 'discard')"
        >
          <IconGlyph v-if="pending === 'discard'" name="spinner" class="h-4 w-4" />
          {{ pending === 'discard' ? cardBusyLabel(card.action, 'discard') : 'Discard' }}
        </button>
      </div>
      <p class="mt-2 text-xs opacity-90">
        Or just keep typing to change something.
      </p>
      <p v-if="pending" class="sr-only" role="status">
        {{ cardBusyLabel(card.action, pending) }}
      </p>
    </template>
  </section>
</template>
