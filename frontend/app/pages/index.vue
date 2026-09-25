<template>
  <main class="flex min-h-screen items-center justify-center bg-background p-6">
    <section class="w-full max-w-lg rounded-2xl border border-secondary/30 p-8 shadow-lg">
      <p class="text-sm font-semibold uppercase tracking-wide text-primary">
        Phase 0
      </p>
      <h1 class="mt-2 text-2xl font-bold text-secondary">
        SCMP Internal Operations AI Assistant - Phase 0
      </h1>
      <p class="mt-3 text-secondary/80">
        Foundation skeleton: Nuxt 4, TypeScript and Tailwind CSS 4 with an env-driven theme. No chat or business logic yet.
      </p>
      <div class="mt-6 flex items-center justify-between gap-4">
        <span class="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-slate-950">Primary</span>
        <ThemeToggle />
      </div>
    </section>
  </main>
</template>
