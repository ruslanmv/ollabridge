/**
 * Per-source UI hints, kept as a tiny generic metadata map so SourceModal never
 * has to embed `if (name === 'open_webui')` checks. Every field is optional and
 * falls back to the generic modal defaults, so unlisted providers are unchanged.
 *
 * No deployment-specific wording lives here: placeholders use example.com hosts;
 * the operator supplies their real URL and display name at runtime.
 */
export type SourceUiProfile = {
  /** The source cannot be configured without an explicit base URL. */
  requiresBaseUrl?: boolean
  baseUrlPlaceholder?: string
  credentialLabel?: string
  credentialPlaceholder?: string
  /** Example model id for this provider (the generic one is OpenAI-shaped). */
  defaultModelPlaceholder?: string
  /** Label for the primary connect button (e.g. "Connect and discover"). */
  connectLabel?: string
  /** Show the "Remote AI source — prompts leave this machine" notice. */
  showRemoteNotice?: boolean
  /** The source discovers its model list dynamically after connecting. */
  supportsDiscovery?: boolean
  /** A short, actionable line explaining how to obtain the credential. */
  setupHint?: string
}

export const SOURCE_UI_PROFILES: Record<string, SourceUiProfile> = {
  watsonx: {
    // The region IS the base URL — watsonx has no separate region field, so
    // the placeholder is what tells the user the URL carries it.
    baseUrlPlaceholder: 'https://us-south.ml.cloud.ibm.com',
    credentialLabel: 'IBM Cloud API key',
    defaultModelPlaceholder: 'ibm/granite-3-8b-instruct',
    showRemoteNotice: true,
    setupHint:
      'Create an IBM Cloud API key at cloud.ibm.com → Manage → Access (IAM) → ' +
      'API keys. Use the base URL for your region (us-south, eu-de, eu-gb, ' +
      'jp-tok, au-syd).',
  },
  open_webui: {
    requiresBaseUrl: true,
    baseUrlPlaceholder: 'https://openwebui.example.com/api',
    credentialLabel: 'API key',
    credentialPlaceholder: 'sk-••••••••••••••••',
    connectLabel: 'Connect and discover',
    showRemoteNotice: true,
    supportsDiscovery: true,
    setupHint:
      'Sign in to your Open WebUI server, create an API key in your account ' +
      'settings, and paste it here. The API root commonly ends with /api.',
  },
}

export function sourceUiProfile(name: string): SourceUiProfile {
  return SOURCE_UI_PROFILES[name] ?? {}
}
