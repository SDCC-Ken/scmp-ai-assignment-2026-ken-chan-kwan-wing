<script setup lang="ts">
import type { AttachmentInfo } from '~/types/chat'

const props = withDefaults(defineProps<{
  attachment: AttachmentInfo
  /** "large" for message bubbles, "small" inside cards. */
  size?: 'large' | 'small'
}>(), { size: 'large' })

const { acquire, release } = useAttachmentBlobs()

const kind = computed(() => attachmentKind(props.attachment.content_type))
type LoadState = 'idle' | 'loading' | 'ready' | 'error' | 'unpreviewable'
const state = ref<LoadState>('idle')
const blobUrl = ref('')
const errorText = ref('')
const previewOpen = ref(false)
const thumb = ref<HTMLButtonElement | null>(null)
const opening = ref(false)
let held = false

async function load(): Promise<string | null> {
  if (blobUrl.value) return blobUrl.value
  state.value = 'loading'
  try {
    const url = await acquire(props.attachment.url)
    held = true
    blobUrl.value = url
    state.value = 'ready'
    return url
  }
  catch (cause) {
    errorText.value = downloadErrorMessage(extractStatus(cause))
    state.value = 'error'
    return null
  }
}

// Images load eagerly (they are the thumbnail); PDFs load only when opened.
onMounted(() => {
  if (kind.value === 'image') void load()
})

onBeforeUnmount(() => {
  if (held) release(props.attachment.url)
})

async function closePreview() {
  previewOpen.value = false
  await nextTick()
  thumb.value?.focus() // focus returns to the thumbnail that opened the dialog
}

function onImageError() {
  state.value = 'unpreviewable' // e.g. HEIC in a browser that cannot show it
}

async function openFile() {
  if (opening.value) return
  if (kind.value === 'image' && state.value === 'ready') {
    previewOpen.value = true
    return
  }
  // Open the tab synchronously (inside the click) so pop-up blockers allow it, then point it at the blob.
  const tab = kind.value === 'pdf' ? window.open('about:blank', '_blank') : null
  if (tab) tab.opener = null
  opening.value = true
  const url = await load()
  opening.value = false
  if (!url) {
    tab?.close()
    return
  }
  if (tab) tab.location.href = url
  else download(url) // unpreviewable image or other type
}

function download(url: string) {
  const link = document.createElement('a')
  link.href = url
  link.download = props.attachment.filename
  link.click()
}

const box = computed(() => (props.size === 'large' ? 'h-24 w-24' : 'h-14 w-14'))
</script>

<template>
  <div class="inline-flex max-w-full">
    <!-- Image thumbnail (opens a larger preview). -->
    <button
      v-if="kind === 'image' && state !== 'unpreviewable' && state !== 'error'"
      ref="thumb"
      type="button"
      class="focus-ring relative flex shrink-0 items-center justify-center overflow-hidden rounded-lg border border-secondary/40 bg-secondary/5"
      :class="box"
      :disabled="state !== 'ready'"
      :aria-label="state === 'ready' ? `Preview ${attachment.filename}` : `Loading ${attachment.filename}`"
      @click="openFile"
    >
      <img v-if="state === 'ready'" :src="blobUrl" :alt="attachment.filename" class="h-full w-full object-cover" @error="onImageError">
      <IconGlyph v-else name="spinner" class="h-5 w-5" />
    </button>

    <!-- Missing or failed file: a placeholder that says why. -->
    <div
      v-else-if="state === 'error'"
      class="flex max-w-full items-center gap-2 rounded-lg border border-dashed px-2.5 py-2 text-xs"
      :class="[toneClass('grey'), size === 'large' ? 'min-h-24' : 'min-h-14']"
      role="img"
      :aria-label="`${attachment.filename}: ${errorText}`"
    >
      <IconGlyph name="alert" class="h-4 w-4 shrink-0" />
      <span class="min-w-0">
        <span class="chat-text block font-semibold">{{ errorText }}</span>
        <span class="chat-text block">{{ attachment.filename }}</span>
      </span>
    </div>

    <!-- PDF, other types, or an image this browser cannot render: a file chip. -->
    <button
      v-else
      type="button"
      class="focus-ring flex max-w-full items-center gap-2 rounded-lg border border-secondary/40 bg-background px-2.5 py-2 text-left text-secondary hover:bg-secondary/10 disabled:cursor-wait"
      :disabled="opening"
      :aria-label="kind === 'pdf' ? `Open ${attachment.filename} in a new tab` : `Download ${attachment.filename}`"
      @click="openFile"
    >
      <IconGlyph :name="opening ? 'spinner' : kind === 'pdf' ? 'file' : 'image'" class="h-5 w-5 shrink-0" />
      <span class="min-w-0">
        <span class="chat-text block truncate text-xs font-semibold">{{ attachment.filename }}</span>
        <span class="block text-xs">
          {{ formatBytes(attachment.size_bytes) }}<template v-if="kind === 'pdf'"> - opens in a new tab</template><template v-else-if="state === 'unpreviewable'"> - preview not available, download</template>
        </span>
      </span>
    </button>

    <AttachmentPreview v-if="kind === 'image'" :open="previewOpen" :src="blobUrl" :filename="attachment.filename" @close="closePreview" />
  </div>
</template>
