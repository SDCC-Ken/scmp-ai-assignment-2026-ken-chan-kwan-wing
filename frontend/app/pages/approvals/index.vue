<script setup lang="ts">
const { user } = useAuth()
const queue = useApprovalQueue()
const heading = computed(() => approvalsHeading(user.value?.approves))
useHead(() => ({ title: `${heading.value} - SCMP Internal Operations AI Assistant` }))

const firstLoad = computed(() => !queue.loaded.value && !queue.error.value)
const refreshing = computed(() => queue.loading.value)

const title = ref<HTMLElement | null>(null)

// A foreground load on entry (the header's 30 s poll keeps the list fresh afterwards, and pauses while hidden).
// After a decision the user lands here with a message; move focus to the heading so keyboard users are not lost.
onMounted(async () => {
  if (queue.flash.value) {
    await nextTick()
    title.value?.focus()
  }
  await queue.refresh()
})

function dismissFlash() {
  queue.flash.value = null
}
</script>

<template>
  <main class="mx-auto max-w-5xl space-y-4 px-4 py-6" aria-labelledby="approvals-title">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 id="approvals-title" ref="title" tabindex="-1" class="text-2xl font-bold outline-none">
          {{ heading }}
        </h1>
        <p class="mt-0.5 text-sm">
          <template v-if="queue.loaded.value">
            {{ queue.count.value }} waiting for your decision, oldest first.
          </template>
          <template v-else>
            Requests assigned to you that are waiting for a decision.
          </template>
        </p>
      </div>
      <button
        type="button"
        class="focus-ring inline-flex min-h-10 items-center gap-2 rounded-lg border border-secondary/50 px-3 py-2 text-sm font-medium hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="refreshing"
        @click="queue.refresh()"
      >
        <IconGlyph :name="refreshing ? 'spinner' : 'refresh'" class="h-4 w-4" />
        {{ refreshing ? 'Refreshing...' : 'Refresh' }}
      </button>
    </div>

    <div
      v-if="queue.flash.value"
      class="flex items-start gap-2 rounded-lg px-3 py-2 text-sm"
      :class="toneClass(queue.flash.value.tone)"
      role="status"
    >
      <IconGlyph :name="queue.flash.value.tone === 'green' ? 'check' : 'alert'" class="mt-0.5 h-4 w-4 shrink-0" />
      <p class="min-w-0 flex-1">
        {{ queue.flash.value.text }}
      </p>
      <button type="button" class="focus-ring shrink-0 rounded-md p-0.5 hover:bg-white/20" @click="dismissFlash">
        <IconGlyph name="close" class="h-4 w-4" />
        <span class="sr-only">Dismiss message</span>
      </button>
    </div>

    <div v-if="queue.error.value" class="flex items-start gap-2 rounded-lg px-3 py-2 text-sm" :class="toneClass('red')" role="alert">
      <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
      <p class="min-w-0 flex-1">
        {{ queue.error.value }}
      </p>
      <button type="button" class="focus-ring shrink-0 rounded-md border border-current px-2 py-0.5 text-xs font-semibold" @click="queue.refresh()">
        Retry
      </button>
    </div>

    <p v-if="firstLoad" role="status" class="flex items-center gap-2 py-10 text-sm">
      <IconGlyph name="spinner" class="h-4 w-4" />
      Loading requests...
    </p>

    <section v-else-if="queue.loaded.value && queue.count.value === 0" class="rounded-2xl border border-dashed border-secondary/40 p-8 text-center">
      <IconGlyph name="check" class="mx-auto h-8 w-8" />
      <h2 class="mt-2 text-lg font-semibold">
        Nothing waiting for you
      </h2>
      <p class="mt-1 text-sm">
        New requests appear here automatically. This page checks every 30 seconds.
      </p>
    </section>

    <ul v-else-if="queue.loaded.value" class="space-y-3" aria-label="Pending requests">
      <li
        v-for="item in queue.items.value"
        :key="`${item.request_type}-${item.id}`"
        class="relative rounded-xl border border-secondary/40 p-4 hover:bg-secondary/5"
      >
        <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
          <h2 class="min-w-0 text-base font-semibold">
            <NuxtLink
              :to="approvalPath(item.request_type, item.id)"
              class="focus-ring rounded-sm after:absolute after:inset-0 after:rounded-xl"
            >
              <span class="chat-text">{{ item.employee.display_name }}</span>
              <span v-if="item.employee.department" class="chat-text font-normal"> · {{ item.employee.department }}</span>
              <span class="sr-only">, {{ item.request_type === 'claim' ? 'claim' : 'leave request' }} #{{ item.id }}</span>
            </NuxtLink>
          </h2>
          <p class="text-xs">
            Submitted <time :datetime="item.submitted_at ?? undefined" :title="formatDateTime(item.submitted_at)">{{ item.submitted_at ? relativeTime(item.submitted_at) : 'earlier' }}</time>
          </p>
        </div>
        <p class="chat-text mt-1 text-sm">
          {{ item.summary }}
        </p>
        <ul v-if="flagBadges(item.flags).length" class="mt-2.5 flex flex-wrap gap-1.5" aria-label="Flags">
          <li
            v-for="badge in flagBadges(item.flags)"
            :key="badge.key"
            class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold"
            :class="toneClass(badge.tone)"
          >
            <IconGlyph :name="badge.icon" class="h-3.5 w-3.5 shrink-0" />
            {{ badge.label }}
          </li>
        </ul>
      </li>
    </ul>

    <MockWarning compact :title="MOCK_SESSION_REMINDER.title" :text="MOCK_SESSION_REMINDER.text" role="note" />
  </main>
</template>
