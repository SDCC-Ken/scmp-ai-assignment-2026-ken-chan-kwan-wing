export interface ThemeConfig {
  lightPrimary: string
  lightSecondary: string
  lightBackground: string
  darkPrimary: string
  darkSecondary: string
  darkBackground: string
}

export type ThemeMode = 'light' | 'dark' | 'system'

export const DEFAULT_THEME: Readonly<ThemeConfig> = {
  lightPrimary: '#32a9e1',
  lightSecondary: '#1e40af',
  lightBackground: '#ffffff',
  darkPrimary: '#7dd3fc',
  darkSecondary: '#94a3b8',
  darkBackground: '#020617',
}

const HEX_RE = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i

export function isValidHex(value: unknown): value is string {
  return typeof value === 'string' && HEX_RE.test(value.trim())
}

/** Returns a lower-cased valid hex colour, or the fallback when malformed. */
export function sanitizeHex(value: unknown, fallback: string): string {
  return isValidHex(value) ? value.trim().toLowerCase() : fallback
}

export function resolveTheme(input?: Partial<Record<keyof ThemeConfig, unknown>> | null): ThemeConfig {
  const source = input ?? {}
  const out = { ...DEFAULT_THEME }
  for (const key of Object.keys(DEFAULT_THEME) as (keyof ThemeConfig)[]) {
    out[key] = sanitizeHex(source[key], DEFAULT_THEME[key])
  }
  return out
}

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

/** Builds the :root CSS for light, prefers-color-scheme dark, and data-theme overrides. */
export function buildThemeCss(input?: Partial<Record<keyof ThemeConfig, unknown>> | null): string {
  const t = resolveTheme(input)
  // --theme-* feed the Tailwind @theme tokens (a token cannot reference its own name);
  // --color-* carry the same values for direct use.
  const vars = (p: string, s: string, b: string) =>
    `--theme-primary:${p};--theme-secondary:${s};--theme-background:${b};--color-primary:${p};--color-secondary:${s};--color-background:${b};`
  const light = vars(t.lightPrimary, t.lightSecondary, t.lightBackground)
  const dark = vars(t.darkPrimary, t.darkSecondary, t.darkBackground)
  return [
    `:root{${light}}`,
    `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){${dark}}}`,
    `:root[data-theme="light"]{${light}}`,
    `:root[data-theme="dark"]{${dark}}`,
  ].join('\n')
}
