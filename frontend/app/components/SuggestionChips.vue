<script setup lang="ts">
defineProps<{ disabled?: boolean }>()
defineEmits<{ pick: [text: string] }>()
</script>

<template>
  <ul class="flex flex-wrap justify-center gap-2" aria-label="Suggested messages">
    <li v-for="text in CHAT_SUGGESTIONS" :key="text" class="max-w-full">
      <button
        type="button"
        class="focus-ring max-w-full rounded-full border border-secondary/40 px-3.5 py-2 text-left text-sm font-medium hover:bg-secondary/10 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="disabled"
        @click="$emit('pick', text)"
      >
        {{ text }}
      </button>
    </li>
  </ul>
</template>
