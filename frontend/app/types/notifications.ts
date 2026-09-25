/** Types for the Phase 3 notification API (see docs/phase3-approval-design.md, section 4 and 5). */
import type { RequestType } from './chat'

export interface AppNotification {
  id: number
  event_type: string
  /** Plain text: always render as text, never as HTML. */
  title: string
  body: string
  request_type: RequestType | null
  request_id: number | null
  read_at: string | null
  created_at: string
  /** Set for approvers (navigate); null for requesters (open the detail dialog). */
  link: string | null
}

export interface NotificationList {
  items: AppNotification[]
  unread_count: number
}
