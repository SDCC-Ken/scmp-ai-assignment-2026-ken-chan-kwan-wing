<script setup lang="ts">
const props = defineProps<{ command: 'play' | 'pause' | 'restart' | 'seek' | 'complete', revision: number }>()
const emit = defineEmits<{ complete: [] }>()
const config = useRuntimeConfig()
const frame = ref<HTMLIFrameElement | null>(null)
const started = ref(false)
const paused = ref(true)
const loginAs = ref<'robin' | 'mia'>('robin')
const needsSignOut = ref(false)
const step = ref(0)
let timer: ReturnType<typeof setTimeout> | undefined
const appUrl = computed(() => (config.public.demoAppOrigin || window.location.origin) + '/login')
const targetDate = '2026-12-09'

function schedule(task: () => void, wait = 850) {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { if (!paused.value) task() }, wait)
}

function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
  setter?.call(textarea, value)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

function activeInbox(doc: Document) {
  return doc.querySelector<HTMLElement>('[data-inbox-active]')
}

function clickButton(root: ParentNode, label: string) {
  const button = Array.from(root.querySelectorAll<HTMLButtonElement>('button')).find(item => item.textContent?.trim() === label)
  button?.click()
  return !!button
}

function clickBell(doc: Document) {
  const bell = doc.querySelector<HTMLButtonElement>('button[title="Open your inbox"]')
  bell?.click()
  return !!bell
}

watch(() => props.revision, () => {
  if (props.command === 'restart') {
    started.value = true
    paused.value = false
    loginAs.value = 'robin'
    needsSignOut.value = true
    step.value = 0
  }
  if (props.command === 'play') paused.value = false
  if (props.command === 'pause' || props.command === 'complete') paused.value = true
  if (props.command === 'restart' || props.command === 'play') run()
}, { immediate: true })

function run() {
  schedule(() => {
    const doc = frame.value?.contentDocument
    if (!doc) return

    if (needsSignOut.value) {
      const signOut = Array.from(doc.querySelectorAll<HTMLButtonElement>('button')).find(button => button.textContent?.trim() === 'Sign out')
      if (signOut) { signOut.click(); needsSignOut.value = false; schedule(run, 650); return }
    }

    const email = loginAs.value === 'robin' ? 'presentation.approver@example.com' : 'presentation.employee@example.com'
    const account = doc.querySelector<HTMLButtonElement>(`[data-account-email="${email}"]`)
    if (account) { account.click(); schedule(run, 1200); return }

    if (step.value === 0) {
      if (clickBell(doc)) { step.value = 1; schedule(run, 900); return }
      schedule(run, 400); return
    }

    if (step.value === 1) {
      const card = activeInbox(doc)
      if (!card) { schedule(run, 400); return }
      if (card.textContent?.includes(targetDate)) { step.value = 2; schedule(run, 400); return }
      schedule(run, 400); return
    }

    if (step.value === 2) {
      const card = activeInbox(doc)
      if (!card) { schedule(run, 400); return }
      const note = card.querySelector<HTMLTextAreaElement>('textarea')
      if (note && !note.value.trim()) { setTextareaValue(note, 'Coverage confirmed for this period.'); schedule(run, 350); return }
      if (clickButton(card, 'Approve')) { step.value = 3; schedule(run, 500); return }
      schedule(run, 400); return
    }

    if (step.value === 3) {
      const card = activeInbox(doc)
      if (card && clickButton(card, 'Confirm approve')) { step.value = 4; schedule(run, 900); return }
      schedule(run, 400); return
    }

    if (step.value === 4) {
      if (doc.body.textContent?.includes('You approved leave request')) {
        loginAs.value = 'mia'
        needsSignOut.value = true
        step.value = 5
        schedule(run, 800)
        return
      }
      schedule(run, 400); return
    }

    if (step.value === 5) {
      if (clickBell(doc)) { step.value = 6; schedule(run, 900); return }
      schedule(run, 400); return
    }

    if (step.value === 6) {
      const card = activeInbox(doc)
      if (!card) { schedule(run, 400); return }
      if (card.textContent?.includes(targetDate) && /approved/i.test(card.textContent ?? '')) {
        paused.value = true
        emit('complete')
        return
      }
      schedule(run, 400)
    }
  })
}

onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <section class="approval-live">
    <iframe v-if="started" ref="frame" :src="appUrl" title="Live bell-to-decision demo" @load="!paused && run()" />
    <div v-else><strong>Ready for one bell-to-decision walkthrough</strong><span>Start: Robin clicks the bell and approves Mia’s dedicated Leave request. The script then signs in again as Mia and opens her bell notification.</span></div>
  </section>
</template>

<style scoped>
.approval-live{width:min(96%,78rem);height:min(62vh,43rem);margin:auto;overflow:hidden;border:1px solid rgb(101 201 255 / 48%);border-radius:.9rem;background:#06101c}.approval-live iframe{width:100%;height:100%;border:0;background:#fff}.approval-live>div{display:grid;height:100%;place-content:center;gap:.6rem;padding:2rem;text-align:center}.approval-live strong{font-size:clamp(1.4rem,3vw,2.3rem)}.approval-live span{max-width:40rem;color:#b9d0dd;line-height:1.5}
</style>
