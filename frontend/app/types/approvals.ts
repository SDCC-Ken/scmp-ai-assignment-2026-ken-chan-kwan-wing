/** Types for the Phase 3 approval API (see docs/phase3-approval-design.md, section 5). All data is fictional. */
import type { AttachmentInfo, RequestStatus, RequestType } from './chat'

export interface ApprovalEmployee {
  id: number
  display_name: string
  department: string | null
}

export interface ApprovalFlags {
  over_limit: boolean
  team_overlap_count: number
  has_attachments: boolean
}

export interface ApprovalListItem {
  request_type: RequestType
  id: number
  employee: ApprovalEmployee
  summary: string
  submitted_at: string | null
  flags: ApprovalFlags
}

export interface ApprovalList {
  items: ApprovalListItem[]
  count: number
}

export interface ApprovalField {
  key: string
  label: string
  value: string
}

export interface LeaveBalanceLimit {
  leave_type: string
  year: number
  entitled_days: number
  approved_days: number
  pending_other_days: number
  requested_days: number
  remaining_after_days: number
  over_limit: boolean
}

/** Money values are decimal strings (for example "60000.00"). */
export interface DepartmentBudgetLimit {
  department: string
  year: number
  limit_amount: string
  approved_amount: string
  pending_other_amount: string
  requested_amount: string
  remaining_after_amount: string
  over_limit: boolean
  currency: string
}

export interface TeamOverlapEntry {
  employee: string
  leave_type: string
  start_date: string
  end_date: string
  status: RequestStatus | string
  working_days: number
}

export interface ApprovalDetail {
  request: {
    request_type: RequestType
    id: number
    status: RequestStatus | string
    submitted_at: string | null
    employee: ApprovalEmployee
    fields: ApprovalField[]
    attachments: AttachmentInfo[]
    external_reference_id: string | null
  }
  limits: {
    leave_balance: LeaveBalanceLimit | null
    department_budget: DepartmentBudgetLimit | null
  }
  team_overlap: TeamOverlapEntry[]
  warnings: string[]
}

export type Decision = 'approve' | 'reject'

export interface DecisionBody {
  decision: Decision
  note: string | null
}

export interface DecisionResult {
  request_type: RequestType
  id: number
  status: string
  reviewed_at: string | null
}
