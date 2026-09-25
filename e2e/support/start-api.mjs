// Starts the FastAPI backend for the e2e run on port 9281 with a fresh SQLite database.
// (Playwright starts webServers BEFORE global setup, so the database and upload folder are
// wiped here, before the API creates and seeds its tables.)
import fs from 'node:fs'
import { API_PORT, BACKEND_DIR, DB_PATH, TMP_DIR, UPLOAD_DIR, backendEnv } from './env.mjs'
import { assertPortFree, run } from './launch.mjs'

await assertPortFree(API_PORT, 'e2e API')

for (const suffix of ['', '-wal', '-shm', '-journal']) fs.rmSync(`${DB_PATH}${suffix}`, { force: true })
fs.rmSync(UPLOAD_DIR, { recursive: true, force: true })
fs.mkdirSync(UPLOAD_DIR, { recursive: true })
fs.mkdirSync(TMP_DIR, { recursive: true })

console.log(`[e2e] API on http://localhost:${API_PORT}, database ${DB_PATH} (fake LLM, fake submission adapter)`)
run('uv', ['run', '--frozen', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(API_PORT)], {
  cwd: BACKEND_DIR,
  env: backendEnv(),
})
