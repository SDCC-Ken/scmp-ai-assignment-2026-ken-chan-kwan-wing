/** Pure, framework-free auth helpers (unit-tested offline in tests/auth.test.ts). */

export type Role = 'employee' | 'hr_approver' | 'finance_approver'

export interface AuthUser {
  id: number
  email: string
  display_name: string
  role: Role
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: AuthUser
}

/** Canonical display order (matches the order the API returns mock users in). */
export const ROLES: readonly Role[] = ['employee', 'hr_approver', 'finance_approver']

export const ROLE_LABELS: Readonly<Record<Role, string>> = {
  employee: 'Employee',
  hr_approver: 'HR Approver',
  finance_approver: 'Finance Approver',
}

export const ROLE_GROUP_LABELS: Readonly<Record<Role, string>> = {
  employee: 'Employees',
  hr_approver: 'HR approvers',
  finance_approver: 'Finance approvers',
}

/** Single source of truth for the mock-SSO warning; reused by the login page and the chooser modal. */
export const MOCK_WARNING = {
  title: 'Mock sign-in: demonstration only',
  text: 'This is a demonstration-only mock sign-in. It is not connected to Google. '
    + 'Choosing an account signs you in immediately as that fictional user, with no password.',
} as const

export const MOCK_SESSION_REMINDER = {
  title: 'Mock session',
  text: 'You are signed in through the demonstration-only mock Google sign-in as a fictional user. '
    + 'No real Google account, password or SCMP data is involved.',
} as const

export interface RoleCapabilities {
  summary: string
  items: readonly string[]
}

/** Product scope from AGENTS.md; every item ships in a later phase. */
export const ROLE_CAPABILITIES: Readonly<Record<Role, RoleCapabilities>> = {
  employee: {
    summary: 'Submit your own requests and follow their status.',
    items: [
      'Create a Leave Application',
      'Create a Staff Claim',
      'View your own requests only',
    ],
  },
  hr_approver: {
    summary: 'Review Leave requests. Staff Claims are out of scope for this role.',
    items: [
      'List Leave requests',
      'View Leave request details',
      'Approve or reject Leave requests',
    ],
  },
  finance_approver: {
    summary: 'Review Staff Claims. Leave requests are out of scope for this role.',
    items: [
      'List Staff Claims',
      'View Staff Claim details',
      'Approve or reject Staff Claims',
    ],
  },
}

export function isRole(value: unknown): value is Role {
  return typeof value === 'string' && (ROLES as readonly string[]).includes(value)
}

export function roleLabel(role: unknown): string {
  return isRole(role) ? ROLE_LABELS[role] : 'Unknown role'
}

export function isAuthUser(value: unknown): value is AuthUser {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return typeof v.id === 'number'
    && typeof v.email === 'string' && v.email.length > 0
    && typeof v.display_name === 'string'
    && isRole(v.role)
}

/** Keeps only well-formed users from an untrusted API payload. */
export function parseMockUsers(payload: unknown): AuthUser[] {
  return Array.isArray(payload) ? payload.filter(isAuthUser) : []
}

export interface RoleGroup {
  role: Role
  label: string
  users: AuthUser[]
}

/** Groups users by role in canonical order, omitting empty groups. */
export function groupUsersByRole(users: readonly AuthUser[]): RoleGroup[] {
  return ROLES
    .map(role => ({ role, label: ROLE_GROUP_LABELS[role], users: users.filter(u => u.role === role) }))
    .filter(group => group.users.length > 0)
}

/** Up to two initials (first + last word), falling back to the e-mail, then "?". */
export function getInitials(displayName: string | null | undefined, email?: string | null): string {
  const words = (displayName ?? '').trim().split(/\s+/).filter(Boolean)
  const letters = (word: string) => Array.from(word)[0] ?? ''
  if (words.length >= 2) return (letters(words[0]!) + letters(words[words.length - 1]!)).toUpperCase()
  if (words.length === 1) return letters(words[0]!).toUpperCase()
  const fromEmail = letters((email ?? '').trim())
  return fromEmail ? fromEmail.toUpperCase() : '?'
}

const AVATAR_COLOURS = ['#1967d2', '#188038', '#a50e0e', '#8430ce', '#0b6e7f', '#b06000'] as const

/** Deterministic avatar background; every colour gives >= 4.5:1 with white initials. */
export function avatarColour(seed: string): string {
  let hash = 0
  for (const ch of seed) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLOURS[hash % AVATAR_COLOURS.length]!
}

export const DEFAULT_COOKIE_MAX_AGE = 3600
const MAX_COOKIE_MAX_AGE = 60 * 60 * 24 * 7

/** Cookie lifetime in seconds from the API's `expires_in`; invalid values fall back to one hour. */
export function authCookieMaxAge(expiresIn: unknown): number {
  if (typeof expiresIn !== 'number' || !Number.isFinite(expiresIn) || expiresIn < 1) {
    return DEFAULT_COOKIE_MAX_AGE
  }
  return Math.min(Math.floor(expiresIn), MAX_COOKIE_MAX_AGE)
}

/** Extracts an HTTP status from an ofetch/FetchError-like value; undefined for network errors. */
export function extractStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) return undefined
  const e = error as { status?: unknown, statusCode?: unknown, response?: { status?: unknown } }
  for (const candidate of [e.statusCode, e.status, e.response?.status]) {
    if (typeof candidate === 'number' && candidate >= 100) return candidate
  }
  return undefined
}

export type AuthAction = 'list-users' | 'login'

/** User-facing message for an auth API failure (never echoes server text or tokens). */
export function authErrorMessage(status: number | undefined, action: AuthAction): string {
  if (status === undefined) return 'Cannot reach the API. Check that the backend is running and try again.'
  if (status === 404) return 'Mock sign-in is disabled on this server.'
  if (action === 'login') {
    if (status === 401) return 'That mock account was not recognised. Please choose another.'
    if (status === 403) return 'That account is inactive and cannot sign in.'
  }
  if (status >= 500) return 'The server had a problem. Please try again in a moment.'
  return 'Something went wrong. Please try again.'
}

/** Picks the API base URL: private container-network URL during SSR, public URL in the browser. */
export function resolveApiBase(opts: { isServer: boolean, publicBase: string, serverBase?: string | null }): string {
  const chosen = opts.isServer && opts.serverBase ? opts.serverBase : opts.publicBase
  return chosen.replace(/\/+$/, '')
}
