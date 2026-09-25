<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  text: string
  /** "alert" for the page banner; the modal uses "note" so the warning is not announced twice. */
  role?: 'alert' | 'note'
}>(), { role: 'alert' })
</script>

<template>
  <div class="mock-warning flex gap-3 rounded-lg p-4" :role="role">
    <svg class="mock-warning-icon mt-0.5 h-6 w-6 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <path d="M12 9v4M12 17h.01" />
    </svg>
    <div class="min-w-0">
      <p class="font-semibold">
        {{ title }}
      </p>
      <p class="mt-1 text-sm leading-relaxed">
        {{ text }}
      </p>
    </div>
  </div>
</template>
