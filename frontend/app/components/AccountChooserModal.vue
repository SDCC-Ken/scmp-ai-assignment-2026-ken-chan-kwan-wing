<script setup lang="ts">
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const { listMockUsers, loginAs } = useAuth()

const dialogRef = ref<HTMLElement | null>(null)
const users = ref<AuthUser[]>([])
const loading = ref(false)
const listError = ref<string | null>(null)
const loginError = ref<string | null>(null)
const signingInEmail = ref<string | null>(null)
const groups = computed(() => groupUsersByRole(users.value))

let returnFocusTo: HTMLElement | null = null
const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

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
  await nextTick()
  // Move focus from the dialog container to the first account once the list is ready.
  if (document.activeElement === dialogRef.value) {
    dialogRef.value?.querySelector<HTMLElement>('[data-account-row]')?.focus()
  }
}

async function choose(user: AuthUser) {
  if (signingInEmail.value) return
  signingInEmail.value = user.email
  loginError.value = null
  try {
    await loginAs(user.email)
    await navigateTo('/')
  }
  catch (error) {
    loginError.value = authErrorMessage(extractStatus(error), 'login')
    signingInEmail.value = null
  }
}

function requestClose() {
  if (signingInEmail.value) return // do not abandon a sign-in in flight
  emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    requestClose()
    return
  }
  if (event.key !== 'Tab' || !dialogRef.value) return
  const items = Array.from(dialogRef.value.querySelectorAll<HTMLElement>(FOCUSABLE))
  if (items.length === 0) {
    event.preventDefault()
    return
  }
  const first = items[0]!
  const last = items[items.length - 1]!
  const active = document.activeElement
  if (event.shiftKey && (active === first || active === dialogRef.value)) {
    event.preventDefault()
    last.focus()
  }
  else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

function keepFocusInside(event: FocusEvent) {
  const dialog = dialogRef.value
  if (dialog && event.target instanceof Node && !dialog.contains(event.target)) {
    dialog.querySelector<HTMLElement>(FOCUSABLE)?.focus()
  }
}

watch(() => props.open, async (isOpen) => {
  if (isOpen) {
    returnFocusTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
    document.body.style.overflow = 'hidden'
    document.addEventListener('focusin', keepFocusInside)
    signingInEmail.value = null
    loginError.value = null
    await nextTick()
    dialogRef.value?.focus()
    void loadUsers()
  }
  else {
    document.body.style.overflow = ''
    document.removeEventListener('focusin', keepFocusInside)
    returnFocusTo?.focus()
    returnFocusTo = null
  }
})

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  document.removeEventListener('focusin', keepFocusInside)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center sm:p-4"
      @pointerdown.self="requestClose"
    >
      <div
        ref="dialogRef"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chooser-title"
        aria-describedby="chooser-warning"
        tabindex="-1"
        class="max-h-[92dvh] w-full max-w-md overflow-y-auto rounded-t-2xl border border-secondary/30 bg-background p-5 text-secondary shadow-2xl outline-none sm:rounded-2xl"
        @keydown="onKeydown"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3">
            <span class="h-6 w-6 shrink-0"><GoogleGLogo /></span>
            <div>
              <h2 id="chooser-title" class="text-lg font-semibold">
                Choose a mock account
              </h2>
              <p class="text-sm opacity-80">
                to sign in to SCMP Internal Operations AI Assistant
              </p>
            </div>
          </div>
          <button
            type="button"
            class="focus-ring -mr-1 -mt-1 rounded-full p-2 hover:bg-secondary/10"
            aria-label="Close account chooser"
            @click="requestClose"
          >
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        <div id="chooser-warning" class="mt-4">
          <MockWarning :title="MOCK_WARNING.title" :text="MOCK_WARNING.text" role="note" />
        </div>

        <p
          v-if="loginError"
          role="alert"
          class="mt-4 rounded-lg border border-red-700 bg-red-50 p-3 text-sm text-red-900 dark-error"
        >
          {{ loginError }}
        </p>

        <div class="mt-4" :aria-busy="loading">
          <p v-if="loading" role="status" class="flex items-center gap-2 py-6 text-sm">
            <svg class="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity="0.25" />
              <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
            </svg>
            Loading mock accounts...
          </p>

          <div v-else-if="listError" role="alert" class="rounded-lg border border-red-700 bg-red-50 p-3 text-sm text-red-900 dark-error">
            <p>{{ listError }}</p>
            <button
              type="button"
              class="focus-ring mt-2 rounded-md border border-red-700 px-3 py-1 font-medium hover:bg-red-500/20"
              @click="loadUsers"
            >
              Try again
            </button>
          </div>

          <p v-else-if="groups.length === 0" class="py-6 text-sm">
            No mock accounts are available. Check that the backend has seeded its fictional users.
          </p>

          <div v-else class="space-y-4">
            <section v-for="group in groups" :key="group.role" :aria-labelledby="`group-${group.role}`">
              <h3 :id="`group-${group.role}`" class="text-xs font-semibold uppercase tracking-wide opacity-80">
                {{ group.label }}
              </h3>
              <ul class="mt-2 space-y-1">
                <li v-for="u in group.users" :key="u.email">
                  <button
                    type="button"
                    data-account-row
                    class="focus-ring flex w-full items-center gap-3 rounded-lg border border-secondary/30 p-2.5 text-left hover:bg-secondary/10 aria-disabled:cursor-not-allowed aria-disabled:opacity-60 aria-disabled:hover:bg-transparent"
                    :aria-disabled="signingInEmail !== null"
                    :aria-busy="signingInEmail === u.email"
                    @click="choose(u)"
                  >
                    <span
                      class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white"
                      :style="{ backgroundColor: avatarColour(u.email) }"
                      aria-hidden="true"
                    >{{ getInitials(u.display_name, u.email) }}</span>
                    <span class="min-w-0 flex-1">
                      <span class="block truncate font-medium">{{ u.display_name }}</span>
                      <span class="block truncate text-sm opacity-80">{{ u.email }}</span>
                      <RoleBadge :role="u.role" class="mt-1" />
                    </span>
                    <span v-if="signingInEmail === u.email" role="status" class="flex shrink-0 items-center gap-1.5 text-sm">
                      <svg class="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" opacity="0.25" />
                        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
                      </svg>
                      <span class="sr-only sm:not-sr-only">Signing in...</span>
                    </span>
                  </button>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
