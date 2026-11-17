// Accent tones used for avatars, icon chips and badges. Each maps to CSS tokens in styles/tokens.css.

export type Tone = 'brand' | 'blue' | 'green' | 'amber' | 'pink' | 'coral' | 'gray' | 'red'

const AVATAR_TONES: Tone[] = ['brand', 'blue', 'green', 'amber', 'pink', 'coral']

/** A stable accent for a name or id, so the same agent always gets the same colour. */
export function toneFor(key: string): Tone {
  let h = 0
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_TONES[h % AVATAR_TONES.length]
}
