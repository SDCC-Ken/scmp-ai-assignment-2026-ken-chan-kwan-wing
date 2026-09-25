<script setup lang="ts">
/**
 * Accessible modal built on the native <dialog>: showModal() gives a focus trap, an inert page behind it, Escape to
 * close and focus return to the opener. `busy` blocks every way of closing (Escape, backdrop, the parent's buttons
 * are disabled by the parent). Mount the content with `v-if` from the parent only when it needs to be created lazily.
 */
const props = defineProps<{
  open: boolean
  /** Accessible name (the visible heading is referenced by `labelledby` instead when given). */
  label?: string
  labelledby?: string
  describedby?: string
  busy?: boolean
  /** Use role="alertdialog" for a confirmation that needs an answer. */
  alert?: boolean
}>()
const emit = defineEmits<{ close: [] }>()

const dialog = ref<HTMLDialogElement | null>(null)

watch(() => props.open, async (open) => {
  await nextTick()
  const el = dialog.value
  if (!el) return
  if (open && !el.open) el.showModal()
  else if (!open && el.open) el.close()
}, { immediate: true, flush: 'post' })

onMounted(() => {
  if (props.open && dialog.value && !dialog.value.open) dialog.value.showModal()
})

function onCancel(event: Event) {
  event.preventDefault() // the parent decides (it flips `open`), so state and DOM never disagree
  if (!props.busy) emit('close')
}

function onBackdrop(event: MouseEvent) {
  if (event.target === dialog.value && !props.busy) emit('close')
}
</script>

<template>
  <dialog
    ref="dialog"
    :role="alert ? 'alertdialog' : 'dialog'"
    :aria-label="labelledby ? undefined : label"
    :aria-labelledby="labelledby"
    :aria-describedby="describedby"
    :aria-busy="busy ? 'true' : undefined"
    class="modal-dialog m-auto w-[min(32rem,calc(100vw-1.5rem))] rounded-xl border border-secondary/50 bg-background p-0 text-secondary shadow-2xl"
    @cancel="onCancel"
    @click="onBackdrop"
  >
    <div v-if="open" class="p-4 sm:p-5">
      <slot />
    </div>
  </dialog>
</template>
