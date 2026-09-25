import type { NitroFetchOptions, NitroFetchRequest } from 'nitropack'

/**
 * `$fetch` wrapper for authenticated API calls: sends the httpOnly session cookie (`credentials: 'include'`,
 * or the forwarded cookie header during SSR), adds the CSRF header on unsafe methods, and signs the user out
 * (clearing state and redirecting to /login) when the API answers 401.
 */
export function useApi() {
  const { request, clearSession, withContext, expiredNotice } = useAuth()

  return async function api<T>(path: string, options: NitroFetchOptions<NitroFetchRequest> = {}): Promise<T> {
    try {
      return await request<T>(path, options)
    }
    catch (error) {
      if (extractStatus(error) === 401) {
        clearSession(expiredNotice)
        await withContext(() => navigateTo('/login'))
      }
      throw error
    }
  }
}
