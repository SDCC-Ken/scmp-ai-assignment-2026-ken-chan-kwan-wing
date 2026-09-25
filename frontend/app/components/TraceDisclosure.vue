<script setup lang="ts">
import type { TraceStep } from '~/types/chat'

defineProps<{ steps: TraceStep[] }>()
</script>

<template>
  <details class="group mt-2 text-sm">
    <summary
      class="focus-ring inline-flex cursor-pointer list-none items-center gap-1 rounded-md py-1 pr-2 text-xs font-medium underline-offset-2 hover:underline [&::-webkit-details-marker]:hidden"
    >
      <IconGlyph name="chevron" class="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
      How I understood this
    </summary>
    <ol class="mt-1 space-y-1.5 rounded-lg border border-secondary/25 p-2.5" aria-label="AI processing steps">
      <li v-for="(step, index) in steps" :key="`${step.step}-${index}`" class="flex items-start gap-2">
        <span
          class="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
          :class="toneClass(step.ok ? 'green' : 'red')"
        >
          <IconGlyph :name="step.ok ? 'check' : 'x'" class="h-3 w-3" />
          <span class="sr-only">{{ step.ok ? 'Succeeded' : 'Failed' }}</span>
        </span>
        <span class="min-w-0 flex-1">
          <span class="block text-xs font-semibold">{{ step.label }}</span>
          <span v-if="step.detail" class="chat-text block text-xs opacity-90">{{ step.detail }}</span>
        </span>
        <span class="shrink-0 text-xs tabular-nums opacity-90">{{ formatDuration(step.duration_ms) }}</span>
      </li>
    </ol>
  </details>
</template>
