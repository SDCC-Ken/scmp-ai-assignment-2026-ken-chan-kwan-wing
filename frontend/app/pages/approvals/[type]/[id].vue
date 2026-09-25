<script setup lang="ts">
import type { ApprovalDetail, Decision } from '~/types/approvals'

const route = useRoute()
const api = useApi()
const queue = useApprovalQueue()
const { user } = useAuth()

const type = computed(() => String(route.params.type))
const id = computed(() => String(route.params.id))

type LoadState = 'loading' | 'ready' | 'missing' | 'error'
const state = ref<LoadState>('loading')
const loadError = ref('')
const detail = ref<ApprovalDetail | null>(null)

const note = ref('')
const confirming = ref<Decision | null>(null)
/** The decision being posted (kept after a failure so Retry can repeat it). */
const posting = ref<Decision | null>(null)
const postError = ref<string | null>(null)
const lastDecision = ref<Decision | null>(null)

const noteRest = computed(() => noteRemaining(note.value))
const noteInvalid = computed(() => noteTooLong(note.value))
const overLimit = computed(() => overLimitSummary(detail.value?.limits))
const requestLabel = computed(() => `${type.value === 'claim' ? 'Claim' : 'Leave request'} #${id.value}`)
const employeeName = computed(() => detail.value?.request.employee.display_name ?? 'the employee')
const busy = computed(() => posting.value !== null)

useHead(() => ({ title: `${requestLabel.value} - SCMP Internal Operations AI Assistant` }))

async function load() {
  state.value = 'loading'
  loadError.value = ''
  if (!isRequestTypeParam(type.value) || !/^\d+$/.test(id.value)) {
    state.value = 'missing'
    return
  }
  try {
    detail.value = await api<ApprovalDetail>(`/api/approvals/${type.value}/${id.value}`)
    state.value = 'ready'
  }
  catch (cause) {
    const status = extractStatus(cause)
    if (status === 404) {
      state.value = 'missing'
    }
    else {
      loadError.value = approvalErrorMessage(status, 'detail')
      state.value = 'error'
    }
  }
}

onMounted(load)

function ask(decision: Decision) {
  if (busy.value || noteInvalid.value) return
  postError.value = null
  confirming.value = decision
}

function cancelConfirm() {
  if (busy.value) return
  confirming.value = null
}

async function submit(decision: Decision) {
  if (busy.value) return
  posting.value = decision
  lastDecision.value = decision
  postError.value = null
  try {
    await api(`/api/approvals/${type.value}/${id.value}/decision`, { method: 'POST', body: buildDecisionBody(decision, note.value) })
    const text = decisionSuccessMessage(decision, type.value, Number(id.value), employeeName.value)
    queue.items.value = queue.items.value.filter(i => !(i.request_type === type.value && String(i.id) === id.value))
    queue.flash.value = { tone: 'green', text }
    confirming.value = null
    await navigateTo('/approvals')
  }
  catch (cause) {
    const status = extractStatus(cause)
    confirming.value = null
    if (status === 409) {
      queue.flash.value = { tone: 'amber', text: `${approvalErrorMessage(409, 'decision')} The list was reloaded.` }
      await queue.refresh({ background: true })
      await navigateTo('/approvals')
    }
    else if (status === 404) {
      state.value = 'missing'
      void queue.refresh({ background: true })
    }
    else {
      postError.value = approvalErrorMessage(status, 'decision')
    }
  }
  finally {
    posting.value = null
  }
}

function retry() {
  if (lastDecision.value) void submit(lastDecision.value)
}

const confirmLabels = computed(() => (confirming.value ? decisionLabels(confirming.value) : null))
</script>

<template>
  <main class="mx-auto max-w-5xl space-y-4 px-4 py-6" aria-labelledby="request-title">
    <NuxtLink
      to="/approvals"
      class="focus-ring inline-flex items-center gap-1 rounded-md py-1 pr-2 text-sm font-medium underline-offset-2 hover:underline"
    >
      <IconGlyph name="back" class="h-4 w-4" />
      Back to {{ approvalsHeading(user?.approves).toLowerCase() }}
    </NuxtLink>

    <p v-if="state === 'loading'" role="status" class="flex items-center gap-2 py-10 text-sm">
      <IconGlyph name="spinner" class="h-4 w-4" />
      Loading request...
    </p>

    <section v-else-if="state === 'missing'" class="rounded-2xl border border-dashed border-secondary/40 p-8 text-center" role="status">
      <IconGlyph name="ban" class="mx-auto h-8 w-8" />
      <h1 id="request-title" class="mt-2 text-lg font-semibold">
        This request is no longer available
      </h1>
      <p class="mt-1 text-sm">
        It may have been decided already, or it is not assigned to you.
      </p>
    </section>

    <div v-else-if="state === 'error'" class="flex items-start gap-2 rounded-lg px-3 py-2 text-sm" :class="toneClass('red')" role="alert">
      <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
      <p class="min-w-0 flex-1">
        {{ loadError }}
      </p>
      <button type="button" class="focus-ring shrink-0 rounded-md border border-current px-2 py-0.5 text-xs font-semibold" @click="load">
        Retry
      </button>
    </div>

    <template v-else-if="detail">
      <header class="rounded-xl border border-secondary/40 p-4">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <h1 id="request-title" class="text-xl font-bold">
              {{ requestLabel }}
            </h1>
            <p class="chat-text mt-1 text-sm">
              <span class="font-semibold">{{ detail.request.employee.display_name }}</span>
              <template v-if="detail.request.employee.department">
                · {{ detail.request.employee.department }}
              </template>
            </p>
          </div>
          <StatusBadge :status="detail.request.status" />
        </div>
        <p class="mt-1 text-xs">
          <template v-if="detail.request.submitted_at">
            Submitted {{ formatDateTime(detail.request.submitted_at) }}
          </template>
          <template v-if="detail.request.external_reference_id">
            · Reference {{ detail.request.external_reference_id }}
          </template>
        </p>
      </header>

      <div v-if="detail.warnings.length" class="space-y-2">
        <div
          v-for="(warning, index) in detail.warnings"
          :key="index"
          class="flex items-start gap-2 rounded-lg px-3 py-2 text-sm"
          :class="toneClass('amber')"
          role="note"
        >
          <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
          <p class="chat-text min-w-0">
            {{ warning }}
          </p>
        </div>
      </div>

      <div class="approval-grid gap-4">
        <ApprovalLimits class="approval-limits" :limits="detail.limits" :request-type="detail.request.request_type" />

        <div class="approval-main space-y-4">
          <section class="rounded-xl border border-secondary/40 p-4" aria-labelledby="fields-title">
            <h2 id="fields-title" class="text-base font-semibold">
              Request details
            </h2>
            <dl class="mt-2 divide-y divide-secondary/15 text-sm">
              <div v-for="field in detail.request.fields" :key="field.key" class="grid grid-cols-1 gap-x-4 gap-y-0.5 py-2 sm:grid-cols-[11rem_1fr]">
                <dt class="font-medium">
                  {{ field.label }}
                </dt>
                <dd class="chat-text min-w-0">
                  {{ fieldValue(field.value) }}
                </dd>
              </div>
            </dl>
          </section>

          <section class="rounded-xl border border-secondary/40 p-4" aria-labelledby="attachments-title">
            <h2 id="attachments-title" class="text-base font-semibold">
              Attachments
            </h2>
            <p v-if="!detail.request.attachments.length" class="mt-2 text-sm">
              No documents were attached.
            </p>
            <ul v-else class="mt-2 flex flex-wrap gap-3" aria-label="Attached documents">
              <li v-for="attachment in detail.request.attachments" :key="attachment.id" class="max-w-full">
                <AttachmentItem :attachment="attachment" />
              </li>
            </ul>
          </section>

          <section v-if="detail.request.request_type === 'leave'" class="rounded-xl border border-secondary/40 p-4" aria-labelledby="team-title">
            <h2 id="team-title" class="text-base font-semibold">
              Team on leave at the same time
            </h2>
            <p v-if="!detail.team_overlap.length" class="mt-2 text-sm">
              Nobody else in the team is on leave then.
            </p>
            <ul v-else class="mt-2 divide-y divide-secondary/15 text-sm">
              <li v-for="(entry, index) in detail.team_overlap" :key="index" class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2">
                <div class="min-w-0">
                  <p class="chat-text font-semibold">
                    {{ entry.employee }}
                  </p>
                  <p class="text-xs">
                    {{ leaveTypeLabel(entry.leave_type) }}, {{ dateRange(entry.start_date, entry.end_date) }}, {{ formatDays(entry.working_days) }}
                  </p>
                </div>
                <StatusBadge :status="entry.status" />
              </li>
            </ul>
          </section>
        </div>

        <section class="approval-decision rounded-xl border border-secondary/60 p-4" aria-labelledby="decision-title">
          <h2 id="decision-title" class="text-base font-semibold">
            Your decision
          </h2>
          <label for="reviewer-note" class="mt-2 block text-sm font-medium">Note for the employee (optional)</label>
          <textarea
            id="reviewer-note"
            v-model="note"
            rows="3"
            :maxlength="NOTE_MAX"
            :disabled="busy"
            aria-describedby="note-counter"
            class="focus-ring mt-1 w-full resize-y rounded-lg border border-secondary/50 bg-background p-2 text-sm text-secondary disabled:opacity-60"
          />
          <p id="note-counter" class="mt-1 text-right text-xs" :class="noteRest < 20 ? 'font-semibold' : ''">
            {{ noteRest }} characters left
          </p>

          <div v-if="postError" class="mt-2 flex items-start gap-2 rounded-lg px-2.5 py-2 text-sm" :class="toneClass('red')" role="alert">
            <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
            <p class="min-w-0 flex-1">
              {{ postError }}
            </p>
            <button type="button" class="focus-ring shrink-0 rounded-md border border-current px-2 py-0.5 text-xs font-semibold" @click="retry">
              Retry
            </button>
          </div>

          <div class="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              class="focus-ring inline-flex min-h-10 flex-1 items-center justify-center rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="busy || noteInvalid"
              @click="ask('approve')"
            >
              Approve
            </button>
            <button
              type="button"
              class="focus-ring inline-flex min-h-10 flex-1 items-center justify-center rounded-lg border border-secondary/60 px-4 py-2 text-sm font-semibold hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="busy || noteInvalid"
              @click="ask('reject')"
            >
              Reject
            </button>
          </div>
          <p class="mt-2 text-xs">
            You will be asked to confirm. The employee is notified of your decision and note.
          </p>
        </section>
      </div>

      <ModalDialog
        :open="confirming !== null"
        alert
        labelledby="confirm-title"
        describedby="confirm-summary"
        :busy="busy"
        @close="cancelConfirm"
      >
        <template v-if="confirming && confirmLabels">
          <h2 id="confirm-title" class="text-lg font-bold">
            {{ confirmLabels.button }} {{ requestLabel.toLowerCase() }}?
          </h2>
          <dl id="confirm-summary" class="mt-3 divide-y divide-secondary/15 text-sm">
            <div class="grid grid-cols-[6rem_1fr] gap-x-3 py-1.5">
              <dt class="font-medium">
                Employee
              </dt>
              <dd class="chat-text">
                {{ detail.request.employee.display_name }}<template v-if="detail.request.employee.department">
                  · {{ detail.request.employee.department }}
                </template>
              </dd>
            </div>
            <div class="grid grid-cols-[6rem_1fr] gap-x-3 py-1.5">
              <dt class="font-medium">
                Request
              </dt>
              <dd class="chat-text">
                {{ detail.request.fields.map(f => `${f.label}: ${fieldValue(f.value)}`).slice(0, 4).join('; ') }}
              </dd>
            </div>
            <div class="grid grid-cols-[6rem_1fr] gap-x-3 py-1.5">
              <dt class="font-medium">
                Decision
              </dt>
              <dd class="font-semibold">
                {{ confirmLabels.button }}
              </dd>
            </div>
            <div class="grid grid-cols-[6rem_1fr] gap-x-3 py-1.5">
              <dt class="font-medium">
                Note
              </dt>
              <dd class="chat-text">
                {{ buildDecisionBody(confirming, note).note ?? 'No note' }}
              </dd>
            </div>
          </dl>
          <div v-if="overLimit" class="mt-3 flex items-start gap-2 rounded-lg px-2.5 py-2 text-sm" :class="toneClass('amber')" role="note">
            <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
            <p><span class="font-semibold">Over limit. </span>{{ overLimit }}</p>
          </div>
          <p v-if="busy" class="sr-only" role="status">
            {{ confirmLabels.busy }}
          </p>
          <div class="mt-4 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              class="focus-ring inline-flex min-h-10 items-center rounded-lg border border-secondary/50 px-4 py-2 text-sm font-medium hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="busy"
              @click="cancelConfirm"
            >
              Cancel
            </button>
            <button
              type="button"
              class="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="busy"
              @click="submit(confirming)"
            >
              <IconGlyph v-if="busy" name="spinner" class="h-4 w-4" />
              {{ busy ? confirmLabels.busy : confirmLabels.confirm }}
            </button>
          </div>
        </template>
      </ModalDialog>
    </template>
  </main>
</template>

<style scoped>
/* One column on phones (limits, details, decision in reading order); from 1024px the limits and the decision sit in a right column. */
.approval-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
}

@media (min-width: 1024px) {
  .approval-grid {
    grid-template-columns: minmax(0, 1fr) 22rem;
    grid-template-areas: "main limits" "main decision";
    grid-template-rows: auto 1fr;
    align-items: start;
  }

  .approval-main { grid-area: main; }
  .approval-limits { grid-area: limits; }
  .approval-decision { grid-area: decision; }
}
</style>
