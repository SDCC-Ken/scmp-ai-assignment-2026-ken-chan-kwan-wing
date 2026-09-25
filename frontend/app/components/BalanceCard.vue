<script setup lang="ts">
import type { BalanceCardData } from '~/types/chat'

const props = defineProps<{ card: BalanceCardData }>()
const views = computed(() => validBalanceLines(props.card).map(line => ({ line, view: balanceLineView(line) })))
</script>

<template>
  <section class="rounded-xl border border-secondary/30 p-3" :aria-label="`Leave balance ${card.year}`">
    <h3 class="text-sm font-semibold">
      Your leave balance for {{ card.year }}
    </h3>
    <p v-if="!views.length" class="mt-2 text-sm">
      No leave balance applies to you.
    </p>
    <ul v-else class="mt-2 space-y-3">
      <li v-for="{ line, view } in views" :key="line.leave_type">
        <div class="flex flex-wrap items-baseline justify-between gap-x-2">
          <p class="text-sm font-semibold">
            {{ view.label }}
          </p>
          <p class="text-sm">
            {{ view.summary }}
          </p>
        </div>
        <LimitBar class="mt-1.5" :bar="view.bar" :label="`${view.label}: ${view.summary}, ${formatDays(line.approved_days)} approved, ${formatDays(line.pending_days)} pending`" />
        <dl class="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs sm:grid-cols-4">
          <div v-for="stat in view.stats" :key="stat.key">
            <dt class="opacity-90">
              {{ stat.label }}
            </dt>
            <dd class="font-semibold">
              {{ stat.value }}
            </dd>
          </div>
        </dl>
      </li>
    </ul>
    <p class="mt-2 text-xs opacity-90">
      Pending requests are shown but not deducted until they are approved.
    </p>
  </section>
</template>
