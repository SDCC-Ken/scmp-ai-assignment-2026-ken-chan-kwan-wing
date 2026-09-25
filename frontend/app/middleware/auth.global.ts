export default defineNuxtRouteMiddleware(async (to) => {
  const { user, notice, checked, fetchMe } = useAuth()

  // First render (SSR) validates the httpOnly session cookie via /me; the result travels to the browser
  // in the payload, so hydration and later navigations do not repeat the call.
  if (!checked.value) await fetchMe()

  if (to.path === '/login') return user.value ? navigateTo('/') : undefined
  if (!user.value) {
    // An SSR redirect starts a new request, so carry the "expired" reason in a harmless query flag.
    return navigateTo(notice.value ? { path: '/login', query: { reason: 'expired' } } : '/login')
  }
})
