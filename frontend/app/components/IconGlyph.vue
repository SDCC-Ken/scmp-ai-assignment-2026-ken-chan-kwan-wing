<script setup lang="ts">
type GlyphName = IconName | 'plus' | 'menu' | 'send' | 'info' | 'chevron' | 'close' | 'spinner' | 'chat' | 'down' | 'paperclip' | 'file' | 'image' | 'bell' | 'users' | 'refresh' | 'back' | 'inbox'

defineProps<{ name: GlyphName }>()
</script>

<template>
  <svg
    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true" focusable="false"
    :class="name === 'spinner' ? 'animate-spin' : ''"
  >
    <template v-if="name === 'clock'">
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
    </template>
    <path v-else-if="name === 'check'" d="M5 12.5l4.5 4.5L19 7.5" />
    <path v-else-if="name === 'x' || name === 'close'" d="M6 6l12 12M18 6L6 18" />
    <template v-else-if="name === 'alert'">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><path d="M12 9v4M12 17h.01" />
    </template>
    <template v-else-if="name === 'ban'">
      <circle cx="12" cy="12" r="9" /><path d="M5.6 5.6l12.8 12.8" />
    </template>
    <template v-else-if="name === 'pencil'">
      <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z" /><path d="M13.5 6.5l4 4" />
    </template>
    <path v-else-if="name === 'plus'" d="M12 5v14M5 12h14" />
    <path v-else-if="name === 'menu'" d="M4 6h16M4 12h16M4 18h16" />
    <path v-else-if="name === 'send'" d="M4 12l16-8-6 16-3-7-7-1z" />
    <template v-else-if="name === 'info'">
      <circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" />
    </template>
    <path v-else-if="name === 'chevron'" d="M9 6l6 6-6 6" />
    <path v-else-if="name === 'down'" d="M6 9l6 6 6-6" />
    <path v-else-if="name === 'chat'" d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
    <path v-else-if="name === 'paperclip'" d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l9-9a3.7 3.7 0 0 1 5.2 5.2l-9 9a1.8 1.8 0 0 1-2.6-2.6l8.3-8.3" />
    <template v-else-if="name === 'file'">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" />
    </template>
    <template v-else-if="name === 'image'">
      <rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="10" r="1.5" /><path d="M21 16l-5-5-8 8" />
    </template>
    <path v-else-if="name === 'spinner'" d="M21 12a9 9 0 1 1-6.2-8.55" />
    <template v-else-if="name === 'bell'">
      <path d="M6 9a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9z" /><path d="M10 20a2 2 0 0 0 4 0" />
    </template>
    <template v-else-if="name === 'users'">
      <circle cx="9" cy="8" r="3.2" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0" /><circle cx="17.5" cy="9" r="2.5" /><path d="M17 14.2a5.2 5.2 0 0 1 4.5 5.8" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 12a8 8 0 1 1-2.6-5.9" /><path d="M20 4v5h-5" />
    </template>
    <path v-else-if="name === 'back'" d="M15 6l-6 6 6 6" />
    <template v-else-if="name === 'inbox'">
      <path d="M4 13l2.5-8h11L20 13v6H4z" /><path d="M4 13h5l1 2h4l1-2h5" />
    </template>
  </svg>
</template>
