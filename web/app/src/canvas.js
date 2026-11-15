// Canvas helpers shared by the players and the lab: size the drawing buffer for the screen's pixel density and
// draw SPHEREx pixels at a whole-number zoom, so every pixel is the same size and sharp (UPGRADE_PLAN.md §8, V5).
import { useLayoutEffect, useState } from 'react'

export const dpr = () => Math.min(3, (typeof window !== 'undefined' && window.devicePixelRatio) || 1)

/** CSS width of an element, kept current with a ResizeObserver (0 until it is laid out). */
export function useBoxWidth(ref) {
  const [w, setW] = useState(0)
  // measured before the first paint (layout effect), so nothing is drawn at a guessed width and then resized
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setW(Math.round(el.getBoundingClientRect().width))
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return w
}

/**
 * Geometry of a square view `span` SPHEREx pixels across, shown `css` CSS px wide.
 * W: device-pixel size of the canvas; s: device px per SPHEREx pixel (a whole number); off: black margin in device px;
 * u: device px per CSS px (multiply line widths and marker sizes by it).
 */
export function pixelFit(css, span, fallback = 600) {
  const c = css > 0 ? css : fallback, u = dpr(), W = Math.round(c * u)
  const s = Math.max(1, Math.floor(W / span))
  return { W, s, off: Math.round((W - span * s) / 2), u, css: c }
}

// Is WebGL hardware-accelerated here? Software WebGL (SwiftShader, llvmpipe: some virtual machines, remote desktops,
// laptops with acceleration turned off) froze the decorative pages for about 6 s, so those get a still picture
// and an explicit "open 3D anyway" (UPGRADE_PLAN.md §8, T4).
let gpu = null
export function gpuOK() {
  if (gpu !== null) return gpu
  try {
    const c = document.createElement('canvas'), o = { failIfMajorPerformanceCaveat: true }
    const gl = c.getContext('webgl2', o) || c.getContext('webgl', o)
    if (!gl) return (gpu = false)
    const dbg = gl.getExtension('WEBGL_debug_renderer_info')
    const r = dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : ''
    gpu = !/swiftshader|llvmpipe|softpipe|software|basic render/i.test(r)
    gl.getExtension('WEBGL_lose_context')?.loseContext()
  } catch { gpu = false }
  return gpu
}
