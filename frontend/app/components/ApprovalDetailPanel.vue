<script setup lang="ts">
import type { ApprovalDetail } from '~/types/approvals'

/**
 * Everything an approver needs to decide, shared by the approvals detail page and the chat inbox card: amber warnings,
 * the limits (leave balance or department budget, with the over-limit notice), the request fields, attachments (with
 * the preview) and the team-overlap list. Plain text only. The `decision` slot holds the note and buttons.
 * `page` lays it out in two columns from 1024px (limits and decision on the right); `stacked` is one compact column for a chat card.
 */
const props = withDefaults(defineProps<{
  detail: ApprovalDetail
  layout?: 'page' | 'stacked'
}>(), { layout: 'page' })

const uid = useId()
const stacked = computed(() => props.layout === 'stacked')
const heading = computed(() => (stacked.value ? 'h4' : 'h2'))
const headingClass = computed(() => (stacked.value ? 'text-sm font-semibold' : 'text-base font-semibold'))
const boxClass = computed(() => (stacked.value ? 'rounded-lg border border-secondary/30 p-3' : 'rounded-xl border border-secondary/40 p-4'))
</script>

<template>
  <div :class="stacked ? 'space-y-3' : 'space-y-4'">
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

    <div :class="stacked ? 'space-y-3' : 'approval-grid gap-4'">
      <ApprovalLimits
        :class="stacked ? '' : 'approval-limits'"
        :limits="detail.limits"
        :request-type="detail.request.request_type"
        :compact="stacked"
      />

      <div :class="stacked ? 'space-y-3' : 'approval-main space-y-4'">
        <section :class="boxClass" :aria-labelledby="`${uid}-fields`">
          <component :is="heading" :id="`${uid}-fields`" :class="headingClass">
            Request details
          </component>
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

        <section :class="boxClass" :aria-labelledby="`${uid}-attachments`">
          <component :is="heading" :id="`${uid}-attachments`" :class="headingClass">
            Attachments
          </component>
          <p v-if="!detail.request.attachments.length" class="mt-2 text-sm">
            No documents were attached.
          </p>
          <ul v-else class="mt-2 flex flex-wrap gap-3" aria-label="Attached documents">
            <li v-for="attachment in detail.request.attachments" :key="attachment.id" class="max-w-full">
              <AttachmentItem :attachment="attachment" :size="stacked ? 'small' : 'large'" />
            </li>
          </ul>
        </section>

        <section v-if="detail.request.request_type === 'leave'" :class="boxClass" :aria-labelledby="`${uid}-team`">
          <component :is="heading" :id="`${uid}-team`" :class="headingClass">
            Team on leave at the same time
          </component>
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

      <div v-if="$slots.decision" :class="stacked ? '' : 'approval-decision'">
        <slot name="decision" />
      </div>
    </div>
  </div>
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
