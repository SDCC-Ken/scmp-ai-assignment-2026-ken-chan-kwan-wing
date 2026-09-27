export default defineNuxtRouteMiddleware(async (to) => {
  if (!['/presentation', '/presenter'].includes(to.path)) return

  const headers = import.meta.server ? useRequestHeaders(['cookie']) : undefined
  const session = await $fetch<{ authorized: boolean }>('/api/presentation/session', { headers }).catch(() => ({ authorized: false }))
  if (!session.authorized) return navigateTo({ path: '/presentation-login', query: { returnTo: to.fullPath } })
})
