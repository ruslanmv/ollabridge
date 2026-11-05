/** Building blocks shared by the Settings page and its sections. */

import { motion } from 'framer-motion'
import { Settings, ToggleLeft, ToggleRight } from 'lucide-react'

// ── Helpers ──────────────────────────────────────────────────────────────

export function GlassCard({
  children,
  className = '',
  delay = 0,
}: {
  children: React.ReactNode
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

export function SectionTitle({
  icon: Icon,
  title,
  subtitle,
  color = '#00e5ff',
  badge,
}: {
  icon: typeof Settings
  title: string
  subtitle?: string
  color?: string
  badge?: { label: string; color: string }
}) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
        style={{
          background: `linear-gradient(135deg, ${color}20, ${color}08)`,
          border: `1px solid ${color}30`,
        }}
      >
        <Icon size={18} style={{ color }} />
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <h2 className="text-white/90 font-semibold text-base">{title}</h2>
          {badge && (
            <span
              className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
              style={{
                background: `${badge.color}15`,
                color: badge.color,
                border: `1px solid ${badge.color}30`,
              }}
            >
              {badge.label}
            </span>
          )}
        </div>
        {subtitle && (
          <p className="text-white/40 text-xs mt-0.5">{subtitle}</p>
        )}
      </div>
    </div>
  )
}

export function SettingField({
  label,
  description,
  children,
}: {
  label: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b border-white/[0.04] last:border-0">
      <div className="flex-1 min-w-0">
        <label className="text-sm text-white/70 font-medium">{label}</label>
        {description && (
          <p className="text-xs text-white/30 mt-0.5">{description}</p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = 'text',
  mono = false,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  mono?: boolean
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-64 px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-white/80 placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors ${mono ? 'font-mono text-xs' : ''}`}
    />
  )
}

export function Toggle({
  enabled,
  onToggle,
}: {
  enabled: boolean
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      className="transition-colors"
      style={{ color: enabled ? '#14b8a6' : 'rgba(255,255,255,0.2)' }}
    >
      {enabled ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
    </button>
  )
}

export function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-64 px-3 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-white/80 focus:outline-none focus:border-glow-cyan/40 transition-colors appearance-none cursor-pointer"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value} className="bg-navy-800">
          {opt.label}
        </option>
      ))}
    </select>
  )
}
