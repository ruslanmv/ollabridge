/**
 * Custom request headers as the Sources form edits them.
 *
 * The backend stores them as one `Name: value` per line and stays the
 * authority: it re-validates on save (providers_meta.parse_header_lines).
 * These helpers mirror its reading so the form can split a pasted block into
 * rows and flag a bad name before Save, instead of after a 422.
 */

export type HeaderRow = { id: number; name: string; value: string }

// RFC 9110 field-name token characters — the backend's rule.
const HEADER_NAME = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/

// Headers OllaBridge sets itself, or that would carry a credential in plain
// text. Same list as the backend's _RESERVED_HEADERS.
const RESERVED = new Set([
  'authorization',
  'proxy-authorization',
  'x-api-key',
  'api-key',
  'cookie',
  'content-type',
  'content-length',
  'host',
  'transfer-encoding',
  'connection',
])

let lastId = 0
export function newRow(name = '', value = ''): HeaderRow {
  lastId += 1
  return { id: lastId, name, value }
}

function isQuoted(text: string): boolean {
  return text.length >= 2 && text[0] === text[text.length - 1] && (text[0] === '"' || text[0] === "'")
}

/** A typed or pasted name as it will be sent: trimmed, JSON quotes dropped. */
export function cleanName(name: string): string {
  const t = name.trim()
  return isQuoted(t) ? t.slice(1, -1).trim() : t
}

/**
 * Read a block of headers: `Name: value` lines, the quoted `"Name": "value",`
 * lines provider docs print, or a whole JSON object.
 */
export function parseHeaderText(text: string): HeaderRow[] {
  const body = text.trim()
  if (body.startsWith('{') && body.endsWith('}')) {
    try {
      const data: unknown = JSON.parse(body)
      if (data && typeof data === 'object' && !Array.isArray(data)) {
        return Object.entries(data as Record<string, unknown>).map(([k, v]) =>
          newRow(k.trim(), v == null ? '' : String(v).trim()),
        )
      }
    } catch {
      // Not one JSON object — read it line by line.
    }
  }
  const rows: HeaderRow[] = []
  for (const raw of body.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#') || line === '{' || line === '}' || line === '},') continue
    const colon = line.indexOf(':')
    let name = (colon < 0 ? line : line.slice(0, colon)).trim()
    let value = colon < 0 ? '' : line.slice(colon + 1).trim()
    if (isQuoted(name)) {
      name = name.slice(1, -1).trim()
      value = value.replace(/,$/, '').trim()
      if (isQuoted(value)) value = value.slice(1, -1)
    }
    rows.push(newRow(name, value))
  }
  return rows
}

/** Rows → the stored text. Only fully blank rows (drafts) are left out, so a
 * value without a name still reaches validation rather than vanishing. */
export function serializeHeaders(rows: HeaderRow[]): string {
  return rows
    .filter((r) => r.name.trim() || r.value.trim())
    .map((r) => `${cleanName(r.name)}: ${r.value.trim()}`)
    .join('\n')
}

/** Why the backend would refuse this row, or null when it is fine. */
export function headerRowError(row: Pick<HeaderRow, 'name' | 'value'>): string | null {
  const name = cleanName(row.name)
  if (!name) return row.value.trim() ? 'Add a header name.' : null
  if (!HEADER_NAME.test(name)) return 'Not a valid header name — no spaces, quotes or colons.'
  if (RESERVED.has(name.toLowerCase())) {
    return `${name} is set by OllaBridge. Put keys in the API key field.`
  }
  if (/[\r\n]/.test(row.value)) return 'A value cannot contain a line break.'
  return null
}

/** The first problem in a stored or typed header block, or null. */
export function headerTextError(text: string): string | null {
  for (const row of parseHeaderText(text)) {
    const error = headerRowError(row)
    if (error) return row.name.trim() ? `${cleanName(row.name)}: ${error}` : error
  }
  return null
}

/** How many headers a block sets — for the collapsed summary. */
export function headerCount(text: string): number {
  return parseHeaderText(text).filter((r) => cleanName(r.name)).length
}
