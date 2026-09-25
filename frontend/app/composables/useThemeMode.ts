/** Cookie-backed theme mode; readable on server and client, so SSR output matches hydration. */
export function useThemeMode() {
  const cookie = useCookie<string>('theme-mode', {
    default: () => 'system',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 365,
  })
  const mode = computed<ThemeMode>({
    get: () => (isThemeMode(cookie.value) ? cookie.value : 'system'),
    set: (value) => {
      cookie.value = value
    },
  })
  return mode
}
