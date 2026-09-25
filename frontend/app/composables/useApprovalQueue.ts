import type { ApprovalList, ApprovalListItem } from '~/types/approvals'

/**
 * The signed-in approver's pending queue (`GET /api/approvals`), shared by the header badge and the list page.
 * A background refresh (the 30 s poll) keeps what is on screen when it fails; a foreground load reports errors.
 */
export function useApprovalQueue() {
  const api = useApi()
  const items = useState<ApprovalListItem[]>('approvals-items', () => [])
  const loaded = useState<boolean>('approvals-loaded', () => false)
  const error = useState<string | null>('approvals-error', () => null)
  /** One-shot message from the detail page ("You approved leave request #12 ...", or the 409 explanation). */
  const flash = useState<{ tone: 'green' | 'amber', text: string } | null>('approvals-flash', () => null)
  const loading = ref(false)
  const count = computed(() => items.value.length)

  async function refresh(options: { background?: boolean } = {}) {
    loading.value = true
    if (!options.background) error.value = null
    try {
      const data = await api<Partial<ApprovalList>>('/api/approvals')
      items.value = Array.isArray(data.items) ? data.items : []
      loaded.value = true
      error.value = null
    }
    catch (cause) {
      if (!options.background || !loaded.value) error.value = approvalErrorMessage(extractStatus(cause), 'list')
    }
    finally {
      loading.value = false
    }
  }

  return { items, count, loaded, loading, error, flash, refresh }
}
