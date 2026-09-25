<script setup lang="ts">
definePageMeta({ layout: 'auth' })
useHead({ title: 'Sign in - SCMP Internal Operations AI Assistant' })

const { notice, expiredNotice } = useAuth()
const route = useRoute()
const message = computed(() => notice.value ?? (route.query.reason === 'expired' ? expiredNotice : null))

// The mock One Tap prompt is shown on load (no click, no cooldown); closing it reveals the button below.
const cardOpen = ref(true)
const card = ref<{ focus: () => void } | null>(null)
const signInButton = ref<{ $el: HTMLElement } | null>(null)

async function openCard() {
  cardOpen.value = true
  await nextTick()
  card.value?.focus() // the user asked for it, so moving focus here is expected
}

async function closeCard(focusWasInside: boolean) {
  cardOpen.value = false
  if (!focusWasInside) return
  await nextTick()
  signInButton.value?.$el.focus() // do not leave keyboard users on <body>
}
// From 768px the fixed card sits beside the copy (360px + 16px gutters reserved via padding);
// 640-767px it overlays the page; under 640px it flows in at the top with 8px side margins.
</script>

<template>
  <div :class="cardOpen ? 'md:pr-[392px]' : ''">
    <main class="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-4 py-16">
      <GoogleOneTapCard v-if="cardOpen" ref="card" @close="closeCard" />

      <header>
        <p class="text-sm font-semibold uppercase tracking-wide">
          Internal operations demo
        </p>
        <h1 class="mt-2 text-3xl font-bold">
          SCMP Internal Operations AI Assistant
        </h1>
        <p class="mt-3 opacity-90">
          A proof-of-concept employee self-service assistant for Leave Applications and Staff Claims.
          It uses fictional data only.
        </p>
      </header>

      <MockWarning :title="MOCK_WARNING.title" :text="MOCK_WARNING.text" />

      <p
        v-if="message"
        role="status"
        class="rounded-lg border border-secondary/40 p-3 text-sm"
      >
        {{ message }}
      </p>

      <div v-if="cardOpen">
        <p class="text-sm opacity-90">
          Pick a fictional account in the Google sign-in prompt to continue.
        </p>
      </div>
      <div v-else>
        <GoogleSignInButton ref="signInButton" aria-controls="one-tap-card" aria-expanded="false" @click="openCard" />
        <p class="mt-3 text-sm opacity-90">
          Opens the sign-in prompt with a list of fictional accounts. No real Google account is used.
        </p>
      </div>
    </main>
  </div>
</template>
