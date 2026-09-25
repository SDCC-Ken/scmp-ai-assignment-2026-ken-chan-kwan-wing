<script setup lang="ts">
const chat = useChat()
const composer = ref<{ focus: () => void } | null>(null)
const drawerOpen = ref(false)
const toggleButton = ref<HTMLButtonElement | null>(null)
const drawer = ref<HTMLElement | null>(null)

function closeDrawer(restoreFocus = false) {
  if (!drawerOpen.value) return
  drawerOpen.value = false
  if (restoreFocus) nextTick(() => toggleButton.value?.focus())
}

async function openDrawer() {
  drawerOpen.value = true
  await nextTick()
  drawer.value?.querySelector<HTMLElement>('button:not([disabled])')?.focus()
}

async function onSelect(id: number) {
  closeDrawer()
  await chat.select(id)
  composer.value?.focus()
}

/** After removing a chip its button is gone; keep keyboard users in the composer. */
async function onRemoveFile(id: string) {
  chat.removeFile(id)
  await nextTick()
  composer.value?.focus()
}

async function onCreate() {
  closeDrawer()
  await chat.newChat()
  await nextTick()
  composer.value?.focus()
}

function onEscape(event: KeyboardEvent) {
  if (event.key === 'Escape' && drawerOpen.value) {
    event.preventDefault()
    closeDrawer(true)
  }
}

// Keep Tab inside the drawer while it is open as a slide-over.
function onDrawerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !drawerOpen.value || !drawer.value) return
  const items = [...drawer.value.querySelectorAll<HTMLElement>('button:not([disabled])')]
  if (!items.length) return
  const first = items[0]!
  const last = items[items.length - 1]!
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  }
  else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

let media: MediaQueryList | undefined
const onWide = (event: MediaQueryListEvent) => {
  if (event.matches) drawerOpen.value = false
}

onMounted(async () => {
  media = window.matchMedia('(min-width: 768px)')
  media.addEventListener('change', onWide)
  window.addEventListener('keydown', onEscape)
  await chat.init()
  await nextTick()
  // Do not pop the on-screen keyboard on phones; on desktop the composer is ready to type in.
  if (media.matches) composer.value?.focus()
})

onBeforeUnmount(() => {
  media?.removeEventListener('change', onWide)
  window.removeEventListener('keydown', onEscape)
})

const title = computed(() => chat.active.value?.title ?? 'Chat')
const activeBadges = computed(() => (chat.active.value ? conversationBadges(chat.active.value) : []))
const composerUnavailable = computed(() => chat.initialising.value || chat.loadingThread.value || chat.activeId.value === null)
</script>

<template>
  <div class="relative mx-auto flex h-full min-h-0 w-full max-w-5xl overflow-hidden md:border-x md:border-secondary/30">
    <!-- Conversation list: static column from 768px, slide-over drawer below. -->
    <div
      v-if="drawerOpen"
      class="fixed inset-0 z-30 bg-slate-950/60 md:hidden"
      aria-hidden="true"
      @click="closeDrawer(true)"
    />
    <nav
      id="chat-conversations"
      ref="drawer"
      aria-label="Conversations"
      class="chat-drawer z-40 flex w-72 max-w-[85vw] shrink-0 flex-col border-r border-secondary/30 bg-background transition-transform duration-200 max-md:fixed max-md:inset-y-0 max-md:left-0 md:static md:translate-x-0"
      :class="drawerOpen ? 'max-md:translate-x-0 max-md:shadow-2xl' : 'max-md:invisible max-md:-translate-x-full'"
      @keydown="onDrawerKeydown"
    >
      <div class="flex items-center justify-between border-b border-secondary/30 px-4 py-2.5 md:hidden">
        <p class="text-sm font-semibold">
          Conversations
        </p>
        <button type="button" class="focus-ring rounded-lg p-1.5 hover:bg-secondary/10" @click="closeDrawer(true)">
          <IconGlyph name="close" class="h-5 w-5" />
          <span class="sr-only">Close conversation list</span>
        </button>
      </div>
      <ChatSidebar
        :conversations="chat.conversations.value"
        :active-id="chat.activeId.value"
        :loading="chat.initialising.value"
        :busy="chat.busy.value"
        @select="onSelect"
        @create="onCreate"
      />
    </nav>

    <section class="flex min-w-0 flex-1 flex-col" aria-label="Chat" :inert="drawerOpen">
      <div class="flex items-center gap-2 border-b border-secondary/30 px-3 py-2 sm:px-5">
        <button
          ref="toggleButton"
          type="button"
          class="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-secondary/40 px-2.5 py-1.5 text-sm font-medium hover:bg-secondary/10 md:hidden"
          aria-controls="chat-conversations"
          :aria-expanded="drawerOpen"
          @click="openDrawer"
        >
          <IconGlyph name="menu" class="h-4 w-4" />
          Chats
        </button>
        <h1 class="min-w-0 flex-1 truncate text-sm font-semibold">
          {{ title }}
        </h1>
        <span
          v-for="badge in activeBadges"
          :key="badge.kind"
          class="hidden items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold sm:inline-flex"
          :class="toneClass(badge.kind === 'card' ? 'amber' : 'grey')"
        >
          {{ badge.label }}
        </span>
      </div>

      <!-- Feedback: one region each, dismissible; errors offer Retry. -->
      <div class="space-y-2 px-3 empty:hidden sm:px-5" :class="chat.error.value || chat.warning.value || chat.notice.value ? 'pt-3' : ''">
        <div
          v-if="chat.error.value"
          class="mx-auto flex max-w-3xl items-start gap-2 rounded-lg px-3 py-2 text-sm"
          :class="toneClass('red')"
          role="alert"
        >
          <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
          <p class="min-w-0 flex-1">
            {{ chat.error.value.text }}
          </p>
          <button
            v-if="chat.error.value.retry"
            type="button"
            class="focus-ring shrink-0 rounded-md border border-current px-2 py-0.5 text-xs font-semibold hover:bg-white/20"
            @click="chat.retry()"
          >
            Retry
          </button>
          <button type="button" class="focus-ring shrink-0 rounded-md p-0.5 hover:bg-white/20" @click="chat.dismissError()">
            <IconGlyph name="close" class="h-4 w-4" />
            <span class="sr-only">Dismiss error</span>
          </button>
        </div>
        <div
          v-if="chat.warning.value"
          class="mx-auto flex max-w-3xl items-start gap-2 rounded-lg px-3 py-2 text-sm"
          :class="toneClass('amber')"
          role="status"
        >
          <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
          <p class="min-w-0 flex-1">
            {{ chat.warning.value }}
          </p>
          <button type="button" class="focus-ring shrink-0 rounded-md p-0.5 hover:bg-white/20" @click="chat.dismissWarning()">
            <IconGlyph name="close" class="h-4 w-4" />
            <span class="sr-only">Dismiss warning</span>
          </button>
        </div>
        <div
          v-if="chat.notice.value"
          class="mx-auto flex max-w-3xl items-start gap-2 rounded-lg px-3 py-2 text-sm"
          :class="toneClass('grey')"
          role="status"
        >
          <IconGlyph name="info" class="mt-0.5 h-4 w-4 shrink-0" />
          <p class="min-w-0 flex-1">
            {{ chat.notice.value }} I reloaded the conversation so you see the latest state.
          </p>
          <button type="button" class="focus-ring shrink-0 rounded-md p-0.5 hover:bg-white/20" @click="chat.dismissNotice()">
            <IconGlyph name="close" class="h-4 w-4" />
            <span class="sr-only">Dismiss notice</span>
          </button>
        </div>
      </div>

      <ChatThread
        :conversation-id="chat.activeId.value"
        :messages="chat.messages.value"
        :loading="chat.initialising.value || chat.loadingThread.value"
        :sending="chat.sending.value"
        :acting="chat.acting.value"
        :busy="chat.busy.value"
        @action="chat.cardAction"
        @suggest="text => chat.send(text)"
      />

      <ChatComposer
        ref="composer"
        v-model="chat.draft.value"
        :busy="chat.busy.value"
        :unavailable="composerUnavailable"
        :staged="chat.staged.value"
        :attachment-errors="chat.attachmentErrors.value"
        @send="chat.send()"
        @files="files => chat.addFiles(files)"
        @remove-file="onRemoveFile"
        @retry-file="id => chat.retryUpload(id)"
        @dismiss-errors="chat.dismissAttachmentErrors()"
      />
    </section>
  </div>
</template>
