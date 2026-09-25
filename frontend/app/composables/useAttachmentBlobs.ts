interface BlobEntry {
  refs: number
  objectUrl: string | null
  promise: Promise<string>
}

// Shared by every thumbnail of the same file (message bubble and card): one download, one object URL.
// Module-level on purpose; it is only touched from mounted components in the browser.
const cache = new Map<string, BlobEntry>()

/**
 * Loads attachment files as object URLs. Files are fetched with `useApi` (session cookie, CSRF header,
 * cross-origin credentials), never through a plain `<img src>`. Every `acquire` must be paired with a `release`;
 * the object URL is revoked when the last user releases it.
 */
export function useAttachmentBlobs() {
  const api = useApi()

  function acquire(path: string): Promise<string> {
    const existing = cache.get(path)
    if (existing) {
      existing.refs++
      return existing.promise
    }
    const entry: BlobEntry = {
      refs: 1,
      objectUrl: null,
      promise: Promise.resolve(''),
    }
    entry.promise = api<Blob>(path, { responseType: 'blob' }).then((blob) => {
      const url = URL.createObjectURL(blob)
      if (entry.refs <= 0) {
        URL.revokeObjectURL(url) // everyone left while it was loading
        cache.delete(path)
        return url
      }
      entry.objectUrl = url
      return url
    })
    entry.promise.catch(() => {
      // A failed download is not cached, so a later attempt can succeed.
      if (cache.get(path) === entry) cache.delete(path)
    })
    cache.set(path, entry)
    return entry.promise
  }

  function release(path: string) {
    const entry = cache.get(path)
    if (!entry) return
    entry.refs--
    if (entry.refs > 0) return
    if (entry.objectUrl) URL.revokeObjectURL(entry.objectUrl)
    cache.delete(path)
  }

  return { acquire, release }
}
