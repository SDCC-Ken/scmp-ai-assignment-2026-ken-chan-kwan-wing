<script setup lang="ts">
useHead({ title: 'My requests - SCMP Internal Operations AI Assistant' })
</script>

<!-- The global middleware only lets users with can_request reach this route. -->
<template>
  <main class="h-full">
    <ChatWorkspace />
  </main>
</template>
