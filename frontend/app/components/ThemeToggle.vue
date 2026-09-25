<script setup lang="ts">
const mode = useThemeMode()
const options: { value: ThemeMode, label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
]
</script>

<template>
  <div
    role="group"
    aria-label="Colour theme"
    class="inline-flex overflow-hidden rounded-lg border border-secondary/40"
  >
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      :aria-pressed="mode === option.value"
      class="px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-primary"
      :class="mode === option.value ? 'bg-primary text-slate-950' : 'text-secondary hover:bg-secondary/10'"
      @click="mode = option.value"
    >
      {{ option.label }}
    </button>
  </div>
</template>
