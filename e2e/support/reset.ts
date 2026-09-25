import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { BACKEND_DIR, backendEnv } from './env.mjs'

const run = promisify(execFile)

/**
 * Drops and re-creates the e2e database with the known fictional seed data
 * (`python -m app.cli seed --reset --yes`), so every test starts from the same state.
 * Runs as a child process with the same environment as the API under test.
 */
export async function resetData(): Promise<void> {
  try {
    await run('uv', ['run', '--frozen', 'python', '-m', 'app.cli', 'seed', '--reset', '--yes'], {
      cwd: BACKEND_DIR,
      env: backendEnv(),
      timeout: 60_000,
    })
  }
  catch (error) {
    const e = error as { stdout?: string, stderr?: string, message: string }
    throw new Error(`resetData failed: ${e.message}\n${e.stdout ?? ''}\n${e.stderr ?? ''}`)
  }
}
