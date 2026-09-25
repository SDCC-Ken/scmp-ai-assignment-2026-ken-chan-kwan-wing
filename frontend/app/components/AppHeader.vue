<script setup lang="ts">
const { user, logout } = useAuth()
const signingOut = ref(false)

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
    <div class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 py-3">
      <p class="font-semibold">
        SCMP Internal Operations AI Assistant
      </p>
      <div class="flex flex-wrap items-center gap-3">
        <div
          v-if="user"
          class="flex items-center gap-2 rounded-full border border-secondary/30 py-1 pl-1 pr-3"
        >
          <span
            class="flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold text-white"
            :style="{ backgroundColor: avatarColour(user.email) }"
            aria-hidden="true"
          >{{ getInitials(user.display_name, user.email) }}</span>
          <span class="max-w-[10rem] truncate text-sm font-medium">{{ user.display_name }}</span>
          <RoleBadge :role="user.role" />
        </div>
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
    </div>
  </header>
</template>
