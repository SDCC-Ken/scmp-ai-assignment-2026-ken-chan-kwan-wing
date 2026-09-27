export type PresentationState = {
  sceneIndex: number
  /** A small command bus for the recorded employee walkthrough. */
  demoCommand: 'play' | 'pause' | 'restart' | 'seek' | 'complete'
  demoTime: number
  revision: number
  updatedAt: number
}

const state: PresentationState = {
  sceneIndex: 0,
  demoCommand: 'pause',
  demoTime: 0,
  revision: 0,
  updatedAt: Date.now(),
}

export function presentationState() {
  return state
}
