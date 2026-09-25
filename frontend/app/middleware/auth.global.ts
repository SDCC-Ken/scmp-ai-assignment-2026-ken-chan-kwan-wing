export default defineNuxtRouteMiddleware(async (to) => {
  const { user, notice, checked, fetchMe } = useAuth()

  // First render (SSR) validates the httpOnly session cookie via /me; the result travels to the browser
  // in the payload, so hydration and later navigations do not repeat the call.
  if (!checked.value) await fetchMe()

  // Role rules live in utils/access.ts: `/` needs can_request, `/approvals*` needs approves, `/login` bounces
  // signed-in users to their home, and a user with neither capability is sent to /no-access.
  const target = routeRedirect(user.value, to.path)
  if (!target) return
  if (target === '/login' && !user.value) {
    // An SSR redirect starts a new request, so carry the "expired" reason in a harmless query flag.
    return navigateTo(notice.value ? { path: '/login', query: { reason: 'expired' } } : '/login')
  }
  return navigateTo(target)
})
