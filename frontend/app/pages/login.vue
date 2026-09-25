<script setup lang="ts">
definePageMeta({ layout: 'auth' })
useHead({ title: 'Sign in - SCMP Internal Operations AI Assistant' })

const { notice, expiredNotice } = useAuth()
const route = useRoute()
const message = computed(() => notice.value ?? (route.query.reason === 'expired' ? expiredNotice : null))
const chooserOpen = ref(false)

function openChooser(event: MouseEvent) {
  // Safari does not focus buttons on click; focus explicitly so focus can return here on close.
  if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus()
  chooserOpen.value = true
}
</script>

<template>
  <main class="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-6 px-4 py-16">
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

    <div>
      <GoogleSignInButton @click="openChooser" />
      <p class="mt-3 text-sm opacity-90">
        Opens a list of fictional accounts. No real Google account is used.
      </p>
    </div>

    <AccountChooserModal :open="chooserOpen" @close="chooserOpen = false" />
  </main>
</template>
