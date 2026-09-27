<script setup lang="ts">
definePageMeta({ layout: false })

const route = useRoute()
const password = ref('')
const error = ref('')
const submitting = ref(false)
const returnTo = computed(() => route.query.returnTo === '/presenter' ? '/presenter' : '/presentation')

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    await $fetch('/api/presentation/login', { method: 'POST', body: { password: password.value } })
    await navigateTo(returnTo.value)
  } catch {
    error.value = 'Incorrect password, or PRESENTATION_PASSWORD is not configured.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="access-shell">
    <form class="access-card" @submit.prevent="submit">
      <span class="access-dot" />
      <p>Private presentation</p>
      <h1>Enter access password</h1>
      <label>Password<input v-model="password" type="password" autocomplete="current-password" autofocus></label>
      <span v-if="error" class="access-error">{{ error }}</span>
      <button :disabled="submitting" type="submit">{{ submitting ? 'Checking…' : 'Continue' }} →</button>
    </form>
  </main>
</template>

<style scoped>
.access-shell { display: grid; min-height: 100dvh; place-items: center; padding: 1.5rem; background: radial-gradient(circle at 50% 15%, #155677, #06101c 52%); color: #edf8ff; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.access-card { display: grid; width: min(100%, 26rem); gap: 1rem; border: 1px solid rgb(182 221 241 / 28%); border-radius: 1rem; padding: 2rem; background: rgb(4 20 33 / 88%); box-shadow: 0 2rem 5rem rgb(0 0 0 / 32%); }
.access-dot { width: 0.65rem; height: 0.65rem; border-radius: 50%; background: #66ceff; box-shadow: 0 0 1rem #66ceff; }.access-card p { margin: 0; color: #66ceff; font-size: 0.7rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }.access-card h1 { margin: 0; font-size: 2rem; letter-spacing: -.05em; }.access-card label { display: grid; gap: .45rem; color: rgb(237 248 255 / 72%); font-size: .8rem; }.access-card input { border: 1px solid rgb(182 221 241 / 30%); border-radius: .6rem; padding: .85rem; background: rgb(255 255 255 / 8%); color: inherit; font: inherit; }.access-card button { border: 0; border-radius: .6rem; padding: .85rem 1rem; background: #66ceff; color: #052037; font-weight: 750; }.access-error { color: #ff9da4; font-size: .8rem; }
</style>
