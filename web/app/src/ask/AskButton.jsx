// The floating "Ask" button (in the entry chunk, so kept small) and the lazily loaded panel it opens.
import { Suspense, lazy, useEffect, useRef, useSyncExternalStore } from 'react'
import { L } from '@sx/i18n/core.js'
import { getAsk, openAsk, subscribe, takeOpener } from './store.js'

const load = () => import('./AskPanel.jsx')
const AskPanel = lazy(load)

export default function AskButton({ stage }) {
  const s = useSyncExternalStore(subscribe, getAsk, getAsk)
  const btn = useRef(), was = useRef(false)
  // closing the panel returns focus to what opened it (an "Ask about this" button), else to the fab
  useEffect(() => {
    if (was.current && !s.open) { const el = takeOpener(); (el?.isConnected && el !== document.body ? el : btn.current)?.focus() }
    was.current = s.open
  }, [s.open])
  return (
    <>
      {!s.open && (
        <button ref={btn} type="button" className="ask-fab" data-stage={stage} aria-haspopup="dialog"
          onPointerEnter={load} onFocus={load} onClick={openAsk}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" /><path d="M9 10.5h.01M12 10.5h.01M15 10.5h.01" /></svg>
          <span>{L('提問', 'Ask')}</span>
        </button>
      )}
      {s.open && <Suspense fallback={<div className="ask-fab ask-wait" data-stage={stage} role="status" aria-label={L('載入中…', 'Loading…')} />}><AskPanel /></Suspense>}
    </>
  )
}
