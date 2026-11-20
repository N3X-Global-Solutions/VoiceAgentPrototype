// Provider helpers shared by the config form, playground, call logs and settings.
// The rules mirror the backend (app/providers/catalog.py), which validates them again on save.

import type { AgentConfig, Catalog, Health, PartKind, Price, Provider, ProviderId, Voice } from './api'

/** Display names, for places that render without the catalog (call logs). */
export const PROVIDER_NAME: Record<string, string> = { sarvam: 'Sarvam', navana: 'Navana', gnani: 'Gnani' }

export const PART_LABEL: Record<PartKind, string> = {
  stt: 'Speech recognition',
  llm: 'AI model',
  tts: 'Voice',
}

/** Mid-sentence form: "Navana: speech recognition", "Gnani: AI model". */
export const PART_LABEL_LOWER: Record<PartKind, string> = {
  stt: 'speech recognition',
  llm: 'AI model',
  tts: 'voice',
}

export const PART_KEY: Record<PartKind, 'stt_provider' | 'llm_provider' | 'tts_provider'> = {
  stt: 'stt_provider',
  llm: 'llm_provider',
  tts: 'tts_provider',
}

// Sarvam voices that are offered in every language, so we can hear how they handle other
// languages. A voice outside its own language isn't guaranteed to sound right: listen before using it.
export const CROSS_LANGUAGE_VOICES = ['aparna_en_edtech']

export function provider(catalog: Catalog, id: string | undefined): Provider | undefined {
  return catalog.providers.find((p) => p.id === id)
}

export function providerName(catalog: Catalog, id: string | undefined) {
  return provider(catalog, id)?.name ?? id ?? ''
}

export function providersFor(catalog: Catalog, kind: PartKind) {
  return catalog.providers.filter((p) => p[kind])
}

export function voiceFits(v: Voice, language: string) {
  if (v.language === '*' || v.language === language) return true
  if (v.provider !== 'sarvam') return false
  return (v.group === 'Hindi-English Code-Mixed' && ['en-IN', 'hi-IN'].includes(language)) || CROSS_LANGUAGE_VOICES.includes(v.id)
}

/** The TTS provider's voices for a language: its own first, then cross-language ones. */
export function voicesFor(catalog: Catalog, tts: ProviderId, language: string) {
  const crossLanguage = (v: Voice) => v.provider === 'sarvam' && v.language !== language && CROSS_LANGUAGE_VOICES.includes(v.id)
  return catalog.voices.filter((v) => v.provider === tts && voiceFits(v, language)).sort((a, b) => Number(crossLanguage(a)) - Number(crossLanguage(b)))
}

export function defaultVoice(catalog: Catalog, tts: ProviderId, language: string) {
  const own = catalog.voices.find((v) => v.provider === tts && v.language === language)
  return (own ?? voicesFor(catalog, tts, language)[0])?.id
}

/** Languages both the speech recognition and voice providers support. */
export function callLanguages(catalog: Catalog, stt: ProviderId, tts: ProviderId) {
  const a = provider(catalog, stt)?.stt?.languages ?? []
  const b = new Set(provider(catalog, tts)?.tts?.languages ?? [])
  return Object.keys(catalog.languages).filter((code) => a.includes(code) && b.has(code))
}

/**
 * Switch one part's provider and keep the config valid: if the language or voice no longer
 * works, fall back to one that does. Returns the new config and a note about what changed.
 */
export function switchProvider(catalog: Catalog, config: AgentConfig, kind: PartKind, id: ProviderId): { config: AgentConfig; note?: string } {
  const next = { ...config, [PART_KEY[kind]]: id } as AgentConfig
  const notes: string[] = []
  const languages = callLanguages(catalog, next.stt_provider, next.tts_provider)
  if (!languages.includes(next.language) && languages.length) {
    notes.push(`${catalog.languages[next.language]} isn't available with this combination, so the language is now ${catalog.languages[languages[0]]}.`)
    next.language = languages[0]
  }
  const voice = catalog.voices.find((v) => v.provider === next.tts_provider && v.id === next.voice)
  if (!voice || !voiceFits(voice, next.language)) {
    const fallback = defaultVoice(catalog, next.tts_provider, next.language)
    if (fallback) {
      next.voice = fallback
      if (kind === 'tts') notes.push(`Voice set to ${catalog.voices.find((v) => v.id === fallback && v.provider === next.tts_provider)?.name}. Pick another in the Voice tab.`)
    }
  }
  if (kind === 'stt' && id !== 'sarvam' && next.turn_detection === 'sarvam') {
    next.turn_detection = 'fast'
    notes.push('Turn detection switched to Fast: Robust mode needs Sarvam speech recognition.')
  }
  return { config: next, note: notes.join(' ') || undefined }
}

export function hasFeature(catalog: Catalog, stt: ProviderId, feature: string) {
  return provider(catalog, stt)?.stt?.features.includes(feature) ?? false
}

/** Env vars the agent's providers need but the server doesn't have. Empty = ready. */
export function missingKeys(catalog: Catalog, health: Health | null, config: AgentConfig) {
  if (!health?.providers) return []
  const ids = [...new Set([config.stt_provider, config.llm_provider, config.tts_provider])]
  return ids.filter((id) => !health.providers[id]).map((id) => provider(catalog, id)?.key_env ?? id)
}

const UNIT: Record<Price['unit'], string> = { min: 'min', '1k_chars': '1K chars', '1m_tokens': '1M tokens' }

export function priceText(p: Price) {
  return `₹${p.rate.toLocaleString(undefined, { maximumFractionDigits: 3 })} / ${UNIT[p.unit]}`
}

/** The headline rate(s) of a provider part, e.g. "₹1.2 / 1K chars" or "₹10 in · ₹25 out / 1M tokens". */
export function partPriceText(part: Provider['stt']) {
  if (!part) return ''
  const pr = part.prices
  if (pr.input) {
    if (!pr.input.rate && !pr.output.rate) return 'Free plan'
    return `₹${pr.input.rate} in · ₹${pr.output.rate} out / 1M tokens`
  }
  const p = pr.audio ?? pr.chars
  return p ? priceText(p) : ''
}

export function partPriceSource(part: Provider['stt']): Price['source'] | undefined {
  if (!part) return undefined
  const all = Object.values(part.prices)
  if (all.some((p) => p.source === 'estimate')) return 'estimate'
  if (all.some((p) => p.source === 'quoted')) return 'quoted'
  return 'published'
}

export const SOURCE_LABEL: Record<Price['source'], string> = {
  published: 'Published rate',
  quoted: 'Your quoted rate',
  estimate: 'Estimate: confirm in the provider console',
}
