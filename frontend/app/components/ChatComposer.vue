<script setup lang="ts">
import type { StagedFile } from '~/utils/attachments'

const props = defineProps<{
  modelValue: string
  /** A turn is in flight: the composer is disabled. */
  busy: boolean
  /** Enables or disables input (no active conversation, loading). */
  unavailable?: boolean
  staged: StagedFile[]
  attachmentErrors: string[]
  /** Users who cannot file requests (approve-only) get a status-only prompt. */
  canRequest?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'send': []
  'files': [files: File[]]
  'remove-file': [localId: string]
  'retry-file': [localId: string]
  'dismiss-errors': []
}>()

const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const remaining = computed(() => remainingChars(props.modelValue))
const overLimit = computed(() => remaining.value < 0)
const uploading = computed(() => isUploading(props.staged))
const sendable = computed(() => !props.unavailable && canSendMessage(props.modelValue, props.staged, props.busy))
const inputsDisabled = computed(() => props.busy || !!props.unavailable)
const dragging = ref(false)
let dragDepth = 0

function resize() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 168)}px`
}

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

function onKeydown(event: KeyboardEvent) {
  // Enter sends, Shift+Enter inserts a newline; never send while an IME (e.g. Chinese) is composing.
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  if (sendable.value) emit('send')
}

function pickFiles() {
  fileInput.value?.click()
}

function onPicked(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files?.length) emit('files', [...input.files])
  input.value = '' // allow picking the same file again
}

/** Pasted screenshots: files on the clipboard become attachments; plain text pastes normally. */
function onPaste(event: ClipboardEvent) {
  const files = [...(event.clipboardData?.files ?? [])]
  if (!files.length || inputsDisabled.value) return
  event.preventDefault()
  emit('files', files.map(file =>
    /^image\.\w+$/i.test(file.name) ? new File([file], pastedFileName(file.type), { type: file.type }) : file,
  ))
}

const hasFiles = (event: DragEvent) => [...(event.dataTransfer?.types ?? [])].includes('Files')

function onDragEnter(event: DragEvent) {
  if (!hasFiles(event) || inputsDisabled.value) return
  dragDepth++
  dragging.value = true
}

function onDragOver(event: DragEvent) {
  if (!hasFiles(event) || inputsDisabled.value) return
  event.preventDefault() // required to allow a drop
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragging.value = false
}

function onDrop(event: DragEvent) {
  dragDepth = 0
  dragging.value = false
  if (!hasFiles(event)) return
  event.preventDefault()
  if (inputsDisabled.value) return
  const files = [...(event.dataTransfer?.files ?? [])]
  if (files.length) emit('files', files)
}

function focus() {
  textarea.value?.focus()
}

watch(() => props.modelValue, () => nextTick(resize))

// Re-measure when the width changes (first paint in a hidden/narrow pane, rotating a phone, opening the drawer).
let observer: ResizeObserver | undefined
let lastWidth = 0
onMounted(() => {
  resize()
  if (!textarea.value || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width ?? 0
    if (width !== lastWidth) {
      lastWidth = width
      resize()
    }
  })
  observer.observe(textarea.value)
})
onBeforeUnmount(() => observer?.disconnect())

// After a turn ends the disabled textarea has lost focus (and a removed card button may have held it): restore it.
watch(() => props.busy, async (busy, wasBusy) => {
  if (wasBusy && !busy) {
    await nextTick()
    const active = document.activeElement
    if (!active || active === document.body) focus()
  }
})

defineExpose({ focus })
</script>

<template>
  <form
    class="relative border-t border-secondary/30 px-3 py-3 sm:px-5"
    @submit.prevent="sendable && emit('send')"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div class="mx-auto max-w-3xl">
      <div
        v-if="attachmentErrors.length"
        class="mb-2 flex items-start gap-2 rounded-lg px-3 py-2 text-sm"
        :class="toneClass('red')"
        role="alert"
      >
        <IconGlyph name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
        <ul class="min-w-0 flex-1 space-y-0.5">
          <li v-for="message in attachmentErrors" :key="message" class="chat-text">
            {{ message }}
          </li>
        </ul>
        <button type="button" class="focus-ring shrink-0 rounded-md p-0.5 hover:bg-white/20" @click="emit('dismiss-errors')">
          <IconGlyph name="close" class="h-4 w-4" />
          <span class="sr-only">Dismiss file errors</span>
        </button>
      </div>

      <ul v-if="staged.length" class="mb-2 flex max-h-32 flex-wrap gap-2 overflow-y-auto" aria-label="Files to send with your message">
        <StagedFileChip
          v-for="item in staged"
          :key="item.localId"
          :item="item"
          @remove="id => emit('remove-file', id)"
          @retry="id => emit('retry-file', id)"
        />
      </ul>

      <div
        class="flex items-end gap-2 rounded-2xl border bg-background p-2 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-secondary"
        :class="overLimit ? 'border-danger' : dragging ? 'border-dashed border-secondary' : 'border-secondary/50'"
      >
        <input
          ref="fileInput"
          type="file"
          multiple
          class="sr-only"
          tabindex="-1"
          aria-hidden="true"
          :accept="ACCEPT_ATTRIBUTE"
          @change="onPicked"
        >
        <button
          type="button"
          class="focus-ring inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Attach files: images or PDF, up to 3 files, 5 MB each"
          aria-describedby="chat-attach-help"
          :disabled="inputsDisabled"
          @click="pickFiles"
        >
          <IconGlyph name="paperclip" class="h-5 w-5" />
        </button>
        <label for="chat-input" class="sr-only">Message</label>
        <textarea
          id="chat-input"
          ref="textarea"
          :value="modelValue"
          rows="1"
          class="max-h-40 min-h-10 min-w-0 flex-1 resize-none bg-transparent px-1 py-2 text-sm outline-none placeholder:text-secondary/70 disabled:cursor-not-allowed disabled:opacity-60"
          :placeholder="staged.length ? 'Add a message (optional)' : canRequest === false ? 'Ask about the status of a request' : 'Ask for leave, submit a claim, or check a status'"
          aria-describedby="chat-input-help chat-input-count"
          :aria-invalid="overLimit"
          :disabled="inputsDisabled"
          @input="onInput"
          @keydown="onKeydown"
          @paste="onPaste"
        />
        <button
          type="submit"
          class="focus-ring inline-flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-secondary px-3.5 text-sm font-semibold text-background hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!sendable"
        >
          <IconGlyph :name="uploading ? 'spinner' : 'send'" class="h-4 w-4" />
          Send
        </button>
      </div>
      <div class="mt-1.5 flex flex-wrap items-start justify-between gap-x-3 gap-y-0.5 text-xs">
        <p id="chat-input-help" class="opacity-90">
          Enter to send, Shift+Enter for a new line
        </p>
        <p
          id="chat-input-count"
          class="tabular-nums"
          :class="overLimit ? 'font-semibold text-danger' : 'opacity-90'"
        >
          {{ modelValue.trim().length }}/{{ MAX_MESSAGE_LENGTH }}<span v-if="overLimit"> - {{ -remaining }} over the limit</span>
        </p>
      </div>
      <p id="chat-attach-help" class="mt-0.5 text-xs opacity-90">
        Attach up to 3 files (JPEG, PNG, WebP, HEIC or PDF), 5 MB each. You can also drop or paste them here.
        <span v-if="uploading" role="status" class="font-semibold"> Uploading, please wait...</span>
      </p>
    </div>

    <div
      v-if="dragging"
      class="pointer-events-none absolute inset-1 flex items-center justify-center rounded-2xl border-2 border-dashed border-secondary bg-background/90 text-sm font-semibold"
      aria-hidden="true"
    >
      <IconGlyph name="paperclip" class="mr-2 h-5 w-5" />
      Drop files to attach
    </div>
  </form>
</template>
