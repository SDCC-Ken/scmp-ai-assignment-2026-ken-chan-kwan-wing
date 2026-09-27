<script setup lang="ts">
const props = defineProps<{ view: number }>()
const active = computed(() => Math.min(Math.max(Math.round(props.view), 0), 3))

const content = computed(() => [
  {
    eyebrow: '03A · BELL OPENS A NEW REVIEW CHAT',
    title: 'The top bell starts', accent: 'a focused review conversation',
    intro: 'Robin opens the bell. The real application creates one isolated inbox conversation with Mia’s assigned request.',
    image: '/presentation/03a-bell-inbox.png',
    alt: 'Robin Ho’s real inbox conversation showing Mia Chan’s assigned leave request.',
    caption: 'Real application capture · one dedicated pending item, with no unrelated work to skip.',
  },
  {
    eyebrow: '03B · APPROVE WITH CONTEXT',
    title: 'A reviewer adds context', accent: 'then confirms approval',
    intro: 'Robin reviews the live request, writes a note, and reaches the explicit Confirm approve step before anything is changed.',
    image: '/presentation/03b-approve-confirm.png',
    alt: 'Robin Ho’s real application showing the confirm approval step for Mia Chan’s leave request.',
    caption: 'Real application capture · the decision is still reversible until Confirm approve is pressed.',
  },
  {
    eyebrow: '03C · REJECT WITH A REASON',
    title: 'The same flow also supports', accent: 'a reasoned rejection',
    intro: 'The reviewer can choose Reject and include a clear note. The real UI then requires a separate Confirm reject action.',
    image: '/presentation/03c-reject-confirm.png',
    alt: 'Robin Ho’s real application showing the confirm rejection step for Mia Chan’s leave request.',
    caption: 'Real application capture · context assists the reviewer; the human still makes the decision.',
  },
  {
    eyebrow: '03D · EMPLOYEE RECEIVES THE RESULT',
    title: 'Mia uses the same bell', accent: 'to receive the outcome',
    intro: 'After Robin approves, Mia signs in, opens her bell, and sees the recorded decision and reviewer note in a new notification chat.',
    image: '/presentation/03d-employee-notification.png',
    alt: 'Mia Chan’s real application notification card showing the approved leave result and Got it button.',
    caption: 'Real application capture · the walkthrough stops here, before the presenter chooses Got it.',
  },
][active.value]!)
</script>

<template>
  <section class="approver-demo" aria-label="Approver journey evidence">
    <header><span class="live-dot" />{{ content.eyebrow }}</header>
    <article class="approver-card">
      <div class="copy">
        <p>{{ content.eyebrow }}</p>
        <h2>{{ content.title }}<br><em>{{ content.accent }}</em></h2>
        <span>{{ content.intro }}</span>
      </div>
      <figure class="real-shot">
        <img :src="content.image" :alt="content.alt">
        <figcaption>{{ content.caption }}</figcaption>
      </figure>
      <footer><span>1 · Bell</span><b>→</b><span>2 · New inbox conversation</span><b>→</b><span>3 · Explicit human decision</span><b>→</b><span>4 · Employee update</span></footer>
    </article>
  </section>
</template>

<style scoped>
.approver-demo{display:grid;gap:.75rem;width:min(96%,74rem);margin:auto}.approver-demo>header{display:flex;gap:.45rem;align-items:center;color:#d6e5ef;font-size:.78rem;font-weight:750;letter-spacing:.08em}.live-dot{width:.55rem;height:.55rem;border-radius:50%;background:#62c9ff;box-shadow:0 0 .8rem #62c9ff}.approver-card{display:grid;gap:1rem;border:1px solid rgb(125 211 252 / 38%);border-radius:1rem;padding:clamp(1rem,2.4vw,1.7rem);background:linear-gradient(140deg,rgb(11 46 70 / 94%),rgb(5 21 35 / 98%))}.copy{display:grid;gap:.35rem;max-width:54rem}.copy p{margin:0;color:#65c9ff;font-size:.67rem;font-weight:800;letter-spacing:.13em}.copy h2{margin:0;font-size:clamp(1.55rem,3.6vw,2.55rem);font-weight:560;letter-spacing:-.05em}.copy h2 em{color:#65c9ff;font-style:normal}.copy>span{color:#b9cfdb;line-height:1.5}.real-shot{margin:0;overflow:hidden;border:1px solid rgb(184 220 241 / 32%);border-radius:.65rem;background:#fff;box-shadow:0 .8rem 2rem rgb(0 0 0 / 26%)}.real-shot img{display:block;width:100%;max-height:clamp(22rem,52vh,38rem);object-fit:contain;object-position:top;background:#fff}.real-shot figcaption{border-top:1px solid #bfd1e8;padding:.55rem .75rem;color:#174986;font-size:.72rem;font-weight:600}.approver-card footer{display:flex;flex-wrap:wrap;align-items:center;gap:.35rem;color:#b9d1de;font-size:.68rem}.approver-card footer b{color:#65c9ff}
</style>
