<script setup lang="ts">
/**
 * Bell with the small unread number. Clicking it opens the inbox: `POST /api/chat/inbox` creates a new chat that shows
 * everything waiting for the person one card at a time (see `useInbox`). While the request runs the bell is disabled with
 * a spinner. When nothing is waiting a small anchored notice ("You are all caught up", role="status") appears and closes
 * itself after about 3 seconds, on Escape, or on a click outside; no page change. The count is announced through a polite
 * live region and is part of the button's accessible name. Polling of the count is owned by AppHeader.
 */
const { unread } = useNotifications()
const inbox = useInbox()

type NoticeKind = 'caught-up' | 'error'
const notice = ref<{ kind: NoticeKind, text: string } | null>(null)
const root = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)
let closeTimer: ReturnType<typeof setTimeout> | undefined

const badge = computed(() => formatBadgeCount(unread.value))
const name = computed(() => (inbox.opening.value ? bellBusyLabel(unread.value) : bellLabel(unread.value)))
const announcement = computed(() => unreadAnnouncement(unread.value))

function closeNotice(restoreFocus = false) {
  clearTimeout(closeTimer)
  if (!notice.value) return
  notice.value = null
  if (restoreFocus) nextTick(() => button.value?.focus())
}

function showNotice(kind: NoticeKind, text: string, ms: number) {
  clearTimeout(closeTimer)
  notice.value = { kind, text }
  closeTimer = setTimeout(() => closeNotice(), ms)
}

async function onClick() {
  if (inbox.opening.value) return
  closeNotice()
  const outcome = await inbox.open()
  if (outcome === 'empty') showNotice('caught-up', 'You are all caught up', 3000)
  else if (outcome === 'error') showNotice('error', inbox.errorText.value ?? 'Could not open your inbox.', 6000)
  // The disabled button dropped focus while the request ran; give it back unless the page moved on to the new chat.
  if (outcome !== 'opened') await nextTick().then(() => button.value?.focus())
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && notice.value) {
    event.preventDefault()
    closeNotice(true)
  }
}

function onDocumentPointerDown(event: PointerEvent) {
  if (notice.value && root.value && !root.value.contains(event.target as Node)) closeNotice()
}

onMounted(() => {
  document.addEventListener('keydown', onDocumentKeydown)
  document.addEventListener('pointerdown', onDocumentPointerDown)
})
onBeforeUnmount(() => {
  clearTimeout(closeTimer)
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('pointerdown', onDocumentPointerDown)
})
</script>

<template>
  <div ref="root" class="relative">
    <button
      ref="button"
      type="button"
      class="focus-ring relative inline-flex h-9 w-9 items-center justify-center rounded-lg border border-secondary/40 hover:bg-secondary/10 disabled:cursor-progress disabled:opacity-80"
      :disabled="inbox.opening.value"
      :aria-busy="inbox.opening.value"
      :aria-label="name"
      title="Open your inbox"
      @click="onClick"
    >
      <IconGlyph :name="inbox.opening.value ? 'spinner' : 'bell'" class="h-5 w-5" />
      <span
        v-if="badge"
        class="bell-badge absolute -right-1.5 -top-1.5 min-w-[1.25rem] rounded-full px-1 text-center text-[0.6875rem] font-bold leading-5"
        aria-hidden="true"
      >{{ badge }}</span>
    </button>
    <span class="sr-only" role="status" aria-live="polite">{{ announcement }}</span>

    <div
      v-if="notice"
      :role="notice.kind === 'error' ? 'alert' : 'status'"
      class="absolute right-0 top-full z-50 mt-2 flex w-max max-w-[min(18rem,calc(100vw-2rem))] items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium shadow-lg"
      :class="toneClass(notice.kind === 'error' ? 'red' : 'grey')"
    >
      <IconGlyph :name="notice.kind === 'error' ? 'alert' : 'check'" class="h-4 w-4 shrink-0" />
      <span>{{ notice.text }}</span>
    </div>
  </div>
</template>
