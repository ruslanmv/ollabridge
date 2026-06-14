import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  PauseCircle,
  CircleDashed,
} from 'lucide-react'
import type { SourceStatus, SourceSharing, SourceStorageMode } from '../../lib/api'

// ── Status metadata ──────────────────────────────────────────────

export const STATUS_META: Record<
  SourceStatus,
  { label: string; color: string; icon: typeof CheckCircle2 }
> = {
  connected: { label: 'Connected', color: '#14b8a6', icon: CheckCircle2 },
  missing_key: { label: 'Missing key', color: '#f59e0b', icon: AlertTriangle },
  error: { label: 'Error', color: '#ef4444', icon: XCircle },
  disabled: { label: 'Disabled', color: 'rgba(255,255,255,0.35)', icon: PauseCircle },
  not_configured: { label: 'Not configured', color: 'rgba(255,255,255,0.35)', icon: CircleDashed },
}

export const STORAGE_LABEL: Record<SourceStorageMode, string> = {
  local_only: 'Local only',
  cloud_encrypted_vault: 'Encrypted vault',
  organization_vault: 'Org vault',
}

export const SHARING_LABEL: Record<SourceSharing, string> = {
  private: 'Private',
  account: 'Account',
  workspace: 'Workspace',
  organization: 'Organization',
}

export function StatusBadge({ status }: { status: SourceStatus }) {
  const meta = STATUS_META[status]
  const Icon = meta.icon
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap"
      style={{
        background: `${meta.color}15`,
        color: meta.color,
        border: `1px solid ${meta.color}30`,
      }}
    >
      <Icon size={11} />
      {meta.label}
    </span>
  )
}

export function Chip({
  label,
  color = 'rgba(255,255,255,0.5)',
  icon: Icon,
  muted = false,
}: {
  label: string
  color?: string
  icon?: typeof CheckCircle2
  muted?: boolean
}) {
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium whitespace-nowrap"
      style={{
        background: muted ? 'rgba(255,255,255,0.03)' : `${color}14`,
        color: muted ? 'rgba(255,255,255,0.4)' : color,
        border: `1px solid ${muted ? 'rgba(255,255,255,0.06)' : `${color}28`}`,
      }}
    >
      {Icon && <Icon size={10} />}
      {label}
    </span>
  )
}

export function GlassCard({
  children,
  className = '',
  delay = 0,
}: {
  children: ReactNode
  className?: string
  delay?: number
}) {
  return (
    <motion.div
      className={`glass-card p-6 ${className}`}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay }}
    >
      {children}
    </motion.div>
  )
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const diff = Date.now() - t
  const s = Math.round(diff / 1000)
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  if (d < 30) return `${d}d ago`
  return new Date(iso).toLocaleDateString()
}
