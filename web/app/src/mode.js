// Story mode (default, for first-time visitors) vs research mode (every control and data-quality note).
// Remembered per browser; the switch lives in the top bar.
import { useSyncExternalStore } from 'react'

const KEY = 'sx:mode:v1'
let mode = (() => { try { return localStorage.getItem(KEY) === 'research' ? 'research' : 'story' } catch { return 'story' } })()
const listeners = new Set()
export const getMode = () => mode
export function setMode(m) {
  mode = m === 'research' ? 'research' : 'story'
  try { localStorage.setItem(KEY, mode) } catch { /* private window */ }
  document.documentElement.dataset.mode = mode
  listeners.forEach((f) => f())
}
const subscribe = (f) => { listeners.add(f); return () => listeners.delete(f) }
export const useMode = () => useSyncExternalStore(subscribe, getMode, getMode)
if (typeof document !== 'undefined') document.documentElement.dataset.mode = mode
