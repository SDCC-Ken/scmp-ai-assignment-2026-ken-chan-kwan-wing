import { grantPresentationAccess } from '../../utils/presentation-auth'

export default defineEventHandler(async (event) => {
  const body = await readBody<{ password?: unknown }>(event)
  if (!grantPresentationAccess(event, String(body?.password || ''))) {
    throw createError({ statusCode: 401, statusMessage: 'Incorrect presentation password' })
  }
  return { authorized: true }
})
