import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Settings2,
  Activity,
  KeyRound,
  Trash2,
  Plus,
  Loader2,
  Lock,
  Route,
  Cpu,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import type { AvailableSource, SourceObject } from '../../lib/api'
import { useDeleteSource, useTestSource, useUpsertSource } from '../../lib/hooks'
import { useToast } from './toast'
import { Chip, SHARING_LABEL, STATUS_META, StatusBadge, STORAGE_LABEL, relTime } from './ui'

function IconButton({
  icon: Icon,
  label,
  onClick,
  busy = false,
  tone = 'default',
}: {
  icon: typeof Settings2
  label: string
  onClick: () => void
  busy?: boolean
  tone?: 'default' | 'danger'
}) {
  const danger = tone === 'danger'
  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={label}
      aria-label={label}
      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-colors disabled:opacity-40"
      style={{
        background: danger ? 'rgba(239,68,68,0.08)' : 'rgba(255,255,255,0.04)',
        border: `1px solid ${danger ? 'rgba(239,68,68,0.25)' : 'rgba(255,255,255,0.08)'}`,
        color: danger ? '#fca5a5' : 'rgba(255,255,255,0.7)',
      }}
    >
      {busy ? <Loader2 size={12} className="animate-spin" /> : <Icon size={12} />}
      {label}
    </button>
  )
}

export function ConfiguredSourceCard({
  source,
  delay = 0,
  onConfigure,
  onRotate,
}: {
  source: SourceObject
  delay?: number
  onConfigure: (s: SourceObject) => void
  onRotate: (s: SourceObject) => void
}) {
  const test = useTestSource()
  const remove = useDeleteSource()
  const upsert = useUpsertSource()
  const toast = useToast()
  const [confirmRemove, setConfirmRemove] = useState(false)

  const meta = STATUS_META[source.status]

  async function handleTest() {
    try {
      const res = await test.mutateAsync(source.name)
      if (res.ok) toast.success(`${source.label} reachable — ${res.detail}`)
      else toast.error(`${source.label}: ${res.detail}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function handleToggle() {
    try {
      await upsert.mutateAsync({ name: source.name, body: { enabled: !source.enabled } })
      toast.info(`${source.label} ${source.enabled ? 'disabled' : 'enabled'}`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function handleRemove() {
    try {
      await remove.mutateAsync(source.name)
      toast.success(`${source.label} removed`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
      className="flex flex-col rounded-2xl border bg-navy-800/50 backdrop-blur p-5 transition-colors hover:border-white/15"
      style={{ borderColor: `${meta.color}25` }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="text-white font-semibold text-[15px] truncate">
            {source.display_name || source.label}
          </div>
          <div className="text-white/40 text-xs truncate">{source.label}</div>
        </div>
        <StatusBadge status={source.status} />
      </div>

      {/* Default model */}
      <div className="flex items-center gap-2 text-xs text-white/55 mb-3 min-w-0">
        <Cpu size={13} className="shrink-0 text-white/30" />
        <span className="font-mono truncate">
          {source.default_model || <span className="text-white/30">no default model</span>}
        </span>
      </div>

      {/* Chips */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        <Chip label={STORAGE_LABEL[source.storage_mode]} icon={Lock} color="#22d3ee" />
        <Chip label={SHARING_LABEL[source.sharing]} color="#8b5cf6" />
        <Chip
          label={source.allow_routing ? 'Routing on' : 'Routing off'}
          icon={Route}
          color="#14b8a6"
          muted={!source.allow_routing}
        />
      </div>

      {/* Key + last test */}
      <div className="flex items-center justify-between gap-2 text-[11px] mb-4">
        <span className="font-mono text-white/45 truncate">
          {source.key ?? <span className="text-amber-400/70">no key</span>}
        </span>
        {source.last_test_ok !== null && (
          <span
            className="inline-flex items-center gap-1 shrink-0"
            style={{ color: source.last_test_ok ? '#5eead4' : '#fca5a5' }}
          >
            {source.last_test_ok ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
            {relTime(source.last_test_at)}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="mt-auto">
        {confirmRemove ? (
          <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/25">
            <span className="text-[11px] text-red-200">Remove and delete its key?</span>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setConfirmRemove(false)}
                className="text-[11px] px-2 py-1 rounded-md text-white/60 hover:text-white/90"
              >
                Cancel
              </button>
              <button
                onClick={handleRemove}
                disabled={remove.isPending}
                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-red-500/25 border border-red-500/40 text-red-200 hover:bg-red-500/35 disabled:opacity-40"
              >
                {remove.isPending ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                Remove
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-1.5">
            <IconButton icon={Settings2} label="Configure" onClick={() => onConfigure(source)} />
            <IconButton icon={Activity} label="Test" onClick={handleTest} busy={test.isPending} />
            <IconButton icon={KeyRound} label="Rotate" onClick={() => onRotate(source)} />
            <button
              onClick={handleToggle}
              disabled={upsert.isPending}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-colors disabled:opacity-40"
              style={{
                background: source.enabled ? 'rgba(20,184,166,0.12)' : 'rgba(255,255,255,0.04)',
                color: source.enabled ? '#14b8a6' : 'rgba(255,255,255,0.45)',
                border: `1px solid ${source.enabled ? 'rgba(20,184,166,0.3)' : 'rgba(255,255,255,0.1)'}`,
              }}
            >
              {upsert.isPending ? (
                <Loader2 size={11} className="animate-spin" />
              ) : null}
              {source.enabled ? 'Enabled' : 'Disabled'}
            </button>
            <IconButton
              icon={Trash2}
              label="Remove"
              tone="danger"
              onClick={() => setConfirmRemove(true)}
            />
          </div>
        )}
      </div>
    </motion.div>
  )
}

export function AvailableSourceCard({
  source,
  delay = 0,
  onAdd,
}: {
  source: AvailableSource
  delay?: number
  onAdd: (s: AvailableSource) => void
}) {
  return (
    <motion.button
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay }}
      onClick={() => onAdd(source)}
      className="group flex flex-col text-left rounded-2xl border border-dashed border-white/10 bg-navy-800/25 p-5 transition-colors hover:border-glow-cyan/40 hover:bg-navy-800/40"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <div className="text-white/85 font-semibold text-[15px] truncate">{source.label}</div>
          <div className="text-white/35 text-xs font-mono truncate">{source.env_var}</div>
        </div>
        <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-white/5 border border-white/10 text-white/40 group-hover:text-glow-cyan group-hover:border-glow-cyan/40 transition-colors">
          <Plus size={14} />
        </span>
      </div>
      {source.notes && (
        <p className="text-[11px] text-white/35 leading-relaxed line-clamp-2 mb-3">{source.notes}</p>
      )}
      <span className="mt-auto inline-flex items-center gap-1.5 text-[11px] font-medium text-glow-cyan/80 group-hover:text-glow-cyan">
        <KeyRound size={12} /> Add API key
      </span>
    </motion.button>
  )
}
