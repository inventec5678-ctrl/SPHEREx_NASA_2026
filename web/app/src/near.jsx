// Mount children only when their place on the page is about to scroll into view (heavy sections of the home page).
import { useEffect, useRef, useState } from 'react'

export function Near({ children, margin = '120%', minHeight = '100svh', className }) {
  const ref = useRef()
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (on) return
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setOn(true); io.disconnect() } }, { rootMargin: `${margin} 0px ${margin} 0px` })
    if (ref.current) io.observe(ref.current)
    return () => io.disconnect()
  }, [on, margin])
  return on ? children : <div ref={ref} className={className} style={{ minHeight }} aria-hidden="true" />
}
