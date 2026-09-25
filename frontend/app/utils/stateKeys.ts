/** `useState` keys that hold data of the signed-in user; cleared on sign-in and sign-out so nothing leaks between accounts. */
export const USER_SCOPED_STATE_KEYS = [
  'notif-unread',
  'inbox-handoff',
  'approvals-items',
  'approvals-loaded',
  'approvals-error',
  'approvals-flash',
] as const
