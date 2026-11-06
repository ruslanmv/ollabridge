import { useId, useState, type ClipboardEvent } from 'react'
import { Plus, X, Rows3, FileText } from 'lucide-react'
import {
  type HeaderRow,
  headerRowError,
  headerTextError,
  newRow,
  parseHeaderText,
  serializeHeaders,
} from './headers'

const INPUT =
  'w-full min-w-0 bg-navy-900/60 border rounded-lg px-2.5 py-2 text-xs font-mono text-white placeholder:text-white/20 focus:outline-none focus:border-glow-cyan/40 transition-colors'

function rowsFrom(text: string): HeaderRow[] {
  const rows = parseHeaderText(text)
  return rows.length > 0 ? rows : [newRow()]
}

/**
 * Name/value editor for custom request headers — rows, the way API clients
 * edit them, with a text mode for editing many at once.
 *
 * `value` is the stored text (one `Name: value` per line). Pasting a block
 * into a name cell — `Name: value` lines or the JSON form provider docs
 * print — splits it into rows, so nobody has to retype a header list.
 */
export function HeadersEditor({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (text: string) => void
  /** Example text for text mode, one `Name: value` per line. */
  placeholder?: string
}) {
  const baseId = useId()
  const [rows, setRows] = useState<HeaderRow[]>(() => rowsFrom(value))
  const [asText, setAsText] = useState(false)

  // Follow the stored text when it changes from outside — after a save the
  // backend hands back its normalized form. Our own edits already match it.
  const [seenValue, setSeenValue] = useState(value)
  if (value !== seenValue) {
    setSeenValue(value)
    if (serializeHeaders(rows) !== value) setRows(rowsFrom(value))
  }

  const commit = (next: HeaderRow[]) => {
    setRows(next)
    onChange(serializeHeaders(next))
  }
  const update = (id: number, patch: Partial<HeaderRow>) =>
    commit(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  const remove = (id: number) => {
    const next = rows.filter((r) => r.id !== id)
    commit(next.length > 0 ? next : [newRow()])
  }
  const valueInputId = (id: number) => `${baseId}-value-${id}`

  /** A name cell that receives a typed colon moves on to the value cell. */
  function onNameChange(row: HeaderRow, text: string) {
    const colon = text.indexOf(':')
    if (colon < 0) return update(row.id, { name: text })
    update(row.id, {
      name: text.slice(0, colon),
      value: (text.slice(colon + 1) + row.value).trimStart(),
    })
    requestAnimationFrame(() => document.getElementById(valueInputId(row.id))?.focus())
  }

  /** Paste a whole header list into one name cell → one row per header. */
  function onNamePaste(row: HeaderRow, e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData('text')
    if (!/[\r\n]/.test(text.trim()) && !text.trim().startsWith('{')) return
    const pasted = parseHeaderText(text)
    if (pasted.length === 0) return
    e.preventDefault()
    const at = rows.findIndex((r) => r.id === row.id)
    const keep = row.name.trim() || row.value.trim() ? [row] : []
    commit([...rows.slice(0, at), ...keep, ...pasted, ...rows.slice(at + 1)])
  }

  function switchMode() {
    if (asText) setRows(rowsFrom(value))
    setAsText(!asText)
  }

  const textError = asText ? headerTextError(value) : null

  return (
    <div className="space-y-2">
      {asText ? (
        <>
          <textarea
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            rows={4}
            spellCheck={false}
            autoComplete="off"
            aria-label="Custom headers, one Name: value per line"
            aria-invalid={!!textError}
            className={`${INPUT} py-2.5`}
            style={{ borderColor: textError ? 'rgba(245,158,11,0.4)' : 'rgba(255,255,255,0.1)' }}
          />
          {textError && <p className="text-[11px] text-amber-300/90">{textError}</p>}
        </>
      ) : (
        <div className="space-y-1.5">
          <div aria-hidden className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_1.75rem] gap-1.5 px-0.5">
            <span className="text-[10px] uppercase tracking-wider text-white/30">
              Name
            </span>
            <span className="text-[10px] uppercase tracking-wider text-white/30">
              Value
            </span>
            <span />
          </div>
          {rows.map((row, i) => {
            const error = headerRowError(row)
            const border = { borderColor: error ? 'rgba(245,158,11,0.4)' : 'rgba(255,255,255,0.1)' }
            return (
              <div key={row.id}>
                <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_1.75rem] gap-1.5 items-center">
                  <input
                    type="text"
                    value={row.name}
                    onChange={(e) => onNameChange(row, e.target.value)}
                    onPaste={(e) => onNamePaste(row, e)}
                    placeholder={i === 0 ? 'x-client-app-id' : 'Header name'}
                    spellCheck={false}
                    autoComplete="off"
                    aria-label={`Header ${i + 1} name`}
                    aria-invalid={!!error}
                    className={INPUT}
                    style={border}
                  />
                  <input
                    id={valueInputId(row.id)}
                    type="text"
                    value={row.value}
                    onChange={(e) => update(row.id, { value: e.target.value })}
                    placeholder={i === 0 ? 'ollabridge' : 'Value'}
                    spellCheck={false}
                    autoComplete="off"
                    aria-label={`Header ${i + 1} value`}
                    className={INPUT}
                    style={border}
                  />
                  <button
                    type="button"
                    onClick={() => remove(row.id)}
                    aria-label={`Remove header ${i + 1}`}
                    className="h-7 w-7 inline-flex items-center justify-center rounded-md text-white/35 hover:text-white/80 hover:bg-white/5 transition-colors"
                  >
                    <X size={13} />
                  </button>
                </div>
                {error && <p className="text-[11px] text-amber-300/90 mt-1">{error}</p>}
              </div>
            )
          })}
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        {asText ? (
          <span className="text-[11px] text-white/30">One Name: value per line, or JSON.</span>
        ) : (
          <button
            type="button"
            onClick={() => commit([...rows, newRow()])}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-glow-cyan/80 hover:text-glow-cyan transition-colors"
          >
            <Plus size={12} /> Add header
          </button>
        )}
        <button
          type="button"
          onClick={switchMode}
          className="inline-flex items-center gap-1 text-[11px] text-white/40 hover:text-white/70 transition-colors"
        >
          {asText ? <Rows3 size={12} /> : <FileText size={12} />}
          {asText ? 'Edit as rows' : 'Edit as text'}
        </button>
      </div>
    </div>
  )
}
