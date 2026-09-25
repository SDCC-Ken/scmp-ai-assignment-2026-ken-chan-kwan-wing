<script setup lang="ts">
const props = defineProps<{
  open: boolean
  src: string
  filename: string
}>()
const emit = defineEmits<{ close: [] }>()

const closeButton = ref<HTMLButtonElement | null>(null)

// Focus moves into the dialog on open; the owner (AttachmentItem) puts it back on the thumbnail on close.
watch(() => props.open, async (open) => {
  if (!open) return
  await nextTick()
  closeButton.value?.focus()
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    emit('close')
  }
  else if (event.key === 'Tab') {
    event.preventDefault() // the close button is the only control: keep focus on it
    closeButton.value?.focus()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex flex-col bg-slate-950/85 p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      :aria-label="`Preview of ${filename}`"
      @keydown="onKeydown"
      @click.self="emit('close')"
    >
      <div class="mb-2 flex items-center justify-between gap-3 text-slate-50" @click.self="emit('close')">
        <p class="min-w-0 truncate text-sm font-semibold">
          {{ filename }}
        </p>
        <button
          ref="closeButton"
          type="button"
          class="focus-ring inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-50 hover:bg-white/10"
          @click="emit('close')"
        >
          <IconGlyph name="close" class="h-4 w-4" />
          Close
        </button>
      </div>
      <div class="flex min-h-0 flex-1 items-center justify-center" @click.self="emit('close')">
        <img :src="src" :alt="filename" class="max-h-full max-w-full rounded-lg object-contain">
      </div>
    </div>
  </Teleport>
</template>
