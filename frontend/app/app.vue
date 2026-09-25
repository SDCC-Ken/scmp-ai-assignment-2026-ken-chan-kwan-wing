<script setup lang="ts">
const { public: { theme } } = useRuntimeConfig()
const mode = useThemeMode()

useHead({
  htmlAttrs: {
    lang: 'en',
    'data-theme': computed(() => (mode.value === 'system' ? undefined : mode.value)),
  },
  title: 'SCMP Internal Operations AI Assistant',
  style: [{ id: 'theme-vars', innerHTML: buildThemeCss(theme) }],
})
</script>

<template>
  <NuxtRouteAnnouncer />
  <NuxtLayout>
    <NuxtPage />
  </NuxtLayout>
</template>
