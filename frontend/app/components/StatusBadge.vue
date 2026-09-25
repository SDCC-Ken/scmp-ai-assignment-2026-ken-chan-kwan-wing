<script setup lang="ts">
const props = defineProps<{
  status: string
  /** Label from the API (shown when the status is not one we know). */
  label?: string
}>()

const meta = computed(() => statusMeta(props.status, props.label))
</script>

<template>
  <span
    class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold"
    :class="toneClass(meta.tone)"
  >
    <IconGlyph :name="meta.icon" class="h-3.5 w-3.5 shrink-0" />
    {{ meta.label }}
  </span>
</template>
