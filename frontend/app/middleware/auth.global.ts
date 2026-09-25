export default defineNuxtRouteMiddleware(async (to) => {
  const { user, notice, getToken, refreshUser } = useAuth()

  if (!getToken()) {
    user.value = null // cookie expired or cleared (e.g. in another tab)
  }
  else if (!user.value) {
    // First load (server or client) or after the state was cleared: validate the token with /me.
    await refreshUser()
  }

  const authenticated = Boolean(user.value && getToken())
  if (to.path === '/login') return authenticated ? navigateTo('/') : undefined
  if (!authenticated) {
    // An SSR redirect starts a new request, so carry the "expired" reason in a harmless query flag.
    return navigateTo(notice.value ? { path: '/login', query: { reason: 'expired' } } : '/login')
  }
})
