<script setup lang="ts">
defineProps<{ role: Role }>()
</script>

<template>
  <span class="role-badge" :data-role="role">{{ roleLabel(role) }}</span>
</template>
