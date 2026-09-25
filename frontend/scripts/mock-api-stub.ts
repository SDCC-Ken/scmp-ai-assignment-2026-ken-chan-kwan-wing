/**
 * DEV AID ONLY - a tiny stand-in for the backend auth contract on port 9181.
 * Run:  bun scripts/mock-api-stub.ts
 * Not used by tests, Docker or production; the real FastAPI backend replaces it.
 *
 * Extra dev endpoints:  POST /__stub/expire  -> every later /api/auth/me returns 401
 *                       POST /__stub/reset   -> clears that flag and the logout counter
 *                       GET  /__stub/state   -> { expired, logouts }
 */
import { Buffer } from 'node:buffer'
import { createServer } from 'node:http'
import process from 'node:process'

const PORT = Number(process.env.API_PORT) || 9181
const ORIGIN = process.env.STUB_ALLOWED_ORIGIN || 'http://localhost:9180'

const USERS = [
  { id: 1, email: 'amy.lau@example.com', display_name: 'Amy Lau', role: 'employee' },
  { id: 2, email: 'ben.wong@example.com', display_name: 'Ben Wong', role: 'employee' },
  { id: 3, email: 'chloe.cheung@example.com', display_name: 'Chloe Cheung', role: 'employee' },
  { id: 4, email: 'henry.ho@example.com', display_name: 'Henry Ho', role: 'hr_approver' },
  { id: 5, email: 'fiona.fung@example.com', display_name: 'Fiona Fung', role: 'finance_approver' },
]

let expired = false
let logouts = 0

function userFromAuth(header: string | undefined) {
  const token = header?.startsWith('Bearer stub.') ? header.slice('Bearer stub.'.length) : ''
  const email = Buffer.from(token, 'base64url').toString()
  return USERS.find(u => u.email === email)
}

createServer((req, res) => {
  const send = (status: number, body?: unknown) => {
    res.writeHead(status, {
      'access-control-allow-origin': ORIGIN,
      'access-control-allow-headers': 'authorization, content-type',
      'access-control-allow-methods': 'GET, POST, OPTIONS',
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
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
      return send(200, {
        access_token: `stub.${Buffer.from(user.email).toString('base64url')}`,
        token_type: 'bearer',
        expires_in: 3600,
        user,
      })
    })
    return
  }

  if (req.method === 'GET' && path === '/api/auth/me') {
    const user = expired ? undefined : userFromAuth(req.headers.authorization)
    return user ? send(200, user) : send(401, { detail: 'Not authenticated' })
  }

  if (req.method === 'POST' && path === '/api/auth/logout') {
    logouts++
    return send(204)
  }

  return send(404, { detail: 'Not found' })
}).listen(PORT, () => console.log(`mock-api-stub listening on http://localhost:${PORT} (CORS origin ${ORIGIN})`))
