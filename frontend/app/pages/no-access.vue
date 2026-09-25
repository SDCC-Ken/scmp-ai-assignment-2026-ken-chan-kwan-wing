<script setup lang="ts">
useHead({ title: 'No access - SCMP Internal Operations AI Assistant' })
const { user } = useAuth()
</script>

<template>
  <main class="mx-auto max-w-xl space-y-6 px-4 py-10">
    <section class="rounded-2xl border border-secondary/30 p-6 text-center">
      <IconGlyph name="inbox" class="mx-auto h-8 w-8" />
      <h1 class="mt-3 text-xl font-bold">
        Nothing to do here yet
      </h1>
      <p class="mt-2 text-sm">
        {{ user?.display_name ?? 'This account' }} has no approver assigned for leave or claims, and does not approve any
        requests, so there are no screens available. In this demonstration, choose another fictional account.
      </p>
      <p class="mt-1 text-sm opacity-90">
        Use "Sign out" in the header to switch account.
      </p>
    </section>
    <MockWarning :title="MOCK_SESSION_REMINDER.title" :text="MOCK_SESSION_REMINDER.text" role="note" />
  </main>
</template>
