// Builds the Nuxt frontend once (incrementally) and serves the production build on port 9280.
//
// The build happens in a private copy (.build/web) so it never touches frontend/.output, which
// other dev servers may be serving, and so a half-edited source tree is snapshotted once.
// It is rebuilt only when the frontend sources changed (rsync sees a difference), when the
// build is missing, or when E2E_REBUILD=1.
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { API_URL, BUILD_DIR, FRONTEND_DIR, WEB_PORT, webEnv } from './env.mjs'
import { assertPortFree, run, runToEnd } from './launch.mjs'

await assertPortFree(WEB_PORT, 'e2e web')

fs.mkdirSync(BUILD_DIR, { recursive: true })
const sync = spawnSync(
  'rsync',
  [
    '-a', '--delete', '--itemize-changes',
    '--exclude', 'node_modules', '--exclude', '.nuxt', '--exclude', '.output',
    '--exclude', '.env*', '--exclude', 'tests', '--exclude', '.DS_Store',
    `${FRONTEND_DIR}/`, `${BUILD_DIR}/`,
  ],
  { encoding: 'utf8' },
)
if (sync.status !== 0) {
  console.error(`[e2e] rsync failed (is rsync installed?): ${sync.stderr}`)
  process.exit(1)
}
// Only file changes count (a leading '.d' line is just a directory timestamp).
const changed = sync.stdout.split('\n').some(line => /^(>f|cf|cL|\*deleting)/.test(line))

const nodeModules = path.join(BUILD_DIR, 'node_modules')
if (!fs.existsSync(nodeModules)) fs.symlinkSync(path.join(FRONTEND_DIR, 'node_modules'), nodeModules)

const entry = path.join(BUILD_DIR, '.output', 'server', 'index.mjs')
if (changed || !fs.existsSync(entry) || process.env.E2E_REBUILD === '1') {
  console.log('[e2e] Building the frontend (first run or sources changed; takes about a minute)...')
  fs.rmSync(path.join(BUILD_DIR, '.output'), { recursive: true, force: true })
  // No --dotenv: the repo-root .env must not influence the test build.
  const code = await runToEnd(path.join(nodeModules, '.bin', 'nuxt'), ['build'], {
    cwd: BUILD_DIR,
    env: { ...webEnv(), NUXT_TELEMETRY_DISABLED: '1' },
  })
  if (code !== 0) {
    console.error('[e2e] Frontend build failed.')
    process.exit(code)
  }
}
else {
  console.log('[e2e] Frontend sources unchanged: reusing the previous build (E2E_REBUILD=1 forces a rebuild).')
}

console.log(`[e2e] Web on http://localhost:${WEB_PORT} (API ${API_URL})`)
run('node', [entry], { cwd: BUILD_DIR, env: webEnv() })
