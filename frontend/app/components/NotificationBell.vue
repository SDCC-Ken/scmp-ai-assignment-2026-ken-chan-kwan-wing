<script setup lang="ts">
import type { AppNotification } from '~/types/notifications'

/**
 * Bell with an unread badge and a non-modal popover (role="dialog", labelled "Notifications"): focus moves into it on
 * open, Escape closes it and returns focus to the bell, a click outside or Tab out of it closes it. The count is
 * announced through a polite live region and is part of the button's accessible name. Items are plain text.
 * Polling is owned by AppHeader (30 s, and on focus, paused while hidden).
 */
const { items, unread, loaded, error, actionError, refresh, markRead, markAllRead } = useNotifications()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const detail = ref<AppNotification | null>(null)
const placement = ref<{ top: number, left: number, width: number, maxHeight: number }>({ top: 0, left: 8, width: 320, maxHeight: 480 })

const route = useRoute()
const badge = computed(() => formatBadgeCount(unread.value))
const name = computed(() => bellLabel(unread.value))
const announcement = computed(() => unreadAnnouncement(unread.value))

function place() {
  const rect = button.value?.getBoundingClientRect()
  if (!rect) return
  const vw = window.innerWidth
  const vh = window.innerHeight
  const width = Math.min(384, vw - 16)
  const left = Math.min(Math.max(8, rect.right - width), vw - width - 8)
  const top = rect.bottom + 8
  placement.value = { top, left, width, maxHeight: Math.max(160, vh - top - 8) }
}

async function openPanel() {
  place()
  open.value = true
  void refresh()
  await nextTick()
  panel.value?.focus()
}

function closePanel(restoreFocus = false) {
  if (!open.value) return
  open.value = false
  if (restoreFocus) nextTick(() => button.value?.focus())
}

function toggle() {
  if (open.value) closePanel()
  else void openPanel()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    closePanel(true)
  }
}

function onDocumentPointerDown(event: PointerEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) closePanel()
}

function onFocusOut(event: FocusEvent) {
  const next = event.relatedTarget as Node | null
  if (open.value && next && root.value && !root.value.contains(next)) closePanel()
}

watch(() => route.fullPath, () => closePanel()) // a page change (for example via the link tabs) closes the popover

onMounted(() => {
  document.addEventListener('keydown', onDocumentKeydown)
  document.addEventListener('pointerdown', onDocumentPointerDown)
  window.addEventListener('resize', place)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  window.removeEventListener('resize', place)
})

async function select(notification: AppNotification) {
  void markRead(notification.id) // optimistic; rolls back by itself on failure
  const target = notificationTarget(notification)
  closePanel()
  if (target.kind === 'link') {
    await navigateTo(target.to)
    return
  }
  detail.value = notification
}

// The dialog closes itself after the next render and the browser then restores focus to the (removed) list item,
// so put focus back on the bell only after that has happened.
function closeDetail() {
  detail.value = null
  setTimeout(() => button.value?.focus(), 0)
}
</script>

<template>
  <div ref="root" class="relative" @focusout="onFocusOut">
    <button
      ref="button"
      type="button"
      class="focus-ring relative inline-flex h-9 w-9 items-center justify-center rounded-lg border border-secondary/40 hover:bg-secondary/10"
      aria-haspopup="dialog"
      aria-controls="notification-popover"
      :aria-expanded="open"
      :aria-label="name"
      @click="toggle"
    >
      <IconGlyph name="bell" class="h-5 w-5" />
      <span
        v-if="badge"
        class="bell-badge absolute -right-1.5 -top-1.5 min-w-[1.25rem] rounded-full px-1 text-center text-[0.6875rem] font-bold leading-5"
        aria-hidden="true"
      >{{ badge }}</span>
    </button>
    <span class="sr-only" role="status" aria-live="polite">{{ announcement }}</span>

    <div
      v-if="open"
      id="notification-popover"
      ref="panel"
      role="dialog"
      aria-label="Notifications"
      tabindex="-1"
      class="fixed z-50 flex flex-col overflow-hidden rounded-xl border border-secondary/50 bg-background text-secondary shadow-2xl outline-none"
      :style="{ top: `${placement.top}px`, left: `${placement.left}px`, width: `${placement.width}px`, maxHeight: `${placement.maxHeight}px` }"
    >
      <div class="flex items-center justify-between gap-2 border-b border-secondary/25 px-3 py-2">
        <h2 class="text-sm font-semibold">
          Notifications
        </h2>
        <button
          type="button"
          class="focus-ring rounded-md border border-secondary/40 px-2.5 py-1 text-xs font-semibold hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="unread === 0"
          @click="markAllRead()"
        >
          Mark all as read
        </button>
      </div>

      <p v-if="actionError" role="alert" class="m-2 rounded-lg px-2.5 py-2 text-xs" :class="toneClass('red')">
        {{ actionError }}
      </p>

      <div class="min-h-0 flex-1 overflow-y-auto">
        <p v-if="!loaded && !error" role="status" class="flex items-center gap-2 px-3 py-6 text-sm">
          <IconGlyph name="spinner" class="h-4 w-4" />
          Loading notifications...
        </p>
        <div v-else-if="error && !loaded" role="alert" class="m-2 rounded-lg px-2.5 py-2 text-sm" :class="toneClass('red')">
          <p>{{ error }}</p>
          <button type="button" class="focus-ring mt-2 rounded-md border border-current px-2.5 py-1 text-xs font-semibold" @click="refresh()">
            Try again
          </button>
        </div>
        <div v-else-if="items.length === 0" class="flex flex-col items-center gap-1 px-3 py-8 text-center">
          <IconGlyph name="inbox" class="h-6 w-6" />
          <p class="text-sm font-semibold">
            You are all caught up
          </p>
          <p class="text-xs">
            New notifications will appear here.
          </p>
        </div>
        <ul v-else class="divide-y divide-secondary/15">
          <li v-for="n in items" :key="n.id">
            <button
              type="button"
              class="focus-ring flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-secondary/10"
              :class="isUnread(n) ? 'bg-secondary/5' : ''"
              @click="select(n)"
            >
              <span class="mt-1.5 flex h-2.5 w-2.5 shrink-0 items-center justify-center">
                <span v-if="isUnread(n)" class="unread-dot" aria-hidden="true" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="chat-text block text-sm" :class="isUnread(n) ? 'font-semibold' : 'font-medium'">
                  <span v-if="isUnread(n)" class="sr-only">Unread: </span>{{ n.title }}
                </span>
                <span v-if="n.body" class="chat-text mt-0.5 block text-xs opacity-90 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] overflow-hidden">{{ n.body }}</span>
                <span class="mt-0.5 block text-xs opacity-90"><time :datetime="n.created_at">{{ relativeTime(n.created_at) }}</time></span>
              </span>
            </button>
          </li>
        </ul>
      </div>
    </div>

    <ModalDialog :open="detail !== null" labelledby="notification-detail-title" @close="closeDetail">
      <template v-if="detail">
        <h2 id="notification-detail-title" class="chat-text text-base font-semibold">
          {{ detail.title }}
        </h2>
        <p class="mt-1 text-xs opacity-90">
          <time :datetime="detail.created_at">{{ formatDateTime(detail.created_at) }}</time>
        </p>
        <p v-if="detail.body" class="chat-text mt-3 rounded-lg border border-secondary/25 p-3 text-sm">
          {{ detail.body }}
        </p>
        <div class="mt-4 flex justify-end">
          <button type="button" class="focus-ring rounded-lg bg-secondary px-4 py-2 text-sm font-semibold text-background hover:opacity-90" @click="closeDetail">
            Close
          </button>
        </div>
      </template>
    </ModalDialog>
  </div>
</template>
