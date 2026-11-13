import { useEffect, useState } from 'react'
import { Wifi, WifiOff } from 'lucide-react'
import { useHealth } from '../lib/hooks'

function clock(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/** A strip under the header while this machine is offline (tunnel, train,
 * Wi-Fi switch, VPN drop), and a short "back online" note when it recovers.
 * The state comes from the gateway's own probes (/health → network). */
export function NetworkBanner() {
  const { data: health } = useHealth()
  const net = health?.network
  const offline = net?.enabled !== false && net?.state === 'offline'

  // "Back online" for a few seconds after offline → online, derived from the
  // previous render's state rather than set from an effect.
  const state = net?.state
  const [prevState, setPrevState] = useState(state)
  const [recovered, setRecovered] = useState(false)
  if (state !== prevState) {
    setPrevState(state)
    setRecovered(prevState === 'offline' && state === 'online')
  }

  useEffect(() => {
    if (!recovered) return
    const t = window.setTimeout(() => setRecovered(false), 6_000)
    return () => window.clearTimeout(t)
  }, [recovered])

  if (offline && net) {
    const since = clock(net.since)
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-start gap-3 px-5 py-2.5 text-sm border-b shrink-0"
        style={{ background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)', color: '#fcd34d' }}
      >
        <WifiOff size={16} className="mt-0.5 shrink-0" />
        <div className="min-w-0">
          <span className="font-semibold">No network connection{since ? ` since ${since}` : ''}.</span>{' '}
          <span className="text-amber-200/80">
            Remote models are paused and fail fast instead of timing out; local models keep working.
            {net.reason ? ` Cause: ${net.reason}.` : ''}
            {typeof net.retry_after_s === 'number' ? ` Checking again in ${net.retry_after_s}s.` : ''}
            {net.failed_fast > 0 ? ` ${net.failed_fast} request${net.failed_fast === 1 ? '' : 's'} refused so far.` : ''}
          </span>
        </div>
      </div>
    )
  }

  if (recovered) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-3 px-5 py-2 text-sm border-b shrink-0"
        style={{ background: 'rgba(20,184,166,0.08)', borderColor: 'rgba(20,184,166,0.25)', color: '#5eead4' }}
      >
        <Wifi size={16} className="shrink-0" />
        <span>Back online. Remote models are available again.</span>
      </div>
    )
  }

  return null
}
