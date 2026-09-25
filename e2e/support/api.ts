import { request, type APIRequestContext, type APIResponse } from '@playwright/test'
import { API_URL } from './env.mjs'
import { USERS, type UserName } from './users'

/** The CSRF marker every unsafe request must carry (README, "Session cookie"). */
export const CSRF = { 'X-Requested-With': 'XMLHttpRequest' } as const

/** A signed-in API client: real login through the API, session cookie kept by the request context. */
export class ApiClient {
  constructor(readonly ctx: APIRequestContext, readonly user: UserName) {}

  get(path: string): Promise<APIResponse> {
    return this.ctx.get(path)
  }

  post(path: string, data?: unknown): Promise<APIResponse> {
    return this.ctx.post(path, { headers: CSRF, data })
  }

  /** GET and parse JSON, failing loudly on a non-2xx answer. */
  async json<T = any>(path: string): Promise<T> { // eslint-disable-line @typescript-eslint/no-explicit-any
    const res = await this.get(path)
    if (!res.ok()) throw new Error(`GET ${path} as ${this.user}: ${res.status()} ${await res.text()}`)
    return (await res.json()) as T
  }

  dispose(): Promise<void> {
    return this.ctx.dispose()
  }
}

/** Signs in as a seeded user through the mock Google endpoint and returns the client. */
export async function apiAs(user: UserName): Promise<ApiClient> {
  const ctx = await request.newContext({ baseURL: API_URL })
  const res = await ctx.post('/api/auth/mock-google/login', { headers: CSRF, data: { email: USERS[user] } })
  if (!res.ok()) throw new Error(`API login as ${user} failed: ${res.status()} ${await res.text()}`)
  return new ApiClient(ctx, user)
}

export interface ApprovalItem {
  request_type: 'leave' | 'claim'
  id: number
  employee: { id: number, display_name: string, department: string | null }
  summary: string
}

/** The caller's approval queue (pending items assigned to them). */
export async function approvalQueue(api: ApiClient): Promise<ApprovalItem[]> {
  return (await api.json<{ items: ApprovalItem[] }>('/api/approvals')).items
}
