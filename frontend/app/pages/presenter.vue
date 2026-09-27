<script setup lang="ts">
definePageMeta({ layout: false })

type PresenterScene = {
  id: string
  label: string
  time: string
  talk: string
  tip: string
  talkZh: string
  tipZh: string
}

const scenes: PresenterScene[] = [
  { id: '01A', label: 'Opening', time: '00:00', talk: 'Good afternoon, and thank you for the opportunity. This is a working self-service prototype for Leave Applications and Staff Claims. Rather than showing every feature, I will follow the request journey from an employee’s first message through to the right approver’s decision. The solution gives employees one starting point, gives HR and Finance clear ownership of approval work, and keeps each request and decision visible. I will first show the operating model behind the journey, then start with the employee experience.', tip: 'All people and records are fictional. Google sign-in is mocked to demonstrate roles safely; HR and Finance always keep the final decision.', talkZh: '各位好，感謝給我這次機會。這是一個可運行的自助服務原型，處理請假申請和員工報銷。我不會逐一展示所有功能，而是會由員工提出第一個訊息開始，跟隨整個申請直到正確的審批人作出決定。這個方案為員工提供一個統一入口，同時讓 HR 和 Finance 清楚擁有各自的審批工作，並讓每一個申請和決定都容易追蹤。我會先介紹流程背後的運作模式，然後由員工體驗開始。', tipZh: '人物和紀錄全部為虛構資料；Google 登入為 mock，用來安全展示不同角色；HR 和 Finance 始終保留最終決定權。' },
  { id: '01B', label: 'Operating model', time: '00:45', talk: 'Every role starts from the same familiar chat interface, rather than switching to separate Leave and Claim forms. An employee describes what they need in natural language. The LLM understands the request and asks only for missing information. The employee reviews a structured confirmation card and explicitly submits it. The request is routed to the configured approver: HR for Leave, and Finance for Claims. The assigned reviewer sees only their work, reviews the context and makes the final decision.', tip: 'The LLM helps understanding and collection. Confirmation, validation, routing and approval remain deterministic controls.', talkZh: '所有角色都由同一個熟悉的 chat interface 開始，而不需要在獨立的請假和報銷表單之間切換。員工以自然語言描述需要；LLM 會理解申請，並只追問遺漏資料。員工檢查結構化確認卡後才明確提交。系統會把請假申請路由至 HR，而報銷申請則路由至 Finance。獲分配的審批人只會看到自己的工作，連同背景資料作出最終決定。', tipZh: 'LLM 協助理解和收集資料；確認、驗證、routing 和批核仍是確定性的控制。' },
  { id: '01C', label: 'Demo rules', time: '02:00', talk: 'To make the scope concrete, the prototype supports four Leave types: Annual, Sick, Personal and Unpaid, and five Claim types: Travel, Meal, Equipment, Training and Other. Annual and Sick Leave have per-user yearly entitlements, and every department has a yearly Claim budget. These values are shown as context to the reviewer. They do not automatically block a request or replace human judgement. Before submission, the application verifies identity, required fields, sensible dates, working days, HKD and explicit confirmation.', tip: 'Final approval remains a business decision.', talkZh: '為了讓範圍更具體，原型支援四種請假類型：Annual、Sick、Personal 和 Unpaid；亦支援五種報銷類型：Travel、Meal、Equipment、Training 和 Other。Annual 和 Sick 有個人年度配額，每個部門亦有年度報銷預算。這些數字只作審批背景，不會自動阻止申請或取代人手判斷。提交前系統會驗證身份、必需欄位、合理日期、工作日、HKD 和明確確認。', tipZh: '最終批核仍然是業務決定。' },
  { id: '01D', label: 'Demo roles', time: '02:45', talk: 'Before the live walkthrough, these are the fictional people used in the demo. Amy and Ben are IT employees, and Daniel is an HR employee. Cathy is the HR Business Partner for IT, so she reviews Leave from Amy and Ben. Helen is the HR Manager and reviews Leave for HR colleagues. Eva is the Finance Manager and reviews every Staff Claim. The important control is that each request carries its assigned approver, so reviewers see only their allocated work.', tip: 'Keep the explanation focused on routing and separation of duties.', talkZh: '在開始 live walkthrough 前，這裡是示範中出現的虛構人物。Amy 和 Ben 是 IT 員工，而 Daniel 是 HR 員工。Cathy 是支援 IT 的 HR Business Partner，因此她審批 Amy 和 Ben 的請假。Helen 是 HR Manager，審批 HR 同事的請假。Eva 是 Finance Manager，審批所有員工報銷。重要的控制是每個申請都帶有已分配的審批人，因此每位審批人只會看到自己的工作。', tipZh: '解說集中在 routing 和 separation of duties。' },
  { id: '02A', label: 'Mock sign-in', time: '03:25', talk: 'This is a clearly marked mock sign-in. It contains fictional accounts only and does not connect to Google. It lets me demonstrate the Employee, HR Approver and Finance Approver paths safely. In production, this boundary would be replaced by enterprise SSO and role mapping.', tip: 'Do not stay on the screen too long; the purpose is safe role switching, not authentication.', talkZh: '這是清楚標示的 mock sign-in，只包含虛構帳戶，亦不會連接 Google。它讓我可以安全展示 Employee、HR Approver 和 Finance Approver 的路徑。正式環境會以企業 SSO 和 role mapping 取代。', tipZh: '不用停留太久；重點是安全切換角色，不是展示登入功能。' },
  { id: '02B', label: 'Leave + calendar', time: '03:45', talk: 'Amy starts with one natural-language message. The assistant returns the essential request information and Amy confirms before submission. The same page also explains the date rule: National Day and the weekend are excluded, so 30 September through 5 October is three working days.', tip: 'Tell the story left to right, then point to the calendar chips below.', talkZh: 'Amy 先輸入自然語言訊息；assistant 回傳核心申請資料，Amy 確認後才提交。同一頁亦解釋日期規則：National Day 和週末不計，因此 9 月 30 日至 10 月 5 日是 3 個工作日。', tipZh: '由左至右講故事，然後指出下方日曆標籤。' },
  { id: '02C', label: 'Claim attachment', time: '04:30', talk: 'The original fictional receipt is attached in the same chat. Amy asks to create a Staff Claim, and the assistant prepares the details for confirmation. This is evidence of the file-based interaction before I open the controlled live demo.', tip: 'Show the receipt first, then the natural-language instruction.', talkZh: '原本的虛構收據在同一個 chat 內附上。Amy 請系統建立 Staff Claim，assistant 再準備資料讓她確認。這是我打開受控 live demo 前，檔案互動的證明。', tipZh: '先展示收據，然後展示自然語言指令。' },
  { id: '02D', label: 'Live demo', time: '04:55', talk: 'This is the controlled live-demo surface. I can select Claim attachment, Leave request, or Edit and cancel Leave from this iPad controller. For time, I will use Claim attachment only: attach the prepared receipt, ask for the Claim, and review the returned details. I can pause the next scripted step whenever we want to discuss the visible UI.', tip: 'Select Claim attachment, Start, then Pause only to stop the next scripted step; the visible UI stays available for questions.', talkZh: '這是受控的 live-demo 畫面。我可由 iPad controller 選擇 Claim attachment、Leave request 或 Edit and cancel Leave。為了時間，我只會使用 Claim attachment：上載預備好的收據、建立 Claim、檢查回傳資料。需要解說時可暫停下一個自動步驟，而畫面仍會保留給提問。', tipZh: '選擇 Claim attachment，再按 Start；Pause 只會停止下一個自動步驟，畫面仍可供解說。' },
  { id: '03A', label: 'Bell inbox', time: '05:30', talk: 'Robin is a dedicated fictional HR Approver for this walkthrough. The top notification bell starts a new inbox conversation and opens exactly one assigned Leave request. This fixture is isolated from Scene 02, so there is no unrelated request and no Skip action to explain.', tip: 'The bell creates the focused review conversation; use Next to move through the four evidence pages.', talkZh: 'Robin 是這個 walkthrough 專用的虛構 HR Approver。頂部通知鈴鐺會開啟新的 inbox conversation，並只顯示一個已分配的 Leave request。這組 fixture 與 Scene 02 完全隔離，因此沒有無關申請，也不需要解釋 Skip。', tipZh: '鈴鐺會建立聚焦的 review conversation；以 Next 逐頁展示四個 evidence pages。' },
  { id: '03B', label: 'Approve', time: '05:45', talk: 'Robin sees the Leave dates and reviewer context, can add an optional note, then explicitly confirms approval. The assistant helps present the assigned request, but the approval is a separate human action.', tip: 'Point out the deliberate two-step decision: Approve, then Confirm approve.', talkZh: 'Robin 會看到 Leave 日期和 reviewer context，可以加入可選備註，然後明確確認批准。assistant 協助呈現已分配申請，但批准是獨立的人手操作。', tipZh: '指出刻意設計的兩個步驟：Approve，然後 Confirm approve。' },
  { id: '03C', label: 'Reject', time: '06:05', talk: 'The same decision surface also supports rejection. The reviewer gives a reason so the employee receives an understandable outcome. The system records the decision; it does not infer or make it automatically.', tip: 'This is an evidence page; the separate live fixture demonstrates the approval path only.', talkZh: '同一個 decision surface 也支援拒絕。reviewer 提供原因，員工便能收到可理解的結果。系統記錄決定，而不會自行推論或自動作出決定。', tipZh: '這是 evidence page；獨立 live fixture 只示範批准路徑。' },
  { id: '03D', label: 'Employee update', time: '06:20', talk: 'Mia signs in again and uses the same notification bell. Her new inbox conversation contains the recorded decision and the reviewer note. The employee gets a visible outcome while the original request history remains intact.', tip: 'The live demo will repeat this exact bell-to-decision story using Robin and Mia.', talkZh: 'Mia 再次登入並使用同一個通知鈴鐺。她的新 inbox conversation 會包含已記錄的決定和 reviewer note。員工收到清楚結果，而原本的 request history 保持完整。', tipZh: 'live demo 會以 Robin 和 Mia 重複相同的 bell-to-decision 流程。' },
  { id: '03E', label: 'Live demo', time: '06:35', talk: 'Now I will run the isolated live fixture once. Robin clicks the bell, reviews and approves Mia’s dedicated Leave request. The script signs in as Mia and opens her bell notification. When it ends, this button returns to Start, so I can repeat it only if there is interest; otherwise I continue to Engineering.', tip: 'Start the demo. Pause stops only the next scripted step, leaving the real UI free for questions.', talkZh: '現在我會運行一次隔離的 live fixture。Robin 點擊鈴鐺、檢查並批准 Mia 專用的 Leave request。script 隨後會以 Mia 登入並打開她的鈴鐺通知。完成後按鈕會回到 Start；如有興趣可重複，否則直接進入 Engineering。', tipZh: '按 Start。Pause 只會停止下一個 scripted step，真實 UI 仍可自由回答問題。' },
  { id: '04A', label: 'Architecture', time: '07:20', talk: 'This working prototype is separated into four deliberate boundaries. Nuxt and Vue provide the role-aware chat and inbox. FastAPI owns validation and routing. SQLite persists request and decision history. A mock external API shows a controlled hand-off. This keeps the user experience conversational without putting business controls inside a prompt.', tip: 'Draft: explain the boundary first, then point to the three cards.', talkZh: '這個可運行原型刻意分為四個邊界：Nuxt 和 Vue 提供角色感知的 chat 和 inbox；FastAPI 負責驗證和 routing；SQLite 儲存申請和決定歷史；mock external API 顯示受控的交接。這讓使用體驗保持對話式，同時不會把業務控制放進 prompt 內。', tipZh: 'Draft：先解釋技術邊界，再指出三張卡。' },
  { id: '04B', label: 'LLM controls', time: '07:45', talk: 'The LLM helps with understanding: it extracts intent, identifies missing fields and proposes structured details from text or a receipt. It does not validate the business decision. Code validates identity, dates, working days, currency and routing; the employee confirms submission and the approver confirms the decision.', tip: 'Draft: make the control boundary explicit—LLM assists, rules validate, people decide.', talkZh: 'LLM 協助理解：由文字或收據提取意圖、找出遺漏欄位和建議結構化資料。它不負責驗證業務決定。程式碼會驗證身份、日期、工作日、貨幣和 routing；員工確認提交，審批人確認決定。', tipZh: 'Draft：清楚說明控制邊界——LLM 協助、規則驗證、人手決定。' },
  { id: '04C', label: 'Data & audit', time: '08:10', talk: 'Each request keeps its evidence together: the source attachment, extracted details, confirmation, assigned approver, reviewer note and final outcome. This is important because the same visible chat journey still creates records that can be explained later and reviewed by the responsible role.', tip: 'Draft: relate the audit record back to the receipt and confirmation you have just shown.', talkZh: '每個申請都把證據保留在一起：原始附件、提取資料、確認、已分配審批人、reviewer note 和最終結果。這很重要，因為同一個可見的 chat journey 仍會建立日後可解釋、由負責角色檢閱的紀錄。', tipZh: 'Draft：把 audit record 連回剛才展示的收據和確認。' },
  { id: '04D', label: 'Quality gates', time: '08:35', talk: 'Finally, the demo is designed to be repeatable. Dedicated fixtures can be reset without touching the other journey. Backend tests verify the business rules, frontend linting and typechecking protect the client contract, and browser automation exercises the sign-in, bell, decision and notification path.', tip: 'Draft: this is the confidence point—repeatable demo data and regression checks.', talkZh: '最後，這個 demo 被設計成可重複運行。專用 fixture 可以 reset，而不會影響其他 journey。backend tests 驗證業務規則；frontend lint 和 typecheck 保護 client contract；browser automation 會測試登入、鈴鐺、決定和通知流程。', tipZh: 'Draft：這是建立信心的重點——可重複的 demo data 和 regression checks。' },
  { id: '05A', label: 'Dashboard', time: '09:00', talk: 'The first extension should be visibility, not more automation. For example, a manager can ask: “Show my team’s Leave requests waiting more than three days, grouped by approver.” The dashboard returns a read-only filtered queue with ageing, assigned reviewer and links to the existing request records. An LLM can help us prototype that view quickly from structured data, but production still needs agreed metrics, role access and quality checks.', tip: 'Draft: say “faster prototype”, not “easy production system”. The question only selects a read-only view.', talkZh: '第一個延伸應該是可見性，而不是更多自動化。例如 manager 可以問：「顯示我的 team 等待超過三天、按 approver 分組的 Leave requests。」dashboard 回傳只讀的 filtered queue，包括 ageing、assigned reviewer 和現有 request records 的連結。LLM 可以由結構化資料加快這個 view 的 prototype，但正式系統仍需要已同意的 metrics、role access 和 quality checks。', tipZh: 'Draft：說「加快 prototype」，不要說「很容易做正式系統」。問題只會選出只讀 view。' },
  { id: '05B', label: 'Jev signals', time: '09:25', talk: 'Jev is useful here because it makes a fast, closed choice rather than writing a free-text answer. We give it the Leave dates, entitlement balance, public-holiday calculation, relevant policy and attached evidence. For example it may return: “Needs clarification. High confidence. The receipt says 20 September, but the request says 22 September.” The reviewer sees that evidence and decides to ask for clarification or continue to approve or reject. Jev cannot submit the decision.', tip: 'Draft: Jev triages the reviewer’s attention; the reviewer sees the evidence and still owns the decision.', talkZh: 'Jev 在這裡有用，因為它能快速作出封閉式選擇，而不是生成自由文字。我們給它 Leave dates、entitlement balance、public-holiday calculation、相關政策和附件證據。例如它可回傳：「Needs clarification。High confidence。收據顯示 9 月 20 日，但申請顯示 9 月 22 日。」reviewer 看到證據後，決定要求補充資料，或繼續批准或拒絕；Jev 不可提交決定。', tipZh: 'Draft：Jev 只協助安排 reviewer 注意力；reviewer 看到證據後仍擁有決定權。' },
  { id: '05C', label: 'Company chat', time: '09:50', talk: 'The next interface does not need to be another new UI. We can integrate with the company chat platform people already use, such as Teams or Slack. The chat becomes the entry point for asking a question or receiving a status update; when an approval action is required, a secure deep link opens the existing confirmation screen. The backend remains the system of record.', tip: 'Draft: company chat is the familiar entry point; this service keeps identity, confirmation, audit and validation.', talkZh: '下一個 interface 不一定要是另一個新 UI。我們可整合員工已在使用的公司 chat 平台，例如 Teams 或 Slack。chat 成為提問或接收狀態更新的入口；當需要審批操作時，secure deep link 會開啟現有確認畫面。backend 仍然是 system of record。', tipZh: 'Draft：公司 chat 是熟悉的入口；這個服務保留身份、確認、audit 和 validation。' },
  { id: '05D', label: 'Governed rollout', time: '10:15', talk: 'I would roll this out in stages: begin with one request type and a small user group, measure completion, exceptions, turnaround and reviewer feedback, then add the dashboard, Jev triage and company-chat entry point only after each control is proven in practice.', tip: 'Draft: close by inviting HR, Finance and Technology to define the pilot boundary together.', talkZh: '我會分階段推出：先由一種申請類型和小型用戶組開始，量度完成率、例外、處理時間和 reviewer feedback；只有在實務中證明每個控制有效後，才加入 dashboard、Jev triage 和公司 chat 入口。', tipZh: 'Draft：以邀請 HR、Finance 和 Technology 共同定義 pilot 範圍作結。' },
]

const currentSceneIndex = ref(0)
const currentScene = computed(() => scenes[currentSceneIndex.value]!)
const nextScene = computed(() => scenes[currentSceneIndex.value + 1])
const connection = ref<'connecting' | 'connected' | 'offline'>('connecting')
const language = ref<'en' | 'zh'>('en')
const liveScenario = ref(0)
const liveRunning = ref(false)
const liveStarted = ref(false)
const liveComplete = ref(false)
const evidenceZoom = ref(0)
let syncTimer: number | undefined

async function refreshSharedScene() {
  try {
    const state = await $fetch<{ sceneIndex: number, demoCommand: 'play' | 'pause' | 'restart' | 'seek' | 'complete', demoTime: number }>('/api/presentation/state')
    if (Number.isInteger(state.sceneIndex) && state.sceneIndex >= 0 && state.sceneIndex < scenes.length) {
      currentSceneIndex.value = state.sceneIndex
    }
    liveScenario.value = state.demoTime
    liveRunning.value = state.demoCommand === 'play' || state.demoCommand === 'restart'
    liveComplete.value = state.demoCommand === 'complete'
    if (liveComplete.value) liveStarted.value = false
    evidenceZoom.value = state.demoTime
    connection.value = 'connected'
  } catch {
    connection.value = 'offline'
  }
}

async function controlLive(command: 'play' | 'pause' | 'restart' | 'seek', scenario = liveScenario.value) {
  liveScenario.value = scenario
  liveRunning.value = command === 'play' || command === 'restart'
  if (command === 'restart') {
    liveStarted.value = true
    liveComplete.value = false
    try {
      await $fetch('/api/presentation/reset-approval-demo', { method: 'POST' })
    } catch {
      connection.value = 'offline'
      return
    }
  }
  try {
    await $fetch('/api/presentation/state', { method: 'PUT', body: { demoCommand: command, demoTime: scenario } })
    connection.value = 'connected'
  } catch {
    connection.value = 'offline'
  }
}

async function controlEvidence(zoom: number) {
  evidenceZoom.value = zoom
  if (zoom < 4) {
    liveStarted.value = false
    liveRunning.value = false
    liveComplete.value = false
  }
  try {
    await $fetch('/api/presentation/state', { method: 'PUT', body: { demoCommand: 'seek', demoTime: zoom } })
    connection.value = 'connected'
  } catch {
    connection.value = 'offline'
  }
}

async function goToScene(index: number) {
  const safeIndex = Math.min(Math.max(index, 0), scenes.length - 1)
  currentSceneIndex.value = safeIndex
  try {
    evidenceZoom.value = 0
    await $fetch('/api/presentation/state', { method: 'PUT', body: { sceneIndex: safeIndex, demoCommand: 'seek', demoTime: 0 } })
    connection.value = 'connected'
  } catch {
    connection.value = 'offline'
  }
}

function jumpToScene(event: Event) {
  void goToScene(Number((event.target as HTMLSelectElement).value))
}

onMounted(() => {
  void refreshSharedScene()
  syncTimer = window.setInterval(() => void refreshSharedScene(), 500)
})

onBeforeUnmount(() => {
  if (syncTimer) window.clearInterval(syncTimer)
})
</script>

<template>
  <main class="presenter-shell">
    <header>
      <div><span class="live-dot" :class="`is-${connection}`" /> Presenter controller</div>
      <div class="header-actions"><button type="button" @click="language = language === 'en' ? 'zh' : 'en'">{{ language === 'en' ? '繁' : 'EN' }}</button><span>{{ connection === 'connected' ? 'Synced' : connection === 'offline' ? 'Offline' : 'Connecting' }}</span></div>
    </header>

    <section class="scene-meta">
      <span>Scene {{ currentScene.id }} · {{ currentScene.time }}</span>
      <label class="scene-jump">Jump to <select :value="currentSceneIndex" @change="jumpToScene"><option v-for="(scene, index) in scenes" :key="scene.id" :value="index">{{ scene.id }} · {{ scene.label }}</option></select></label>
    </section>

    <section class="current-card" aria-live="polite">
      <p>Now presenting</p>
      <h1>{{ currentScene.label }}</h1>
      <div class="progress"><i :style="{ width: `${((currentSceneIndex + 1) / scenes.length) * 100}%` }" /></div>
    </section>

    <section class="talk-card">
      <p>Say this</p>
      <strong>{{ language === 'en' ? currentScene.talk : currentScene.talkZh }}</strong>
    </section>

    <section class="tip-card">
      <p>Remember</p>
      <span>{{ language === 'en' ? currentScene.tip : currentScene.tipZh }}</span>
    </section>

    <section class="next-card">
      <p>Next</p>
      <strong v-if="nextScene">{{ nextScene.id }} · {{ nextScene.label }}</strong>
      <strong v-else>Questions &amp; discussion</strong>
    </section>

    <section v-if="currentScene.id === '02B'" class="live-controls">
      <p>Zoom real evidence</p>
      <div><button type="button" @click="controlEvidence(0)">Overview</button><button type="button" @click="controlEvidence(1)">1 · Input</button><button type="button" @click="controlEvidence(2)">2 · Confirm</button><button type="button" @click="controlEvidence(3)">3 · Success</button></div>
    </section>

    <section v-if="currentScene.id === '02C'" class="live-controls">
      <p>Zoom Claim evidence</p>
      <div><button type="button" @click="controlEvidence(0)">Overview</button><button type="button" @click="controlEvidence(1)">1 · Receipt</button><button type="button" @click="controlEvidence(2)">2 · Upload + Send</button><button type="button" @click="controlEvidence(3)">3 · Confirm</button><button type="button" @click="controlEvidence(4)">4 · Success</button></div>
    </section>

    <section v-if="currentScene.id === '02D'" class="live-controls">
      <p>Live demo control</p>
      <div><button v-for="(label, index) in ['Claim attachment', 'Leave request', 'Edit / cancel Leave']" :key="label" type="button" :class="{ active: liveScenario === index }" @click="controlLive('seek', index)">{{ label }}</button></div>
      <strong v-if="liveComplete" class="demo-finished">Demo complete — ready to start again or continue to Scene 03.</strong>
      <button class="live-toggle" type="button" @click="controlLive(liveRunning ? 'pause' : (liveStarted ? 'play' : 'restart'))">{{ liveRunning ? 'Pause next step' : (liveStarted ? 'Resume steps' : 'Start new demo') }}</button>
    </section>

    <section v-if="currentScene.id === '03E'" class="live-controls">
      <p>Live bell-to-decision demo</p>
      <strong v-if="liveComplete" class="demo-finished">Live approval complete — the employee has been notified. Ready for Scene 04.</strong>
      <button class="live-toggle" type="button" @click="controlLive(liveRunning ? 'pause' : (liveStarted ? 'play' : 'restart'), 0)">{{ liveRunning ? 'Pause next step' : (liveStarted ? 'Resume steps' : 'Start bell-to-decision demo') }}</button>
    </section>

    <nav class="presenter-controls" aria-label="Scene controls">
      <button type="button" :disabled="currentSceneIndex === 0" @click="goToScene(currentSceneIndex - 1)">←<span>Back</span></button>
      <button type="button" class="next-button" :disabled="currentSceneIndex === scenes.length - 1" @click="goToScene(currentSceneIndex + 1)"><span>Next</span>→</button>
    </nav>
  </main>
</template>

<style scoped>
.presenter-shell {
  display: grid;
  min-height: 100dvh;
  grid-template-rows: auto auto auto minmax(7rem, 1fr) auto auto;
  gap: clamp(0.45rem, 1vh, 0.7rem);
  overflow: auto;
  padding: clamp(0.75rem, 2vw, 1.15rem);
  background: radial-gradient(circle at 75% 0%, rgb(28 117 164 / 30%), transparent 22rem), #06101c;
  color: #eef8ff;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}
.presenter-shell > header, .scene-meta { display: flex; align-items: center; justify-content: space-between; color: rgb(238 248 255 / 58%); font-size: 0.7rem; font-weight: 650; letter-spacing: 0.08em; text-transform: uppercase; }.header-actions { display:flex; align-items:center; gap:.65rem; }.header-actions button { border:1px solid rgb(170 213 238 / 30%); border-radius:.35rem; padding:.25rem .42rem; background:transparent; color:#65c9ff; font:inherit; }.scene-jump { display:flex; align-items:center; gap:.35rem; }.scene-jump select { max-width:11.5rem; border:1px solid rgb(101 201 255 / 45%); border-radius:.35rem; padding:.32rem .4rem; background:#0b293d; color:#eef8ff; font:inherit; text-transform:none; }
.live-dot { display: inline-block; width: 0.5rem; height: 0.5rem; margin-right: 0.4rem; border-radius: 50%; background: #f5b942; box-shadow: 0 0 0.7rem rgb(245 185 66 / 60%); }
.live-dot.is-connected { background: #50d49b; box-shadow: 0 0 0.7rem rgb(80 212 155 / 60%); }
.live-dot.is-offline { background: #fa6e76; box-shadow: 0 0 0.7rem rgb(250 110 118 / 60%); }
.scene-meta { border-top: 1px solid rgb(170 213 238 / 16%); padding-top: 0.55rem; }
.current-card, .talk-card, .tip-card, .next-card { border: 1px solid rgb(170 213 238 / 20%); border-radius: .75rem; padding: clamp(.7rem, 1.6vw, .95rem); background: rgb(7 28 44 / 70%); }
.current-card { display: grid; align-content: space-between; background: linear-gradient(145deg, rgb(26 118 170 / 42%), rgb(7 28 44 / 84%)); }
.current-card p, .talk-card p, .tip-card p, .next-card p { margin: 0; color: #65c9ff; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }
.current-card h1 { margin: .3rem 0 .45rem; font-size: clamp(1.35rem, 5vw, 2rem); font-weight: 600; letter-spacing: -0.045em; line-height: 1; }
.progress { height: 0.28rem; overflow: hidden; border-radius: 99px; background: rgb(238 248 255 / 16%); }
.progress i { display: block; height: 100%; border-radius: inherit; background: #65c9ff; transition: width 180ms ease; }
.talk-card, .tip-card { display: grid; gap: 0.45rem; }
.talk-card strong { font-size: clamp(.88rem, 2.6vw, 1.08rem); font-weight: 520; line-height: 1.35; }
.tip-card span { color: rgb(238 248 255 / 68%); font-size: clamp(.72rem, 2.2vw, .9rem); line-height: 1.42; }
.next-card { display: flex; align-items: center; justify-content: space-between; padding-block: 0.65rem; }
.next-card strong { color: rgb(238 248 255 / 80%); font-size: 0.9rem; }
.presenter-controls { display: grid; grid-template-columns: 1fr 1.35fr; gap: 0.75rem; }
.presenter-controls button { display: flex; align-items: center; justify-content: center; gap: 0.65rem; border: 1px solid rgb(170 213 238 / 28%); border-radius: 0.85rem; background: rgb(238 248 255 / 8%); color: #eef8ff; font-size: 1.1rem; font-weight: 650; }
.presenter-controls button span { font-size: 0.9rem; }
.presenter-controls .next-button { border-color: #65c9ff; background: #65c9ff; color: #052037; }
.presenter-controls button:disabled { cursor: not-allowed; opacity: 0.36; }
.live-controls{display:grid;gap:.5rem;border:1px solid rgb(101 201 255 / 34%);border-radius:.85rem;padding:.7rem .9rem;background:rgb(11 41 61 / 72%)}.live-controls p{margin:0;color:#65c9ff;font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase}.live-controls div{display:grid;grid-template-columns:repeat(3,1fr);gap:.35rem}.live-controls button{border:1px solid rgb(170 213 238 / 28%);border-radius:.4rem;background:transparent;padding:.42rem;color:#c5d9e5;font:inherit;font-size:.7rem}.live-controls button.active,.live-controls .live-toggle{border-color:#65c9ff;background:#65c9ff;color:#052037;font-weight:750}.live-controls .live-toggle{justify-self:start;padding-inline:.7rem}.demo-finished{color:#8be5b7;font-size:.72rem;line-height:1.35}
</style>
