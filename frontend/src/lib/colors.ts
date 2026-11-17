// Tones used for status, badges and avatars. Each maps to CSS tokens in styles/tokens.css.
// Colour is reserved for meaning (accent, status); everything else stays neutral.

export type Tone = 'brand' | 'blue' | 'green' | 'amber' | 'red' | 'gray'

const AVATAR_TONES: Tone[] = ['brand', 'blue', 'amber', 'green', 'gray']

/** A stable avatar tone for a name or id, so the same agent always gets the same colour. */
export function toneFor(key: string): Tone {
  let h = 0
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_TONES[h % AVATAR_TONES.length]
}

/** Older call records may contain raw provider errors; never show the provider's name. */
export function publicText(text: string) {
  return text.replace(/sarvam(\s*ai)?|saaras|saarika|bulbul/gi, 'AI provider')
}
