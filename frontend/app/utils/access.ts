/** Role-aware access and navigation rules (pure; unit-tested in tests/access.test.ts). */
import type { ApprovalScope, AuthUser } from './auth'

type Capabilities = Pick<AuthUser, 'can_request' | 'approves'>

export const NO_ACCESS_PATH = '/no-access'

/** Where a signed-in user lands: the chat when they may file requests, else their approvals queue, else "no access". */
export function homePath(user: Capabilities | null | undefined): string {
  if (!user) return '/login'
  if (user.can_request) return '/'
  if (user.approves) return '/approvals'
  return NO_ACCESS_PATH
}

export function hasAnyAccess(user: Capabilities | null | undefined): boolean {
  return !!user && (user.can_request || user.approves !== null)
}

/** The chat (`/`) is open to users who file requests and to users who approve something (the bell inbox lives there). */
export function canUseChat(user: Capabilities | null | undefined): boolean {
  return !!user && (user.can_request || user.approves !== null)
}

/**
 * Route rule for the global middleware. Returns the path to redirect to, or null when the route is allowed.
 * `/` needs can_request or approves; `/approvals*` needs approves; `/no-access` is only for users who have nothing else.
 */
export function routeRedirect(user: Capabilities | null | undefined, path: string): string | null {
  const clean = path.split(/[?#]/)[0] || '/'
  if (clean === '/login') return user ? homePath(user) : null
  if (!user) return '/login'
  if (clean === '/') return canUseChat(user) ? null : homePath(user)
  if (clean === '/approvals' || clean.startsWith('/approvals/')) return user.approves ? null : homePath(user)
  if (clean === NO_ACCESS_PATH) return hasAnyAccess(user) ? homePath(user) : null
  return null
}

export interface NavTab {
  key: 'requests' | 'approvals'
  label: string
  to: string
}

/** Label of the chat tab: "My requests" for people who file requests, "Inbox" for approve-only users. */
export function chatTabLabel(user: Capabilities | null | undefined): string {
  return user?.can_request ? 'My requests' : 'Inbox'
}

/** Header tabs the user may use, in a fixed order. */
export function navTabs(user: Capabilities | null | undefined): NavTab[] {
  const tabs: NavTab[] = []
  if (canUseChat(user)) tabs.push({ key: 'requests', label: chatTabLabel(user), to: '/' })
  if (user?.approves) tabs.push({ key: 'approvals', label: 'Approvals', to: '/approvals' })
  return tabs
}

/** True when the tab is the current section (`/` is only current on exactly `/`). */
export function isTabActive(tab: NavTab, path: string): boolean {
  return tab.to === '/' ? path === '/' : path === tab.to || path.startsWith(`${tab.to}/`)
}

export function approvalsHeading(approves: ApprovalScope | null | undefined): string {
  if (approves === 'leave') return 'Leave approvals'
  if (approves === 'claim') return 'Claim approvals'
  return 'Approvals'
}
