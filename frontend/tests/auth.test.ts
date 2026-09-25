import { describe, expect, it } from 'vitest'
import {
  apiRequestHeaders,
  authErrorMessage,
  avatarColour,
  CSRF_HEADER,
  extractStatus,
  firstName,
  getInitials,
  groupUsersByRole,
  hasSessionCookie,
  isAuthUser,
  isUnsafeMethod,
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

describe('firstName ("Continue as ...")', () => {
  it('uses the first word of the display name', () => {
    expect(firstName('Amy Lau')).toBe('Amy')
    expect(firstName('  Chloe   Cheung ')).toBe('Chloe')
  })

  it('falls back to the e-mail local part, then a generic word', () => {
    expect(firstName('', 'henry.ho@example.com')).toBe('henry.ho')
    expect(firstName(null, null)).toBe('account')
  })
})

describe('httpOnly cookie session helpers', () => {
  it('flags only unsafe methods (case-insensitive; missing method is a GET)', () => {
    for (const m of ['POST', 'put', 'PATCH', 'delete']) expect(isUnsafeMethod(m)).toBe(true)
    for (const m of ['GET', 'head', 'OPTIONS', undefined, null]) expect(isUnsafeMethod(m)).toBe(false)
  })

  it('adds the CSRF header to unsafe requests only, and keeps caller headers', () => {
    expect(apiRequestHeaders('POST')).toEqual({ [CSRF_HEADER.name]: 'XMLHttpRequest' })
    expect(apiRequestHeaders('delete', { 'x-trace': '1' })).toEqual({ 'x-trace': '1', 'X-Requested-With': 'XMLHttpRequest' })
    expect(apiRequestHeaders('GET')).toEqual({})
    expect(apiRequestHeaders(undefined, { a: 'b' })).toEqual({ a: 'b' })
  })

  it('forwards a cookie header only when given (SSR) and never builds an Authorization header', () => {
    expect(apiRequestHeaders('GET', {}, 'scmp_session=abc; theme-mode=dark')).toEqual({ cookie: 'scmp_session=abc; theme-mode=dark' })
    expect(apiRequestHeaders('GET', {}, '')).toEqual({})
    expect(Object.keys(apiRequestHeaders('POST', {}, 'x=y')).map(k => k.toLowerCase())).not.toContain('authorization')
  })

  it('detects the session cookie by name in a raw Cookie header', () => {
    expect(hasSessionCookie('theme-mode=dark; scmp_session=abc')).toBe(true)
    expect(hasSessionCookie('scmp_session=abc')).toBe(true)
    expect(hasSessionCookie('theme-mode=dark; not_scmp_session=abc')).toBe(false)
    expect(hasSessionCookie('')).toBe(false)
    expect(hasSessionCookie(undefined)).toBe(false)
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
