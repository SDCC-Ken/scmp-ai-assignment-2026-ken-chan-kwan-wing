<script setup lang="ts">
import type { BarView } from '~/utils/approvals'

/**
 * Stacked bar: approved | this request | other pending, with a marker at the limit. It is a picture of numbers that
 * the parent lists as text, so it is exposed as one labelled image (colour is never the only cue).
 */
const props = defineProps<{
  bar: BarView
  label: string
  /** Show the "this request" legend entry (balance cards in chat have no current request). */
  showRequested?: boolean
}>()
</script>

<template>
  <div>
    <div class="limit-track" role="img" :aria-label="label">
      <div class="limit-seg-approved h-full" :style="{ width: `${bar.approvedPct}%` }" />
      <div v-if="bar.requestedPct > 0" class="limit-seg-requested h-full" :class="bar.exceeds ? 'is-over' : ''" :style="{ width: `${bar.requestedPct}%` }" />
      <div v-if="bar.pendingPct > 0" class="limit-seg-pending h-full" :style="{ width: `${bar.pendingPct}%` }" />
      <div v-if="bar.limitPct > 0 && bar.limitPct < 100" class="limit-marker" :style="{ left: `calc(${bar.limitPct}% - 1px)` }" />
    </div>
    <p class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs" aria-hidden="true">
      <span><span class="limit-swatch limit-seg-approved" /> Approved</span>
      <span v-if="props.showRequested"><span class="limit-swatch limit-seg-requested" :class="bar.exceeds ? 'is-over' : ''" /> This request</span>
      <span><span class="limit-swatch limit-seg-pending" /> Pending</span>
    </p>
  </div>
</template>
