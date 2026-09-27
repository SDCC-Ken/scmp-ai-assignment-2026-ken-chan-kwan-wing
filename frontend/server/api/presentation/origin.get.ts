import { networkInterfaces } from 'node:os'
import { requirePresentationAccess } from '../../utils/presentation-auth'

function isPrivateIpv4(address: string) {
  return /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(address)
}

export default defineEventHandler((event) => {
  requirePresentationAccess(event)
  const host = getHeader(event, 'host') || 'localhost:9180'
  const port = host.includes(':') ? host.split(':').at(-1) : '9180'
  const entries = Object.entries(networkInterfaces())
    .flatMap(([name, addresses]) => (addresses || []).map((address) => ({ name, address })))
    .filter(({ address }) => address.family === 'IPv4' && !address.internal && isPrivateIpv4(address.address))
    // On macOS, physical LAN interfaces are named en*.  Do not use eth0 here:
    // in Docker it is the container bridge (for example 172.20.x.x), which an
    // iPad cannot reach.
    .filter(({ name }) => /^(en\d+|wlan\d+)$/i.test(name))
    .sort((a, b) => a.name.localeCompare(b.name))
  const address = entries[0]?.address.address || 'localhost'
  return { origin: `http://${address}:${port}` }
})
