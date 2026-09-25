<script setup lang="ts">
import type { InboxAction, InboxCardData } from '~/types/chat'

/**
 * One bell-inbox item. Kind "approval" reuses the approvals detail (fields, attachments, limits, team overlap,
 * warnings) plus an optional note and Approve / Reject / Skip; approve and reject use an inline second step
 * ("Confirm approve" + "Back"), and only the confirming click posts. Kind "notice" is a title and body with Got it / Skip.
 * Only the newest open card has active controls; every other card is read-only with a state badge. Plain text only.
 */
const props = defineProps<{
  card: InboxCardData
  /** This is the newest open inbox card of the conversation. */
  active: boolean
  /** The action in flight for THIS card, if any. */
  pending: InboxAction | null
  /** Any turn or card action is running: every control stays disabled. */
  locked: boolean
  /** Inline error of the last failed action of this card. */
  error: { action: InboxAction, text: string } | null
}>()
const emit = defineEmits<{ action: [cardId: string, action: InboxAction, note: string | null] }>()

const uid = useId()
const titleId = computed(() => `inbox-title-${props.card.card_id}`)
const noteId = `${uid}-note`
const counterId = `${uid}-counter`
const promptId = `${uid}-prompt`

const note = ref('')
const confirming = ref<'approve' | 'reject' | null>(null)
const expanded = ref(false)
const approveButton = ref<HTMLButtonElement | null>(null)
const rejectButton = ref<HTMLButtonElement | null>(null)
const confirmButton = ref<HTMLButtonElement | null>(null)

const interactive = computed(() => props.active && props.card.state === 'open')
const badge = computed(() => inboxStateMeta(props.card, props.active))
const disabled = computed(() => props.locked || props.pending !== null)
const noteRest = computed(() => noteRemaining(note.value))
const noteInvalid = computed(() => noteTooLong(note.value))
const overLimit = computed(() => overLimitSummary(props.card.detail?.limits))
const showDetail = computed(() => !!props.card.detail && (interactive.value || expanded.value))
const canApprove = computed(() => props.card.actions.includes('approve'))
const canReject = computed(() => props.card.actions.includes('reject'))
const canSkip = computed(() => props.card.actions.includes('skip'))
const canAcknowledge = computed(() => props.card.actions.includes('acknowledge'))
const submitted = computed(() => props.card.detail?.request.submitted_at ?? null)
const confirmLabels = computed(() => (confirming.value ? inboxActionLabels(confirming.value) : null))

// Once the server has accepted the action (or the card is replaced) the second step goes away.
watch(() => props.card.state, () => {
  confirming.value = null
})

async function ask(action: 'approve' | 'reject') {
  if (disabled.value || noteInvalid.value) return
  confirming.value = action
  await nextTick()
  confirmButton.value?.focus()
}

async function back() {
  if (disabled.value) return
  const previous = confirming.value
  confirming.value = null
  await nextTick()
  ;(previous === 'reject' ? rejectButton.value : approveButton.value)?.focus()
}

function post(action: InboxAction) {
  if (disabled.value) return
  emit('action', props.card.card_id, action, action === 'approve' || action === 'reject' ? note.value : null)
}

const primaryClass = 'focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60'
const outlineClass = 'focus-ring inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-secondary/60 px-4 py-2 text-sm font-semibold hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60'
</script>

<template>
  <section
    class="rounded-xl border p-3"
    :class="interactive ? 'border-secondary/60 bg-background shadow-sm' : 'border-dashed border-secondary/30 bg-secondary/5'"
    :aria-labelledby="titleId"
    :aria-busy="pending !== null"
    :data-inbox-active="interactive ? 'true' : undefined"
  >
    <div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
      <p class="text-xs font-semibold uppercase tracking-wide">
        {{ positionLabel(card.position) }}
      </p>
      <span
        v-if="badge"
        class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold"
        :class="toneClass(badge.tone)"
      >
        <IconGlyph :name="badge.icon" class="h-3.5 w-3.5 shrink-0" />
        {{ badge.label }}
      </span>
    </div>
    <h3
      :id="titleId"
      tabindex="-1"
      data-inbox-heading
      class="focus-ring chat-text mt-1 rounded-sm text-base font-semibold outline-none"
    >
      {{ card.title }}
    </h3>

    <!-- Notice -->
    <p v-if="card.kind === 'notice' && card.notice" class="chat-text mt-2 rounded-lg border border-secondary/25 p-3 text-sm">
      <span v-if="card.notice.title && card.notice.title !== card.title" class="mb-1 block font-semibold">{{ card.notice.title }}</span>
      {{ card.notice.body }}
    </p>

    <!-- Approval: the same detail as the approvals screen -->
    <template v-if="card.kind === 'approval' && card.detail">
      <p class="chat-text mt-1 text-xs">
        <span class="font-medium">{{ card.detail.request.employee.display_name }}</span>
        <template v-if="card.detail.request.employee.department">
          · {{ card.detail.request.employee.department }}
        </template>
        <template v-if="submitted">
          · Submitted {{ formatDateTime(submitted) }}
        </template>
      </p>
      <div v-if="showDetail" class="mt-3">
        <ApprovalDetailPanel :detail="card.detail" layout="stacked" />
      </div>
      <button
        v-else
        type="button"
        class="focus-ring mt-2 inline-flex items-center gap-1 rounded-md py-1 pr-2 text-sm font-medium underline underline-offset-2"
        :aria-expanded="expanded"
        @click="expanded = true"
      >
        Show details
      </button>
      <button
        v-if="!interactive && expanded"
        type="button"
        class="focus-ring mt-2 inline-flex items-center gap-1 rounded-md py-1 pr-2 text-sm font-medium underline underline-offset-2"
        aria-expanded="true"
        @click="expanded = false"
      >
        Hide details
      </button>
    </template>

    <!-- Controls: only on the newest open card -->
    <div v-if="interactive" class="mt-3 rounded-lg border border-secondary/40 p-3">
      <template v-if="card.kind === 'approval'">
        <label :for="noteId" class="block text-sm font-medium">Note for the employee (optional)</label>
        <textarea
          :id="noteId"
          v-model="note"
          rows="2"
          :maxlength="NOTE_MAX"
          :disabled="disabled"
          :aria-describedby="counterId"
          class="focus-ring mt-1 w-full resize-y rounded-lg border border-secondary/50 bg-background p-2 text-sm text-secondary disabled:opacity-60"
        />
        <p :id="counterId" class="mt-1 text-right text-xs" :class="noteRest < 20 ? 'font-semibold' : ''">
          {{ noteRest }} characters left
        </p>
      </template>

      <div v-if="error" class="mt-2 flex items-start gap-2 rounded-lg px-2.5 py-2 text-sm" :class="toneClass('red')" role="alert">
        <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
        <p class="min-w-0 flex-1">
          {{ error.text }}
        </p>
        <button
          type="button"
          class="focus-ring shrink-0 rounded-md border border-current px-2 py-0.5 text-xs font-semibold disabled:opacity-60"
          :disabled="disabled"
          @click="post(error.action)"
        >
          Retry
        </button>
      </div>

      <!-- Approve / Reject: second step -->
      <template v-if="card.kind === 'approval' && confirming && confirmLabels">
        <p :id="promptId" class="mt-2 text-sm font-medium">
          {{ confirming === 'approve' ? 'Approve' : 'Reject' }} this request? Press "{{ confirmLabels.confirm }}" to send your decision.
        </p>
        <div v-if="overLimit" class="mt-2 flex items-start gap-2 rounded-lg px-2.5 py-2 text-sm" :class="toneClass('amber')" role="note">
          <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
          <p><span class="font-semibold">Over limit. </span>{{ overLimit }} You decide.</p>
        </div>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            ref="confirmButton"
            type="button"
            :class="primaryClass"
            :disabled="disabled"
            :aria-describedby="promptId"
            @click="post(confirming)"
          >
            <IconGlyph v-if="pending === confirming" name="spinner" class="h-4 w-4" />
            {{ pending === confirming ? confirmLabels.busy : confirmLabels.confirm }}
          </button>
          <button type="button" :class="outlineClass" :disabled="disabled" @click="back">
            Back
          </button>
        </div>
      </template>

      <!-- First step -->
      <div v-else class="mt-3 flex flex-wrap gap-2">
        <template v-if="card.kind === 'approval'">
          <button v-if="canApprove" ref="approveButton" type="button" :class="primaryClass" :disabled="disabled || noteInvalid" @click="ask('approve')">
            Approve
          </button>
          <button v-if="canReject" ref="rejectButton" type="button" :class="outlineClass" :disabled="disabled || noteInvalid" @click="ask('reject')">
            Reject
          </button>
        </template>
        <button v-if="card.kind === 'notice' && canAcknowledge" type="button" :class="primaryClass" :disabled="disabled" @click="post('acknowledge')">
          <IconGlyph v-if="pending === 'acknowledge'" name="spinner" class="h-4 w-4" />
          {{ pending === 'acknowledge' ? inboxActionLabels('acknowledge').busy : 'Got it' }}
        </button>
        <button v-if="canSkip" type="button" :class="outlineClass" :disabled="disabled" @click="post('skip')">
          <IconGlyph v-if="pending === 'skip'" name="spinner" class="h-4 w-4" />
          {{ pending === 'skip' ? inboxActionLabels('skip').busy : 'Skip' }}
        </button>
      </div>
      <p v-if="card.kind === 'approval' && !confirming" class="mt-2 text-xs">
        You will be asked to confirm Approve or Reject. Skip keeps the item for later.
      </p>
      <p v-if="pending" class="sr-only" role="status">
        {{ inboxActionLabels(pending).busy }}
      </p>
    </div>
  </section>
</template>
