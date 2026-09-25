<script setup lang="ts">
/**
 * Mock "Google One Tap"-style prompt: a non-modal card (no backdrop, no focus trap, no focus stealing) fixed at
 * the top-right of the viewport on >= 640px and in normal flow on small screens. The parent mounts it with v-if,
 * so it loads the fictional accounts on mount; Escape or the close button emit `close`.
 */
const emit = defineEmits<{ close: [focusWasInside: boolean] }>()

const { listMockUsers, login } = useAuth()

const root = ref<HTMLElement | null>(null)
const users = ref<AuthUser[]>([])
const loading = ref(true) // true from the start so the server render and hydration agree
const listError = ref<string | null>(null)
const loginError = ref<string | null>(null)
const signingInEmail = ref<string | null>(null)
const groups = computed(() => groupUsersByRole(users.value))

async function loadUsers() {
  loading.value = true
  listError.value = null
  try {
    users.value = await listMockUsers()
  }
  catch (error) {
    users.value = []
    listError.value = authErrorMessage(extractStatus(error), 'list-users')
  }
  finally {
    loading.value = false
  }
}

async function choose(user: AuthUser) {
  if (signingInEmail.value) return
  signingInEmail.value = user.email
  loginError.value = null
  try {
    await login(user.email)
  }
  catch (error) {
    loginError.value = authErrorMessage(extractStatus(error), 'login')
    signingInEmail.value = null
  }
}

function requestClose() {
  if (signingInEmail.value) return // do not abandon a sign-in in flight
  emit('close', root.value?.contains(document.activeElement) ?? false)
}

// Escape works wherever focus is, because the card never takes focus by itself.
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') requestClose()
}

onMounted(() => {
  document.addEventListener('keydown', onDocumentKeydown)
  void loadUsers()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onDocumentKeydown))

defineExpose({ focus: () => root.value?.focus() })
</script>

<template>
  <div
    id="one-tap-card"
    ref="root"
    role="dialog"
    aria-label="Sign in with Google (mock prompt)"
    aria-describedby="one-tap-warning"
    tabindex="-1"
    class="one-tap relative z-[100] -mx-2 overflow-y-auto rounded-xl border border-secondary/30 bg-background text-secondary outline-none sm:fixed sm:right-4 sm:top-4 sm:mx-0 sm:max-h-[calc(100dvh-2rem)] sm:w-[360px]"
  >
    <div class="flex items-start gap-2.5 px-3 pb-1 pt-3">
      <span class="mt-0.5 h-5 w-5 shrink-0"><GoogleGLogo /></span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <h2 class="text-sm font-semibold">
            Sign in with Google
          </h2>
          <span class="mock-chip">MOCK</span>
        </div>
        <p class="mt-0.5 text-xs opacity-90">
          to continue to SCMP Internal Operations AI Assistant
        </p>
      </div>
      <button
        type="button"
        class="focus-ring -mr-1 -mt-1 shrink-0 rounded-full p-2 hover:bg-secondary/10 aria-disabled:cursor-not-allowed aria-disabled:opacity-50"
        aria-label="Close sign-in prompt"
        :aria-disabled="signingInEmail !== null"
        @click="requestClose"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>

    <div class="px-3 pb-3" aria-live="polite" :aria-busy="loading || signingInEmail !== null">
      <p
        v-if="loginError"
        role="alert"
        class="mt-2 rounded-lg border border-red-700 bg-red-50 p-2.5 text-xs text-red-900 dark-error"
      >
        {{ loginError }}
      </p>

      <p v-if="signingInEmail" role="status" class="sr-only">
        Signing in as {{ signingInEmail }}...
      </p>

      <p v-if="loading" role="status" class="flex items-center gap-2 py-5 text-sm">
        <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity="0.25" />
          <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
        </svg>
        Loading mock accounts...
      </p>

      <div v-else-if="listError" role="alert" class="mt-2 rounded-lg border border-red-700 bg-red-50 p-2.5 text-xs text-red-900 dark-error">
        <p>{{ listError }}</p>
        <button
          type="button"
          class="focus-ring mt-2 rounded-md border border-red-700 px-3 py-1 font-medium hover:bg-red-500/20"
          @click="loadUsers"
        >
          Try again
        </button>
      </div>

      <p v-else-if="groups.length === 0" class="py-4 text-sm">
        No mock accounts are available. Check that the backend has seeded its fictional users.
      </p>

      <div v-else class="mt-1 space-y-2">
        <section v-for="group in groups" :key="group.role" :aria-labelledby="`one-tap-group-${group.role}`">
          <h3 :id="`one-tap-group-${group.role}`" class="text-[11px] font-semibold uppercase tracking-wide opacity-90">
            {{ group.label }}
          </h3>
          <ul class="mt-1 space-y-1">
            <li v-for="u in group.users" :key="u.email">
              <button
                type="button"
                data-account-row
                class="focus-ring flex w-full items-center gap-2.5 rounded-lg border border-secondary/30 p-2 text-left hover:bg-secondary/10 aria-disabled:cursor-not-allowed aria-disabled:opacity-60 aria-disabled:hover:bg-transparent"
                :aria-disabled="signingInEmail !== null && signingInEmail !== u.email"
                :aria-busy="signingInEmail === u.email"
                @click="choose(u)"
              >
                <span
                  class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
                  :style="{ backgroundColor: avatarColour(u.email) }"
                  aria-hidden="true"
                >{{ getInitials(u.display_name, u.email) }}</span>
                <span class="min-w-0 flex-1">
                  <span class="flex items-center justify-between gap-x-2">
                    <span class="block min-w-0 truncate text-sm font-medium leading-tight">{{ u.display_name }}</span>
                    <RoleBadge :role="u.role" class="shrink-0" />
                  </span>
                  <span v-if="userSubtitle(u)" class="mt-0.5 block truncate text-xs font-medium leading-tight">{{ userSubtitle(u) }}</span>
                  <span class="block truncate text-xs leading-tight opacity-90">{{ u.email }}</span>
                  <span class="mt-0.5 flex items-center justify-end gap-x-2">
                    <span v-if="signingInEmail === u.email" class="flex items-center gap-1 text-xs font-semibold">
                      <svg class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity="0.25" />
                        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
                      </svg>
                      Signing in...
                    </span>
                    <span v-else class="one-tap-cta text-xs font-semibold">Continue as {{ firstName(u.display_name, u.email) }} &rarr;</span>
                  </span>
                </span>
              </button>
            </li>
          </ul>
        </section>
      </div>

      <div id="one-tap-warning" class="mt-3">
        <MockWarning compact :title="MOCK_WARNING.title" :text="MOCK_WARNING.text" role="note" />
      </div>
    </div>
  </div>
</template>
