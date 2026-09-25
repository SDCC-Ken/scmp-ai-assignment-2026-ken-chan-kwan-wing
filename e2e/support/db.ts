import { execFileSync } from 'node:child_process'
import { DB_PATH } from './env.mjs'

export interface AuditRow {
  id: number
  actor_user_id: number | null
  entity_type: string
  entity_id: number | null
  event_type: string
  from_status: string | null
  to_status: string | null
}

/** Read-only look at the e2e database (sqlite3 CLI, `-readonly`). Never writes. */
function query<T>(sql: string): T[] {
  const out = execFileSync('sqlite3', ['-readonly', '-json', DB_PATH, sql], { encoding: 'utf8' }).trim()
  return out ? (JSON.parse(out) as T[]) : []
}

/** Audit events of one request (`entity_type` is "leave_request" or "claim_request"), oldest first. */
export function auditEvents(entityType: 'leave_request' | 'claim_request', entityId: number): AuditRow[] {
  return query<AuditRow>(
    'SELECT id, actor_user_id, entity_type, entity_id, event_type, from_status, to_status ' +
    `FROM audit_events WHERE entity_type = '${entityType}' AND entity_id = ${Number(entityId)} ORDER BY id`,
  )
}
