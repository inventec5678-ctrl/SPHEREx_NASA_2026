// Each .reveal element rises once as it enters the viewport (delay from --d). One observer for the page; elements
// added later (sections that load their data) are picked up as they appear.
import { useEffect } from 'react'

export function useReveal() {
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target) }
    }), { rootMargin: '0px 0px -8% 0px' })
    const scan = () => document.querySelectorAll('.reveal:not(.in):not([data-io])').forEach((el) => { el.dataset.io = '1'; io.observe(el) })
    scan()
    // a render can add many nodes at once: rescan at most once per frame
    let raf = 0
    const mo = new MutationObserver(() => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; scan() }) })
    mo.observe(document.body, { childList: true, subtree: true })
    return () => { cancelAnimationFrame(raf); io.disconnect(); mo.disconnect() }
  }, [])
}
