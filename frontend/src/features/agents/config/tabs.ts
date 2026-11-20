import type { TabItem } from '@/components/ui'

/** The agent configuration sub-tabs (shared by the workspace and the create page). */
export type ConfigTab = 'prompt' | 'providers' | 'voice' | 'speech' | 'call' | 'tools'

export const CONFIG_TABS: TabItem<ConfigTab>[] = [
  { id: 'prompt', label: 'Prompt', icon: 'fileText' },
  { id: 'providers', label: 'Providers', icon: 'server' },
  { id: 'voice', label: 'Voice', icon: 'globe' },
  { id: 'speech', label: 'Transcription', icon: 'mic' },
  { id: 'call', label: 'Behaviour', icon: 'sliders' },
  { id: 'tools', label: 'Tools', icon: 'wrench' },
]
