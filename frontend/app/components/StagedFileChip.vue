<script setup lang="ts">
import type { StagedFile } from '~/utils/attachments'

const props = defineProps<{ item: StagedFile }>()
defineEmits<{
  remove: [localId: string]
  retry: [localId: string]
}>()

const thumbFailed = ref(false)
const showThumb = computed(() => !!props.item.previewUrl && !thumbFailed.value)
const statusText = computed(() => {
  if (props.item.status === 'uploading') return 'Uploading...'
  if (props.item.status === 'error') return props.item.error ?? 'Upload failed'
  return 'Ready to send'
})
</script>

<template>
  <li
    class="flex min-w-0 max-w-full items-center gap-2 rounded-xl border p-1.5 pr-2 text-xs sm:max-w-[16rem]"
    :class="item.status === 'error' ? toneClass('red') : 'border-secondary/40 bg-secondary/5'"
  >
    <span class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-secondary/30 bg-background text-secondary">
      <img v-if="showThumb" :src="item.previewUrl!" alt="" class="h-full w-full object-cover" @error="thumbFailed = true">
      <IconGlyph v-else :name="item.mime === 'application/pdf' ? 'file' : 'image'" class="h-5 w-5" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="chat-text block truncate font-semibold">{{ item.name }}</span>
      <span class="flex items-center gap-1" :role="item.status === 'error' ? 'alert' : undefined">
        <IconGlyph v-if="item.status === 'uploading'" name="spinner" class="h-3 w-3 shrink-0" />
        <IconGlyph v-else-if="item.status === 'uploaded'" name="check" class="h-3 w-3 shrink-0" />
        <IconGlyph v-else name="alert" class="h-3 w-3 shrink-0" />
        <span class="min-w-0" :class="item.status === 'error' ? '' : 'truncate'">{{ formatBytes(item.size) }} - {{ statusText }}</span>
      </span>
    </span>
    <button
      v-if="item.status === 'error'"
      type="button"
      class="focus-ring shrink-0 rounded-md border border-current px-2 py-0.5 font-semibold hover:bg-white/20"
      :aria-label="`Retry uploading ${item.name}`"
      @click="$emit('retry', item.localId)"
    >
      Retry
    </button>
    <button
      type="button"
      class="focus-ring shrink-0 rounded-md p-1 hover:bg-secondary/10"
      :aria-label="`Remove ${item.name}`"
      @click="$emit('remove', item.localId)"
    >
      <IconGlyph name="close" class="h-4 w-4" />
    </button>
  </li>
</template>
