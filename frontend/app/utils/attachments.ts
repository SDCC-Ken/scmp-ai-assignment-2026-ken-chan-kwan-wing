/** Pure attachment helpers (validation, sizes, MIME mapping, staged-file state machine); tested in tests/attachments.test.ts. */
import type { AttachmentInfo } from '../types/chat'
import { MAX_MESSAGE_LENGTH } from './chat'

export const MAX_FILE_MB = 5
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
export const MAX_FILES_PER_MESSAGE = 3

export const ALLOWED_MIME_TYPES = [
  'image/jpeg',
  'image/png',
  'image/webp',
  'image/heic',
  'image/heif',
  'application/pdf',
] as const

export type AllowedMime = (typeof ALLOWED_MIME_TYPES)[number]

/** Value for the `accept` attribute of the file input (types plus extensions, since HEIC often has no MIME type). */
export const ACCEPT_ATTRIBUTE = [...ALLOWED_MIME_TYPES, '.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.pdf'].join(',')

const EXTENSION_MIME: Readonly<Record<string, AllowedMime>> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  heic: 'image/heic',
  heif: 'image/heif',
  pdf: 'application/pdf',
}

const MIME_EXTENSION: Readonly<Record<AllowedMime, string>> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'image/heic': 'heic',
  'image/heif': 'heif',
  'application/pdf': 'pdf',
}

export function isAllowedMime(value: string): value is AllowedMime {
  return (ALLOWED_MIME_TYPES as readonly string[]).includes(value)
}

/** File extension without the dot, lower-case ("" when none). */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toLowerCase() : ''
}

export function extensionForMime(mime: string): string {
  return isAllowedMime(mime) ? MIME_EXTENSION[mime] : ''
}

/**
 * The allowed MIME type of a picked file, or null. The browser's type wins; the extension is only used when
 * the browser gives none (typical for HEIC) or a generic one. A wrong type (e.g. text/plain named .pdf) is rejected.
 */
export function resolveMime(file: { name: string, type: string }): AllowedMime | null {
  const declared = file.type.toLowerCase().split(';')[0]!.trim()
  const type = declared === 'image/jpg' || declared === 'image/pjpeg' ? 'image/jpeg' : declared
  if (isAllowedMime(type)) return type
  if (type === '' || type === 'application/octet-stream') return EXTENSION_MIME[fileExtension(file.name)] ?? null
  return null
}

/** "512 B", "183 KB", "7.2 MB" (1 MB = 1024 * 1024 bytes, the same unit as the 5 MB limit). */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(/\.0$/, '')} MB`
}

export type FileRejection = 'count' | 'type' | 'empty' | 'size'

export type FileCheck =
  | { ok: true, mime: AllowedMime }
  | { ok: false, reason: FileRejection, message: string }

export const COUNT_MESSAGE = `You can attach up to ${MAX_FILES_PER_MESSAGE} files to one message.`

/** Checks one picked file against the limits. `currentCount` = files already staged (or accepted earlier in the same batch). */
export function validateAttachment(file: { name: string, size: number, type: string }, currentCount: number): FileCheck {
  if (currentCount >= MAX_FILES_PER_MESSAGE) return { ok: false, reason: 'count', message: COUNT_MESSAGE }
  const mime = resolveMime(file)
  if (!mime) {
    return { ok: false, reason: 'type', message: `${file.name} is not a supported file type. Attach a JPEG, PNG, WebP, HEIC or PDF file.` }
  }
  if (file.size <= 0) return { ok: false, reason: 'empty', message: `${file.name} is empty.` }
  if (file.size > MAX_FILE_BYTES) {
    return { ok: false, reason: 'size', message: `${file.name} is ${formatBytes(file.size)}; the limit is ${MAX_FILE_MB} MB.` }
  }
  return { ok: true, mime }
}

export interface SelectionResult<T> {
  accepted: { file: T, mime: AllowedMime }[]
  errors: string[]
}

/** Validates a whole selection (button, drop or paste); the "too many files" message appears once. */
export function validateSelection<T extends { name: string, size: number, type: string }>(files: readonly T[], currentCount: number): SelectionResult<T> {
  const accepted: SelectionResult<T>['accepted'] = []
  const errors: string[] = []
  for (const file of files) {
    const check = validateAttachment(file, currentCount + accepted.length)
    if (check.ok) accepted.push({ file, mime: check.mime })
    else if (!errors.includes(check.message)) errors.push(check.message)
  }
  return { accepted, errors }
}

/** Name for a pasted screenshot, which browsers call just "image.png". */
export function pastedFileName(mime: string, now: Date = new Date()): string {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15)
  return `pasted-image-${stamp}.${extensionForMime(mime) || 'png'}`
}

export type AttachmentKind = 'image' | 'pdf' | 'other'

export function attachmentKind(contentType: string): AttachmentKind {
  if (contentType.startsWith('image/')) return 'image'
  if (contentType === 'application/pdf') return 'pdf'
  return 'other'
}

/* ---- Staged files (state machine: uploading -> uploaded | error; error -> uploading on retry) ---- */

export type StagedStatus = 'uploading' | 'uploaded' | 'error'

export interface StagedFile {
  localId: string
  /** The (MIME-normalised) file to upload; kept so Retry can upload again. */
  file: Blob
  name: string
  size: number
  mime: string
  /** Object URL for the thumbnail (images only); the owner revokes it when the chip goes away. */
  previewUrl: string | null
  status: StagedStatus
  attachment: AttachmentInfo | null
  error: string | null
}

export function newStagedFile(localId: string, file: Blob, name: string, mime: string, previewUrl: string | null): StagedFile {
  return { localId, file, name, size: file.size, mime, previewUrl, status: 'uploading', attachment: null, error: null }
}

function patch(list: readonly StagedFile[], localId: string, change: Partial<StagedFile>): StagedFile[] {
  return list.map(item => (item.localId === localId ? { ...item, ...change } : item))
}

export function markUploaded(list: readonly StagedFile[], localId: string, attachment: AttachmentInfo): StagedFile[] {
  return patch(list, localId, { status: 'uploaded', attachment, error: null })
}

export function markUploadFailed(list: readonly StagedFile[], localId: string, error: string): StagedFile[] {
  return patch(list, localId, { status: 'error', attachment: null, error })
}

/** Only a failed file can be retried; anything else is returned unchanged. */
export function markRetrying(list: readonly StagedFile[], localId: string): StagedFile[] {
  return list.map(item => (item.localId === localId && item.status === 'error' ? { ...item, status: 'uploading' as const, error: null } : item))
}

export function removeStaged(list: readonly StagedFile[], localId: string): StagedFile[] {
  return list.filter(item => item.localId !== localId)
}

export const isUploading = (list: readonly StagedFile[]) => list.some(item => item.status === 'uploading')
export const hasUploadError = (list: readonly StagedFile[]) => list.some(item => item.status === 'error')

/** Server ids of the files that are ready to be sent, in the order they were added. */
export function uploadedIds(list: readonly StagedFile[]): number[] {
  return list.flatMap(item => (item.status === 'uploaded' && item.attachment ? [item.attachment.id] : []))
}

/**
 * Send rule: text (trimmed, at most 1000 characters) or at least one uploaded file; nothing may be uploading
 * or failed (a failed chip must be retried or removed, so no file is dropped silently); no turn in flight.
 */
export function canSendMessage(text: string, staged: readonly StagedFile[], busy: boolean): boolean {
  if (busy || isUploading(staged) || hasUploadError(staged)) return false
  const trimmed = text.trim()
  if (trimmed.length > MAX_MESSAGE_LENGTH) return false
  return trimmed.length > 0 || uploadedIds(staged).length > 0
}

/** Friendly text for a failed upload (never echoes server text). `status` undefined = network error. */
export function uploadErrorMessage(status: number | undefined): string {
  if (status === undefined) return 'Upload failed: cannot reach the server.'
  if (status === 413) return `The server says this file is over the ${MAX_FILE_MB} MB limit.`
  if (status === 415) return 'This file type is not supported, or the file does not match its type.'
  if (status === 422) return 'The server did not accept this upload (too many files, or no file).'
  if (status === 404) return 'This conversation no longer exists.'
  if (status === 403) return 'Uploads are available to employees only.'
  if (status >= 500) return 'The server had a problem with this upload.'
  return 'This file could not be uploaded.'
}

/** Text of the download placeholder for a failed fetch (404 = the file is gone). */
export function downloadErrorMessage(status: number | undefined): string {
  return status === 404 ? 'File unavailable' : 'Could not load file'
}
