import type { NitroFetchOptions, NitroFetchRequest } from 'nitropack'

const EXPIRED_NOTICE = 'Your session has expired. Please sign in again.'

/**
 * Session state. The session JWT lives only in the API's httpOnly `scmp_session` cookie, which page scripts
 * cannot read; this composable never sees or stores it. Auth state is just the (non-secret) user object in
 * `useState`, which is safe to serialise into the SSR payload.
 *
 * Every browser call to the API is cross-origin (web :9180 -> API :9181), so it uses `credentials: 'include'`.
 * During SSR the incoming request's `cookie` header is forwarded to the API by hand.
 */
export function useAuth() {
  const nuxtApp = useNuxtApp()
  const config = useRuntimeConfig()
  // Read once, in a valid Nuxt context (empty object in the browser).
  const ssrCookie = useRequestHeaders(['cookie']).cookie

  const user = useState<AuthUser | null>('auth-user', () => null)
  const notice = useState<string | null>('auth-notice', () => null)
  /** True once the session has been validated (server render) or set by an explicit sign-in / sign-out. */
  const checked = useState<boolean>('auth-checked', () => false)

  function apiBase(): string {
    return resolveApiBase({
      isServer: import.meta.server,
      publicBase: config.public.apiBase,
      serverBase: import.meta.server ? config.apiBaseServer : undefined, // private key: never read in the browser
    })
  }

  // navigateTo needs the Nuxt context, which is lost after an `await` in event handlers.
  // Re-enter it only when it is really missing: a nested runWithContext during SSR would clear the
  // outer context and break later composable calls in the same middleware.
  function withContext<T>(fn: () => T): T {
    return tryUseNuxtApp() ? fn() : nuxtApp.runWithContext(fn) as T
  }

  /** Low-level API call: base URL, cookie credentials, CSRF header. No 401 handling (see useApi). */
  async function request<T>(path: string, options: NitroFetchOptions<NitroFetchRequest> = {}): Promise<T> {
    return await $fetch<T>(path, {
      ...options,
      baseURL: apiBase(),
      headers: apiRequestHeaders(
        options.method,
        options.headers as Record<string, string> | undefined,
        import.meta.server ? ssrCookie : undefined,
      ),
      ...(import.meta.client ? { credentials: 'include' as const } : {}),
    }) as T
  }

  function clearSession(message: string | null = null) {
    user.value = null
    notice.value = message
    withContext(() => clearNuxtState([...USER_SCOPED_STATE_KEYS]))
  }

  async function listMockUsers(): Promise<AuthUser[]> {
    return parseMockUsers(await request<unknown>('/api/auth/mock-users', { timeout: 8000 }))
  }

  /** Signs in as a seeded mock user (the API sets the httpOnly cookie), stores the user and redirects home. */
  async function login(email: string): Promise<AuthUser> {
    const data = await request<Partial<LoginResponse>>('/api/auth/mock-google/login', {
      method: 'POST',
      body: { email },
      timeout: 8000,
    })
    const signedIn = normalizeUser(data.user)
    if (!signedIn) throw new Error('Malformed login response')
    withContext(() => clearNuxtState([...USER_SCOPED_STATE_KEYS])) // nothing of a previous account survives
    user.value = signedIn
    notice.value = null
    checked.value = true
    await withContext(() => navigateTo(homePath(signedIn)))
    return signedIn
  }

  /**
   * Validates the session cookie with /api/auth/me (server: forwards the incoming cookie header).
   * A 401/403 clears the user; the "expired" notice is only set when a session actually existed.
   */
  async function fetchMe(): Promise<AuthUser | null> {
    if (import.meta.server && !ssrCookie) {
      user.value = null // no cookies at all: cannot be signed in, skip the API call
      checked.value = true
      return null
    }
    const hadSession = user.value !== null || hasSessionCookie(ssrCookie)
    try {
      const me = await request<unknown>('/api/auth/me', { timeout: 8000 })
      const current = normalizeUser(me)
      if (!current) throw new Error('Malformed /me response')
      user.value = current
      return current
    }
    catch (error) {
      const status = extractStatus(error)
      if (status === 401 || status === 403) clearSession(hadSession ? EXPIRED_NOTICE : null)
      else user.value = null
      return null
    }
    finally {
      checked.value = true
    }
  }

  /** Best-effort server logout (clears the cookie); the local session is always cleared. */
  async function logout() {
    try {
      await request('/api/auth/logout', { method: 'POST', timeout: 3000 })
    }
    catch { /* best effort */ }
    clearSession()
    checked.value = true
    await withContext(() => navigateTo('/login'))
  }

  return { user, notice, checked, apiBase, withContext, request, clearSession, listMockUsers, login, fetchMe, logout, expiredNotice: EXPIRED_NOTICE }
}
