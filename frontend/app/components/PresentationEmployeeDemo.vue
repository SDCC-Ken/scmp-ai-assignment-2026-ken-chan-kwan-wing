<script setup lang="ts">
type EmployeeStage = 'sign-in' | 'leave-flow' | 'working-days' | 'claim-upload'

const props = defineProps<{ stage: EmployeeStage, zoom?: number }>()
const config = useRuntimeConfig()
const liveAppUrl = computed(() => (config.public.demoAppOrigin || 'http://localhost:9180') + '/login')
const focusDialog = ref<HTMLDialogElement | null>(null)
const focusImage = computed(() => {
  if (props.stage === 'leave-flow') return props.zoom === 1
    ? '/demo/employee-01-unified-chat.png'
    : props.zoom === 2 ? '/demo/employee-02-confirmation-card.png' : '/demo/employee-03-submitted-result.png'
  return props.zoom === 1
    ? '/demo/receipt-sample.png'
    : props.zoom === 2 ? '/demo/employee-03-claim-upload.png'
      : props.zoom === 3 ? '/demo/claim-03-confirmation-card.png' : '/demo/claim-04-submitted-result.png'
})
const focusTitle = computed(() => {
  if (props.stage === 'leave-flow') return props.zoom === 1
    ? 'Natural-language request, ready to send'
    : props.zoom === 2 ? 'Explicit confirmation before submission' : 'Submitted request → visible result'
  return props.zoom === 1
    ? 'Original fictional receipt'
    : props.zoom === 2 ? 'Attachment, instruction and Send'
      : props.zoom === 3 ? 'Claim confirmation before submission' : 'Claim submitted → visible result'
})
const focusNote = computed(() => props.stage === 'leave-flow'
  ? 'A real application capture: the employee has entered the request and can review it before selecting Send.'
  : props.zoom === 1
    ? 'The original fictional receipt stays in the same conversation.'
    : props.zoom === 2
      ? 'The employee attaches the receipt and sends a natural-language Claim instruction.'
      : props.zoom === 3
        ? 'The extracted Claim details and original receipt are shown for explicit confirmation.'
        : 'The submitted Claim is recorded and routed to the assigned Finance approver.')

watch(() => props.zoom, async (zoom) => {
  await nextTick()
  if (!focusDialog.value) return
  if (zoom && !focusDialog.value.open) focusDialog.value.showModal()
  if (!zoom && focusDialog.value.open) focusDialog.value.close()
})

onBeforeUnmount(() => focusDialog.value?.close())

const stageCopy = computed(() => ({
  'sign-in': {
    eyebrow: '02A · Mock sign-in',
    title: 'Safe role demonstration',
    body: 'The Google-style account chooser is visibly marked MOCK and lists fictional identities only. It makes the role-specific journey easy to show without using a real SCMP account.',
  },
  'leave-flow': {
    eyebrow: '02B · Leave request',
    title: 'A guided conversation, not a form',
    body: 'Amy starts with a natural message. The assistant returns the essential request information, then asks for an explicit confirmation before anything is submitted.',
  },
  'working-days': {
    eyebrow: '02C · Working-day calculation',
    title: 'Dates explained before submission',
    body: 'The leave period includes National Day and a weekend. The rule is visible to Amy and the reviewer: only three weekdays are counted.',
  },
  'claim-upload': {
    eyebrow: '02C · Staff Claim',
    title: 'The receipt stays in the same chat',
    body: 'Amy attaches the original fictional receipt, then asks the assistant to create a Staff Claim. This is the prepared live demo use case.',
  },
})[props.stage])
</script>

<template>
  <section class="employee-demo" :class="'employee-demo--' + stage" aria-label="Employee journey">
    <header>
      <span class="live-dot" />
      <span>{{ stageCopy.eyebrow }}</span>
    </header>

    <div class="employee-stage">
      <div class="employee-copy">
        <p>{{ stageCopy.eyebrow }}</p>
        <h2>{{ stageCopy.title }}</h2>
        <span>{{ stageCopy.body }}</span>
      </div>

      <div v-if="stage === 'sign-in'" class="sign-in-layout">
        <img src="/demo/employee-00-mock-sign-in.png" alt="Mock sign-in screen with fictional accounts">
        <aside>
          <strong>What this proves</strong>
          <p>One demo application can safely switch between Employee, HR Approver and Finance Approver roles.</p>
          <small>Production assumption: replace this mock with enterprise SSO and role mapping.</small>
        </aside>
      </div>

      <div v-else-if="stage === 'leave-flow'" class="leave-flow-layout">
          <article class="chat-message chat-message--user">
            <small>AMY · EMPLOYEE</small>
            <strong>I would like Annual Leave from 30 Sep to 5 Oct.</strong>
          </article>
          <span class="flow-arrow">→</span>
          <article class="chat-message">
            <small>ASSISTANT</small>
            <strong>I found your leave type and dates. Here is the request for review.</strong>
            <div class="base-fields"><span>Annual</span><span>30 Sep → 5 Oct</span><span>3 working days</span></div>
          </article>
          <span class="flow-arrow">→</span>
          <article class="confirm-card">
            <small>EXPLICIT CONFIRMATION</small>
            <strong>Review before submit</strong>
            <button type="button" disabled>Submit leave request</button>
          </article>
          <div class="inline-calendar">
            <span><b>30 Sep</b> Working day</span><span class="holiday"><b>1 Oct</b> National Day</span><span><b>2 Oct</b> Working day</span><span class="weekend"><b>3–4 Oct</b> Weekend</span><span><b>5 Oct</b> Working day</span><strong>= 3 working days</strong>
          </div>
          <div class="evidence-strip" aria-label="Real application evidence">
            <figure class="evidence-input"><img src="/demo/employee-01-unified-chat.png" alt="Input box and Send button"><figcaption>1 · Natural-language input + Send</figcaption></figure>
            <figure class="evidence-confirm"><img src="/demo/employee-02-confirmation-card.png" alt="Leave confirmation card"><figcaption>2 · Confirmation card</figcaption></figure>
            <figure class="evidence-success"><img src="/demo/employee-03-submitted-result.png" alt="Green submitted result"><figcaption>3 · Submitted result</figcaption></figure>
          </div>
      </div>

      <div v-else-if="stage === 'working-days'" class="calendar-layout">
        <div class="date-row">
          <article class="workday"><small>WED</small><strong>30</strong><span>Working day</span></article>
          <article class="holiday"><small>THU</small><strong>01</strong><span>National Day</span></article>
          <article class="workday"><small>FRI</small><strong>02</strong><span>Working day</span></article>
          <article class="weekend"><small>SAT</small><strong>03</strong><span>Weekend</span></article>
          <article class="weekend"><small>SUN</small><strong>04</strong><span>Weekend</span></article>
          <article class="workday"><small>MON</small><strong>05</strong><span>Working day</span></article>
        </div>
        <div class="calendar-result"><span>30 Sep – 5 Oct 2026</span><strong>3 working days</strong><small>National Day + weekend excluded</small></div>
      </div>

      <div v-else class="claim-layout">
        <img src="/demo/receipt-sample.png" alt="Fictional original receipt attached to a Staff Claim">
        <div class="claim-flow">
          <span class="file-chip">receipt-sample.png · 65 KB</span>
          <article class="chat-message chat-message--user">
            <small>AMY · EMPLOYEE</small>
            <strong>Create a Staff Claim from this receipt.</strong>
          </article>
          <article class="chat-message">
            <small>ASSISTANT</small>
            <strong>I can read the attachment and prepare the claim details for your confirmation.</strong>
          </article>
          <a :href="liveAppUrl" target="_blank" rel="noopener">Open real Claim demo ↗</a>
          <small class="live-note">Prepared interaction: attach the sample receipt, then submit the message above.</small>
        </div>
        <figure class="claim-evidence"><img src="/demo/employee-03-claim-upload.png" alt="Real Claim upload conversation"><figcaption>2 · Attachment, instruction and Send</figcaption></figure>
        <div class="claim-outcomes" aria-label="Claim confirmation and result evidence">
          <figure><img src="/demo/claim-03-confirmation-card.png" alt="Staff Claim confirmation card"><figcaption>3 · Confirm the extracted Claim details</figcaption></figure>
          <figure><img src="/demo/claim-04-submitted-result.png" alt="Submitted Staff Claim result"><figcaption>4 · Submitted result and Finance approval route</figcaption></figure>
        </div>
      </div>
    </div>

    <dialog ref="focusDialog" class="evidence-dialog" @cancel.prevent>
      <header><span>DEMO EVIDENCE</span><strong>{{ focusTitle }}</strong><small>{{ focusNote }}</small></header>
      <figure>
        <img :src="focusImage" :alt="focusTitle">
        <figcaption>Use the iPad controller’s Overview button to return to the presentation.</figcaption>
      </figure>
    </dialog>
  </section>
</template>

<style scoped>
.employee-demo{display:grid;gap:.75rem;width:min(96%,72rem);margin:0 auto}.employee-demo header{display:flex;align-items:center;gap:.45rem;color:#d6e5ef;font-size:.78rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase}.live-dot{width:.55rem;height:.55rem;border-radius:50%;background:#62c9ff;box-shadow:0 0 .8rem rgb(98 201 255 / 70%)}.employee-stage{display:grid;gap:1rem;border:1px solid rgb(125 211 252 / 38%);border-radius:.9rem;background:linear-gradient(140deg,rgb(11 46 70 / 90%),rgb(5 21 35 / 96%));padding:clamp(1rem,2.6vw,1.7rem);box-shadow:0 1rem 3rem rgb(0 0 0 / 22%)}.employee-copy{display:grid;gap:.35rem;max-width:52rem}.employee-copy p,.chat-message small,.confirm-card small{margin:0;color:#65c9ff;font-size:.67rem;font-weight:750;letter-spacing:.12em;text-transform:uppercase}.employee-copy h2{margin:0;color:#f0f9ff;font-size:clamp(1.45rem,3.4vw,2.3rem);font-weight:560;letter-spacing:-.045em}.employee-copy>span{color:#b8ccda;font-size:.92rem;line-height:1.5}.sign-in-layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(13rem,.65fr);gap:1rem;align-items:center}.sign-in-layout img{width:100%;border-radius:.55rem;background:white}.sign-in-layout aside{display:grid;gap:.65rem;border-left:2px solid #65c9ff;padding-left:1rem;color:#bed2df;line-height:1.5}.sign-in-layout aside strong{color:#eef8ff;font-size:1rem}.sign-in-layout aside p{margin:0}.sign-in-layout aside small{color:#82a2b5}.leave-flow-layout{display:grid;grid-template-columns:1fr auto 1.18fr auto .9fr;gap:.55rem;align-items:center}.chat-message,.confirm-card{display:grid;gap:.55rem;border:1px solid rgb(182 219 240 / 22%);border-radius:.65rem;background:rgb(5 25 40 / 72%);padding:1rem;color:#e6f6ff}.chat-message--user{background:linear-gradient(145deg,rgb(33 119 171 / 55%),rgb(7 42 66 / 88%))}.chat-message strong,.confirm-card strong{font-size:.92rem;line-height:1.4}.base-fields{display:flex;flex-wrap:wrap;gap:.35rem}.base-fields span,.file-chip{border:1px solid rgb(116 210 255 / 32%);border-radius:99px;padding:.25rem .48rem;color:#c9edff;font-size:.68rem}.flow-arrow{color:#65c9ff;font-size:1.4rem}.confirm-card button{border:0;border-radius:.42rem;background:#65c9ff;padding:.55rem;color:#062038;font-weight:800;opacity:.86}.calendar-layout{display:grid;gap:.8rem}.date-row{display:grid;grid-template-columns:repeat(6,1fr);gap:.45rem}.date-row article{display:grid;gap:.18rem;min-height:7rem;border:1px solid rgb(182 219 240 / 20%);border-radius:.55rem;padding:.7rem;background:rgb(5 25 40 / 68%)}.date-row small{color:#8ab0c6;font-size:.66rem;font-weight:750}.date-row strong{font-size:2rem;letter-spacing:-.06em}.date-row span{color:#bbd2df;font-size:.72rem}.date-row .workday{border-color:rgb(101 201 255 / 48%)}.date-row .holiday{border-color:rgb(245 185 66 / 70%);background:rgb(101 70 20 / 24%)}.date-row .weekend{opacity:.58}.calendar-result{display:flex;align-items:baseline;justify-content:space-between;gap:.8rem;border-left:3px solid #65c9ff;padding:.55rem .8rem;background:rgb(6 37 57 / 74%)}.calendar-result span{color:#b8ccda}.calendar-result strong{color:#65c9ff;font-size:1.35rem}.calendar-result small{color:#9ab3c2}.claim-layout{display:grid;grid-template-columns:minmax(11rem,.55fr) minmax(16rem,1.25fr);gap:1rem;align-items:center}.claim-layout>img{width:min(100%,16rem);max-height:19rem;justify-self:center;object-fit:contain;border-radius:.45rem;background:#f8fafc;box-shadow:0 .8rem 2rem rgb(0 0 0 / 28%)}.claim-flow{display:grid;gap:.65rem}.claim-flow a{justify-self:start;border:1px solid #65c9ff;border-radius:.5rem;background:#65c9ff;padding:.55rem .75rem;color:#062038;font-size:.82rem;font-weight:800;text-decoration:none}.live-note{color:#99b5c6;line-height:1.35}@media (max-width:850px){.sign-in-layout,.claim-layout{grid-template-columns:1fr}.leave-flow-layout{grid-template-columns:1fr;gap:.45rem}.flow-arrow{justify-self:center;transform:rotate(90deg)}.date-row{overflow:auto}.date-row article{min-width:4.9rem}.calendar-result{align-items:flex-start;flex-direction:column;gap:.25rem}}
.inline-calendar{grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:.35rem;border-top:1px solid rgb(182 219 240 / 18%);padding-top:.7rem;color:#afc5d1;font-size:.68rem}.inline-calendar span{border:1px solid rgb(182 219 240 / 20%);border-radius:99px;padding:.26rem .45rem}.inline-calendar b{color:#dff4ff}.inline-calendar .holiday{border-color:rgb(245 185 66 / 65%);color:#f5d590}.inline-calendar .weekend{opacity:.6}.inline-calendar strong{margin-left:auto;color:#65c9ff}.evidence-strip{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,1fr);gap:.45rem;margin:0}.evidence-strip figure,.claim-evidence{display:grid;gap:.25rem;margin:0}.evidence-strip img,.claim-evidence img{width:100%;border:1px solid rgb(182 219 240 / 24%);border-radius:.35rem;background:#fff}.evidence-strip figcaption,.claim-evidence figcaption{color:#8faeba;font-size:.62rem}.claim-evidence{grid-column:1/-1}.claim-evidence img{max-height:8.5rem;object-fit:contain}
.evidence-strip figure{height:9rem;overflow:hidden}.evidence-strip figure img{height:7.7rem;object-fit:cover}.evidence-input img{object-position:50% 91%}.evidence-confirm img{object-position:50% 49%}.evidence-success img{object-position:50% 58%}.claim-evidence{overflow:hidden}.claim-evidence img{height:12rem;max-height:none!important;object-fit:cover;object-position:50% 86%}.focus-evidence{grid-column:1/-1;margin:0}.focus-evidence img{width:100%;max-height:24rem;object-fit:contain;border-radius:.45rem;background:#fff}.focus-evidence figcaption{color:#8faeba;font-size:.7rem}
.claim-layout--focus{grid-template-columns:1fr}.claim-outcomes{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.45rem;margin:0}.claim-outcomes figure{display:grid;gap:.25rem;min-width:0;margin:0}.claim-outcomes img{width:100%;height:8rem;object-fit:cover;object-position:50% 70%;border:1px solid rgb(182 219 240 / 24%);border-radius:.35rem;background:white}.claim-outcomes figcaption{color:#8faeba;font-size:.62rem}
.evidence-dialog{width:min(96vw,110rem);height:min(94dvh,64rem);margin:auto;border:1px solid rgb(101 201 255 / 72%);border-radius:.8rem;background:#061522;color:#ecf8ff;box-shadow:0 2rem 8rem rgb(0 0 0 / 70%);padding:clamp(.8rem,1.4vw,1.3rem)}.evidence-dialog::backdrop{background:rgb(0 7 13 / 82%);backdrop-filter:blur(.25rem)}.evidence-dialog header{display:grid;gap:.18rem;margin-bottom:.7rem}.evidence-dialog header span{color:#65c9ff;font-size:.66rem;font-weight:800;letter-spacing:.14em}.evidence-dialog header strong{font-size:clamp(1.1rem,2vw,1.7rem)}.evidence-dialog header small{color:#a9c2d1}.evidence-dialog figure{display:grid;height:calc(100% - 4.8rem);margin:0;grid-template-rows:minmax(0,1fr) auto;gap:.35rem}.evidence-dialog figure img{width:100%;height:100%;min-height:0;object-fit:contain;background:white;border-radius:.3rem}.evidence-dialog figcaption{color:#8faeba;font-size:.68rem}
</style>
