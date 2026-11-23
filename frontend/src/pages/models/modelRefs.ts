/** Small helpers shared by the Get models drawer and the page that hosts it. */

/** `qwen2.5` and `qwen2.5:latest` are the same model; Ollama ignores case. */
export function normalizeRef(ref: string): string {
  const lower = ref.trim().toLowerCase()
  return lower.endsWith(':latest') ? lower.slice(0, -':latest'.length) : lower
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return '—'
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1)} GB`
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`
}
