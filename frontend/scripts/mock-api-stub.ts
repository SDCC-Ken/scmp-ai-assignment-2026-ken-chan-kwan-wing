/**
 * DEV AID ONLY - a tiny stand-in for the backend auth contract on port 9181.
 * Run:  bun scripts/mock-api-stub.ts
 * Not used by tests, Docker or production; the real FastAPI backend replaces it.
 *
 * Contract (same as the FastAPI backend):
 *   POST /api/auth/mock-google/login {email} -> 200 {expires_in, user} + Set-Cookie scmp_session (HttpOnly, no token in body)
 *   GET  /api/auth/me                        -> user, authenticated from the cookie (401 otherwise)
 *   POST /api/auth/logout                    -> 204 and clears the cookie
 *   Every POST/PUT/PATCH/DELETE needs `X-Requested-With: XMLHttpRequest` (else 403 "CSRF check failed").
 *   CORS: explicit allowed origin + Access-Control-Allow-Credentials: true (credentials are used, so no "*").
 *
 * Extra dev endpoints (no CSRF header needed, so they work with plain curl):
 *   POST /__stub/expire  -> every later /api/auth/me returns 401 (cookie stays in the browser)
 *   POST /__stub/reset   -> clears that flag and the logout counter
 *   GET  /__stub/state   -> { expired, logouts }
 */
import { Buffer } from 'node:buffer'
import { createServer } from 'node:http'
import process from 'node:process'

const PORT = Number(process.env.API_PORT) || 9181
const ORIGIN = process.env.STUB_ALLOWED_ORIGIN || 'http://localhost:9180'
const COOKIE_NAME = 'scmp_session'
const MAX_AGE = 3600

const USERS = [
  { id: 1, email: 'amy.lau@example.com', display_name: 'Amy Lau', role: 'employee' },
  { id: 2, email: 'ben.wong@example.com', display_name: 'Ben Wong', role: 'employee' },
  { id: 3, email: 'chloe.cheung@example.com', display_name: 'Chloe Cheung', role: 'employee' },
  { id: 4, email: 'henry.ho@example.com', display_name: 'Henry Ho', role: 'hr_approver' },
  { id: 5, email: 'fiona.fung@example.com', display_name: 'Fiona Fung', role: 'finance_approver' },
]

let expired = false
let logouts = 0

function userFromCookie(header: string | undefined) {
  const pair = (header ?? '').split(';').map(p => p.trim()).find(p => p.startsWith(`${COOKIE_NAME}=`))
  const value = pair?.slice(COOKIE_NAME.length + 1) ?? ''
  if (!value.startsWith('stub.')) return undefined
  const email = Buffer.from(value.slice('stub.'.length), 'base64url').toString()
  return USERS.find(u => u.email === email)
}

const sessionCookie = (value: string, maxAge: number) =>
  `${COOKIE_NAME}=${value}; HttpOnly; SameSite=Lax; Path=/; Max-Age=${maxAge}`

createServer((req, res) => {
  const send = (status: number, body?: unknown, extraHeaders: Record<string, string> = {}) => {
    res.writeHead(status, {
      'access-control-allow-origin': ORIGIN,
      'access-control-allow-credentials': 'true',
      'access-control-allow-headers': 'content-type, x-requested-with',
      'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      vary: 'Origin',
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
      ...extraHeaders,
    })
    res.end(body === undefined ? undefined : JSON.stringify(body))
  }
  const path = (req.url || '').split('?')[0]
  if (req.method === 'OPTIONS') return send(204)

  if (req.method === 'POST' && path === '/__stub/expire') {
    expired = true
    return send(200, { expired })
  }
  if (req.method === 'POST' && path === '/__stub/reset') {
    expired = false
    logouts = 0
    return send(200, { expired, logouts })
  }
  if (req.method === 'GET' && path === '/__stub/state') return send(200, { expired, logouts })

  // CSRF: unsafe methods must carry the marker header (a cross-site form post cannot set it).
  const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(req.method || 'GET')
  if (unsafe && req.headers['x-requested-with'] !== 'XMLHttpRequest') {
    return send(403, { detail: 'CSRF check failed' })
  }

  if (req.method === 'GET' && path === '/api/auth/mock-users') return send(200, USERS)

  if (req.method === 'POST' && path === '/api/auth/mock-google/login') {
    let raw = ''
    req.on('data', chunk => (raw += chunk))
    req.on('end', () => {
      let email = ''
      try {
        email = JSON.parse(raw).email
      }
      catch { /* falls through to 401 */ }
      const user = USERS.find(u => u.email === email)
      if (!user) return send(401, { detail: 'Invalid credentials' })
      expired = false
      return send(200, { expires_in: MAX_AGE, user }, {
        'set-cookie': sessionCookie(`stub.${Buffer.from(user.email).toString('base64url')}`, MAX_AGE),
      })
    })
    return
  }

  if (req.method === 'GET' && path === '/api/auth/me') {
    const user = expired ? undefined : userFromCookie(req.headers.cookie)
    return user ? send(200, user) : send(401, { detail: 'Not authenticated' })
  }

  if (req.method === 'POST' && path === '/api/auth/logout') {
    logouts++
    return send(204, undefined, { 'set-cookie': sessionCookie('', 0) })
  }

  return send(404, { detail: 'Not found' })
}).listen(PORT, () => console.log(`mock-api-stub listening on http://localhost:${PORT} (CORS origin ${ORIGIN})`))
