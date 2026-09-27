import { presentationState } from '../../utils/presentation-state'
import { requirePresentationAccess } from '../../utils/presentation-auth'

// Keep this in sync with the presenter and presentation scene lists.
const TOTAL_SCENES = 21
const DEMO_COMMANDS = new Set(['play', 'pause', 'restart', 'seek', 'complete'])

export default defineEventHandler(async (event) => {
  requirePresentationAccess(event)
  const body = await readBody<{ sceneIndex?: unknown, demoCommand?: unknown, demoTime?: unknown }>(event)
  const sceneIndex = body?.sceneIndex === undefined ? undefined : Number(body.sceneIndex)

  if (sceneIndex !== undefined && (!Number.isInteger(sceneIndex) || sceneIndex < 0 || sceneIndex >= TOTAL_SCENES)) {
    throw createError({ statusCode: 400, statusMessage: 'sceneIndex must name a presentation scene' })
  }
  const demoCommand = body?.demoCommand
  const demoTime = body?.demoTime === undefined ? undefined : Number(body.demoTime)
  if (demoCommand !== undefined && (typeof demoCommand !== 'string' || !DEMO_COMMANDS.has(demoCommand))) {
    throw createError({ statusCode: 400, statusMessage: 'demoCommand must be a recognised video command' })
  }
  if (demoTime !== undefined && (!Number.isFinite(demoTime) || demoTime < 0)) {
    throw createError({ statusCode: 400, statusMessage: 'demoTime must be a non-negative number' })
  }
  if (sceneIndex === undefined && demoCommand === undefined) {
    throw createError({ statusCode: 400, statusMessage: 'provide a sceneIndex or demoCommand' })
  }

  const state = presentationState()
  if (sceneIndex !== undefined) state.sceneIndex = sceneIndex
  if (demoCommand !== undefined) {
    state.demoCommand = demoCommand as typeof state.demoCommand
    state.demoTime = demoTime ?? state.demoTime
  }
  state.revision += 1
  state.updatedAt = Date.now()
  return state
})
