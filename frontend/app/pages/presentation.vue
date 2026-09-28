<script setup lang="ts">
import QRCode from 'qrcode'

definePageMeta({ layout: false })

type Scene = {
  id: string
  label: string
  time: string
  cue: string
  eyebrow: string
  title: string
  accent: string
  summary: string
  cards: Array<[string, string]>
  assumptions?: string[]
}

const scenes: Scene[] = [
  {
    id: '01A', label: 'Opening', time: '00:00', cue: 'Start with the workflow, then show the working product',
    eyebrow: 'SCMP AI Engineer assignment', title: 'Internal requests,', accent: 'guided from one place',
    summary: 'A working self-service prototype for Leave Applications and Staff Claims. Today’s walkthrough follows the experience from request to approval.',
    cards: [['One starting point', 'Employees begin Leave and Staff Claim requests in the same guided conversation.'], ['Clear ownership', 'HR reviews Leave requests and Finance reviews Staff Claims.'], ['Visible decisions', 'Requests, approvals and updates remain easy to follow.']],
    assumptions: ['All people, requests and records in this demo are fictional.', 'Google sign-in is mocked so each role can be demonstrated safely.', 'HR and Finance keep the final decision for every request.'],
  },
  {
    id: '01B', label: 'Operating model', time: '00:45', cue: 'Explain the SOP before opening the live product',
    eyebrow: 'Operating model', title: 'One chat,', accent: 'one accountable route',
    summary: 'A single familiar chat interface replaces separate request forms, while structured confirmation and routing preserve the required controls.',
    cards: [['Employee', 'Starts a Leave or Claim request in the shared conversation and confirms before submission.'], ['HR / Finance', 'Reviews only work assigned to them, with context, and makes the final decision.'], ['Reference data', 'Roles, routing, leave entitlements and department claim budgets are preconfigured demo data.']],
  },
  {
    id: '01C', label: 'Demo rules', time: '02:00', cue: 'Set the policy boundary: context supports, but does not replace, judgement',
    eyebrow: 'Scope and safeguards', title: 'Guided by rules,', accent: 'decided by people',
    summary: 'The prototype validates the request journey and exposes useful context, while HR and Finance retain the business decision.',
    cards: [['Leave', 'Annual, Sick, Personal and Unpaid. Annual and Sick have per-user yearly entitlements.'], ['Claim', 'Travel, Meal, Equipment, Training and Other. Department budgets are visible as context.'], ['Verification', 'Signed-in user, required fields, sensible dates, working days, HKD and explicit confirmation.']],
  },
  {
    id: '01D', label: 'Demo roles', time: '02:45', cue: 'Introduce the people once, so the live journey is easy to follow',
    eyebrow: 'Fictional demo identities', title: 'The right people,', accent: 'on the right work',
    summary: 'Each request carries its assigned approver. The role map makes separation of duties visible without making the UI complex.',
    cards: [['Demo journey', 'Amy and Ben (IT), Daniel (HR), and Cathy (HR) are the people used in this walkthrough.'], ['Leave reviewers', 'Cathy reviews IT Leave; Helen reviews Leave for HR colleagues.'], ['Claim reviewer', 'Eva, Finance Manager, reviews all Staff Claims. Cathy also demonstrates reviewer permissions.']],
  },
  {
    id: '02A', label: 'Mock sign-in', time: '03:25', cue: 'Show the fictional role selector, then explain why it is clearly marked MOCK',
    eyebrow: 'Employee journey · 1 of 4', title: 'Start safely,', accent: 'with a fictional role',
    summary: 'The demonstration uses fictional identities to make Employee, HR Approver and Finance Approver journeys visible without a real account.',
    cards: [],
  },
  {
    id: '02B', label: 'Leave + calendar', time: '03:45', cue: 'Show input, returned details, explicit confirmation and the three-working-day calculation',
    eyebrow: 'Employee journey · 2 of 4', title: 'From one message,', accent: 'to a clear request',
    summary: 'Amy asks for leave in natural language. The assistant returns the key request information, and Amy reviews it before submission.',
    cards: [],
  },
  {
    id: '02C', label: 'Claim attachment', time: '04:30', cue: 'Show the original fictional receipt and the Claim conversation',
    eyebrow: 'Employee journey · 3 of 4', title: 'A claim begins', accent: 'with the original receipt',
    summary: 'The attachment and natural-language instruction remain in the same conversation, ready for an explicit confirmation.',
    cards: [],
  },
  {
    id: '02D', label: 'Live demo', time: '04:55', cue: 'Use Claim upload for the prepared live interaction; other scenarios are available only if time permits',
    eyebrow: 'Employee journey · 4 of 4', title: 'A controlled,', accent: 'real interaction',
    summary: 'The presenter selects the scenario on iPad. For time, the prepared Claim attachment flow is the recommended live use case.',
    cards: [],
  },
  {
    id: '03A', label: 'Bell inbox', time: '05:30', cue: 'The reviewer starts from the top notification bell',
    eyebrow: 'Approver journey · 1 of 5', title: 'The bell opens', accent: 'a focused review chat',
    summary: 'Robin opens the bell and receives one dedicated fictional Leave request. No unrelated work needs to be skipped.',
    cards: [],
  },
  {
    id: '03B', label: 'Approve', time: '05:45', cue: 'Show the reviewer context and the explicit approval step',
    eyebrow: 'Approver journey · 2 of 5', title: 'Context informs,', accent: 'a person approves',
    summary: 'The reviewer reads the request, may add a note, and confirms the approval as a separate human decision.',
    cards: [],
  },
  {
    id: '03C', label: 'Reject', time: '06:05', cue: 'Show the equivalent rejection outcome with a reason',
    eyebrow: 'Approver journey · 3 of 5', title: 'The same control', accent: 'supports a reasoned rejection',
    summary: 'The reviewer can reject instead, with a clear note returned to the employee. The assistant does not decide the outcome.',
    cards: [],
  },
  {
    id: '03D', label: 'Employee update', time: '06:20', cue: 'Return to the employee and open the decision from the bell',
    eyebrow: 'Approver journey · 4 of 5', title: 'The decision returns', accent: 'to the original employee',
    summary: 'Mia signs in again and uses the same notification bell to see the recorded decision and reviewer note.',
    cards: [],
  },
  {
    id: '03E', label: 'Live demo', time: '06:35', cue: 'Run the isolated bell-to-decision journey once, then continue to engineering',
    eyebrow: 'Approver journey · 5 of 5', title: 'A controlled,', accent: 'live decision',
    summary: 'This live fixture is separate from the Scene 02 request data: Robin approves Mia’s dedicated fictional Leave request.',
    cards: [],
  },
  {
    id: '04A', label: 'Architecture', time: '07:20', cue: 'Move from the user journey to the technical boundaries behind it',
    eyebrow: 'Engineering draft · 1 of 4', title: 'One product,', accent: 'four clear boundaries',
    summary: 'The working prototype deliberately separates the user experience, application rules, persistent records and external integration.',
    cards: [['Experience', 'Nuxt and Vue provide the role-aware chat, inbox and notification interface.'], ['Application rules', 'FastAPI validates requests, routes work and enforces explicit confirmation.'], ['Records & integration', 'SQLite persists the audit trail; a mock API represents a controlled external hand-off.']],
  },
  {
    id: '04B', label: 'LLM controls', time: '07:45', cue: 'Explain what the LLM does and, equally importantly, what it cannot do',
    eyebrow: 'Engineering draft · 2 of 4', title: 'LLM for understanding,', accent: 'rules for control',
    summary: 'Natural language and receipt content are interpreted into structured fields, but deterministic services decide whether a request is valid and where it goes.',
    cards: [['LLM assists', 'Extract intent, identify missing information and propose structured request details.'], ['Rules decide', 'Identity, dates, working days, currency, mandatory fields and assignment are validated in code.'], ['People approve', 'No model output can submit, approve or reject without the relevant user confirmation.']],
  },
  {
    id: '04C', label: 'Data & audit', time: '08:10', cue: 'Connect every visible decision to a record that can be explained later',
    eyebrow: 'Engineering draft · 3 of 4', title: 'Every decision,', accent: 'keeps its evidence',
    summary: 'The same request carries its attachment, structured data, assigned approver, reviewer note and decision outcome through the workflow.',
    cards: [['Request history', 'Conversation, confirmation and submission status remain linked rather than copied between screens.'], ['Separation of duties', 'Approver assignment is stored with the request, limiting work to the responsible role.'], ['Traceability', 'Decision notes and mock external references make the demonstration auditable end to end.']],
  },
  {
    id: '04D', label: 'Quality gates', time: '08:35', cue: 'Close the engineering view with how the workflow is protected from regression',
    eyebrow: 'Engineering draft · 4 of 4', title: 'A demo should be', accent: 'repeatable',
    summary: 'The presentation fixtures are isolated, resettable and exercised alongside backend, frontend and browser-level checks.',
    cards: [['Backend tests', 'Validate routing, entitlement rules, claim handling and dedicated presentation fixtures.'], ['Frontend checks', 'Linting and TypeScript typecheck keep the client contract explicit.'], ['Browser journey', 'Automated capture and live scripts verify sign-in, bells, decisions and employee notification.']],
  },
  {
    id: '05A', label: 'Dashboard', time: '09:00', cue: 'Start the future view with visibility before adding automation',
    eyebrow: 'Roadmap draft · 1 of 4', title: 'A dashboard,', accent: 'for visible work',
    summary: 'LLM-assisted development can accelerate a first dashboard from structured request data, but production still needs agreed metrics, role access and quality checks.',
    cards: [['Ask in plain language', '“Show my team’s Leave requests waiting more than 3 days, grouped by approver.”'], ['Dashboard returns', 'A filtered queue: request count, ageing, assigned reviewer and links to the existing request records.'], ['Control boundary', 'The question selects a read-only view; role access and the source-of-truth records stay unchanged.']],
  },
  {
    id: '05B', label: 'JEV signals', time: '09:25', cue: 'Frame JEV as explainable decision support, never an approval engine',
    eyebrow: 'Roadmap draft · 2 of 4', title: 'Decision support,', accent: 'not auto-decision',
    summary: 'Jev can answer a closed, explainable triage question over policy, balance, budget and supporting evidence before the reviewer decides.',
    cards: [['Give Jev', 'Leave dates, entitlement balance, public-holiday calculation, policy excerpt and attached evidence.'], ['Jev returns', '“Needs clarification” — receipt date conflicts with the request date. Confidence: high. Evidence: receipt says 20 Sep; request says 22 Sep.'], ['Reviewer confirms', 'The approver sees the evidence, asks for clarification or continues to approve/reject. Jev cannot submit the decision.']],
  },
  {
    id: '05C', label: 'Company chat', time: '09:50', cue: 'Describe meeting employees where they already work, without rebuilding the workflow UI',
    eyebrow: 'Roadmap draft · 3 of 4', title: 'Use the company chat,', accent: 'keep the controls',
    summary: 'The next interface could be a company chat platform such as Teams or Slack, while this service remains the controlled system of record.',
    cards: [['Chat entry point', 'Employees ask or receive status in a familiar company chat thread.'], ['Secure hand-off', 'Sign-in and deep links open the existing confirmation or reviewer decision screen when action is needed.'], ['Same controls', 'Role access, explicit confirmation, audit history and backend validation remain in this application.']],
  },
  {
    id: '05D', label: 'Governed rollout', time: '10:15', cue: 'Finish with a practical sequence from prototype to controlled adoption',
    eyebrow: 'Roadmap draft · 4 of 4', title: 'Adopt in stages,', accent: 'measure each one',
    summary: 'The safest next step is a narrow pilot with enterprise identity, policy owners, measurement and explicit rollout gates.',
    cards: [['1 · Pilot', 'One request type, limited users and clear operational ownership.'], ['2 · Measure', 'Track completion, exception rate, turnaround and reviewer feedback.'], ['3 · Expand', 'Add dashboard, Jev triage and company-chat entry points only after each control is proven.']],
  },
]

const currentSceneIndex = ref(0)
const currentScene = computed(() => scenes[currentSceneIndex.value]!)
const approverView = computed(() => ['03A', '03B', '03C', '03D'].indexOf(currentScene.value.id))
const isFullLiveDemo = computed(() => currentScene.value.id === '03E')
const presenterQr = ref('')
const presenterUrl = ref('')
const demoCommand = ref<'play' | 'pause' | 'restart' | 'seek' | 'complete'>('pause')
const demoTime = ref(0)
const demoRevision = ref(0)
const config = useRuntimeConfig()
let syncTimer: number | undefined

async function refreshSharedScene() {
  try {
    const state = await $fetch<{ sceneIndex: number, demoCommand: typeof demoCommand.value, demoTime: number, revision: number }>('/api/presentation/state')
    if (Number.isInteger(state.sceneIndex) && state.sceneIndex >= 0 && state.sceneIndex < scenes.length) {
      currentSceneIndex.value = state.sceneIndex
    }
    demoCommand.value = state.demoCommand
    demoTime.value = state.demoTime
    demoRevision.value = state.revision
  } catch {
    // The showcase remains usable locally when its optional presenter controller is unavailable.
  }
}

async function publishSharedScene() {
  try {
    await $fetch('/api/presentation/state', {
      method: 'PUT',
      body: { sceneIndex: currentSceneIndex.value },
    })
  } catch {
    // Keep keyboard and rail navigation responsive even if a network drops during rehearsal.
  }
}

async function finishLiveDemo() {
  try {
    await $fetch('/api/presentation/state', { method: 'PUT', body: { demoCommand: 'complete' } })
  } catch {
    // The completed UI remains visible even if the optional controller connection drops.
  }
}

function goToScene(index: number) {
  currentSceneIndex.value = Math.min(Math.max(index, 0), scenes.length - 1)
  void publishSharedScene()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    goToScene(currentSceneIndex.value + 1)
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    goToScene(currentSceneIndex.value - 1)
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)
  void refreshSharedScene()
  syncTimer = window.setInterval(() => void refreshSharedScene(), 500)
  const isLanAddress = /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(window.location.hostname)
  const detected = isLanAddress ? null : await $fetch<{ origin: string }>('/api/presentation/origin').catch(() => null)
  presenterUrl.value = `${config.public.presentationOrigin || (isLanAddress ? window.location.origin : detected?.origin || window.location.origin)}/presenter`
  void QRCode.toDataURL(presenterUrl.value, { width: 180, margin: 1, color: { dark: '#06101c', light: '#f5fbff' } }).then((url) => {
    presenterQr.value = url
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (syncTimer) window.clearInterval(syncTimer)
})
</script>

<template>
  <main class="presentation-shell">
    <div class="presentation-grain" aria-hidden="true" />

    <header class="presentation-header">
      <NuxtLink class="presentation-mark" to="/presentation" aria-label="Presentation home">
        <span class="presentation-mark-dot" />
        <span>Internal Operations AI Assistant</span>
      </NuxtLink>
      <span class="presentation-state">Presentation workspace</span>
    </header>

    <section class="presentation-stage" aria-label="Presentation stage">
      <div v-if="!isFullLiveDemo" class="presentation-stage-topline">
        <span>Scene {{ currentScene.id }}</span>
        <span>{{ currentScene.time }}</span>
      </div>

      <Transition name="scene" mode="out-in">
        <div :key="currentScene.id" class="opening-scene" :class="{ 'opening-scene--employee': currentScene.id.startsWith('02'), 'opening-scene--evidence': ['02A', '02C', '03A', '03B', '03C', '03D'].includes(currentScene.id), 'opening-scene--live': isFullLiveDemo }">
          <template v-if="currentScene.id !== '02D' && !isFullLiveDemo && !['02A', '02C', '03A', '03B', '03C', '03D'].includes(currentScene.id)">
            <p class="presentation-kicker">{{ currentScene.eyebrow }}</p>
            <h1>{{ currentScene.title }}<br><span>{{ currentScene.accent }}</span></h1>
            <p class="opening-summary">{{ currentScene.summary }}</p>
          </template>

          <div v-if="currentScene.id === '01B'" class="process-flow" aria-label="Request and approval process">
            <div class="process-node">
              <span class="process-step">01</span><strong>Describe</strong><small>Employee starts naturally in one chat</small>
            </div>
            <span class="process-arrow" aria-hidden="true">→</span>
            <div class="process-node process-node--accent">
              <span class="process-step">02</span><strong>Complete</strong><small>LLM asks only for missing details</small>
            </div>
            <span class="process-arrow" aria-hidden="true">→</span>
            <div class="process-node">
              <span class="process-step">03</span><strong>Confirm</strong><small>Review the structured request card</small>
            </div>
            <span class="process-arrow" aria-hidden="true">→</span>
            <div class="process-node">
              <span class="process-step">04</span><strong>Route &amp; decide</strong><small>Leave to HR · Claim to Finance</small>
            </div>
          </div>

          <div v-else-if="currentScene.id === '01C'" class="rules-dashboard" aria-label="Demo rules">
            <section class="rule-count"><span>Leave types</span><strong>4</strong><small>Annual · Sick · Personal · Unpaid</small></section>
            <section class="rule-count"><span>Claim types</span><strong>5</strong><small>Travel · Meal · Equipment · Training · Other</small></section>
            <section class="human-gate"><span>Final control</span><strong>Human in<br><em>the loop</em></strong><small>Context informs. It does not auto-approve or block.</small></section>
            <section class="rule-checks"><span>Checked before submission</span><div><b>Identity</b><b>Required fields</b><b>Dates &amp; working days</b><b>HKD claim currency</b><b>Explicit confirmation</b></div></section>
            <section class="rule-details" aria-label="Additional decision context">
              <span>Additional decision context</span>
              <div><b>Leave:</b> Annual / Sick balance and team overlap</div>
              <div><b>Claims:</b> Department yearly budget status</div>
              <div><b>Approval:</b> Assigned reviewer and pending status required</div>
            </section>
          </div>

          <div v-else-if="currentScene.id === '01D'" class="role-map" aria-label="Demo role map">
            <div class="role-requesters">
              <span class="map-caption">People used in this walkthrough</span>
              <div class="person-row">
                <div class="person"><i>AL</i><strong>Amy</strong><small>IT · Employee</small></div>
                <div class="person"><i>BC</i><strong>Ben</strong><small>IT · Employee</small></div>
                <div class="person"><i>DW</i><strong>Daniel</strong><small>HR · Employee</small></div>
                <div class="person person--dual"><i>CN</i><strong>Cathy</strong><small>HR · Requester + reviewer</small></div>
              </div>
            </div>
            <div class="role-routes">
              <span>Leave requests</span><b>→</b><strong>HR reviewers: Cathy for IT · Helen for HR</strong>
              <span>Staff Claims</span><b>→</b><strong>Finance reviewer: Eva</strong>
            </div>
            <p class="role-map-note">Each request stores its assigned approver, so every reviewer sees only their allocated work.</p>
          </div>

          <PresentationEmployeeDemo
            v-else-if="['02A', '02B', '02C'].includes(currentScene.id)"
            :stage="currentScene.id === '02A' ? 'sign-in' : currentScene.id === '02B' ? 'leave-flow' : 'claim-upload'"
            :zoom="['02B', '02C'].includes(currentScene.id) ? demoTime : 0"
          />
          <PresentationLiveDemo
            v-else-if="currentScene.id === '02D'"
            :command="demoCommand"
            :scenario="demoTime"
            :revision="demoRevision"
            @complete="finishLiveDemo"
          />
          <PresentationApproverDemo v-else-if="approverView >= 0" :view="approverView" />
          <PresentationApprovalLiveDemo v-else-if="currentScene.id === '03E'" :command="demoCommand" :revision="demoRevision" @complete="finishLiveDemo" />

          <dl v-else class="opening-outcomes">
            <div v-for="([title, description], index) in currentScene.cards" :key="title" class="opening-outcome">
            <dt>0{{ index + 1 }} <strong>{{ title }}</strong></dt>
            <dd>{{ description }}</dd>
            </div>
          </dl>

          <section v-if="currentScene.assumptions" class="opening-assumptions" aria-label="Demo assumptions">
            <p>Demo assumptions</p>
            <ul>
              <li v-for="assumption in currentScene.assumptions" :key="assumption">{{ assumption }}</li>
            </ul>
          </section>
        </div>
      </Transition>

      <div class="presentation-stage-corner presentation-stage-corner--top" aria-hidden="true" />
      <div class="presentation-stage-corner presentation-stage-corner--bottom" aria-hidden="true" />
      <aside v-if="currentScene.id === '01A' && presenterQr" class="presentation-qr" aria-label="Open private presenter controller">
        <img :src="presenterQr" alt="QR code for private presenter controller">
        <div><strong>Private controller</strong><span>Scan on iPad</span></div>
      </aside>
    </section>

  </main>
</template>

<style scoped>
.presentation-shell {
  --stage-blue: #58c5ff;
  --stage-ink: #06101c;
  --stage-muted: #92a6b8;
  --stage-line: rgb(166 204 229 / 19%);
  position: relative;
  display: grid;
  min-height: 100dvh;
  overflow: hidden;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr);
  gap: 0.85rem;
  padding: clamp(.75rem,1.35vw,1.25rem) clamp(.75rem,2.4vw,2.4rem);
  background:
    radial-gradient(circle at 54% 41%, rgb(23 86 126 / 22%), transparent 32rem),
    radial-gradient(circle at 88% 5%, rgb(59 175 230 / 14%), transparent 24rem),
    var(--stage-ink);
  color: #edf7ff;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.presentation-grain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.17;
  background-image: radial-gradient(rgb(255 255 255 / 32%) 0.55px, transparent 0.65px);
  background-size: 5px 5px;
  mask-image: linear-gradient(to bottom, black, transparent 82%);
}

.presentation-header,
.presentation-stage,
.presentation-rail,
.presentation-notes,
.presentation-controls {
  position: relative;
  z-index: 1;
}

.presentation-header {
  display: flex;
  grid-column: 1 / -1;
  align-items: center;
  justify-content: space-between;
  min-height: 2.25rem;
  border-bottom: 1px solid var(--stage-line);
  padding-bottom: 1rem;
  color: var(--stage-muted);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.presentation-mark {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  color: inherit;
  font-weight: 650;
  text-decoration: none;
}

.presentation-mark-dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: var(--stage-blue);
  box-shadow: 0 0 1.1rem rgb(88 197 255 / 72%);
}

.presentation-state { color: rgb(237 247 255 / 56%); }

.presentation-stage {
  grid-column: 1;
  display: flex;
  aspect-ratio: 16 / 9;
  width: min(100%, calc((100dvh - 5.4rem) * 16 / 9));
  align-self: center;
  justify-self: center;
  flex-direction: column;
  border: 1px solid rgb(190 225 245 / 32%);
  border-radius: 0.35rem;
  background:
    linear-gradient(135deg, rgb(255 255 255 / 5%) 25%, transparent 25%) 0 0 / 16px 16px,
    linear-gradient(315deg, rgb(255 255 255 / 4%) 25%, transparent 25%) 0 0 / 16px 16px,
    linear-gradient(140deg, rgb(20 84 121 / 58%), rgb(5 17 30 / 90%) 57%, rgb(3 12 21 / 96%));
  box-shadow: 0 2.25rem 6rem rgb(0 0 0 / 38%), inset 0 1px 0 rgb(255 255 255 / 10%);
}

.presentation-stage-topline {
  display: flex;
  justify-content: space-between;
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--stage-line);
  color: rgb(237 247 255 / 62%);
  font-size: 0.68rem;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.presentation-kicker {
  color: var(--stage-blue);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.presentation-note-rule {
  height: 0.7rem;
  border-radius: 99px;
  background: linear-gradient(90deg, rgb(220 243 255 / 65%), rgb(220 243 255 / 16%));
}

.opening-scene {
  display: grid;
  width: min(80%, 67rem);
  margin: auto;
  align-content: center;
  gap: clamp(1rem, 1.8vw, 1.65rem);
}

.opening-scene h1 {
  max-width: 20ch;
  margin: 0;
  color: #f6fbff;
  font-size: clamp(2.2rem, 4vw, 4.9rem);
  font-weight: 560;
  letter-spacing: -0.055em;
  line-height: 0.98;
}

.opening-scene h1 span { color: var(--stage-blue); }

.opening-summary {
  max-width: 52rem;
  margin: 0;
  color: rgb(237 247 255 / 72%);
  font-size: clamp(0.9rem, 1.12vw, 1.25rem);
  line-height: 1.55;
}

.opening-outcomes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  border-top: 1px solid var(--stage-line);
  border-bottom: 1px solid var(--stage-line);
}

.opening-outcome { min-height: 8.5rem; padding: 1.35rem 1.35rem 1.25rem 0; }
.opening-outcome + .opening-outcome { border-left: 1px solid var(--stage-line); padding-left: 1.35rem; }
.opening-outcome dt { color: var(--stage-blue); font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; }
.opening-outcome dt strong { margin-left: 0.4rem; color: #eaf6ff; font-size: 0.98rem; font-weight: 700; }
.opening-outcome dd { margin: 0.7rem 0 0; color: rgb(237 247 255 / 74%); font-size: clamp(0.88rem, 1.08vw, 1.12rem); line-height: 1.52; }

.opening-assumptions { max-width: 52rem; }
.opening-assumptions > p { margin: 0 0 0.45rem; color: rgb(237 247 255 / 86%); font-size: 0.76rem; font-weight: 650; }
.opening-assumptions ul { display: flex; flex-wrap: wrap; gap: 0.35rem 1rem; margin: 0; padding: 0; color: rgb(237 247 255 / 52%); font-size: 0.72rem; line-height: 1.45; list-style: none; }
.opening-assumptions li::before { margin-right: 0.42rem; color: var(--stage-blue); content: '·'; }

.process-flow { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr auto 1fr; align-items: stretch; gap: 0.65rem; margin-top: 0.45rem; }
.process-node { display: grid; min-height: 8.75rem; align-content: space-between; border: 1px solid var(--stage-line); padding: 1rem; background: rgb(4 19 32 / 38%); }
.process-node--accent { border-color: rgb(88 197 255 / 58%); background: rgb(40 132 183 / 20%); box-shadow: inset 0 0 2.5rem rgb(60 180 238 / 8%); }
.process-step, .map-caption, .rule-count > span, .human-gate > span, .rule-checks > span { color: var(--stage-blue); font-size: 0.65rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }
.process-node strong { color: #f3fbff; font-size: clamp(1.1rem, 1.45vw, 1.45rem); font-weight: 590; }
.process-node small { color: rgb(237 247 255 / 57%); font-size: 0.72rem; line-height: 1.4; }
.process-arrow { align-self: center; color: var(--stage-blue); font-size: 1.25rem; }

.rules-dashboard { display: grid; grid-template-columns: 1fr 1fr 1.2fr; gap: 0.65rem; }
.rule-count, .human-gate, .rule-checks { border: 1px solid var(--stage-line); background: rgb(4 19 32 / 38%); padding: 1rem 1.1rem; }
.rule-count { display: grid; min-height: 10rem; align-content: space-between; }
.rule-count strong { color: #f3fbff; font-size: clamp(3.5rem, 5vw, 5.9rem); font-weight: 520; letter-spacing: -0.08em; line-height: 0.8; }
.rule-count small, .human-gate small { color: rgb(237 247 255 / 57%); font-size: 0.7rem; line-height: 1.4; }
.human-gate { display: grid; min-height: 10rem; align-content: space-between; border-color: rgb(88 197 255 / 55%); background: radial-gradient(circle at 70% 45%, rgb(88 197 255 / 18%), transparent 8rem), rgb(7 35 54 / 55%); }
.human-gate strong { color: #f3fbff; font-size: clamp(1.65rem, 2.3vw, 2.55rem); font-weight: 550; letter-spacing: -0.045em; line-height: 0.9; }
.human-gate em { color: var(--stage-blue); font-style: normal; }
.rule-checks { grid-column: 1 / -1; display: grid; grid-template-columns: 10rem 1fr; align-items: center; gap: 1rem; }
.rule-checks div { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.rule-checks b { border: 1px solid rgb(166 204 229 / 24%); border-radius: 99px; padding: 0.38rem 0.55rem; color: rgb(237 247 255 / 75%); font-size: 0.67rem; font-weight: 550; }
.rule-details { grid-column: 1 / -1; display: grid; grid-template-columns: 10rem repeat(3, minmax(0, 1fr)); gap: .6rem; align-items: center; color: rgb(237 247 255 / 54%); font-size: .62rem; line-height: 1.35; }.rule-details > span { color: var(--stage-blue); font-size: .65rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }.rule-details div { border-left: 1px solid var(--stage-line); padding-left: .6rem; }.rule-details b { color: rgb(237 247 255 / 82%); font-weight: 650; }

.role-map { display: grid; gap: 1.05rem; }
.role-requesters { border: 1px solid var(--stage-line); padding: 1rem 1.1rem; background: rgb(4 19 32 / 38%); }
.person-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.8rem; margin-top: 0.75rem; }
.person { display: grid; grid-template-columns: 2.2rem 1fr; column-gap: 0.6rem; align-items: center; }
.person i { display: grid; width: 2.2rem; height: 2.2rem; grid-row: span 2; place-items: center; border-radius: 50%; background: rgb(176 225 249 / 12%); color: var(--stage-blue); font-size: 0.62rem; font-style: normal; font-weight: 700; }
.person strong { color: #f3fbff; font-size: 0.82rem; }
.person small { color: rgb(237 247 255 / 54%); font-size: 0.62rem; line-height: 1.35; }
.person--dual i { background: var(--stage-blue); color: #052037; }
.role-routes { display: grid; grid-template-columns: 8.5rem 1.5rem 1fr; align-items: center; row-gap: 0.5rem; padding: 0.2rem 0.5rem; }
.role-routes span { color: rgb(237 247 255 / 58%); font-size: 0.72rem; }
.role-routes b { color: var(--stage-blue); font-size: 1.05rem; }
.role-routes strong { color: #f3fbff; font-size: 0.8rem; font-weight: 550; }
.role-map-note { margin: 0; padding-top: 0.7rem; border-top: 1px solid var(--stage-line); color: rgb(237 247 255 / 53%); font-size: 0.73rem; line-height: 1.45; }

.scene-enter-active,
.scene-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.scene-enter-from { opacity: 0; transform: translateY(0.45rem); }
.scene-leave-to { opacity: 0; transform: translateY(-0.35rem); }

.presentation-stage-corner {
  position: absolute;
  right: 1rem;
  width: 1.1rem;
  height: 1.1rem;
  border-right: 1px solid var(--stage-blue);
}
.presentation-stage-corner--top { top: 3.7rem; border-top: 1px solid var(--stage-blue); }
.presentation-stage-corner--bottom { bottom: 1rem; border-bottom: 1px solid var(--stage-blue); }
.presentation-qr { position: absolute; right: 1.15rem; bottom: 1.15rem; display: flex; align-items: center; gap: .4rem; border: 1px solid rgb(190 225 245 / 34%); border-radius: .28rem; padding: .3rem; background: rgb(3 13 22 / 88%); box-shadow: 0 .8rem 2rem rgb(0 0 0 / 28%); }.presentation-qr img { width: 3rem; height: 3rem; border-radius: .1rem; }.presentation-qr div { display: grid; gap: .12rem; }.presentation-qr strong { color: #eef8ff; font-size: .56rem; }.presentation-qr span { color: rgb(237 247 255 / 55%); font-size: .5rem; }

.presentation-rail {
  grid-column: 1;
  width: min(100%, 88rem);
  justify-self: center;
  align-self: start;
}

.presentation-rail ol {
  display: grid;
  grid-template-columns: repeat(20, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.presentation-rail button {
  position: relative;
  display: grid;
  width: 100%;
  grid-template-columns: 1fr;
  gap: 0.2rem;
  border: 0;
  border-top: 1px solid var(--stage-line);
  padding: 0.75rem 0.5rem 0.25rem;
  background: transparent;
  color: var(--stage-muted);
  text-align: left;
  cursor: pointer;
}

.presentation-rail-number { font-size: 0.65rem; font-variant-numeric: tabular-nums; }
.presentation-rail-label { overflow: hidden; font-size: 0.7rem; text-overflow: ellipsis; white-space: nowrap; }
.presentation-rail li:not(:last-child) button { border-right: 1px solid rgb(166 204 229 / 10%); }
.presentation-rail .is-current button { border-top-color: var(--stage-blue); color: #f3fbff; }
.presentation-rail .is-current button::before {
  position: absolute;
  top: -0.25rem;
  left: 0.5rem;
  width: 0.42rem;
  height: 0.42rem;
  border-radius: 50%;
  background: var(--stage-blue);
  box-shadow: 0 0 0.85rem rgb(88 197 255 / 75%);
  content: '';
}
.presentation-rail .is-current .presentation-rail-number { color: var(--stage-blue); }

.presentation-notes {
  display: grid;
  width: min(100%, 88rem);
  grid-column: 1;
  grid-template-columns: 9rem minmax(0, 1fr) auto;
  align-items: center;
  justify-self: center;
  gap: 1rem;
  padding: 0.85rem 0;
  border-top: 1px solid var(--stage-line);
}

.presentation-note-rule { width: 100%; margin: 0; opacity: 0.56; }
.presentation-note-rule--short { display: none; }
.presentation-notes-status { color: rgb(237 247 255 / 36%); font-size: 0.7rem; line-height: 1.45; white-space: nowrap; }

.presentation-controls {
  display: flex;
  grid-column: 1 / -1;
  justify-content: center;
  gap: clamp(0.85rem, 3vw, 2.5rem);
  border-top: 1px solid var(--stage-line);
  padding-top: 0.85rem;
  color: rgb(237 247 255 / 42%);
  font-size: 0.67rem;
  letter-spacing: 0.04em;
}

@media (max-width: 820px) {
  .presentation-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto auto auto auto;
    gap: 0.75rem;
    padding: 1rem;
  }
  .presentation-stage { grid-column: 1; width: 100%; }
  .presentation-rail { grid-column: 1; align-self: auto; overflow-x: auto; }
  .presentation-rail ol { display: flex; min-width: max-content; }
  .presentation-rail button { min-width: 8.5rem; }
  .presentation-notes { grid-column: 1; grid-template-columns: 1fr; gap: 0.5rem; }
  .presentation-notes-status { white-space: normal; }
  .presentation-controls { justify-content: flex-start; overflow-x: auto; white-space: nowrap; }
  .opening-scene { width: min(88%, 40rem); }
  .opening-outcomes { grid-template-columns: 1fr; }
  .opening-outcome + .opening-outcome { border-top: 1px solid var(--stage-line); border-left: 0; padding-left: 0; }
  .process-flow { grid-template-columns: 1fr; }
  .process-arrow { display: none; }
  .rules-dashboard { grid-template-columns: 1fr; }
  .rule-checks { grid-column: auto; grid-template-columns: 1fr; }
  .rule-details { grid-column: auto; grid-template-columns: 1fr; }
  .rule-details div { border-top: 1px solid var(--stage-line); border-left: 0; padding: .4rem 0 0; }
  .person-row { grid-template-columns: repeat(2, 1fr); }
  .role-routes { grid-template-columns: 6rem 1.5rem 1fr; }
  .presentation-qr { right: .75rem; bottom: .75rem; }
}
.opening-scene--employee{width:min(88%,74rem);gap:clamp(.65rem,1.15vw,1rem)}.opening-scene--employee h1{font-size:clamp(1.8rem,3.25vw,3.65rem)}.opening-scene--employee .opening-summary{font-size:clamp(.78rem,.95vw,1rem);line-height:1.4}.opening-scene--evidence{width:min(88%,74rem);height:calc(100% - 2.75rem);align-content:center}.opening-scene--evidence :deep(.employee-demo),.opening-scene--evidence :deep(.approver-demo){max-height:100%}.opening-scene--employee:has(.live-demo),.opening-scene--live{width:94%;height:100%;align-content:stretch}.opening-scene--live :deep(.approval-live){width:100%;height:100%;max-height:none}
</style>
