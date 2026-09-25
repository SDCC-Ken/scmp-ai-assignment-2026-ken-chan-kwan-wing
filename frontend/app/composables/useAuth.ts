import type { CookieRef } from '#app'

const TOKEN_COOKIE = 'auth-token'
const tokenCookies = new WeakMap<object, CookieRef<string | null>>()
const EXPIRED_NOTICE = 'Your session has expired. Please sign in again.'

/**
 * Session state. The JWT lives only in the `auth-token` cookie (never in useState, so it is not
 * serialised into the SSR payload); only the user object is shared state.
 */
export function useAuth() {
  const nuxtApp = useNuxtApp()
  const config = useRuntimeConfig()
  const secure = useRequestURL().protocol === 'https:'

  const user = useState<AuthUser | null>('auth-user', () => null)
  const notice = useState<string | null>('auth-notice', () => null)

  function apiBase(): string {
    return resolveApiBase({
      isServer: import.meta.server,
      publicBase: config.public.apiBase,
      serverBase: import.meta.server ? config.apiBaseServer : undefined, // private key: never read in the browser
    })
  }

  // useCookie/navigateTo need the Nuxt context, which is lost after an `await` in event handlers.
  // Re-enter it only when it is really missing: a nested runWithContext during SSR would clear the
  // outer context and break later composable calls in the same middleware.
  function withContext<T>(fn: () => T): T {
    return tryUseNuxtApp() ? fn() : nuxtApp.runWithContext(fn) as T
  }

  const cookieOptions = { sameSite: 'lax', secure, default: () => null } as const
  // One ref per Nuxt app (i.e. per SSR request, or once in the browser), created in a valid context
  // and reused for reads and clearing, so navigations do not pile up cookie watchers.
  const tokenCookie = tokenCookies.get(nuxtApp) ?? useCookie<string | null>(TOKEN_COOKIE, cookieOptions)
  tokenCookies.set(nuxtApp, tokenCookie)

  const getToken = (): string | null => tokenCookie.value || null

  /** Client-only (called from the sign-in click handler). */
  function setToken(token: string, expiresIn: number) {
    // A cookie ref's maxAge is fixed at creation, so make one with the lifetime the API gave us.
    // Create it before touching tokenCookie so it still sees the old value and therefore writes.
    const withLifetime = withContext(() =>
      useCookie<string | null>(TOKEN_COOKIE, { ...cookieOptions, maxAge: authCookieMaxAge(expiresIn) }),
    ) as CookieRef<string | null>
    tokenCookie.value = token // keep this instance in sync
    withLifetime.value = token // last write wins: cookie now carries Max-Age
  }

  function clearSession(message: string | null = null) {
    tokenCookie.value = null
    user.value = null
    notice.value = message
  }

  const bearer = (token: string) => ({ Authorization: `Bearer ${token}` })

  async function listMockUsers(): Promise<AuthUser[]> {
    const data = await $fetch<unknown>('/api/auth/mock-users', { baseURL: apiBase(), timeout: 8000 })
    return parseMockUsers(data)
  }

  async function loginAs(email: string): Promise<AuthUser> {
    const data = await $fetch<Partial<LoginResponse>>('/api/auth/mock-google/login', {
      method: 'POST',
      baseURL: apiBase(),
      body: { email },
      timeout: 8000,
    })
    if (typeof data.access_token !== 'string' || !isAuthUser(data.user)) {
      throw new Error('Malformed login response')
    }
    setToken(data.access_token, data.expires_in ?? 0)
    user.value = data.user
    notice.value = null
    return data.user
  }

  /** Validates the cookie token with /api/auth/me. Clears the session on 401/403. */
  async function refreshUser(): Promise<AuthUser | null> {
    const token = getToken()
    if (!token) {
      user.value = null
      return null
    }
    try {
      const me = await $fetch<unknown>('/api/auth/me', { baseURL: apiBase(), headers: bearer(token), timeout: 8000 })
      if (!isAuthUser(me)) throw new Error('Malformed /me response')
      user.value = me
      return me
    }
    catch (error) {
      const status = extractStatus(error)
      if (status === 401 || status === 403) clearSession(EXPIRED_NOTICE)
      else user.value = null
      return null
    }
  }

  /** Best-effort server logout; the local session is always cleared first. */
  async function logout() {
    const token = getToken()
    clearSession()
    if (token) {
      void $fetch('/api/auth/logout', { method: 'POST', baseURL: apiBase(), headers: bearer(token), timeout: 3000 })
        .catch(() => undefined)
    }
    await withContext(() => navigateTo('/login'))
  }

  return { user, notice, apiBase, withContext, getToken, clearSession, listMockUsers, loginAs, refreshUser, logout, expiredNotice: EXPIRED_NOTICE }
}
