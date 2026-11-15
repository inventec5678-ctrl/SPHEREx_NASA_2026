import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { t } from '@sx/i18n/core.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { DET, L, api, colorizeDiff, frameImg, getField, legendGradient, pix2world, ready, reducedMotion, trackTitle } from './lib.js'
import { usePlayback } from './play.js'
import { PlayButton } from './playbar.jsx'
import { hashParams, setHashParams } from './sky.js'
import { useMode } from './mode.js'
import { ICON } from './icons.jsx'
import { fieldDesc, fieldName } from './fields_text.js'
import { go } from './nav.js'
import { CandCard, Detail, Hint, ObjLabel, ProbeCard, Row, SkyPanel, SourceCard, ViewerSettings, membersOf, pLink, trackColor } from './viewer_parts.jsx'
import { drawOverlay, drawTimeline } from './viewer_draw.js'
import { setPageContext } from './ask/store.js'
import './viewer2.css'

const Sky3D = lazy(() => import('./sky3d.jsx'))
const MAX_HZ = 3            // photosensitivity: never blink faster than 3 Hz
const Z_MAX = 8             // deepest zoom (x the fitted size)
const MIN_COVER = 0.2       // an exposure covering less of the field than this is not played
const HOME = { z: 1, cx: 0.5, cy: 0.5 }   // the whole image, centred
const MODES = ['change', 'sky', 'ref', '3d', 'universe'], IMG_MODES = ['change', 'sky', 'ref']
const HINT_KEY = 'sx:hint:v2'
const clamp = (v, a, b) => Math.min(b, Math.max(a, v))

// ---- viewer ----------------------------------------------------------------

export default function Viewer({ fieldId }) {
  useLanguage()
  const research = useMode() === 'research'
  const [field, setField] = useState(null)
  const [err, setErr] = useState(null)
  const [mode, setMode] = useState(() => { const m = hashParams().get('m'); return MODES.includes(m) ? m : 'sky' })
  const [band, setBand] = useState('one')            // 'one' detector at a time, or 'all'
  const [oneDet, setOneDet] = useState(1)
  const [dets, setDets] = useState(() => new Set([1, 2, 3, 4, 5, 6]))
  const [sel, setSel] = useState(null)               // selected track id
  const [hov, setHov] = useState(null)               // hovered track id
  const [tour, setTour] = useState(false)            // the automatic first look; plays once, then a summary
  const [done, setDone] = useState(false)
  const [hz, setHz] = useState('auto')
  const [view, setView] = useState(HOME)   // zoom and centre (fractions of the image)
  const [box, setBox] = useState([600, 600])
  const [show, setShow] = useState({ cands: true, known: true, flags: false, gaia: false, wise: false })
  const [cats, setCats] = useState(null)
  useEffect(() => {
    if (!field?.products || !(show.gaia || show.wise) || cats?.id === field.id) return
    fetch(`/data/fields/${field.id}/overlays.json`).then((r) => r.json()).then((o) => setCats({ ...o, id: field.id })).catch(() => {})
  }, [field, show.gaia, show.wise, cats])
  const [settings, setSettings] = useState(false)
  const [sheet, setSheet] = useState(0)            // phone bottom sheet: 0 peek, 1 half, 2 full
  // first-visit tour, taught by doing: 0 = point at a moving object, 1 = its evidence, 2 = the point check, 3 = done
  const [hint, setHintRaw] = useState(() => { try { return Number(localStorage.getItem(HINT_KEY) ?? 0) } catch { return 3 } })
  const setHint = useCallback((h) => { setHintRaw(h); try { localStorage.setItem(HINT_KEY, String(h)) } catch { /* ignore */ } }, [])
  const [imgMode, setImgMode] = useState('sky')        // which image the 'image' view shows: sky / change (difference) / ref
  const [panelOpen, setPanelOpen] = useState(true)
  const [menu, setMenu] = useState(false)             // 'switch sky' menu
  const [fieldList, setFieldList] = useState([])
  const insetRef = useRef()
  const [revealSim, setRevealSim] = useState(false)
  const cursorRef = useRef()
  const [pin, setPin] = useState(null)            // a candidate picked from the list (fields with no tracks)
  const [probe, setProbe] = useState(null)        // result of 'is this point a planet?'
  const [probePt, setProbePt] = useState(null)
  const [armed, setArmed] = useState(false)
  const [srcSel, setSrcSel] = useState(null)       // a star or galaxy picked in the 3D universe
  const [hasUni, setHasUni] = useState(true)
  const [loadTick, setLoadTick] = useState(0)
  const panelBody = useRef()
  const stageRef = useRef(), baseRef = useRef(), ovRef = useRef(), tlRef = useRef()
  const anim = useRef(0), viewRef = useRef(view)
  const stCanvas = useRef(), stLabels = useRef()
  const [st, setSt] = useState(null)
  const [stLoad, setStLoad] = useState(null)
  const [noise, setNoise] = useState(false)       // open on what the AI kept; 'show noise' is the before
  viewRef.current = view
  useEffect(() => { setHashParams({ m: mode === 'sky' ? null : mode }) }, [mode])
  // automatic proper-motion candidates of this field: a different kind of mover from the asteroid tracks listed here
  const [stars, setStars] = useState(null)
  useEffect(() => { setStars(null); fetch(`/data/fields/${encodeURIComponent(fieldId)}/pm_candidates.json`).then((r) => (r.ok ? r.json() : null)).then((d) => setStars(d?.candidates || null)).catch(() => {}) }, [fieldId])

  useEffect(() => { setField(null); setSel(null); setErr(null); setMenu(false); getField(fieldId).then(setField).catch(() => setErr('notfound')) }, [fieldId])
  // The viewer opens on the SPHEREx images themselves (what the challenge asks for); the reconstructed 3D scene is
  // one of the modes, offered when this field has one (the field list says so).
  useEffect(() => {
    setHasUni(false)
    api('/api/fields').then((fs) => {
      setFieldList(fs.filter((f) => !f.user || f.id === fieldId).slice(0, 12))
      const uni = !!fs.find((f) => f.id === fieldId)?.has_universe
      setHasUni(uni); if (!uni) setMode((m) => (m === 'universe' ? 'sky' : m))
    }).catch(() => {})
  }, [fieldId])
  useEffect(() => { if (field) document.title = `SPHEREx Sky Change · ${fieldName(field)}` }, [field])
  useEffect(() => {
    if (!field) return undefined
    setPageContext({ kind: 'field', id: field.id, name: fieldName(field), ra: field.ra, dec: field.dec,
      facts: { exposures: field.exposures?.length, size_deg: field.size_deg, tracks: field.tracks?.length, known_objects: field.tracks?.filter((x) => x.known).length,
        distant_candidates: field.tracks?.filter((x) => x.kind === 'distant').length, simulated: field.simulated ? true : null } })
    return () => setPageContext(null)
  }, [field])
  useEffect(() => { if (IMG_MODES.includes(mode)) setImgMode(mode) }, [mode])
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setBox([Math.round(e.contentRect.width), Math.round(e.contentRect.height)]))
    if (stageRef.current) ro.observe(stageRef.current)
    return () => ro.disconnect()
  }, [field])

  const W = field?.shape[1] || 1, H = field?.shape[0] || 1
  const [Sw, Sh] = box
  // the floating panels cover parts of the full-bleed stage: fit the image into the free area between them
  const wide = Sw >= 1000
  const sheetPx = [58, Sh * 0.46, Sh - 56][sheet] || 58
  const ins = useMemo(() => (wide ? { l: 16, t: 72, r: panelOpen ? 404 : 16, b: 92 } : { l: 8, t: 104, r: 8, b: Math.round(sheetPx + 80) }), [wide, panelOpen, sheetPx])
  const Fw = Math.max(80, Sw - ins.l - ins.r), Fh = Math.max(80, Sh - ins.t - ins.b)
  const s0 = Math.min(Fw / W, Fh / H), s = s0 * view.z
  // screen = pan + image * s ; centre (cx, cy) of the image sits mid free-area, clamped so no empty band opens up
  const pan = useMemo(() => {
    const iw = W * s, ih = H * s
    const px = iw <= Fw ? ins.l + (Fw - iw) / 2 : clamp(ins.l + Fw / 2 - view.cx * iw, ins.l + Fw - iw, ins.l)
    const py = ih <= Fh ? ins.t + (Fh - ih) / 2 : clamp(ins.t + Fh / 2 - view.cy * ih, ins.t + Fh - ih, ins.t)
    return [px, py]
  }, [W, H, s, Fw, Fh, view, ins.l, ins.t])

  const animateTo = useCallback((to) => {
    cancelAnimationFrame(anim.current)
    const from = viewRef.current
    if (reducedMotion()) { setView(to); return }
    const t0 = performance.now(), D = 420, e = (k) => 1 - (1 - k) ** 3
    const step = (now) => {
      const k = e(Math.min(1, (now - t0) / D))
      setView({ z: from.z + (to.z - from.z) * k, cx: from.cx + (to.cx - from.cx) * k, cy: from.cy + (to.cy - from.cy) * k })
      if (k < 1) anim.current = requestAnimationFrame(step)
    }
    anim.current = requestAnimationFrame(step)
  }, [])
  const zoomBy = (f) => animateTo({ ...viewRef.current, z: clamp(viewRef.current.z * f, 1, Z_MAX) })

  const selTrack = field && sel != null ? field.tracks[sel] : null
  // the object the first-visit hint points at: an unconfirmed mover first, then a distant candidate, then anything
  const hintTrack = useMemo(() => {
    if (!field || !field.tracks.length) return null
    const by = (f) => field.tracks.filter(f).sort((a, b) => b.members.length - a.members.length)[0]
    // a confirmed mover first (a known asteroid, or the injected planet); an unconfirmed track is the last resort
    return by((x) => x.kind === 'fast' && x.known) || by((x) => x.kind === 'distant') || by(() => true)
  }, [field])
  const touring = hint === 0 && hintTrack && sel == null && !pin

  // frames to play: the selected object's own images, or the whole field
  const frames = useMemo(() => {
    if (!field) return []
    const ex = field.exposures
    if (selTrack) {
      let fr = [...new Set(membersOf(field, selTrack).map((c) => c.i))].sort((a, b) => ex[a].mjd - ex[b].mjd)
      if (band === 'one') {
        const cnt = {}; for (const j of fr) cnt[ex[j].detector] = (cnt[ex[j].detector] || 0) + 1
        const best = Object.entries(cnt).sort((a, b) => b[1] - a[1])[0]
        if (best && best[1] >= 4) fr = fr.filter((j) => ex[j].detector === +best[0])
      }
      return fr
    }
    if (touring) {     // first visit: loop the few days when the hinted object crosses the sky, so it is seen moving
      const ms = membersOf(field, hintTrack).map((c) => ex[c.i].mjd), lo = Math.min(...ms) - 0.3, hi = Math.max(...ms) + 0.3
      const win = ex.filter((e) => e.mjd >= lo && e.mjd <= hi && e.coverage > MIN_COVER).map((e) => e.i)
      if (win.length >= 4) return win
    }
    return ex.filter((e) => (pin ? true : band === 'one' ? e.detector === oneDet : dets.has(e.detector)) && e.coverage > MIN_COVER).map((e) => e.i)
  }, [field, selTrack, band, oneDet, dets, pin, touring, hintTrack])
  const rate = hz === 'auto' ? (selTrack ? clamp(frames.length / 7, 1, MAX_HZ) : MAX_HZ) : Math.min(hz, MAX_HZ)
  // playback (the shared loop); the first-visit tour plays once and ends on the summary
  const { k: cur, setK: setCur, playing, setPlaying } = usePlayback(frames.length, {
    hz: rate, autoplay: false, loop: !tour, onEnd: () => { setDone(true); setTour(false) },
  })
  const i = frames[cur]
  const ex = field && i !== undefined ? field.exposures[i] : null

  // pick the detector with the most good images; open on a tour of the most-detected object
  useEffect(() => {
    if (!field) return
    const cnt = {}; for (const e of field.exposures) if (e.coverage > MIN_COVER) cnt[e.detector] = (cnt[e.detector] || 0) + 1
    setOneDet(+Object.entries(cnt).sort((a, b) => b[1] - a[1])[0][0])
    setView(HOME); setCur(0)
    setPlaying(!reducedMotion())   // the sky opens in motion: things that move are seen moving
  }, [field]) // eslint-disable-line react-hooks/exhaustive-deps

  function focusTrack(tr) {
    const pts = membersOf(field, tr)
    const xs = pts.map((c) => c.x), ys = pts.map((c) => H - 1 - c.y)
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
    const pad = 28, bw = x1 - x0 + 2 * pad, bh = y1 - y0 + 2 * pad
    const z = clamp(Math.min(Fw / bw, Fh / bh) / s0, 1, 6)
    animateTo({ z, cx: (x0 + x1) / 2 / W, cy: (y0 + y1) / 2 / H })
  }
  function select(id, { tour: isTour = false } = {}) {
    setPin(null); setSrcSel(null); setSel(id); setDone(false); setTour(isTour); setCur(0)
    if (id != null) { setPanelOpen(true); setSheet((v) => Math.max(v, 1)); if (hint === 0) setHint(1); panelBody.current?.scrollTo({ top: 0 }) }
    if (id == null) { setPlaying(false); animateTo(HOME); return }
    setPlaying(!reducedMotion())
    if (field) focusTrack(field.tracks[id])
  }
  const stopTour = () => { if (tour) setTour(false) }
  /** Show exposure `j` (a click on the selected object's chart): that image if it is playing, else the nearest in time. */
  function seekExposure(j) {
    if (!field || !frames.length) return
    let k = frames.indexOf(j)
    if (k < 0) { const m = field.exposures[j].mjd; k = frames.reduce((b, f, q) => (Math.abs(field.exposures[f].mjd - m) < Math.abs(field.exposures[frames[b]].mjd - m) ? q : b), 0) }
    stopTour(); setDone(false); setPlaying(false); setCur(k)
  }

  // draw base frame (colourised difference frames cached per exposure; only redraws when the frame changes)
  const colorCache = useRef(new Map())
  useEffect(() => {
    if (!field || i === undefined || mode === '3d' || mode === 'universe') return
    const cv = baseRef.current; if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H }
    const g = cv.getContext('2d'); g.fillStyle = '#000'; g.fillRect(0, 0, W, H)
    const kind = mode === 'change' ? 'diff' : mode === 'ref' ? 'ref' : 'sci'
    const im = frameImg(field, kind, i)
    if (!ready(im)) frameImg(field, kind, i, (ok) => ok && setLoadTick((n) => n + 1))
    else if (kind === 'diff') {
      const key = `${field.id}:${i}`, cache = colorCache.current
      let c = cache.get(key)
      if (!c) {
        c = document.createElement('canvas'); c.width = W; c.height = H
        const wg = c.getContext('2d', { willReadFrequently: true }); wg.drawImage(im, 0, 0); colorizeDiff(wg, W, H)
        cache.set(key, c); if (cache.size > 96) cache.delete(cache.keys().next().value)
      }
      g.drawImage(c, 0, 0)
    } else g.drawImage(im, 0, 0)
    // contamination flags (bad grey, ghost magenta, outlier orange) over the frame
    if (show.flags && field.products?.flags) {
      const fm = frameImg(field, 'flag', i)
      if (ready(fm)) g.drawImage(fm, 0, 0); else frameImg(field, 'flag', i, (ok) => ok && setLoadTick((n) => n + 1))
    }
    for (let k = 1; k <= 8; k++) { const j = frames[(cur + k) % frames.length]; if (j !== undefined) frameImg(field, kind, j) }
    // tracking inset: a 6x close-up that keeps the selected object in the middle
    const ic = insetRef.current
    if (ic && selTrack) {
      const pts = membersOf(field, selTrack), t0 = field.exposures[i].mjd, ex_ = field.exposures
      let px = null
      const k = pts.findIndex((c) => ex_[c.i].mjd >= t0 - 1e-6)
      if (k === -1) px = pts.at(-1); else if (k === 0) px = pts[0]
      else { const a = pts[k - 1], b = pts[k], f = (t0 - ex_[a.i].mjd) / Math.max(ex_[b.i].mjd - ex_[a.i].mjd, 1e-9); px = { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f } }
      const R = 15, ig = ic.getContext('2d'); ig.imageSmoothingEnabled = false
      ig.fillStyle = '#000'; ig.fillRect(0, 0, ic.width, ic.height)
      ig.drawImage(cv, Math.round(px.x) - R, H - 1 - Math.round(px.y) - R, 2 * R + 1, 2 * R + 1, 0, 0, ic.width, ic.height)
      ig.strokeStyle = trackColor(selTrack); ig.lineWidth = 2; ig.beginPath(); ig.arc(ic.width / 2, ic.height / 2, ic.width / 9, 0, 7); ig.stroke()
    }
  }, [field, i, mode, W, H, loadTick, frames, cur, selTrack, show.flags])
  // a short cross-fade when the mode changes
  useEffect(() => { if (baseRef.current && !reducedMotion()) baseRef.current.animate([{ opacity: 0.25 }, { opacity: 1 }], { duration: 260, easing: 'ease-out' }) }, [mode])

  // overlay (device pixels)
  useEffect(() => {
    if (!field) return
    const cv = ovRef.current, dpr = window.devicePixelRatio || 1, cw = Sw * dpr, ch = Sh * dpr
    if (cv.width !== cw >>> 0 || cv.height !== ch >>> 0) { cv.width = cw; cv.height = ch }   // resizing reallocates
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, Sw, Sh)
    if (i === undefined) return
    drawOverlay(g, { field, i, Sw, Sh, X: (x) => pan[0] + (x + 0.5) * s, Y: (y) => pan[1] + (H - 0.5 - y) * s, r0: Math.max(7, 2.2 * s),
      focus: sel ?? hov, research, show, revealSim, pin, probe, probePt, cats })
  }, [field, i, Sw, Sh, pan, s, sel, hov, show, revealSim, pin, H, research, probe, probePt, cats])

  // timeline: one band per survey pass, detector ticks, the selected object's images in amber
  useEffect(() => {
    if (!field) return
    drawTimeline(tlRef.current, { field, frames, selTrack, ex, research })
  }, [field, frames, selTrack, ex, Sw, Sh, research, panelOpen, sheet])
  const onTimeline = (e) => {
    const cv = tlRef.current; if (!cv._x || !frames.length) return
    const x = e.nativeEvent.offsetX * (window.devicePixelRatio || 1)
    let best = 0, bd = 1e9
    frames.forEach((j, k) => { const d = Math.abs(cv._x(field.exposures[j].mjd) - x); if (d < bd) { bd = d; best = k } })
    stopTour(); setPlaying(false); setDone(false); setCur(best)
  }

  // keyboard: one window listener for the viewer's lifetime; it calls this render's handler
  const keyRef = useRef()
  keyRef.current = (e) => {
    // keys belong to the focused control (buttons, tabs, sliders, links); the viewer only takes them from the page or the stage
    const barBtn = e.target.tagName === 'BUTTON' && e.target.closest('.vbar, .zoomctl') && e.key !== ' ' && e.key !== 'Enter'
    if (e.key === 'Escape' && armed) { setArmed(false); return }
    if (e.target !== document.body && !e.target.classList?.contains('stage') && !barBtn) return
    if (e.ctrlKey || e.metaKey || e.altKey) return
    const n = frames.length; if (!n) return
    if (e.key === ' ') { e.preventDefault(); stopTour(); setDone(false); setPlaying((p) => !p) }
    else if (e.key === 'ArrowRight') { stopTour(); setPlaying(false); setCur((c) => (c + 1) % n) }
    else if (e.key === 'ArrowLeft') { stopTour(); setPlaying(false); setCur((c) => (c - 1 + n) % n) }
    else if (e.key === 'Home') setCur(0)
    else if (e.key === 'End') setCur(n - 1)
    else if (e.key === '+' || e.key === '=') zoomBy(1.5)
    else if (e.key === '-') zoomBy(1 / 1.5)
    else if (e.key === '0') animateTo(HOME)
    else if (e.key === 'm') setMode((m) => ({ sky: 'change', change: 'ref', ref: '3d', '3d': hasUni ? 'universe' : 'sky', universe: 'sky' })[m])
    else if (e.key === 'Escape') { if (armed) setArmed(false); else if (settings) setSettings(false); else if (menu) setMenu(false); else select(null) }
  }
  useEffect(() => {
    const on = (e) => keyRef.current(e)
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])

  // pointer: drag to pan, wheel to zoom, click a detection to select its object
  const drag = useRef(null), touches = useRef(new Map()), pinch = useRef(null)
  const toImage = (e) => { const r = stageRef.current.getBoundingClientRect(); return [(e.clientX - r.left - pan[0]) / s - 0.5, H - 0.5 - (e.clientY - r.top - pan[1]) / s] }
  const onDown = (e) => {
    if (mode === '3d' || mode === 'universe' || e.target.closest('button, a, input, label, .summary, .zoomctl, .st')) return
    e.currentTarget.setPointerCapture(e.pointerId)
    touches.current.set(e.pointerId, [e.clientX, e.clientY])
    if (touches.current.size === 2) {       // second finger down: start a pinch, stop the pan
      const [a, b] = [...touches.current.values()]
      pinch.current = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, v: viewRef.current }
      if (drag.current) drag.current.moved = true
      return
    }
    drag.current = { x: e.clientX, y: e.clientY, v: view, moved: false }; stageRef.current.classList.add('dragging')
  }
  const onMove = (e) => {
    if (mode === '3d' || mode === 'universe') return
    if (touches.current.has(e.pointerId)) touches.current.set(e.pointerId, [e.clientX, e.clientY])
    if (pinch.current && touches.current.size >= 2) {
      const [a, b] = [...touches.current.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1])
      cancelAnimationFrame(anim.current)
      setView({ ...pinch.current.v, z: clamp(pinch.current.v.z * (d / pinch.current.d), 1, Z_MAX) })
      return
    }
    const [fx, fy] = toImage(e)
    const cel = cursorRef.current
    if (cel) {
      if (field && fx >= 0 && fy >= 0 && fx < W && fy < H) { const [ra, dec] = pix2world(field, fx, fy); cel.textContent = `RA ${ra.toFixed(4)}°  Dec ${dec >= 0 ? '+' : ''}${dec.toFixed(4)}°`; cel.hidden = false } else cel.hidden = true
    }
    if (!drag.current) return
    const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y
    if (Math.hypot(dx, dy) > 3) drag.current.moved = true
    const v = drag.current.v
    setView({ ...v, cx: clamp(v.cx - dx / (W * s), 0, 1), cy: clamp(v.cy - dy / (H * s), 0, 1) })
  }
  const onUp = (e) => {
    touches.current.delete(e.pointerId)
    if (pinch.current) { if (touches.current.size < 2) pinch.current = null; drag.current = null; stageRef.current.classList.remove('dragging'); return }
    if (mode === '3d' || mode === 'universe') return
    stageRef.current.classList.remove('dragging')
    const d = drag.current; drag.current = null
    if (d && !d.moved && field && i !== undefined) {
      const [fx, fy] = toImage(e)
      const hit = !armed && (field.byExp.get(i) || []).find((c) => c.track != null && Math.hypot(c.x - fx, c.y - fy) < Math.max(3, 10 / s))
      if (hit) { setProbe(null); setProbePt(null); select(hit.track) }
      else if (fx >= 0 && fy >= 0 && fx < W && fy < H) runProbe(fx, fy)
    } else if (d?.moved) stopTour()
  }
  useEffect(() => {
    const el = stageRef.current; if (!el) return
    const on = (e) => {
      if (el.classList.contains('is3d')) return
      e.preventDefault(); cancelAnimationFrame(anim.current)
      const r = el.getBoundingClientRect(), v = viewRef.current
      const z = clamp(v.z * (e.deltaY < 0 ? 1.25 : 0.8), 1, Z_MAX)
      // keep the image point under the cursor fixed
      const iw = W * s0 * v.z, ih = H * s0 * v.z
      const ux = (e.clientX - r.left - pan[0]) / iw, uy = (e.clientY - r.top - pan[1]) / ih
      const k = v.z / z
      setView({ z, cx: clamp(ux + (v.cx - ux) * k, 0, 1), cy: clamp(uy + (v.cy - uy) * k, 0, 1) })
    }
    el.addEventListener('wheel', on, { passive: false })
    return () => el.removeEventListener('wheel', on)
  }, [field, W, H, s0, pan])

  // ---- 3D space-time cube -------------------------------------------------
  useEffect(() => {
    if (mode !== '3d' || !field) return
    let dead = false, inst = null
    import('./spacetime.js').then(({ SpaceTime }) => {
      if (dead) return
      try { inst = new SpaceTime(stCanvas.current, stLabels.current, { reduced: reducedMotion(), onProgress: (n, m) => setStLoad(n < m ? [n, m] : null) }) } catch { setStLoad('nogl'); return }
      setSt(inst)
    })
    return () => { dead = true; inst?.destroy(); setSt(null) }
  }, [mode, field])
  const frames3d = useMemo(() => {
    if (!field) return []
    const ex = field.exposures
    if (!selTrack) return ex.filter((e) => e.coverage > MIN_COVER).map((e) => e.i)   // the whole field, all detectors (sampled)
    const mem = membersOf(field, selTrack)
    if (selTrack.kind === 'distant') return [...new Set(mem.map((c) => c.i))]
    // every image taken while the object was being tracked (all detectors), so its streak is continuous
    const ms = mem.map((c) => ex[c.i].mjd), lo = Math.min(...ms) - 0.2, hi = Math.max(...ms) + 0.2
    return ex.filter((e) => e.mjd >= lo && e.mjd <= hi && e.coverage > MIN_COVER).map((e) => e.i)
  }, [field, selTrack])
  useEffect(() => { if (st && field) { setStLoad([0, frames3d.length]); st.setData({ field, frames: frames3d, track: selTrack, color: selTrack ? trackColor(selTrack) : null }) } }, [st, field, frames3d, selTrack])
  useEffect(() => { if (st && i !== undefined) st.setCurrent(i) }, [st, i])
  useEffect(() => { st?.showNoise(noise) }, [st, noise])

  // test hook (automated checks): where field pixel (x, y) is on screen, and which exposure is shown
  useEffect(() => { window.__sxView = { i, toScreen: (x, y) => { const r = stageRef.current?.getBoundingClientRect(); return r ? [r.left + pan[0] + (x + 0.5) * s, r.top + pan[1] + (H - 0.5 - y) * s] : null } } }, [i, pan, s, H])
  async function runProbe(fx, fy) {
    setPlaying(false); stopTour(); setDone(false); setArmed(false)
    setProbePt({ x: fx, y: fy, i }); setProbe('loading'); setSheet((v) => Math.max(v, 1)); setPanelOpen(true); panelBody.current?.scrollTo({ top: 0 })
    try { setProbe(await api(`/api/probe?field=${encodeURIComponent(field.id)}&x=${fx.toFixed(2)}&y=${fy.toFixed(2)}&i=${i}`)) }
    catch { setProbe({ error: '伺服器暫時無法分析，請稍後再試。' }) }
  }
  // once the pinned candidate's frame is in the list, jump to it
  useEffect(() => { if (pin) { const k = frames.indexOf(pin.i); if (k >= 0) setCur(k) } }, [pin, frames])

  // what is in this sky: fixed per field, so built once (the rows keep their identity and the list skips re-rendering)
  const lists = useMemo(() => {
    if (!field) return null
    const fastAll = field.tracks.filter((tr) => tr.kind === 'fast')
    const groups = []
    for (const tr of fastAll) { const g = tr.known && groups.find((x) => x[0].known === tr.known); if (g) g.push(tr); else groups.push([tr]) }
    const distant = field.tracks.filter((tr) => tr.kind === 'distant')
    const pl = pLink(field)
    return {
      distant,
      // list order: distant candidates (and the simulated planet), then unconfirmed movers, then known ones
      rows: [...distant.map((tr) => [tr]), ...groups.sort((a, b) => (!!a[0].known - !!b[0].known) || b[0].mean_p - a[0].mean_p)],
      nKnown: new Set(fastAll.filter((x) => x.known).map((x) => x.known)).size,
      nUnknown: fastAll.filter((x) => !x.known).length,
      nSim: field.tracks.filter((x) => x.sim).length,
      nMatched: field.candidates.filter((c) => c.known).length,
      loose: field.candidates.filter((c) => c.track == null && !c.known && c.p >= pl).sort((a, b) => b.p - a.p),
    }
  }, [field])
  // handlers handed to memoised children keep one identity and call this render's code
  const act = useRef()
  act.current = { select, pick: (id) => { setProbe(null); setProbePt(null); setSrcSel(null); select(id) } }
  const pick = useCallback((id) => act.current.pick(id), [])
  const onRowSelect = useCallback((id) => (id == null ? act.current.select(null) : act.current.pick(id)), [])
  const skipTour = useCallback(() => setHint(3), [setHint])
  const hintId = touring ? hintTrack.id : null
  const tagFor = useCallback((tr) => <ObjLabel tr={tr} on={tr.id === sel} hint={tr.id === hintId} onPick={pick} onSkip={skipTour} />, [sel, hintId, pick, skipTour])
  const labels3d = useMemo(() => (field && mode === 'universe' ? field.tracks.map((tr) => ({ key: `m${tr.id}`, node: tagFor(tr) })) : null), [field, mode, tagFor])

  if (err) return <section className="band"><h1>找不到這個天區</h1><p className="lead">這個網址沒有對應的天區，可能已被移除或網址打錯了。</p><p className="lead">可以看看：<a href="#/field/cybele">65 Cybele</a>、<a href="#/field/planetx">Planet X 測試</a>、<a href="#/field/taurus">金牛座</a>。</p><button className="btn" onClick={() => go(null)}>回到首頁</button></section>
  if (!field) return <div className="viewer loading"><p className="st-load">載入天區資料中…</p></div>

  const { distant, rows, nKnown, nUnknown, nSim, nMatched, loose } = lists
  const sim = field.simulated?.[0]
  const lowRef = ex && ex.nref < 2
  function pinCand(c) {
    setSel(null); setTour(false); setDone(false); setPlaying(false); setPin(c)
    const ys = H - 1 - c.y
    animateTo({ z: 4, cx: c.x / W, cy: ys / H })
  }
  const curMember = selTrack && i !== undefined ? membersOf(field, selTrack).find((c) => c.i === i) : null
  const is3D = mode === 'universe' || mode === '3d'
  const selGroup = selTrack ? (rows.find((g) => g.some((x) => x.id === sel)) || [selTrack]) : null

  // name tags on the image view: where each object is at the current image (interpolated inside its span)
  const tags2d = []
  if (!is3D && ex) {
    const tnow = ex.mjd
    for (const tr of field.tracks) {
      if (sel != null && tr.id !== sel) continue
      const pts = membersOf(field, tr), ts = pts.map((c) => field.exposures[c.i].mjd)
      if (tnow < ts[0] - 0.05 || tnow > ts.at(-1) + 0.05) continue
      let k = ts.findIndex((m) => m >= tnow - 1e-6); if (k < 0) k = pts.length - 1
      const a = pts[Math.max(0, k - 1)], b = pts[k], f = k === 0 ? 1 : clamp((tnow - ts[k - 1]) / Math.max(ts[k] - ts[k - 1], 1e-9), 0, 1)
      if (tr.kind === 'distant' && Math.abs(ts[k] - tnow) > 2 && Math.abs((ts[k - 1] ?? -1e9) - tnow) > 2) continue   // between passes it is not in the sky we see
      const x = a.x + (b.x - a.x) * f, y = a.y + (b.y - a.y) * f
      tags2d.push({ tr, left: pan[0] + (x + 0.5) * s, top: pan[1] + (H - 0.5 - y) * s })
    }
  }
  const nObjects = rows.length
  const listSummary = nObjects ? L(`${nObjects} 個太陽系移動天體（幾小時內移動）`, `${nObjects} Solar System mover${nObjects > 1 ? 's' : ''} (moving within hours)`) : t`${loose.length} 個沒有串成軌跡的 AI 候選`
  const nStars = stars ? stars.filter((c) => c.status !== 'static').length : 0

  return (
    <div className={`viewer v2 sheet-${sheet} ${panelOpen ? '' : 'panel-closed'}`}>
      <div className={`stage ${is3D ? 'is3d' : ''} ${armed ? 'armed' : ''}`} ref={stageRef} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp} onPointerLeave={() => { if (cursorRef.current) cursorRef.current.hidden = true }}
        tabIndex={0} aria-label={L('SPHEREx 影像。方向鍵逐張、空白鍵播放、+/- 縮放（觸控用雙指）、0 重設、M 切換模式、Esc 取消選取', 'SPHEREx images. Arrow keys step, Space plays, +/- zoom (pinch on touch screens), 0 resets, M changes mode, Esc deselects')}>
        <canvas ref={baseRef} style={{ width: W, height: H, transform: `translate(${pan[0]}px, ${pan[1]}px) scale(${s})` }} />
        <canvas ref={ovRef} style={{ width: Sw, height: Sh }} />
        {!is3D && tags2d.map(({ tr, left, top }) => <div key={tr.id} className="tag2d" style={{ transform: `translate(${left}px, ${top}px)` }}>{tagFor(tr)}</div>)}
        {mode === 'universe' && (
          <Suspense fallback={<p className="st-load">正在建構這片天空…</p>}>
            <Sky3D field={field} mjd={ex ? ex.mjd : null} sel={sel} frame={ins}
              labels={labels3d}
              onPickTrack={pick}
              onPickSource={(src) => { setProbe(null); setProbePt(null); setSrcSel(src); setPanelOpen(true); setSheet((v) => Math.max(v, 1)) }}
              onPlane={({ x, y }) => { setSrcSel(null); runProbe(x, y) }} />
          </Suspense>
        )}
        {mode === '3d' && (
          <div className="st">
            <canvas ref={stCanvas} aria-label="時空立方體：差分影像依時間疊成 3D，拖曳旋轉、滾輪縮放" />
            <div ref={stLabels} className="st-labels" aria-hidden="true" />
            <div className="st-ctl seg" role="group" aria-label="點雲">
              <button aria-pressed={!noise} onClick={() => setNoise(false)}>只看 AI 偵測</button>
              <button aria-pressed={noise} onClick={() => setNoise(true)}>顯示雜訊</button>
            </div>
            {stLoad === 'nogl' ? <p className="st-cap">這個瀏覽器不支援 WebGL，無法顯示 3D。</p>
              : stLoad ? <p className="st-load">{t`正在疊合差分影像 ${stLoad[0]} / ${stLoad[1]}`}</p>
              : <p className="st-cap">{selTrack ? (selTrack.kind === 'distant' ? t`深度是時間，越深越晚。${trackTitle(selTrack)} 在每輪巡天之間來回擺動：這是地球繞太陽造成的視差，擺幅越小越遠（擬合 ${selTrack.d_au} AU）。` : t`深度是時間，越深越晚。亮點是 AI 偵測；${trackTitle(selTrack)} 在時空中拉成一條斜線，斜率就是它在天空中的速度。`) : (noise ? '淡色的點就是 AI 要篩掉的東西：差分影像裡所有的變化。切回「只看 AI 偵測」，剩下的移動天體會連成斜線。' : '深度是時間，越深越晚。亮點是 AI 偵測，移動的天體連成斜線。按「顯示雜訊」看看 AI 篩掉了多少東西。')}</p>}
          </div>
        )}
        <div className="cursor" ref={cursorRef} hidden />
        {selTrack && !is3D && <figure className="inset" aria-label="放大追蹤：天體保持在中央"><canvas ref={insetRef} width={186} height={186} /><figcaption>放大 6 倍追蹤</figcaption></figure>}
      </div>

      {/* top left: which sky this is, and how to get to another one */}
      <header className="vfield glass">
        <h1>{fieldName(field)}</h1>
        <p>{fieldDesc(field)}</p>
        <div className="vf-row">
          {nSim > 0 && <span className="tag sim">含模擬行星</span>}
          {field.target && <a className="chip" href={`#/target/${field.id}`}>目標分析 {ICON.next}</a>}
          {field.products && !field.target && <a className="chip" href={`#/lab/${encodeURIComponent(field.id)}`}>天區工作台 {ICON.next}</a>}
          <button className="chip vf-switch" onClick={() => setMenu((v) => !v)} aria-expanded={menu} aria-haspopup="true">換一片天空 {ICON.next}</button>
        </div>
        {menu && (
          <ul className="vf-menu" role="menu">
            {fieldList.map((f) => (
              <li key={f.id} role="none"><button role="menuitem" aria-current={f.id === field.id ? 'true' : undefined} onClick={() => { setMenu(false); if (f.id !== field.id) go(f.id) }}>
                <b>{fieldName(f)}</b><span>{t`${f.n_exposures} 張影像 · ${f.n_tracks} 條軌跡`}</span></button></li>
            ))}
            <li role="none"><button role="menuitem" onClick={() => { setMenu(false); go(null); setTimeout(() => document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth' }), 400) }}><b>分析任何一片天空 →</b><span>在全天圖上選一個位置</span></button></li>
          </ul>
        )}
      </header>

      {/* top centre: two ways of looking */}
      <div className="vmodes">
        <div className="seg glass" role="group" aria-label="檢視模式">
          {[['sky', L('影像', 'Images')], ['change', L('差分', 'Difference')], ...(research ? [['ref', L('參考', 'Reference')]] : [])].map(([m, l]) => <button key={m} aria-pressed={mode === m} onClick={() => setMode(m)}>{l}</button>)}
          {hasUni ? <button className="m3d" aria-pressed={is3D} onClick={() => setMode('universe')}>{L('3D 重建', '3D model')}</button>
            : <button className="m3d" aria-pressed={mode === '3d'} onClick={() => setMode('3d')}>{L('3D 時空', '3D space-time')}</button>}
        </div>
        {hasUni && is3D && <button className={`chip glass ${mode === '3d' ? 'on' : ''}`} onClick={() => setMode(mode === '3d' ? 'universe' : '3d')} aria-pressed={mode === '3d'}>{mode === '3d' ? '回到 3D 宇宙' : '把時間疊起來'}</button>}
        {armed && <p className="armbar">點天空任何一點檢查它 · Esc 取消</p>}
      </div>

      <div className="zoomctl glass" hidden={is3D}>
        <button onClick={() => zoomBy(1.5)} aria-label="放大">{ICON.plus}</button>
        <button onClick={() => zoomBy(1 / 1.5)} aria-label="縮小">{ICON.minus}</button>
        <button onClick={() => animateTo(HOME)} aria-label="重設縮放">{ICON.reset}</button>
      </div>

      {/* bottom: time */}
      <div className="vplayer vbar glass">
        <PlayButton playing={playing} bare small={false} onClick={() => { stopTour(); setDone(false); setPlaying((p) => !p) }} />
        {research && <>
          <button className="iconbtn" onClick={() => { stopTour(); setPlaying(false); setCur((c) => (c - 1 + frames.length) % frames.length) }} aria-label="上一張">{ICON.prev}</button>
          <button className="iconbtn" onClick={() => { stopTour(); setPlaying(false); setCur((c) => (c + 1) % frames.length) }} aria-label="下一張">{ICON.next}</button>
        </>}
        <div className="tl">
          <canvas ref={tlRef} className="timeline" role="img" aria-label="拍攝時間軸：每段是一輪巡天；琥珀色是選取天體出現的影像。點一下跳到那個時間" onClick={onTimeline} />
          <p className="tl-meta" aria-live={playing ? 'off' : 'polite'}>
            {ex && <span className="num">{ex.iso.slice(0, 16).replace('T', ' ')} UTC · {ex.lam_um.toFixed(2)} µm{ex.release ? ` · ${ex.release}` : ''}{research && <> · <span style={{ color: DET[ex.detector].c }}>D{ex.detector}</span></>}</span>}
            {selTrack && <span className="num">{t`${trackTitle(selTrack)} · 第 ${cur + 1} / ${frames.length} 張`}</span>}
            {touring && <span>{t`正在播放 ${trackTitle(hintTrack)} 經過的那幾天`}</span>}
            {lowRef && mode === 'change' && <span className="warn">參考影像不足，變化圖可信度較低</span>}
            {curMember == null && selTrack && ex && !is3D && <span className="warn">這張影像裡沒有偵測到它</span>}
            {mode === 'change' && <span className="ramp-wrap"><span>變暗</span><i className="ramp" style={{ background: legendGradient() }} /><span>變亮</span></span>}
            <span className="keys">空白鍵播放 · ← → 逐張</span>
          </p>
        </div>
        <div className="probe-wrap">
          {hint === 2 && <Hint className="at-probe" onNext={skipTour} next="知道了">想自己判斷？按這裡，再點天空任何一點</Hint>}
          <button className={`chip probe-btn ${armed ? 'on' : ''}`} onClick={() => { setArmed((v) => !v); if (hint === 2) setHint(3) }} aria-pressed={armed} title="點天空裡的任何一點，檢查它是不是行星">{ICON.target}<span>檢查一點</span></button>
        </div>
        <button className={`iconbtn settings-btn ${settings ? 'on' : ''}`} onClick={() => setSettings((v) => !v)} aria-expanded={settings} aria-label="更多設定" title="更多設定">{ICON.settings}</button>
        {settings && <ViewerSettings field={field} onClose={() => setSettings(false)} band={band} setBand={setBand} oneDet={oneDet} setOneDet={setOneDet} dets={dets} setDets={setDets}
          hasSel={!!selTrack} show={show} setShow={setShow} sim={sim} revealSim={revealSim} setRevealSim={setRevealSim} hz={hz} setHz={setHz} maxHz={MAX_HZ}
          onReplayTour={() => { setSettings(false); select(null); setHint(0); setPlaying(!reducedMotion()) }} />}
      </div>

      {!panelOpen && <button className="vpanel-open glass" onClick={() => setPanelOpen(true)}>{listSummary} {ICON.prev}</button>}

      {/* right: what is in this sky, and the selected object */}
      <aside className="vpanel glass side" aria-label="天體清單">
        <button className="drawer-handle" onClick={() => setSheet((v) => (v + 1) % 3)} aria-label={['展開清單', '全螢幕清單', '收合清單'][sheet]}>
          <i aria-hidden="true" /><span>{selTrack ? trackTitle(selTrack) : listSummary}</span><span className="dh-act">{['展開', '全部', '收合'][sheet]}</span>
        </button>
        <div className="vpanel-body" ref={panelBody}>
          {srcSel && !probe && <SourceCard field={field} src={srcSel} onClose={() => setSrcSel(null)} onProbe={(x, y) => { setSrcSel(null); runProbe(x, y) }} />}
          {probe && <ProbeCard field={field} probe={probe} onClose={() => { setProbe(null); setProbePt(null) }} onSelect={(id) => { setProbe(null); setProbePt(null); select(id) }} />}
          {!probe && !srcSel && selTrack && (
            <Detail field={field} group={selGroup} sel={sel} research={research} onSelect={(id) => select(id)} onClose={() => select(null)}
              current={i} frames={frames} onSeek={seekExposure}
              hint={hint === 1} onHintNext={hint === 1 ? () => setHint(2) : null} onSkip={skipTour} />
          )}
          <div className="vlist-head">
            <h2>{listSummary}</h2>
            <button className="iconbtn small collapse" onClick={() => setPanelOpen(false)} aria-label="收起清單">{ICON.next}</button>
          </div>
          {nSim > 0 && sim && <p className="note sim">{t`這片天空有 ${nSim} 顆注入的模擬行星（距離 ${sim.d_au.toFixed(0)} AU，刻意調亮到 AB ${sim.mag_ab.toFixed(1)}），用來測試管線；不是發現。`}</p>}
          <ul className="tracklist">
            {rows.map((g) => <Row key={g[0].id} field={field} group={g} sel={sel} onSelect={onRowSelect} onHover={setHov} glow={touring && g.some((x) => x.id === hintTrack.id)} />)}
          </ul>
          {stars && (nStars > 0 || field.target) && (
            <p className="note stars-note">
              {nStars > 0 ? L(`另外，這片天空有 ${nStars} 顆在各輪巡天之間移動的恆星（幾年才移動一點，和上面的小行星是兩回事）。`, `Separately, ${nStars} star${nStars > 1 ? 's' : ''} in this sky move${nStars > 1 ? '' : 's'} between survey passes (a little over years; not the same thing as the asteroids above).`)
                : L('這片天空沒有找到在各輪巡天之間移動的恆星。', 'No star in this sky was found moving between survey passes.')}
              {' '}<a href={field.target ? `#/target/${field.id}` : `#/lab/${encodeURIComponent(field.id)}`}>{L('在工作台看 →', 'See them in the lab →')}</a>
            </p>
          )}
          {!rows.length && <p className="hint">這片天空目前沒有串成軌跡的移動天體。軌跡至少要有 4 次偵測、跨越 3 個時間點、總位移大於 16″；下面是 AI 認為像真訊號、但沒有串成軌跡的單次偵測。</p>}
          {!rows.length && loose.length > 0 && <ul className="tracklist">{loose.slice(0, 40).map((c) => <CandCard key={c.id} field={field} c={c} on={pin?.id === c.id} onPick={() => pinCand(c)} />)}</ul>}
          {research && (
            <details className="quality">
              <summary>資料品質</summary>
              <p className="hint">{t`${field.exposures.length} 張影像 · ${nKnown} 個已知天體 · ${nUnknown} 個未確認`}{nSim ? t` · ${nSim} 顆模擬行星` : ''}</p>
              {field.static_veto?.n > 0 && <p className="hint">{L(`${field.static_veto.n} 個偵測落在同一個位置反覆出現超過 ${field.static_veto.gap_d} 天的地方（亮星或飽和星的殘差），沒有列入軌跡連結。`, `${field.static_veto.n} detections sit where detections keep recurring for more than ${field.static_veto.gap_d} days (residuals of bright or saturated stars) and were left out of track linking.`)}</p>}
              {field.blind_link && field.tracks.length > 0 && <p className="hint">{t`只靠 AI 分數、不看星表的盲連結會串出 ${field.blind_link.n_tracks} 條軌跡（${field.blind_link.n_known} 條對上已知小行星）；標「星表輔助」的軌跡是靠 JPL 預測位置才串起來的。`}</p>}
              {nKnown === 0 && field.known_bodies.length > 0 && <p className="hint">{t`有 ${field.known_bodies.length} 個已知小天體經過這片天空，其中 ${nMatched} 次偵測對上位置，但沒有串成軌跡。`}</p>}
              {field.known_lookup && !field.known_lookup.ok && <p className="hint warn">{t`有 ${field.known_lookup.failed} 次 JPL 已知天體查詢失敗；部分「未辨識」可能其實是已知天體。`}</p>}
              {!distant.length && <p className="hint">{field.distant_search?.skipped ? t`這片天空太擁擠（${field.distant_search.pool} 個候選），這次沒有執行遠距搜尋。` : '遠距搜尋沒有找到符合視差的軌跡。'}</p>}
            </details>
          )}
          {research && <details className="quality"><summary>這片天空的資料</summary><SkyPanel field={field} /></details>}
        </div>
      </aside>
    </div>
  )
}
