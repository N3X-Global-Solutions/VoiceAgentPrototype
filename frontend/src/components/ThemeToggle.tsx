import { useEffect, useState } from 'react'
import { Icon, type IconName } from './Icon'

type Theme = 'system' | 'light' | 'dark'

function readTheme(): Theme {
  try {
    const t = localStorage.getItem('theme')
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch {
    return 'system'
  }
}

const OPTIONS: [Theme, IconName, string][] = [
  ['light', 'sun', 'Light'],
  ['system', 'monitor', 'System'],
  ['dark', 'moon', 'Dark'],
]

export function ThemeToggle({ labels }: { labels?: boolean }) {
  const [theme, setTheme] = useState<Theme>(readTheme)

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') delete root.dataset.theme
    else root.dataset.theme = theme
    try {
      if (theme === 'system') localStorage.removeItem('theme')
      else localStorage.setItem('theme', theme)
    } catch {
      /* storage blocked: theme still applies for this visit */
    }
  }, [theme])

  return (
    <div className="segmented theme-toggle" role="radiogroup" aria-label="Theme">
      {OPTIONS.map(([value, icon, label]) => (
        <button
          key={value}
          role="radio"
          aria-checked={theme === value}
          className={theme === value ? 'active' : ''}
          onClick={() => setTheme(value)}
          title={`${label} theme`}
        >
          <Icon name={icon} size={14} />
          {labels && label}
        </button>
      ))}
    </div>
  )
}
