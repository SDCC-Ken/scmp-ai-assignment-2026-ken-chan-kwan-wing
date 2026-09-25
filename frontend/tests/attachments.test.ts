import { describe, expect, it } from 'vitest'
import {
  attachmentKind,
  canSendMessage,
  downloadErrorMessage,
  extensionForMime,
  formatBytes,
  hasUploadError,
  isUploading,
  markRetrying,
  markUploaded,
  markUploadFailed,
  MAX_FILE_BYTES,
  newStagedFile,
  pastedFileName,
  removeStaged,
  resolveMime,
  uploadedIds,
  uploadErrorMessage,
  validateAttachment,
  validateSelection,
} from '../app/utils/attachments'
import type { StagedFile } from '../app/utils/attachments'
import type { AttachmentInfo } from '../app/types/chat'

const info = (id: number): AttachmentInfo => ({
  id,
  filename: `f${id}.pdf`,
  content_type: 'application/pdf',
  size_bytes: 1000,
  url: `/api/attachments/${id}`,
  created_at: '2026-09-25T03:00:00Z',
})

const staged = (localId: string): StagedFile => newStagedFile(localId, new Blob(['x']), `${localId}.pdf`, 'application/pdf', null)
const file = (name: string, size: number, type: string) => ({ name, size, type })

describe('formatBytes', () => {
  it('formats bytes, kilobytes and megabytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(183_204)).toBe('179 KB')
    expect(formatBytes(7_549_747)).toBe('7.2 MB')
    expect(formatBytes(MAX_FILE_BYTES)).toBe('5 MB')
  })

  it('returns an empty string for invalid sizes', () => {
    expect(formatBytes(-1)).toBe('')
    expect(formatBytes(Number.NaN)).toBe('')
  })
})

describe('MIME resolution', () => {
  it('accepts every allowed type as declared by the browser', () => {
    for (const type of ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif', 'application/pdf']) {
      expect(resolveMime({ name: 'x', type })).toBe(type)
    }
    expect(resolveMime({ name: 'x.jpg', type: 'image/jpg' })).toBe('image/jpeg')
  })

  it('falls back to the extension only when the browser gives no useful type (HEIC)', () => {
    expect(resolveMime({ name: 'IMG_0001.HEIC', type: '' })).toBe('image/heic')
    expect(resolveMime({ name: 'scan.pdf', type: 'application/octet-stream' })).toBe('application/pdf')
    expect(resolveMime({ name: 'notes.txt', type: '' })).toBeNull()
  })

  it('rejects a declared type that is not allowed, even when the extension is', () => {
    expect(resolveMime({ name: 'fake.pdf', type: 'text/plain' })).toBeNull()
    expect(resolveMime({ name: 'a.gif', type: 'image/gif' })).toBeNull()
  })

  it('maps MIME types back to extensions', () => {
    expect(extensionForMime('image/jpeg')).toBe('jpg')
    expect(extensionForMime('application/pdf')).toBe('pdf')
    expect(extensionForMime('text/plain')).toBe('')
  })
})

describe('file validation', () => {
  it('accepts a valid file', () => {
    expect(validateAttachment(file('note.pdf', 1000, 'application/pdf'), 0)).toEqual({ ok: true, mime: 'application/pdf' })
  })

  it('rejects an oversize file with the size in the message', () => {
    const result = validateAttachment(file('clinic-note.pdf', 7_549_747, 'application/pdf'), 0)
    expect(result).toEqual({ ok: false, reason: 'size', message: 'clinic-note.pdf is 7.2 MB; the limit is 5 MB.' })
  })

  it('allows exactly 5 MB but not one byte more', () => {
    expect(validateAttachment(file('a.png', MAX_FILE_BYTES, 'image/png'), 0).ok).toBe(true)
    expect(validateAttachment(file('a.png', MAX_FILE_BYTES + 1, 'image/png'), 0).ok).toBe(false)
  })

  it('rejects wrong types, empty files and a fourth file', () => {
    expect(validateAttachment(file('a.gif', 10, 'image/gif'), 0)).toMatchObject({ ok: false, reason: 'type' })
    expect(validateAttachment(file('a.png', 0, 'image/png'), 0)).toMatchObject({ ok: false, reason: 'empty' })
    expect(validateAttachment(file('a.png', 10, 'image/png'), 3)).toMatchObject({ ok: false, reason: 'count' })
  })

  it('validates a selection, keeps the valid files and reports "too many" once', () => {
    const result = validateSelection([
      file('a.png', 10, 'image/png'),
      file('b.gif', 10, 'image/gif'),
      file('c.pdf', 10, 'application/pdf'),
      file('d.pdf', 10, 'application/pdf'),
      file('e.pdf', 10, 'application/pdf'),
      file('f.pdf', 10, 'application/pdf'),
    ], 0)
    expect(result.accepted.map(a => a.file.name)).toEqual(['a.png', 'c.pdf', 'd.pdf'])
    expect(result.errors).toHaveLength(2)
    expect(result.errors[0]).toMatch(/b\.gif is not a supported file type/)
    expect(result.errors[1]).toMatch(/up to 3 files/)
  })

  it('counts files that are already staged', () => {
    const result = validateSelection([file('a.png', 10, 'image/png'), file('b.png', 10, 'image/png')], 2)
    expect(result.accepted).toHaveLength(1)
    expect(result.errors).toHaveLength(1)
  })
})

describe('naming and kinds', () => {
  it('names a pasted screenshot from the time and type', () => {
    expect(pastedFileName('image/png', new Date('2026-09-25T03:05:09Z'))).toBe('pasted-image-20260925-030509.png')
    expect(pastedFileName('image/jpeg', new Date('2026-09-25T03:05:09Z'))).toMatch(/\.jpg$/)
  })

  it('classifies attachments for display', () => {
    expect(attachmentKind('image/heic')).toBe('image')
    expect(attachmentKind('application/pdf')).toBe('pdf')
    expect(attachmentKind('text/plain')).toBe('other')
  })
})

describe('staged-file state machine', () => {
  it('starts uploading and becomes uploaded with the server info', () => {
    let list = [staged('a')]
    expect(isUploading(list)).toBe(true)
    list = markUploaded(list, 'a', info(12))
    expect(list[0]).toMatchObject({ status: 'uploaded', error: null })
    expect(uploadedIds(list)).toEqual([12])
    expect(isUploading(list)).toBe(false)
  })

  it('records a failure, and only a failed file can be retried', () => {
    let list = [staged('a'), staged('b')]
    list = markUploadFailed(list, 'a', 'Nope')
    expect(list[0]).toMatchObject({ status: 'error', error: 'Nope' })
    expect(hasUploadError(list)).toBe(true)
    list = markRetrying(list, 'a')
    expect(list[0]).toMatchObject({ status: 'uploading', error: null })
    list = markUploaded(list, 'b', info(2))
    expect(markRetrying(list, 'b')[1]!.status).toBe('uploaded') // not failed: unchanged
  })

  it('keeps upload order for ids and removes one file without touching the others', () => {
    let list = [staged('a'), staged('b'), staged('c')]
    list = markUploaded(markUploaded(markUploaded(list, 'c', info(3)), 'a', info(1)), 'b', info(2))
    expect(uploadedIds(list)).toEqual([1, 2, 3])
    expect(uploadedIds(removeStaged(list, 'b'))).toEqual([1, 3])
  })

  it('never mutates its input', () => {
    const list = [staged('a')]
    markUploaded(list, 'a', info(1))
    expect(list[0]!.status).toBe('uploading')
  })
})

describe('send rule with attachments', () => {
  const ready = markUploaded([staged('a')], 'a', info(1))

  it('allows an empty text when a file is ready', () => {
    expect(canSendMessage('', ready, false)).toBe(true)
    expect(canSendMessage('   ', ready, false)).toBe(true)
  })

  it('needs text or a ready file', () => {
    expect(canSendMessage('', [], false)).toBe(false)
    expect(canSendMessage('hello', [], false)).toBe(true)
  })

  it('is blocked while an upload is in flight, after a failed upload, or during a turn', () => {
    expect(canSendMessage('hello', [staged('a')], false)).toBe(false)
    expect(canSendMessage('hello', markUploadFailed([staged('a')], 'a', 'x'), false)).toBe(false)
    expect(canSendMessage('hello', ready, true)).toBe(false)
  })

  it('still enforces the 1000 character limit on the trimmed text', () => {
    expect(canSendMessage('a'.repeat(1001), ready, false)).toBe(false)
    expect(canSendMessage(` ${'a'.repeat(1000)} `, ready, false)).toBe(true)
  })
})

describe('error messages', () => {
  it('maps upload statuses to friendly text', () => {
    expect(uploadErrorMessage(413)).toMatch(/over the 5 MB limit/)
    expect(uploadErrorMessage(415)).toMatch(/not supported/)
    expect(uploadErrorMessage(422)).toMatch(/too many files/)
    expect(uploadErrorMessage(undefined)).toMatch(/cannot reach the server/)
    expect(uploadErrorMessage(500)).toMatch(/server had a problem/)
  })

  it('shows "File unavailable" for a missing download', () => {
    expect(downloadErrorMessage(404)).toBe('File unavailable')
    expect(downloadErrorMessage(undefined)).toBe('Could not load file')
  })
})
