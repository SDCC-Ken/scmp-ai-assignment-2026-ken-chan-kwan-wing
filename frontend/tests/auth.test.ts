import { describe, expect, it } from 'vitest'
import {
  authCookieMaxAge,
  authErrorMessage,
  avatarColour,
  extractStatus,
  getInitials,
  groupUsersByRole,
  isAuthUser,
  MOCK_WARNING,
  parseMockUsers,
  resolveApiBase,
  ROLE_CAPABILITIES,
  roleLabel,
  ROLES,
} from '../app/utils/auth'

const user = (id: number, role: string) => ({ id, email: `u${id}@example.com`, display_name: `User ${id}`, role })

describe('role labels and capabilities', () => {
  it('maps every role to a label and falls back for unknown values', () => {
    expect(roleLabel('employee')).toBe('Employee')
    expect(roleLabel('hr_approver')).toBe('HR Approver')
    expect(roleLabel('finance_approver')).toBe('Finance Approver')
    expect(roleLabel('admin')).toBe('Unknown role')
  })

  it('keeps approver scopes separate: HR is Leave-only, Finance is Claim-only', () => {
    const hr = ROLE_CAPABILITIES.hr_approver.items.join(' ')
    const finance = ROLE_CAPABILITIES.finance_approver.items.join(' ')
    expect(hr).toMatch(/Leave/)
    expect(hr).not.toMatch(/Claim/)
    expect(finance).toMatch(/Claim/)
    expect(finance).not.toMatch(/Leave/)
    expect(ROLE_CAPABILITIES.employee.items.join(' ')).toMatch(/own requests only/)
  })

  it('defines capabilities for every role', () => {
    for (const role of ROLES) expect(ROLE_CAPABILITIES[role].items.length).toBeGreaterThan(0)
  })
})

describe('getInitials / avatarColour', () => {
  it('uses first and last word, uppercased', () => {
    expect(getInitials('Amy Lau')).toBe('AL')
    expect(getInitials('  ben  chi  wong ')).toBe('BW')
    expect(getInitials('Madonna')).toBe('M')
  })

  it('falls back to the e-mail, then a question mark', () => {
    expect(getInitials('', 'zed@example.com')).toBe('Z')
    expect(getInitials(null, null)).toBe('?')
  })

  it('returns a stable colour for the same seed', () => {
    expect(avatarColour('amy.lau@example.com')).toBe(avatarColour('amy.lau@example.com'))
    expect(avatarColour('x')).toMatch(/^#[0-9a-f]{6}$/i)
  })
})

describe('authCookieMaxAge', () => {
  it('uses expires_in seconds when valid', () => {
    expect(authCookieMaxAge(3600)).toBe(3600)
    expect(authCookieMaxAge(90.9)).toBe(90)
  })

  it('falls back to one hour for invalid values and caps very long ones', () => {
    for (const bad of [0, -5, Number.NaN, Infinity, '3600', null, undefined]) expect(authCookieMaxAge(bad)).toBe(3600)
    expect(authCookieMaxAge(10 ** 9)).toBe(60 * 60 * 24 * 7)
  })
})

describe('error mapping', () => {
  it('extracts a status from ofetch-like errors and returns undefined for network errors', () => {
    expect(extractStatus({ statusCode: 401 })).toBe(401)
    expect(extractStatus({ response: { status: 403 } })).toBe(403)
    expect(extractStatus(new TypeError('fetch failed'))).toBeUndefined()
    expect(extractStatus(null)).toBeUndefined()
  })

  it('maps login failures to distinct, non-leaky messages', () => {
    expect(authErrorMessage(401, 'login')).toMatch(/not recognised/)
    expect(authErrorMessage(403, 'login')).toMatch(/inactive/)
    expect(authErrorMessage(404, 'login')).toMatch(/disabled/)
    expect(authErrorMessage(undefined, 'login')).toMatch(/Cannot reach the API/)
    expect(authErrorMessage(500, 'list-users')).toMatch(/server had a problem/)
    expect(authErrorMessage(401, 'list-users')).toBe('Something went wrong. Please try again.')
  })
})

describe('user payload handling', () => {
  it('validates users and drops malformed entries', () => {
    expect(isAuthUser(user(1, 'employee'))).toBe(true)
    expect(isAuthUser(user(1, 'root'))).toBe(false)
    expect(isAuthUser({ id: '1', email: 'a@b.c', display_name: 'A', role: 'employee' })).toBe(false)
    expect(parseMockUsers([user(1, 'employee'), { nope: true }, null])).toHaveLength(1)
    expect(parseMockUsers({ not: 'an array' })).toEqual([])
  })

  it('groups users by role in canonical order and omits empty groups', () => {
    const users = parseMockUsers([user(1, 'finance_approver'), user(2, 'employee'), user(3, 'employee')])
    const groups = groupUsersByRole(users)
    expect(groups.map(g => g.role)).toEqual(['employee', 'finance_approver'])
    expect(groups[0]!.users).toHaveLength(2)
    expect(groups[0]!.label).toBe('Employees')
  })
})

describe('resolveApiBase and warning copy', () => {
  it('uses the private server base only during SSR and strips trailing slashes', () => {
    const base = { publicBase: 'http://localhost:9181/', serverBase: 'http://api:9181' }
    expect(resolveApiBase({ isServer: true, ...base })).toBe('http://api:9181')
    expect(resolveApiBase({ isServer: false, ...base })).toBe('http://localhost:9181')
    expect(resolveApiBase({ isServer: true, publicBase: 'http://localhost:9181', serverBase: '' })).toBe('http://localhost:9181')
  })

  it('states plainly that the sign-in is a mock, not Google, and passwordless', () => {
    expect(MOCK_WARNING.text).toMatch(/demonstration-only mock sign-in/)
    expect(MOCK_WARNING.text).toMatch(/not connected to Google/)
    expect(MOCK_WARNING.text).toMatch(/no password/)
  })
})
