import { describe, expect, it } from 'vitest'
import { approvalsHeading, canUseChat, chatTabLabel, hasAnyAccess, homePath, isTabActive, navTabs, routeRedirect } from '../app/utils/access'
import { normalizeUser, parseMockUsers, userSubtitle } from '../app/utils/auth'

const amy = { can_request: true, approves: null }
const cathy = { can_request: true, approves: 'leave' as const }
const helen = { can_request: false, approves: 'leave' as const }
const eva = { can_request: false, approves: 'claim' as const }
const nobody = { can_request: false, approves: null }

describe('user shape (Phase 3 fields)', () => {
  const full = {
    id: 3, email: 'cathy.ng@example.com', display_name: 'Cathy Ng', role: 'hr_approver',
    department: { id: 2, name: 'HR' }, job_title: 'HR Business Partner (IT)', can_request: true, approves: 'leave',
  }

  it('keeps the new fields when present', () => {
    expect(normalizeUser(full)).toEqual(full)
  })

  it('treats missing fields (older API) as null / false', () => {
    const old = normalizeUser({ id: 1, email: 'a@example.com', display_name: 'A', role: 'employee' })
    expect(old).toMatchObject({ department: null, job_title: null, can_request: false, approves: null })
  })

  it('rejects junk values for the new fields instead of trusting them', () => {
    const user = normalizeUser({ ...full, department: 'HR', job_title: 5, can_request: 'yes', approves: 'everything' })
    expect(user).toMatchObject({ department: null, job_title: null, can_request: false, approves: null })
    expect(normalizeUser({ id: 1 })).toBeNull()
  })

  it('parses a six-user list and builds the account subtitle', () => {
    const users = parseMockUsers([full, { ...full, id: 4, email: 'b@example.com' }, { bad: true }])
    expect(users).toHaveLength(2)
    expect(userSubtitle(users[0]!)).toBe('HR Business Partner (IT) · HR')
    expect(userSubtitle({ job_title: null, department: { id: 1, name: 'IT' } })).toBe('IT')
    expect(userSubtitle({ job_title: null, department: null })).toBe('')
  })
})

describe('landing page after sign-in', () => {
  it('goes to the chat when the user can request, else to approvals, else to /no-access', () => {
    expect(homePath(amy)).toBe('/')
    expect(homePath(cathy)).toBe('/')
    expect(homePath(helen)).toBe('/approvals')
    expect(homePath(eva)).toBe('/approvals')
    expect(homePath(nobody)).toBe('/no-access')
    expect(homePath(null)).toBe('/login')
  })

  it('knows whether a user has any screen at all', () => {
    expect(hasAnyAccess(amy)).toBe(true)
    expect(hasAnyAccess(eva)).toBe(true)
    expect(hasAnyAccess(nobody)).toBe(false)
  })
})

describe('route rules', () => {
  it('sends anonymous visitors to /login and lets them see /login', () => {
    expect(routeRedirect(null, '/')).toBe('/login')
    expect(routeRedirect(null, '/approvals')).toBe('/login')
    expect(routeRedirect(null, '/login')).toBeNull()
  })

  it('bounces signed-in users away from /login to their own home', () => {
    expect(routeRedirect(amy, '/login')).toBe('/')
    expect(routeRedirect(helen, '/login')).toBe('/approvals')
  })

  it('/ is open to users who file requests or approve something (the bell inbox lives there)', () => {
    expect(routeRedirect(amy, '/')).toBeNull()
    expect(routeRedirect(cathy, '/')).toBeNull()
    expect(routeRedirect(helen, '/')).toBeNull()
    expect(routeRedirect(eva, '/')).toBeNull()
    expect(routeRedirect(nobody, '/')).toBe('/no-access')
    expect(canUseChat(helen)).toBe(true)
    expect(canUseChat(nobody)).toBe(false)
    expect(canUseChat(null)).toBe(false)
  })

  it('/approvals and its children need approves', () => {
    expect(routeRedirect(cathy, '/approvals')).toBeNull()
    expect(routeRedirect(eva, '/approvals/claim/9')).toBeNull()
    expect(routeRedirect(amy, '/approvals')).toBe('/')
    expect(routeRedirect(amy, '/approvals/leave/12')).toBe('/')
    expect(routeRedirect(nobody, '/approvals')).toBe('/no-access')
    expect(routeRedirect(amy, '/approvals?x=1')).toBe('/')
  })

  it('does not treat a look-alike path as /approvals', () => {
    expect(routeRedirect(amy, '/approvals-archive')).toBeNull()
  })

  it('/no-access is only for users with nothing else to do', () => {
    expect(routeRedirect(nobody, '/no-access')).toBeNull()
    expect(routeRedirect(amy, '/no-access')).toBe('/')
    expect(routeRedirect(eva, '/no-access')).toBe('/approvals')
  })
})

describe('navigation tabs', () => {
  const keys = (u: typeof amy) => navTabs(u).map(t => t.label)

  it('shows only the tabs a user may use (Cathy both; Amy chat; Helen and Eva Inbox and Approvals)', () => {
    expect(keys(amy)).toEqual(['My requests'])
    expect(keys(cathy)).toEqual(['My requests', 'Approvals'])
    expect(keys(helen)).toEqual(['Inbox', 'Approvals'])
    expect(keys(eva)).toEqual(['Inbox', 'Approvals'])
    expect(keys(nobody)).toEqual([])
    expect(navTabs(null)).toEqual([])
  })

  it('labels the chat tab "My requests" for requesters and "Inbox" for approve-only users', () => {
    expect(chatTabLabel(amy)).toBe('My requests')
    expect(chatTabLabel(cathy)).toBe('My requests')
    expect(chatTabLabel(helen)).toBe('Inbox')
    expect(chatTabLabel(eva)).toBe('Inbox')
  })

  it('marks the current tab (the chat tab only on exactly "/")', () => {
    const [requests, approvals] = navTabs(cathy)
    expect(isTabActive(requests!, '/')).toBe(true)
    expect(isTabActive(requests!, '/approvals')).toBe(false)
    expect(isTabActive(approvals!, '/approvals')).toBe(true)
    expect(isTabActive(approvals!, '/approvals/leave/12')).toBe(true)
    expect(isTabActive(approvals!, '/approvals-archive')).toBe(false)
  })

  it('titles the approvals page by scope', () => {
    expect(approvalsHeading('leave')).toBe('Leave approvals')
    expect(approvalsHeading('claim')).toBe('Claim approvals')
    expect(approvalsHeading(null)).toBe('Approvals')
  })
})
