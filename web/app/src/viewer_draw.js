// Canvas drawing of the sky viewer, kept apart from its state: the overlay on the image (tracks, detections,
// catalogue stars, the probed point) and the timeline under it. Both are pure functions of what they are given.
import { t } from '@sx/i18n/core.js'
import { DET, mjdDate } from './lib.js'
import { membersOf, pLink, trackColor } from './viewer_parts.jsx'

const C_KNOWN = '#6ec3ff', C_TARGET = '#c08bff', C_PIN = '#ffb547', C_SIM = '#ff4fd8'
const LABEL_FONT = 'Manrope, sans-serif'
const CATS = [['gaia', 'rgba(110,195,255,.8)'], ['catwise', 'rgba(239,111,108,.85)']]
const CORNERS = [[-1, -1], [1, -1], [-1, 1], [1, 1]]
const PASS_GAP_D = 40      // exposures closer than this many days belong to the same survey pass
const EPS = 1e-6

/** Start a path through the detections `pts` (field pixels, mapped by X and Y). */
function trace(g, pts, X, Y) {
  g.beginPath()
  pts.forEach((c, k) => (k ? g.lineTo(X(c.x), Y(c.y)) : g.moveTo(X(c.x), Y(c.y))))
}
const ring = (g, x, y, r) => { g.beginPath(); g.arc(x, y, r, 0, 7); g.stroke() }

/** Everything drawn over the current frame. X and Y map field pixels to screen pixels; r0 is the marker radius;
 *  focus is the selected or hovered track id (or null). */
export function drawOverlay(g, { field, i, Sw, Sh, X, Y, r0, focus, research, show, revealSim, pin, probe, probePt, cats }) {
  // tracks: faint context lines; the focused one as an onion-skin trail that grows with time
  const tnow = field.exposures[i].mjd
  const ex_ = field.exposures
  for (const tr of field.tracks) {
    const isF = tr.id === focus
    if (focus != null && !isF) continue
    const pts = membersOf(field, tr), col = trackColor(tr)
    if (!isF) {
      g.strokeStyle = col; g.globalAlpha = 0.22; g.lineWidth = 1.5
      trace(g, pts, X, Y); g.stroke()
      continue
    }
    const past = pts.filter((c) => ex_[c.i].mjd <= tnow + EPS), future = pts.filter((c) => ex_[c.i].mjd > tnow + EPS)
    if (research && future.length) {      // the rest of the path, faint (research only)
      g.strokeStyle = col; g.globalAlpha = 0.18; g.lineWidth = 1.5; g.setLineDash([3, 5])
      trace(g, [past.at(-1) || future[0], ...future], X, Y); g.stroke(); g.setLineDash([])
    }
    // onion skin: every earlier position, older = smaller and fainter
    const tmin = past.length ? ex_[past[0].i].mjd : tnow, span = Math.max(tnow - tmin, EPS)
    g.strokeStyle = col; g.globalAlpha = 0.55; g.lineWidth = 2
    trace(g, past, X, Y); g.stroke()
    for (const c of past) {
      const age = (tnow - ex_[c.i].mjd) / span
      g.globalAlpha = 0.25 + 0.75 * (1 - age); g.fillStyle = col
      g.beginPath(); g.arc(X(c.x), Y(c.y), 2 + 3.5 * (1 - age), 0, 7); g.fill()
    }
  }
  g.globalAlpha = 1
  const pl = pLink(field)
  for (const c of field.byExp.get(i) || []) {
    const tr = c.track != null ? field.tracks[c.track] : null
    if (focus != null && (!tr || tr.id !== focus)) {
      if (c.known && show.known) { g.globalAlpha = 0.35; g.strokeStyle = C_KNOWN; g.lineWidth = 1.5; ring(g, X(c.x), Y(c.y), r0); g.globalAlpha = 1 }
      continue
    }
    if (tr && tr.id === focus) {
      g.strokeStyle = trackColor(tr); g.lineWidth = 3; ring(g, X(c.x), Y(c.y), r0 + 6)
    } else if (c.known && show.known) {
      g.strokeStyle = C_KNOWN; g.lineWidth = 1.5; ring(g, X(c.x), Y(c.y), r0 + 2)
      g.fillStyle = C_KNOWN; g.font = `600 13px ${LABEL_FONT}`; g.fillText(c.known.replace(/\s*\(.*\)/, ''), X(c.x) + r0 + 6, Y(c.y) - r0)
    } else if (show.cands && c.p >= pl) {
      g.strokeStyle = tr ? trackColor(tr) : `rgba(255,255,255,${0.25 + 0.5 * c.p})`; g.lineWidth = 1.5
      ring(g, X(c.x), Y(c.y), r0)
    }
  }
  const sim = field.simByExp.get(i)
  if (sim && revealSim) { g.strokeStyle = C_SIM; g.lineWidth = 2; ring(g, X(sim.x), Y(sim.y), r0 + 10) }
  // catalogue overlays, moved to this exposure's epoch by their proper motion
  if (cats && cats.id === field.id) {
    for (const [key, col] of CATS) {
      if (!(key === 'gaia' ? show.gaia : show.wise)) continue
      g.strokeStyle = col; g.lineWidth = 1.2
      for (const st of cats[key]) {
        const dt = (tnow - st.mjd0) / 365.25, x = X(st.x + st.pmx * dt), y = Y(st.y + st.pmy * dt)
        if (x < -10 || y < -10 || x > Sw + 10 || y > Sh + 10) continue
        g.beginPath()
        if (key === 'gaia') g.arc(x, y, r0 - 2, 0, 7); else { g.moveTo(x, y - r0); g.lineTo(x + r0, y); g.lineTo(x, y + r0); g.lineTo(x - r0, y); g.closePath() }
        g.stroke()
      }
    }
  }
  // a challenge target: corner brackets at its catalogue-predicted position on this frame
  const tp = field.tgByExp?.get(i)
  if (tp) {
    const tx = X(tp.x), ty = Y(tp.y), R = r0 + 12, k = 7
    g.strokeStyle = C_TARGET; g.lineWidth = 2; g.beginPath()
    for (const [sx, sy] of CORNERS) { g.moveTo(tx + sx * R, ty + sy * (R - k)); g.lineTo(tx + sx * R, ty + sy * R); g.lineTo(tx + sx * (R - k), ty + sy * R) }
    g.stroke(); g.fillStyle = C_TARGET; g.font = `700 13px ${LABEL_FONT}`; g.fillText(field.target.name, tx + R + 6, ty - R + 10)
  }
  if (probePt) {
    const px = X(probePt.x), py = Y(probePt.y)
    const pm = probe && probe !== 'loading' && probe.distant?.ok ? probe.distant.members.map((m) => field.cand.get(m)).sort((a, b) => ex_[a.i].mjd - ex_[b.i].mjd) : null
    if (pm) { g.strokeStyle = C_TARGET; g.globalAlpha = 0.85; g.lineWidth = 2; trace(g, pm, X, Y); g.stroke(); g.globalAlpha = 1 }
    g.strokeStyle = '#ffffff'; g.lineWidth = 2
    g.beginPath(); g.moveTo(px - 18, py); g.lineTo(px - 7, py); g.moveTo(px + 7, py); g.lineTo(px + 18, py); g.moveTo(px, py - 18); g.lineTo(px, py - 7); g.moveTo(px, py + 7); g.lineTo(px, py + 18); g.stroke()
  }
  if (pin && pin.i === i) { g.strokeStyle = C_PIN; g.lineWidth = 3; ring(g, X(pin.x), Y(pin.y), r0 + 8) }
}

/** The timeline: one band per survey pass, detector ticks, the selected object's images in amber, the current
 *  exposure as a white line. Sets cv._x (MJD -> x) for click handling and returns the passes. */
export function drawTimeline(cv, { field, frames, selTrack, ex, research }) {
  const dpr = window.devicePixelRatio || 1, Wt = cv.clientWidth * dpr, Ht = cv.clientHeight * dpr
  // resize the buffer only when the box changed (assigning a size reallocates it even when it is the same)
  if (cv.width !== Wt >>> 0 || cv.height !== Ht >>> 0) { cv.width = Wt; cv.height = Ht }
  const g = cv.getContext('2d'); g.clearRect(0, 0, Wt, Ht)
  const ts = field.exposures.map((e) => e.mjd), passes = []
  for (const m of ts) { const p = passes.at(-1); if (p && m - p.end < PASS_GAP_D) p.end = m; else passes.push({ start: m, end: m }) }
  const gap = 10 * dpr, usable = Wt - gap * (passes.length - 1), tot = passes.reduce((a, p) => a + Math.max(p.end - p.start, 1), 0)
  let x0 = 0; for (const p of passes) { p.x0 = x0; p.w = usable * Math.max(p.end - p.start, 1) / tot; x0 += p.w + gap }
  const Xm = (m) => { const p = passes.find((q) => m >= q.start - EPS && m <= q.end + EPS) || passes[0]; return p.x0 + p.w * (m - p.start) / Math.max(p.end - p.start, 1) }
  cv._x = Xm
  const top = 18 * dpr, band = Ht - top
  g.font = `600 ${12 * dpr}px Manrope, "PingFang TC", "Noto Sans CJK TC", "Microsoft JhengHei", sans-serif`
  let labelEnd = -1                       // a label that would run into the previous one is shortened, then left out
  passes.forEach((p, k) => {
    g.fillStyle = '#ffffff14'; g.beginPath(); g.roundRect(p.x0, top, p.w, band, 6 * dpr); g.fill()
    const d = mjdDate(p.start).toISOString().slice(0, 7)
    const text = [p.w > 150 * dpr ? t`第 ${k + 1} 輪 · ${d}` : d, d, d.slice(2)].find((s) => p.x0 + 2 * dpr > labelEnd && g.measureText(s).width < p.w + gap - 4 * dpr)
    if (!text) return
    g.fillStyle = '#a3b4af'; g.fillText(text, p.x0 + 2 * dpr, 12 * dpr)
    labelEnd = p.x0 + 2 * dpr + g.measureText(text).width + 6 * dpr
  })
  const shown = new Set(frames), mine = selTrack ? new Set(membersOf(field, selTrack).map((c) => c.i)) : null
  for (const e of field.exposures) {
    const x = Xm(e.mjd)
    if (research) {      // research: one row per detector, coloured when that image is in the playlist
      g.fillStyle = shown.has(e.i) ? DET[e.detector].c : '#1d2a33'
      g.fillRect(x, top + (4 + (e.detector - 1) * ((band - 14 * dpr) / 6)), 2 * dpr, (band - 14 * dpr) / 6 - dpr)
    } else if (shown.has(e.i)) { g.fillStyle = '#ffffff40'; g.fillRect(x, top + band * 0.3, 1.5 * dpr, band * 0.4) }
    if (mine?.has(e.i)) { g.fillStyle = C_PIN; g.fillRect(x - dpr, top + band * 0.15, 3 * dpr, band * 0.7) }
  }
  if (ex) { g.fillStyle = '#eef3f1'; g.fillRect(Xm(ex.mjd) - dpr, top - 2 * dpr, 2.5 * dpr, band + 2 * dpr) }
  return passes
}
