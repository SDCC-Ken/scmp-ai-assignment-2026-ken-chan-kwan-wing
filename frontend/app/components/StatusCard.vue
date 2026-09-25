<script setup lang="ts">
import type { StatusCardData } from '~/types/chat'

defineProps<{ card: StatusCardData }>()
</script>

<template>
  <section class="rounded-xl border border-secondary/30 p-3" aria-label="Your requests">
    <p v-if="card.empty || !card.requests.length" class="text-sm">
      No matching requests.
    </p>
    <ul v-else class="space-y-2.5">
      <li v-for="req in card.requests" :key="`${req.request_type}-${req.id}`" class="rounded-lg border border-secondary/25 p-2.5">
        <div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <p class="text-sm font-semibold">
            {{ req.request_type === 'leave' ? 'Leave application' : 'Staff claim' }} #{{ req.id }}
          </p>
          <StatusBadge :status="req.status" :label="req.status_label" />
        </div>
        <p class="chat-text mt-1 text-sm">
          {{ req.summary }}
        </p>
        <dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
          <template v-if="req.submitted_at">
            <dt class="font-semibold">
              Submitted
            </dt>
            <dd>{{ formatDateTime(req.submitted_at) }}</dd>
          </template>
          <template v-if="req.reviewed_at">
            <dt class="font-semibold">
              Reviewed
            </dt>
            <dd>{{ formatDateTime(req.reviewed_at) }}</dd>
          </template>
          <template v-if="req.reviewer_note">
            <dt class="font-semibold">
              Reviewer note
            </dt>
            <dd class="chat-text">
              {{ req.reviewer_note }}
            </dd>
          </template>
          <template v-if="req.external_reference_id">
            <dt class="font-semibold">
              Reference
            </dt>
            <dd class="chat-text">
              {{ req.external_reference_id }}
            </dd>
          </template>
        </dl>
      </li>
    </ul>
  </section>
</template>
