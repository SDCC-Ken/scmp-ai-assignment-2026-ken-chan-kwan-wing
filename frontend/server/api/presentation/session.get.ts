import { hasPresentationAccess } from '../../utils/presentation-auth'

export default defineEventHandler((event) => ({ authorized: hasPresentationAccess(event) }))
