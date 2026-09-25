// Shared constants for the e2e suite: ports, paths and the environment of the API under test.
// Plain .mjs on purpose: the server launcher scripts run it with bare `node`.
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))

export const E2E_DIR = path.resolve(here, '..')
export const REPO_DIR = path.resolve(E2E_DIR, '..')
export const BACKEND_DIR = path.join(REPO_DIR, 'backend')
export const FRONTEND_DIR = path.join(REPO_DIR, 'frontend')

// 9280/9281 never clash with Docker (9180/9181) or other dev servers (9190/9191/9199).
export const WEB_PORT = 9280
export const API_PORT = 9281
// `localhost` everywhere: the session cookie is host-scoped and must be shared by both ports.
export const WEB_URL = `http://localhost:${WEB_PORT}`
export const API_URL = `http://localhost:${API_PORT}`

export const SCREENSHOT_DIR = path.join(REPO_DIR, 'docs', 'screenshots')
export const TMP_DIR = path.join(E2E_DIR, '.tmp') // wiped on every run
export const DB_PATH = path.join(TMP_DIR, 'e2e.db')
export const UPLOAD_DIR = path.join(TMP_DIR, 'uploads')
export const BUILD_DIR = path.join(E2E_DIR, '.build', 'web') // kept between runs (incremental)

/**
 * Environment of the backend under test. Explicit variables beat the repo `.env`, so a real key
 * can never be used: the LLM and submission providers are the offline fakes and every key is empty.
 */
export function backendEnv() {
  return {
    ...process.env,
    APP_ENV: 'development',
    DATABASE_URL: `sqlite:///${DB_PATH}`,
    UPLOAD_DIR,
    LLM_PROVIDER: 'fake',
    LLM_FALLBACK_PROVIDER: '',
    SUBMISSION_PROVIDER: 'fake',
    JWT_SECRET_KEY: 'e2e-test-secret-not-for-production-0123456789',
    CORS_ORIGINS: WEB_URL,
    MOCK_SSO_ENABLED: 'true',
    DB_AUTO_SEED: 'true',
    GEMINI_API_KEY: '',
    REQRES_API_KEY: '',
    OLLAMA_BASE_URL: 'http://127.0.0.1:9', // nothing listens there: no accidental local model
  }
}

export function webEnv() {
  return {
    ...process.env,
    NITRO_PORT: String(WEB_PORT),
    NITRO_HOST: '127.0.0.1',
    NUXT_PUBLIC_API_BASE: API_URL,
    NUXT_API_BASE_SERVER: API_URL,
  }
}
