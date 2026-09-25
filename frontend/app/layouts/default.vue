<!-- Fixed-height shell: the header stays put and each page scrolls (or, for the chat, lays itself out) below it. -->
<template>
  <div class="flex h-dvh flex-col bg-background text-secondary">
    <AppHeader class="shrink-0" />
    <div class="min-h-0 flex-1 overflow-y-auto">
      <slot />
    </div>
  </div>
</template>
