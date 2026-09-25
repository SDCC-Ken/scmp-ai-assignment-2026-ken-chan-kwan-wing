<script setup lang="ts">
import type { ResultCardData } from '~/types/chat'

const props = defineProps<{ card: ResultCardData }>()
const meta = computed(() => outcomeMeta(props.card.outcome))
</script>

<template>
  <section class="rounded-xl border p-3" :class="toneClass(meta.tone)" :aria-label="`${meta.label} result`">
    <div class="flex items-start gap-2.5">
      <IconGlyph :name="meta.icon" class="mt-0.5 h-5 w-5 shrink-0" />
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold">
          {{ meta.label }}
          <span class="font-normal">- {{ card.request_type === 'leave' ? 'Leave application' : 'Staff claim' }} #{{ card.request_id }}</span>
        </p>
        <p class="chat-text mt-1 text-sm">
          {{ card.message }}
        </p>
        <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <StatusBadge :status="card.status" :label="card.status_label" />
          <span v-if="card.external_reference_id">ReqRes reference: <span class="font-semibold">{{ card.external_reference_id }}</span></span>
        </div>
      </div>
    </div>
  </section>
</template>
