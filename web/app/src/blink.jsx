// A small blink of one star through its survey passes (review cards, the home page).
// It never plays by itself when the visitor asked for reduced motion, and it can always be paused.
// Pixels are drawn at a whole-number zoom on a canvas sized for the screen's pixel density, so every SPHEREx pixel
// is the same size and sharp; the text labels are HTML on top, not painted into the picture.
import { useEffect, useRef, useState } from 'react'
import { L, PASS_C, loadImage } from './lib.js'
import { usePlayback } from './play.js'
import { PlayBar } from './playbar.jsx'
import { dpr } from './canvas.js'

const BLINK_HZ = 1 / 0.8                                   // one pass every 0.8 s
const TICKS = [[1, 0], [-1, 0], [0, 1], [0, -1]]

/** c: {field, source: 'field' | 'quick', det_band, track: [{k, x, y}, ...], base?} */
export function stackUrl(c, k) {
  if (c.base) return `${c.base}/pass/p${k}_d${c.det_band ?? 0}.webp`        // a flagged position: the lab's pass stacks
  const b = c.source === 'quick' ? (c.det_band || 6) : c.det_band ?? 0
  return c.source === 'quick' ? `/data/quick/${c.field}/stack/p${k}_d${b}.webp` : `/data/fields/${c.field}/pass/p${k}_d${b}.webp`
}

/** Device-pixel size of a square canvas shown `css` px wide. */
export const devicePx = (css) => Math.round(css * dpr())

/**
 * size  SPHEREx pixels across (the picture shows at least this many)
 * px    CSS width of the picture
 * trail draw every pass's position joined by a line, with an arrow to the last
 */
export function Blink({ c, size = 25, px = 300, label, trail = false }) {
  const cv = useRef()
  const pts = c.track
  const pb = usePlayback(pts.length, { hz: BLINK_HZ })
  const { k } = pb
  const [ims, setIms] = useState(() => pts.map(() => null))
  useEffect(() => {
    let live = true
    setIms(pts.map(() => null))
    pts.forEach((t, j) => loadImage(stackUrl(c, t.k), (im) => live && im && setIms((a) => { const b = [...a]; b[j] = im; return b })))
    return () => { live = false }
  }, [c.field, c.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = cv.current, g = el?.getContext('2d'), im = ims[k]
    if (!g || !im) return
    const W = devicePx(px)
    if (el.width !== W || el.height !== W) { el.width = W; el.height = W }
    const z = Math.max(1, Math.round(W / size)), n = Math.ceil(W / z) + 1
    const cx = Math.round(pts[0].x), cy = im.height - 1 - Math.round(pts[0].y)
    const sx = cx - Math.floor(n / 2), sy = cy - Math.floor(n / 2)
    const off = Math.round((W - n * z) / 2)
    g.imageSmoothingEnabled = false
    g.fillStyle = '#000'; g.fillRect(0, 0, W, W)
    g.drawImage(im, sx, sy, n, n, off, off, n * z, n * z)
    const P = (t) => [off + (t.x - sx + 0.5) * z, off + (im.height - 1 - t.y - sy + 0.5) * z]
    const u = W / px, r = Math.max(10 * u, 1.6 * z), lw = 2 * u      // u: device px per CSS px
    if (trail && pts.length > 1) {
      g.lineWidth = lw; g.strokeStyle = 'rgba(255,255,255,.7)'
      g.beginPath(); pts.forEach((t, j) => { const [x, y] = P(t); j ? g.lineTo(x, y) : g.moveTo(x, y) }); g.stroke()
      const [ax, ay] = P(pts.at(-1)), [bx, by] = P(pts.at(-2)), a = Math.atan2(ay - by, ax - bx), h = 9 * u
      g.beginPath(); g.moveTo(ax, ay); g.lineTo(ax - h * Math.cos(a - 0.45), ay - h * Math.sin(a - 0.45)); g.lineTo(ax - h * Math.cos(a + 0.45), ay - h * Math.sin(a + 0.45)); g.closePath()
      g.fillStyle = 'rgba(255,255,255,.85)'; g.fill()
      pts.forEach((t, j) => { const [x, y] = P(t); g.fillStyle = PASS_C[j % PASS_C.length]; g.beginPath(); g.arc(x, y, 3 * u, 0, 7); g.fill() })
    }
    const [qx, qy] = P(pts[k])
    g.strokeStyle = PASS_C[k % PASS_C.length]; g.lineWidth = lw
    if (trail) {
      // four ticks around the position in this pass, leaving the star itself uncovered
      const a = Math.max(8 * u, 1.1 * z), b = a + 18 * u
      g.beginPath()
      for (const [dx, dy] of TICKS) { g.moveTo(qx + dx * a, qy + dy * a); g.lineTo(qx + dx * b, qy + dy * b) }
      g.stroke()
    } else { g.beginPath(); g.arc(qx, qy, r, 0, 7); g.stroke() }
  }, [ims, k, size, px, trail]) // eslint-disable-line react-hooks/exhaustive-deps
  const last = pts.length - 1
  return (
    <div className="blinkbox">
      <div className="blink-frame" style={{ width: px }}>
        <canvas ref={cv} className="mv-blink" role="img" aria-label={label || L('各輪巡天的疊加影像，輪流顯示', 'Stacks of each survey pass, shown in turn')} />
        <span className="blink-tag" style={{ '--c': PASS_C[k % PASS_C.length] }} aria-hidden="true">
          {L(`第 ${k + 1} 輪`, `Pass ${k + 1}`)}<small>{L(` / 共 ${last + 1} 輪`, ` of ${last + 1}`)}</small>
        </span>
      </div>
      <PlayBar pb={pb} n={pts.length} slider={false} label={L('輪播各輪巡天', 'Blink the survey passes')} />
    </div>
  )
}
