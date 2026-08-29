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
  /** The source discovers its model list dynamically after connecting.
   * Only a hint: the backend's `supports_discovery` is authoritative. */
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
    // No defaultModelPlaceholder: which foundation models exist depends on
    // the region, the plan and what the account has been granted, so any
    // fixed example would be wrong for someone. The picker lists the real
    // ones once a key is saved.
    connectLabel: 'Connect and discover',
    showRemoteNotice: true,
    supportsDiscovery: true,
    setupHint:
      'Create an IBM Cloud API key at cloud.ibm.com → Manage → Access (IAM) → ' +
      'API keys. Use the base URL for your region (us-south, eu-de, eu-gb, ' +
      'jp-tok, au-syd). Leave the model blank and OllaBridge picks the best ' +
      'chat model your account can reach.',
  },
  groq: {
    // The base URL the OpenAI SDK is pointed at for Groq. A bare
    // https://api.groq.com works too — the backend normalizes both.
    baseUrlPlaceholder: 'https://api.groq.com/openai/v1',
    credentialLabel: 'API key',
    credentialPlaceholder: 'gsk_••••••••••••••••',
    defaultModelPlaceholder: 'openai/gpt-oss-20b',
    connectLabel: 'Connect and discover',
    showRemoteNotice: true,
    supportsDiscovery: true,
    setupHint:
      'Create a key at console.groq.com → API Keys. Leave the model blank and ' +
      'OllaBridge picks a free one from the models your key can reach.',
  },
  openrouter: {
    baseUrlPlaceholder: 'https://openrouter.ai/api/v1',
    credentialPlaceholder: 'sk-or-••••••••••••••••',
    defaultModelPlaceholder: 'meta-llama/llama-3.3-70b-instruct:free',
    connectLabel: 'Connect and discover',
    showRemoteNotice: true,
    supportsDiscovery: true,
    setupHint:
      'Create a key at openrouter.ai/keys. Model ids ending in :free cost ' +
      'nothing to run.',
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
