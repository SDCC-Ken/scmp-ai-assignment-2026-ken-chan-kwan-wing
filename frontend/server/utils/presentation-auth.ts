import { createHmac, timingSafeEqual } from 'node:crypto'
import type { H3Event } from 'h3'

const COOKIE = 'scmp_presentation_access'

function password(event: H3Event) {
  return String(useRuntimeConfig(event).presentationPassword || '')
}

function token(value: string) {
  return createHmac('sha256', value).update('scmp-presentation-controller-v1').digest('hex')
}

function equal(a: string, b: string) {
  const aa = Buffer.from(a)
  const bb = Buffer.from(b)
  return aa.length === bb.length && timingSafeEqual(aa, bb)
}

export function hasPresentationAccess(event: H3Event) {
  const value = password(event)
  return Boolean(value) && equal(getCookie(event, COOKIE) || '', token(value))
}

export function grantPresentationAccess(event: H3Event, suppliedPassword: string) {
  const value = password(event)
  if (!value || !equal(suppliedPassword, value)) return false
  setCookie(event, COOKIE, token(value), { httpOnly: true, sameSite: 'lax', path: '/', maxAge: 24 * 60 * 60 })
  return true
}

export function requirePresentationAccess(event: H3Event) {
  if (!hasPresentationAccess(event)) {
    throw createError({ statusCode: 401, statusMessage: 'Presentation access required' })
  }
}
