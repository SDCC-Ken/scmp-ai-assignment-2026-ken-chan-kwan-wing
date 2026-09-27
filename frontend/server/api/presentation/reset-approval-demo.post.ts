import { requirePresentationAccess } from '../../utils/presentation-auth'

type ResetApprovalDemoResponse = { reset: boolean }

export default defineEventHandler(async (event): Promise<ResetApprovalDemoResponse> => {
  requirePresentationAccess(event)
  const config = useRuntimeConfig(event)
  const apiBase = String(config.apiBaseServer || config.public.apiBase).replace(/\/$/, '')
  return await $fetch<ResetApprovalDemoResponse>(`${apiBase}/api/presentation/reset-approval-demo`, {
    method: 'POST',
    headers: {
      'X-Requested-With': 'XMLHttpRequest',
      'X-Presentation-Reset': String(config.presentationPassword || ''),
    },
  })
})
