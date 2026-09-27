<script setup lang="ts">
const props = defineProps<{
  command: 'play' | 'pause' | 'restart' | 'seek' | 'complete'
  scenario: number
  revision: number
}>()
const emit = defineEmits<{ complete: [] }>()
const config = useRuntimeConfig()
const started = ref(false)
const paused = ref(true)
const scenarioIndex = ref(0)
const runId = ref(0)
const requiresFreshLogin = ref(false)
const requiresFreshConversation = ref(false)
const requestPreparing = ref(false)
const messageDispatched = ref(false)
const submissionFinished = ref(false)
const previousConversationId = ref<number | null>(null)
const waitingForFreshConversation = ref(false)
const frame = ref<HTMLIFrameElement | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let confirmationTimer: ReturnType<typeof setTimeout> | undefined
const scenarios = ['Claim attachment', 'Leave request', 'Edit or cancel Leave']
const appUrl = ref('')
onMounted(() => {
  appUrl.value = (config.public.demoAppOrigin || window.location.origin) + '/login'
})

watch(() => props.revision, () => {
  scenarioIndex.value = Math.min(Math.max(Math.round(props.scenario), 0), scenarios.length - 1)
  if (props.command === 'restart') {
    started.value = true
    paused.value = false
    requiresFreshLogin.value = true
    requiresFreshConversation.value = true
    requestPreparing.value = false
    messageDispatched.value = false
    submissionFinished.value = false
    previousConversationId.value = null
    waitingForFreshConversation.value = false
    runId.value += 1
  }
  if (props.command === 'play') {
    started.value = true
    paused.value = false
  }
  if (props.command === 'pause') paused.value = true
  if (props.command === 'complete') paused.value = true
  if (props.command === 'play' || props.command === 'restart') runNext()
}, { immediate: true })

function schedule(task: () => void, wait = 900) {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    if (!paused.value) task()
  }, wait)
}

function scheduleConfirmation(task: () => void, wait = 700) {
  if (confirmationTimer) clearTimeout(confirmationTimer)
  confirmationTimer = setTimeout(() => {
    if (!paused.value) task()
  }, wait)
}

function runNext() {
  schedule(() => {
    const doc = frame.value?.contentDocument
    if (!doc) return
    if (requiresFreshLogin.value) {
      requiresFreshLogin.value = false
      const signOut = Array.from(doc.querySelectorAll<HTMLButtonElement>('button'))
        .find(button => button.textContent?.trim() === 'Sign out')
      if (signOut) {
        signOut.click()
        // Sign-out is a Nuxt client-side route change, so an iframe load event is
        // not guaranteed. Continue the state machine explicitly.
        schedule(runNext, 900)
      }
      else if (frame.value) frame.value.src = appUrl.value
      return
    }
    const account = doc.querySelector<HTMLButtonElement>('[data-account-email="daniel.wong@example.com"]')
    if (account) {
      account.click()
      schedule(runNext, 1200)
      return
    }
    if (requiresFreshConversation.value) {
      requiresFreshConversation.value = false
      previousConversationId.value = Number(doc.querySelector('[data-active-conversation-id]')?.getAttribute('data-active-conversation-id')) || null
      const newChat = doc.querySelector<HTMLButtonElement>('[data-testid="presentation-new-chat-button"]')
      if (!newChat || newChat.disabled) {
        requiresFreshConversation.value = true
        schedule(runNext, 500)
        return
      }
      waitingForFreshConversation.value = true
      newChat.click()
      schedule(runNext, 350)
      return
    }
    if (waitingForFreshConversation.value) {
      const activeId = Number(doc.querySelector('[data-active-conversation-id]')?.getAttribute('data-active-conversation-id')) || null
      if (!activeId || activeId === previousConversationId.value) {
        schedule(runNext, 350)
        return
      }
      waitingForFreshConversation.value = false
    }
    if (requiresFreshConversation.value) {
      schedule(runNext, 350)
      return
    }
    if (messageDispatched.value && !submissionFinished.value) {
      confirmSubmission()
      return
    }
    if (requestPreparing.value || submissionFinished.value) return
    const textarea = doc.querySelector<HTMLTextAreaElement>('#chat-input')
    if (!textarea) return
    requestPreparing.value = true
    const message = scenarioIndex.value === 0
      ? 'Create a staff claim from this receipt.'
      : scenarioIndex.value === 1
        ? 'I would like annual leave from 30 Sep to 5 Oct.'
        : 'Please cancel my Annual Leave from 10 Nov 2026 to 12 Nov 2026.'
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
    setter?.call(textarea, message)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
    if (scenarioIndex.value === 0) {
      const input = doc.querySelector<HTMLInputElement>('input[type="file"]')
      if (input && typeof DataTransfer !== 'undefined') {
        fetch('/demo/receipt-sample.png').then(response => response.blob()).then((blob) => {
          if (paused.value) return
          const transfer = new DataTransfer()
          transfer.items.add(new File([blob], 'receipt-sample.png', { type: 'image/png' }))
          input.files = transfer.files
          input.dispatchEvent(new Event('change', { bubbles: true }))
          schedule(() => send(doc), 2800)
        })
        return
      }
    }
    send(doc)
  })
}

function send(doc: Document, attempt = 0) {
  if (paused.value) return
  const submit = Array.from(doc.querySelectorAll<HTMLButtonElement>('button'))
    .find(button => button.textContent?.trim() === 'Send' && !button.disabled)
  if (!submit) {
    if (attempt < 12) schedule(() => send(frame.value?.contentDocument ?? doc, attempt + 1), 500)
    return
  }
  messageDispatched.value = true
  submit.click()
  scheduleConfirmation(() => confirmSubmission(0), 2500)
}

function confirmSubmission(attempt = 0) {
  if (paused.value) return
  const doc = frame.value?.contentDocument
  if (!doc) return
  const confirmationLabel = scenarioIndex.value === 2 ? 'Cancel request' : 'Submit'
  const confirm = Array.from(doc.querySelectorAll<HTMLButtonElement>('button'))
    .find(button => button.textContent?.trim() === confirmationLabel && !button.disabled)
  if (confirm) {
    confirm.click()
    submissionFinished.value = true
    scheduleConfirmation(confirmResult, 700)
    return
  }
  if (attempt < 20) scheduleConfirmation(() => confirmSubmission(attempt + 1), 700)
}

function confirmResult(attempt = 0) {
  if (paused.value) return
  const text = frame.value?.contentDocument?.body.textContent ?? ''
  if (
    text.includes('Submitted - Staff claim')
    || text.includes('Submitted - Leave application')
    || text.includes('Cancelled - Leave application')
  ) {
    paused.value = true
    emit('complete')
    return
  }
  if (attempt < 15) scheduleConfirmation(() => confirmResult(attempt + 1), 500)
}

function onFrameLoad() {
  if (!paused.value) runNext()
}

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
  if (confirmationTimer) clearTimeout(confirmationTimer)
})
</script>

<template>
  <section class="live-demo">
    <div class="live-frame">
      <iframe v-if="started" ref="frame" :key="runId" :src="appUrl" title="Live SCMP Internal Operations AI Assistant" @load="onFrameLoad" />
      <div v-else class="live-ready">
        <strong>Ready for a real interaction</strong>
        <span>Recommended: Claim attachment. Upload the fictional receipt and ask to create a Staff Claim.</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.live-demo{display:grid;width:100%;height:100%}.live-frame{position:relative;min-height:0;overflow:hidden;border:1px solid rgb(101 201 255 / 45%);border-radius:.8rem;background:#06101c}.live-frame iframe{width:100%;height:100%;border:0;background:white}.live-ready{position:absolute;inset:0;display:grid;place-content:center;gap:.6rem;padding:2rem;text-align:center;background:radial-gradient(circle,rgb(29 121 172 / 35%),transparent 50%),#06101c}.live-ready strong{font-size:clamp(1.4rem,3vw,2.2rem);font-weight:560}.live-ready span{max-width:34rem;color:#b9d0dd;line-height:1.5}
</style>
