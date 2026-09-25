<script setup lang="ts">
import type { ApprovalDetail } from '~/types/approvals'

const props = defineProps<{ limits: ApprovalDetail['limits'], requestType: string }>()

const leave = computed(() => props.limits.leave_balance)
const budget = computed(() => props.limits.department_budget)
const over = computed(() => overLimitSummary(props.limits))

const view = computed(() => {
  if (leave.value) {
    const lb = leave.value
    return {
      title: `${leaveTypeLabel(lb.leave_type)} balance ${lb.year}`,
      rows: leaveBalanceRows(lb),
      bar: limitBar(leaveBarInput(lb)),
      label: limitBarLabel(`${leaveTypeLabel(lb.leave_type)} balance`, {
        limit: formatDays(lb.entitled_days),
        approved: formatDays(lb.approved_days),
        requested: formatDays(lb.requested_days),
        pending: formatDays(lb.pending_other_days),
        over: lb.over_limit,
      }),
      over: lb.over_limit,
    }
  }
  if (budget.value) {
    const b = budget.value
    return {
      title: `${b.department} department claim budget ${b.year}`,
      rows: budgetRows(b),
      bar: limitBar(budgetBarInput(b)),
      label: limitBarLabel(`${b.department} claim budget`, {
        limit: formatMoney(b.limit_amount, b.currency),
        approved: formatMoney(b.approved_amount, b.currency),
        requested: formatMoney(b.requested_amount, b.currency),
        pending: formatMoney(b.pending_other_amount, b.currency),
        over: b.over_limit,
      }),
      over: b.over_limit,
    }
  }
  return null
})
</script>

<template>
  <section class="rounded-xl border border-secondary/40 p-4" aria-labelledby="limits-title">
    <h2 id="limits-title" class="text-base font-semibold">
      Limits
    </h2>

    <p v-if="!view" class="mt-2 text-sm">
      <template v-if="requestType === 'leave'">
        No balance applies to personal or unpaid leave.
      </template>
      <template v-else>
        No department budget information is available for this claim.
      </template>
    </p>

    <template v-else>
      <p class="mt-1 text-sm font-medium">
        {{ view.title }}
      </p>
      <div
        v-if="view.over"
        class="mt-2 flex items-start gap-2 rounded-lg px-2.5 py-2 text-sm"
        :class="toneClass('amber')"
        role="note"
      >
        <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          <span class="font-semibold">Over limit. </span>{{ over }} The limit does not block the request; you decide.
        </p>
      </div>
      <LimitBar class="mt-3" :bar="view.bar" :label="view.label" show-requested />
      <dl class="mt-3 divide-y divide-secondary/15 text-sm">
        <div v-for="row in view.rows" :key="row.key" class="flex items-baseline justify-between gap-3 py-1.5">
          <dt :class="row.emphasis ? 'font-semibold' : ''">
            {{ row.label }}
          </dt>
          <dd class="text-right tabular-nums" :class="row.emphasis ? 'font-bold' : ''">
            {{ row.value }}
          </dd>
        </div>
      </dl>
    </template>
  </section>
</template>
