import { describe, expect, it } from 'vitest'
import { buildThemeCss, DEFAULT_THEME, isValidHex, resolveTheme, sanitizeHex } from '../app/utils/theme'

describe('theme utils', () => {
  it('accepts 3/6-digit hex and rejects malformed values', () => {
    expect(isValidHex('#32a9e1')).toBe(true)
    expect(isValidHex('#FFF')).toBe(true)
    for (const bad of ['32a9e1', '#12345', '#gggggg', 'red', '#fff;}body{', '', null, 42]) {
      expect(isValidHex(bad)).toBe(false)
    }
  })

  it('normalises valid values and falls back on malformed ones', () => {
    expect(sanitizeHex(' #ABCDEF ', '#000000')).toBe('#abcdef')
    expect(sanitizeHex('nope', '#123456')).toBe('#123456')
  })

  it('resolves a partial/invalid config to defaults', () => {
    expect(resolveTheme(undefined)).toEqual(DEFAULT_THEME)
    const t = resolveTheme({ lightPrimary: '#ff0000', darkPrimary: 'bad' })
    expect(t.lightPrimary).toBe('#ff0000')
    expect(t.darkPrimary).toBe(DEFAULT_THEME.darkPrimary)
  })

  it('builds CSS for light, prefers-color-scheme and data-theme overrides', () => {
    const css = buildThemeCss({ lightPrimary: '#ff0000' })
    expect(css).toContain(':root{--theme-primary:#ff0000;')
    expect(css).toContain('@media (prefers-color-scheme: dark)')
    expect(css).toContain(':root[data-theme="dark"]{--theme-primary:#7dd3fc;')
    expect(css).toContain(':root[data-theme="light"]{--theme-primary:#ff0000;')
    expect(css).toContain('--color-primary:#ff0000;')
  })
})
