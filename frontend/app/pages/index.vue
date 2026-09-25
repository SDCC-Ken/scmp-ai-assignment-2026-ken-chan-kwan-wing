<script setup lang="ts">
useHead({ title: 'Home - SCMP Internal Operations AI Assistant' })

const { user } = useAuth()
const capabilities = computed(() => (user.value ? ROLE_CAPABILITIES[user.value.role] : null))
</script>

<template>
  <main v-if="user && capabilities" class="mx-auto max-w-3xl space-y-6 px-4 py-8">
    <section>
      <h1 class="text-2xl font-bold">
        Signed in as {{ user.display_name }} ({{ roleLabel(user.role) }})
      </h1>
      <p class="mt-1 text-sm opacity-90">
        {{ user.email }}
      </p>
    </section>

    <MockWarning :title="MOCK_SESSION_REMINDER.title" :text="MOCK_SESSION_REMINDER.text" role="note" />

    <section class="rounded-2xl border border-secondary/30 p-5" aria-labelledby="capabilities-title">
      <div class="flex flex-wrap items-center gap-2">
        <h2 id="capabilities-title" class="text-lg font-semibold">
          What you can do
        </h2>
        <RoleBadge :role="user.role" />
      </div>
      <p class="mt-2 text-sm opacity-90">
        {{ capabilities.summary }}
      </p>
      <ul class="mt-4 space-y-2">
        <li
          v-for="item in capabilities.items"
          :key="item"
          class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-secondary/20 px-3 py-2"
        >
          <span>{{ item }}</span>
          <span class="rounded-full border border-secondary/40 px-2 py-0.5 text-xs font-medium">Coming in the next phase</span>
        </li>
      </ul>
    </section>
  </main>
</template>
