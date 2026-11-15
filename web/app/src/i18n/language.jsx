import { useSyncExternalStore, useEffect } from 'react'
import { getLanguage, setLanguage, subscribe } from './core.js'
export function useLanguage() {
  const lang = useSyncExternalStore(subscribe, getLanguage, getLanguage)
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  return lang
}
export function LanguageSwitch() {
  const lang = useLanguage()
  return (
    <div className="lang" role="group" aria-label="Language / 語言">
      <button type="button" lang="en" aria-pressed={lang === 'en'} onClick={() => setLanguage('en')}>EN</button>
      <button type="button" lang="zh-Hant" aria-pressed={lang === 'zh-Hant'} onClick={() => setLanguage('zh-Hant')}>繁中</button>
    </div>
  )
}
