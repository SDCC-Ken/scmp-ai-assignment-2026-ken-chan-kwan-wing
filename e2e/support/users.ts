// The six fictional seed users (docs/phase3-approval-design.md, section 1).
export const USERS = {
  'Amy Lau': 'amy.lau@example.com', // IT employee; leave: Cathy, claims: Eva
  'Ben Chow': 'ben.chow@example.com',
  'Cathy Ng': 'cathy.ng@example.com', // HR approver: decides IT leave
  'Daniel Wong': 'daniel.wong@example.com',
  'Helen Yeung': 'helen.yeung@example.com', // HR manager: decides HR leave
  'Eva Cheung': 'eva.cheung@example.com', // Finance approver: decides all claims
} as const

export type UserName = keyof typeof USERS
