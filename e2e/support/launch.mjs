// Small helpers for the server launcher scripts (start-api.mjs, start-web.mjs).
import { spawn } from 'node:child_process'
import net from 'node:net'

/** True when something already accepts connections on `port` (IPv4 or IPv6 loopback). */
function accepts(port, host) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host })
    socket.once('connect', () => { socket.destroy(); resolve(true) })
    socket.once('error', () => resolve(false))
    socket.setTimeout(1000, () => { socket.destroy(); resolve(false) })
  })
}

export async function assertPortFree(port, what) {
  if ((await accepts(port, '127.0.0.1')) || (await accepts(port, '::1'))) {
    console.error(
      `\n[e2e] Port ${port} (${what}) is already in use.\n` +
      `      Stop whatever listens there (lsof -iTCP:${port} -sTCP:LISTEN) and run the tests again.\n`,
    )
    process.exit(1)
  }
}

/** Runs a child in the foreground of this launcher; its exit ends the launcher. Signals are forwarded. */
export function run(command, args, options) {
  const child = spawn(command, args, { stdio: 'inherit', ...options })
  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, () => child.kill(signal))
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
  child.on('error', (error) => {
    console.error(`[e2e] Could not start ${command}: ${error.message}`)
    process.exit(1)
  })
  return child
}

/** Runs a command to completion and returns its exit code (output is shown). */
export function runToEnd(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit', ...options })
    child.on('error', reject)
    child.on('exit', (code) => resolve(code ?? 1))
  })
}
