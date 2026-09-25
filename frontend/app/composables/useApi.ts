import type { NitroFetchOptions, NitroFetchRequest } from 'nitropack'

/**
 * `$fetch` wrapper for authenticated API calls: adds the Bearer header and signs the user out
 * (clearing the cookie and redirecting to /login) when the API answers 401.
 */
export function useApi() {
  const { apiBase, getToken, clearSession, withContext, expiredNotice } = useAuth()

  return async function api<T>(path: string, options: NitroFetchOptions<NitroFetchRequest> = {}): Promise<T> {
    const token = getToken()
    try {
      return await $fetch<T>(path, {
        ...options,
        baseURL: apiBase(),
        headers: { ...(options.headers as Record<string, string> | undefined), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      }) as T
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
