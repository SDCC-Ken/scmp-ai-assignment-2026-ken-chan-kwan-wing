<template>
  <div class="min-h-screen bg-background text-secondary">
    <!-- Top-left: the top-right corner belongs to the One Tap card. -->
    <div class="absolute left-4 top-4">
      <ThemeToggle />
    </div>
    <slot />
  </div>
</template>
