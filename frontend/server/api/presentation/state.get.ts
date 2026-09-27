import { presentationState } from '../../utils/presentation-state'
import { requirePresentationAccess } from '../../utils/presentation-auth'

export default defineEventHandler((event) => {
  requirePresentationAccess(event)
  return presentationState()
})
