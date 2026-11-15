// Section links for the long tool pages (the sky page, the field lab): they stay under the top bar.
import { useEffect, useState } from 'react'
import { L } from './lib.js'

const SPY = { rootMargin: '-120px 0px -55% 0px' }     // a section is "here" once its top is under the top bar

/** Scroll to a section (opening it when it is a <details>). */
function jump(e, id) {
  e.preventDefault()
  const el = document.getElementById(id)
  if (!el) return
  if (el.tagName === 'DETAILS') el.open = true
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** A row of section links that stays under the top bar: where each part of this long page is (V10). */
export function SectionNav({ items }) {
  const [on, setOn] = useState(null)
  const ids = items.map((it) => it.id).join()
  useEffect(() => {
    const els = items.map((it) => document.getElementById(it.id)).filter(Boolean)
    if (!els.length || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver((es) => { const v = es.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]; if (v) setOn(v.target.id) }, SPY)
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [ids]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <nav className="secnav" aria-label={L('本頁段落', 'On this page')}>
      {items.map((it) => <a key={it.id} href={`#${it.id}`} aria-current={on === it.id ? 'true' : undefined}
        onClick={(e) => jump(e, it.id)}>{it.label}</a>)}
    </nav>
  )
}
