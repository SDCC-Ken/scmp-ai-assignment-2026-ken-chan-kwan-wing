<script setup lang="ts">
const { user } = useAuth()
useHead(() => ({ title: `${chatTabLabel(user.value)} - SCMP Internal Operations AI Assistant` }))
</script>

<!-- The global middleware lets users who file requests or approve something reach this route. -->
<template>
  <main class="h-full">
    <ChatWorkspace />
  </main>
</template>
