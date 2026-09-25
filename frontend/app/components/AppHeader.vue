<script setup lang="ts">
const { user, logout } = useAuth()
const route = useRoute()
const notifications = useNotifications()
const queue = useApprovalQueue()
const signingOut = ref(false)

const tabs = computed(() => navTabs(user.value))

// One poll for everything in the header: the bell and (for approvers) the pending queue that feeds the tab badge and
// the approvals list. Every 30 s, on window focus, paused while the tab is hidden.
usePolling(async () => {
  if (!user.value) return
  await Promise.all([
    notifications.refresh(),
    user.value.approves ? queue.refresh({ background: true }) : Promise.resolve(),
  ])
})

async function signOut() {
  signingOut.value = true
  try {
    await logout()
  }
  finally {
    signingOut.value = false
  }
}
</script>

<template>
  <header class="border-b border-secondary/30">
    <div class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
      <p class="font-semibold">
        SCMP Internal Operations AI Assistant
      </p>
      <div class="flex flex-wrap items-center gap-3">
        <div
          v-if="user"
          class="flex min-w-0 items-center gap-2 rounded-full border border-secondary/30 py-1 pl-1 pr-3"
        >
          <span
            class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
            :style="{ backgroundColor: avatarColour(user.email) }"
            aria-hidden="true"
          >{{ getInitials(user.display_name, user.email) }}</span>
          <span class="max-w-[8rem] truncate text-sm font-medium">{{ user.display_name }}</span>
          <RoleBadge :role="user.role" />
        </div>
        <NotificationBell v-if="user" />
        <ThemeToggle />
        <button
          type="button"
          class="focus-ring rounded-lg border border-secondary/40 px-3 py-1.5 text-sm font-medium hover:bg-secondary/10 disabled:opacity-60"
          :disabled="signingOut"
          @click="signOut"
        >
          Sign out
        </button>
      </div>
      <nav v-if="tabs.length" aria-label="Main" class="-mb-3 w-full">
        <ul class="flex gap-1">
          <li v-for="tab in tabs" :key="tab.key">
            <NuxtLink
              :to="tab.to"
              class="focus-ring inline-flex items-center gap-2 rounded-t-lg border-b-2 px-3 py-2 text-sm font-semibold hover:bg-secondary/10"
              :class="isTabActive(tab, route.path) ? 'border-secondary' : 'border-transparent'"
              :aria-current="isTabActive(tab, route.path) ? 'page' : undefined"
            >
              {{ tab.label }}
              <span
                v-if="tab.key === 'approvals' && queue.loaded.value && queue.count.value > 0"
                class="rounded-full bg-secondary px-1.5 text-xs font-bold leading-5 text-background"
              >
                <span aria-hidden="true">{{ queue.count.value }}</span>
                <span class="sr-only">{{ queue.count.value }} pending</span>
              </span>
            </NuxtLink>
          </li>
        </ul>
      </nav>
    </div>
  </header>
</template>
