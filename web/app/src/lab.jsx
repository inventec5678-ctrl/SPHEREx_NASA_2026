// Field lab: everything the challenge's "potential considerations" ask for, on one page per field.
//   - per-pass stacks of all bands or of one detector array, blinked, combined (deeper) or subtracted (what changed)
//   - a false-colour view of the 102 bands (D1 blue, D3 green, D6 red)
//   - Gaia DR3 and CatWISE2020 overlays with proper-motion arrows
//   - SPHEREx contamination flags per pass (saturation, persistence, ghosts, outliers, unusable pixels)
//   - click any pixel: light curve and spectrum from every exposure, on the fly, with CSV download, and a button to
//     flag the position for others to review
//   - field of view, data freshness and a one-click update with the newest SPHEREx data, Aladin Lite, coordinate link
// QuickLab is the same lab for any position: a finished quick look writes the same products (sxlib/quicklook.py).
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { DET, L, PASS_C, PIX, api, dataBase, forgetField, getField, mjdToIso, pix2world, reducedMotion } from './lib.js'
import { fieldDesc, fieldName } from './fields_text.js'
import { go } from './nav.js'
import { AladinView } from './quick.jsx'
import { EmbedCode } from './embedcode.jsx'
import { Tour } from './tour.jsx'
import { targetAbout, targetName } from './targets_meta.jsx'
import { SkySearch } from './search.jsx'
import { hashParams, setHashParams } from './sky.js'
import { usePlayback } from './play.js'
import { dpr, useBoxWidth } from './canvas.js'
import { PlayButton } from './playbar.jsx'
import { TimeWave } from './timewave.jsx'
import { MotionPlot } from './motion.jsx'
import { FieldFacts } from './fieldcard.jsx'
import SPEC_T from './spec_templates.json'
import { ChartCard, COL, DET_RANGE, Meter, Plot, extent } from './charts.jsx'
import { SectionNav } from './secnav.jsx'
import { useMode } from './mode.js'
import { askAbout, setPageContext } from './ask/store.js'
import { jobError, jobFinished, poll, postJson } from './jobs.js'
import { ElsewhereLinks } from './elsewhere.jsx'
import { NeossatCoverage } from './neossat.jsx'
import { StarCard } from './starcard.jsx'
import { finite, jacobian, loadGroup as loadGroupAt, motionToPix, passTimes, pixToMotion, quant, stretchMap } from './shiftadd.js'
import { BrightnessPop, ShiftPanel, drawShift, sharpness, shiftGeometry, shiftPix, useBright, useShiftAdd } from './wiseview.jsx'

// movers.jsx pulls in the validation and WiseView pages (~150 kB): load it only when its lists are shown
const loadMovers = () => import('./movers.jsx')
const MoverList = lazy(() => loadMovers().then((m) => ({ default: m.MoverList })))
const VariableList = lazy(() => loadMovers().then((m) => ({ default: m.VariableList })))
const BdText = lazy(() => loadMovers().then((m) => ({ default: ({ s }) => m.bdText(s) })))

export { targetName }
const fmtFlux = (f) => (Math.abs(f) >= 1000 ? `${(f / 1000).toPrecision(3)} mJy` : `${f.toPrecision(3)} µJy`)
// what to look for, per target (shown under the description)
const LOOK = {
  barnard: ['看什麼：用「輪播」或「差分」。它每半年移動約 5″（將近 1 個像素），差分時會變成一對橘藍點。', 'What to look for: Blink or Difference. It moves about 5″ (nearly a pixel) every six months, so the difference shows an orange-blue pair.'],
  epsindi: ['看什麼：選 D6 或假彩色。兩顆棕矮星在長波段最亮；每半年移動約 2.4″，比一個像素小，所以輪播時只會微微偏移。注意：Ba 和 Bb 兩顆只相距約 0.7″，不到 SPHEREx 一個像素（6.15″）的八分之一，所以在影像上合成一個點，量到的是兩顆加起來的光；要分開它們得用哈伯或 JWST 等級的解析度。', 'What to look for: pick D6 or False colour. The brown dwarfs are brightest at long wavelengths; they move about 2.4″ per six months, under a pixel, so the blink shows only a slight shift. Note: Ba and Bb are only about 0.7″ apart, less than an eighth of a SPHEREx pixel (6.15″), so they merge into one point and the photometry is their combined light; splitting them takes Hubble- or JWST-class resolution.'],
  wise0855: ['看什麼：光譜。流量在 3.5 µm 附近最低，過了 4 µm 又升高：這是極冷 Y 型棕矮星的特徵（甲烷與水吸收，4–5 µm 有「窗口」）。短波長的光大多來自旁邊的星。', 'What to look for: the spectrum. Flux bottoms out near 3.5 µm and climbs again past 4 µm, the signature of a cold Y dwarf (methane and water absorption with a 4–5 µm window). Most of the short-wavelength light comes from a neighbouring star.'],
  rwaur: ['看什麼：光變曲線與各輪光譜。同一波段的點在不同輪次高低不同，代表它的亮度真的在變。', 'What to look for: the light curve and the per-pass spectra. Points of one band sit at different heights in different passes: its brightness really changes.'],
  rdra: ['看什麼：光譜的顏色代表巡天輪次。米拉變星在亮與暗之間差好幾倍，不同輪次的光譜會整條上下移動。', 'What to look for: the spectrum, coloured by survey pass. A Mira changes brightness several-fold, so whole spectra from different passes sit higher or lower.'],
}
// ---- float16 stacks: one band group at a time (pass/stacks_g<k>.bin; the loader lives in shiftadd.js, which the
// "find movers" practice shares) ----------------------------------------------------------------------------------
const loadGroup = (id, g, P, n, onProgress) => loadGroupAt(dataBase(id), g, P, n, onProgress)
// per-pass contamination map (pass/flags.bin, sxlib/products.pass_flags): bit, colour, name
const PFLAG = [
  [2, [255, 70, 70], ['飽和（OVERFLOW）', 'saturated (OVERFLOW)']],
  [16, [170, 120, 255], ['殘影（PERSIST）', 'persistence (PERSIST)']],
  [4, [255, 79, 216], ['鬼影（GHOST）', 'ghost (GHOST)']],
  [8, [255, 160, 60], ['離群，例如宇宙射線（OUTLIER）', 'outlier, e.g. a cosmic ray (OUTLIER)']],
  [1, [150, 150, 150], ['不可用（熱、冷、壞像素或偵測器邊緣）', 'unusable (hot, cold or dead pixel, or the detector edge)']],
]
const flagCache = new Map()
function loadFlags(id) {
  if (!flagCache.has(id)) {
    flagCache.set(id, fetch(`${dataBase(id)}/pass/flags.bin`).then((r) => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer() }).then((b) => {
      const [P, , n] = new Int32Array(b, 0, 4), u = new Uint8Array(b, 16)
      return { P, n, get: (p) => u.subarray(p * n * n, (p + 1) * n * n) }
    }).catch((e) => { flagCache.delete(id); throw e }))
  }
  return flagCache.get(id)
}
const flagNames = (v) => PFLAG.filter(([b]) => v & b).map(([, , t]) => L(...t))
// the Gaia / CatWISE overlay of a field, fetched once and shared by the image and Aladin (a failure is retried next time)
const NO_OVERLAYS = { gaia: [], catwise: [] }
const overlayCache = new Map()
function loadOverlays(id) {
  if (!overlayCache.has(id)) overlayCache.set(id, fetch(`${dataBase(id)}/overlays.json`).then((r) => r.json()).catch((e) => { overlayCache.delete(id); throw e }))
  return overlayCache.get(id)
}
/** A field's JSON product, or null when it is missing. */
const fetchProduct = (id, name) => fetch(`${dataBase(id)}/${name}`).then((r) => (r.ok ? r.json() : null))

function divMap(a) {
  const v = finite(a, 3)
  const sig = Math.max(1e-6, quant(v.map(Math.abs).sort((x, y) => x - y), 0.5) * 1.48)
  return (x) => (isFinite(x) ? Math.max(-1, Math.min(1, x / (6 * sig))) : 0)
}

/** Channels (one grey, or red / green / blue) -> an n x n ImageData, each through its own brightness map. */
function paint(n, chans, maps) {
  const out = new Uint8ClampedArray(n * n * 4), grey = chans.length === 1
  for (let y = 0, k = 0; y < n; y++) {
    for (let x = 0, o = (n - 1 - y) * n * 4; x < n; x++, k++, o += 4) {    // row 0 is the bottom: flip for the canvas
      if (grey) { const v = maps[0](chans[0][k]); out[o] = v; out[o + 1] = v; out[o + 2] = v } else { out[o] = maps[0](chans[0][k]); out[o + 1] = maps[1](chans[1][k]); out[o + 2] = maps[2](chans[2][k]) }
      out[o + 3] = 255
    }
  }
  return new ImageData(out, n, n)
}

/**
 * Paint one view of the stacks: { img, vals } (vals: the values behind the picture, for the brightness histogram).
 * br: the visitor's brightness settings (percentile limits, linear or asinh, invert); sa: the plain and shifted sums
 * of the shift-and-add view, both drawn on the plain sum's scale so a sharper star really shows brighter.
 */
function render(S, view, br, sa) {
  const { n } = S, N = n * n
  if (view.mode === 'shift') {
    if (!sa) return null
    const maps = sa.plain.map((c) => stretchMap(c, br))
    return { img: paint(n, sa.plain, maps), img2: paint(n, sa.shifted, maps), vals: sa.plain[0] }
  }
  const passes = view.mode === 'all' ? [...Array(S.P).keys()] : [view.a]
  const combine = (d) => {
    const acc = new Float32Array(N), cnt = new Uint16Array(N)
    for (const p of passes) { const s = S.get(p, d); for (let k = 0; k < N; k++) if (isFinite(s[k])) { acc[k] += s[k]; cnt[k]++ } }
    for (let k = 0; k < N; k++) acc[k] = cnt[k] ? acc[k] / cnt[k] : NaN
    return acc
  }
  if (view.mode === 'diff') {
    const out = new Uint8ClampedArray(N * 4)
    const A = S.get(view.a, view.band === 'rgb' ? 0 : view.band), B = S.get(view.b, view.band === 'rgb' ? 0 : view.band)
    // each pass has its own residual background: compare them about their own medians
    const ma = quant(finite(A, 3), 0.5) || 0, mb = quant(finite(B, 3), 0.5) || 0
    const d = new Float32Array(N)
    for (let k = 0; k < N; k++) d[k] = (A[k] - ma) - (B[k] - mb)
    const m = divMap(d)
    for (let y = 0, k = 0; y < n; y++) {
      for (let x = 0, o = (n - 1 - y) * n * 4; x < n; x++, k++, o += 4) {
        const v = m(d[k])
        out[o] = v > 0 ? 255 * Math.sqrt(v) : 0; out[o + 1] = v > 0 ? 180 * Math.sqrt(v) : 120 * Math.sqrt(-v); out[o + 2] = v < 0 ? 255 * Math.sqrt(-v) : 0; out[o + 3] = 255
      }
    }
    return { img: new ImageData(out, n, n), vals: null }
  }
  const chans = view.band === 'rgb' ? [6, 3, 1].map((d) => combine(d)) : [combine(view.band)]
  return { img: paint(n, chans, chans.map((c) => stretchMap(c, br))), vals: chans[0] }
}

/** Catalogue stars worth drawing: every fast mover, plus the brightest `n` (a crowded field otherwise hides the image). */
const canvasOf = (r) => r.current || (r.current = document.createElement('canvas'))
const fastStar = (st) => Math.hypot(st.pmx, st.pmy) * PIX > 0.15
export function thinStars(list, n = 150) {
  const bright = new Set([...list].sort((a, b) => (a.m ?? 99) - (b.m ?? 99)).slice(0, n))
  return list.filter((st) => bright.has(st) || fastStar(st))
}

function StackView({ field, tg, onPick, pick, movers, side, chart = true }) {
  const pr = field.products
  const P = pr.passes.length
  const [err, setErr] = useState(false)
  // the view lives in the URL (?t=mode&a=&b=&band=&z=), so a shared link opens on the same picture
  const init = useMemo(() => { const u = hashParams(), n = (k) => (u.get(k) != null && isFinite(+u.get(k)) ? +u.get(k) : null); return { t: u.get('t'), a: n('a'), b: n('b'), band: u.get('band'), z: n('z'), fl: u.get('fl') === '1' } }, [])
  const [mode, setMode] = useState(['blink', 'one', 'all', 'diff', 'shift'].includes(init.t) && (P > 1 || init.t === 'one') ? init.t : P > 1 ? 'blink' : 'one')
  const [a, setA] = useState(init.a != null && init.a < P ? init.a : 0), [b, setB] = useState(init.b != null && init.b < P ? init.b : Math.max(0, P - 1))
  const [band, setBand] = useState(init.band === 'rgb' ? 'rgb' : init.band != null && +init.band >= 0 && +init.band <= 6 ? +init.band : tg?.id === 'wise0855' ? 6 : 0)
  const [zoom, setZoom] = useState([1, 2, 4].includes(init.z) ? init.z : tg ? 4 : 1)
  const [kb, setKb] = useState(null)                                 // keyboard cross (field pixels), before Enter measures it
  const [br, setBr] = useBright()                                    // brightness: percentile limits, stretch, invert (WiseView-style)
  // shift-and-add: the trial motion in arcsec/yr toward the east and the north, kept in the link (?sm=east,north)
  const [mot, setMot] = useState(() => { const m = (hashParams().get('sm') || '').split(',').map(Number); return m.length === 2 && m.every(Number.isFinite) ? { east: m[0], north: m[1] } : { east: 0, north: 0 } })
  const [how, setHow] = useState('mean'), [ref, setRef] = useState(null)
  const drag = useRef(null)
  const isShift = mode === 'shift'
  useEffect(() => { const t = setTimeout(() => setHashParams({ sm: isShift && (mot.east || mot.north) ? `${+mot.east.toFixed(2)},${+mot.north.toFixed(2)}` : null }), 300); return () => clearTimeout(t) }, [mot, isShift])
  useEffect(() => { setHashParams({ t: mode === (P > 1 ? 'blink' : 'one') ? null : mode, a: mode === 'one' || mode === 'diff' ? a : null, b: mode === 'diff' ? b : null, band: band === (tg?.id === 'wise0855' ? 6 : 0) ? null : band, z: zoom === (tg ? 4 : 1) ? null : zoom }) }, [mode, a, b, band, zoom, P, tg])
  const [ov, setOv] = useState({ gaia: !tg || tg.kind === 'pm', wise: false, target: true, flags: init.fl })
  useEffect(() => { setHashParams({ fl: ov.flags ? 1 : null }) }, [ov.flags])
  const [overlays, setOverlays] = useState(null)
  const [hover, setHover] = useState(null)
  const [F, setF] = useState(null)                                   // per-pass flag maps
  const cv = useRef(), off = useRef(null), offF = useRef(null)
  const stage = useRef()
  const stageW = useBoxWidth(stage)                     // the image hugs its pixels; the side column gets the rest
  const [allStars, setAllStars] = useState(false)
  const [smooth, setSmooth] = useState(false)          // pixels (the real sampling) by default
  // the band groups this view needs (false colour: D6, D3, D1; a difference in false colour uses all detectors)
  const [G, setG] = useState({}), [prog, setProg] = useState(0)
  const need = useMemo(() => (mode === 'diff' ? [band === 'rgb' ? 0 : band] : band === 'rgb' ? [6, 3, 1] : [band]), [mode, band])
  useEffect(() => { setG({}); setProg(0) }, [field.id])
  useEffect(() => {
    let live = true
    for (const g of need) if (!G[g]) loadGroup(field.id, g, P, field.shape[0], (f) => live && setProg(f)).then((x) => live && setG((o) => (o[g] ? o : { ...o, [g]: x }))).catch(() => live && setErr(true))
    return () => { live = false }
  }, [field.id, need, G, P, field.shape])
  const S = useMemo(() => (need.every((g) => G[g]) ? { P, B: 7, n: field.shape[0], get: (p, d) => G[d].get(p) } : null), [G, need, P, field.shape])
  useEffect(() => { setF(null); if (pr?.pass_flags) loadFlags(field.id).then(setF).catch(() => setF(null)) }, [field.id, pr?.pass_flags])
  useEffect(() => { loadOverlays(field.id).then(setOverlays).catch(() => setOverlays(NO_OVERLAYS)) }, [field.id])
  // the blink of survey passes (never starts by itself under reduced motion)
  const blink = usePlayback(P, { hz: 1 / 0.9, active: mode === 'blink' })
  const blinkK = blink.k, run = blink.playing
  const view = useMemo(() => ({ mode: mode === 'blink' ? 'one' : mode, a: mode === 'blink' ? blinkK : a, b, band }), [mode, blinkK, a, b, band])
  const n = field.shape[0]
  // flags of the passes in view (OR), painted over the image
  const fmask = useMemo(() => {
    if (!F || F.n !== n) return null
    const ps = view.mode === 'all' || view.mode === 'shift' ? [...Array(F.P).keys()] : view.mode === 'diff' ? [view.a, view.b] : [view.a]
    const N = n * n, m = new Uint8Array(N)
    for (const p of ps) { if (p >= F.P) continue; const s = F.get(p); for (let k = 0; k < N; k++) m[k] |= s[k] }
    return m
  }, [F, view, n])
  const fimg = useMemo(() => {
    if (!fmask || !ov.flags) return null
    const out = new Uint8ClampedArray(n * n * 4)
    for (let y = 0, k = 0; y < n; y++) {
      for (let x = 0, o = (n - 1 - y) * n * 4; x < n; x++, k++, o += 4) {
        const v = fmask[k]
        if (!v) continue
        const c = PFLAG.find(([b]) => v & b)[1]
        out[o] = c[0]; out[o + 1] = c[1]; out[o + 2] = c[2]; out[o + 3] = v & 1 && !(v & 30) ? 110 : 165
      }
    }
    return new ImageData(out, n, n)
  }, [fmask, ov.flags, n])
  const flagCount = useMemo(() => (fmask ? PFLAG.map(([b]) => { let c = 0; for (let k = 0; k < fmask.length; k++) if (fmask[k] & b) c++; return c }) : null), [fmask])
  const centre = pick || (tg ? { x: tg.passes[0]?.x ?? (n - 1) / 2, y: tg.passes[0]?.y ?? (n - 1) / 2 } : { x: (n - 1) / 2, y: (n - 1) / 2 })
  const half = n / 2 / zoom
  const cx = zoom === 1 ? (n - 1) / 2 : Math.min(n - half, Math.max(half, centre.x)), cy = zoom === 1 ? (n - 1) / 2 : Math.min(n - half, Math.max(half, centre.y))
  const passMjd = (k) => (pr.passes[k].mjd0 + pr.passes[k].mjd1) / 2
  // the view is 2·half SPHEREx pixels across; a whole number of device pixels per SPHEREx pixel, and a box exactly that size (no black margins)
  const wide = stageW >= 900
  const avail = stageW ? (wide ? Math.min(760, Math.max(320, stageW * 0.56)) : stageW) : 600
  const geo = useMemo(() => { const u = dpr(), sp = Math.max(1, Math.floor((avail * u) / (2 * half))), W = Math.round(sp * 2 * half); return { W, s: sp, off: 0, u, css: W / u } }, [avail, half])
  const x0 = cx - half, ytop = n - 1 - cy - half
  // shift-and-add: two panels of the same view (plain sum | shifted along the trial motion), computed for what is on screen
  const geo2 = useMemo(() => shiftGeometry(avail, half), [avail, half])
  const G2 = isShift ? geo2 : geo
  const times = useMemo(() => passTimes(pr.passes, field.exposures), [pr, field.exposures])
  const J = useMemo(() => jacobian((x, y) => pix2world(field, x, y), (n - 1) / 2, (n - 1) / 2), [field, n])
  const v = useMemo(() => motionToPix(J, mot.east, mot.north), [J, mot.east, mot.north])
  const sa = useShiftAdd({ on: isShift, S, chans: need, times, v, how, box: [Math.floor(x0) - 8, Math.floor(cy - half) - 8, Math.ceil(x0 + 2 * half) + 8, Math.ceil(cy + half) + 8] })
  const rend = useMemo(() => (S ? render(S, view, br, sa) : null), [S, view, br, sa])
  const img = rend?.img
  const read = useMemo(() => (isShift ? sharpness(sa, n, ref) : null), [isShift, sa, n, ref])
  // the shift view starts on the target (its mean position over the passes), else on the measured point
  useEffect(() => {
    if (!isShift || ref) return
    if (tg?.passes?.length) setRef({ x: tg.passes.reduce((s, p) => s + p.x, 0) / tg.passes.length, y: tg.passes.reduce((s, p) => s + p.y, 0) / tg.passes.length })
    else if (pick) setRef({ ...pick })
  }, [isShift]) // eslint-disable-line react-hooks/exhaustive-deps
  // catalogue stars in view: all of them when zoomed in or asked for, otherwise the brightest 150 and the fast movers
  const gaiaIn = useMemo(() => {
    if (!overlays?.gaia) return null
    const inView = overlays.gaia.filter((st) => st.x >= x0 - 2 && st.x <= x0 + 2 * half + 2 && st.y >= cy - half - 2 && st.y <= cy + half + 2)
    // about one drawn star per 100 SPHEREx pixels in view (an 89-pixel field: ~80), at most 150
    const nb = Math.min(150, Math.max(30, Math.round((2 * half) ** 2 / 100)))
    return { all: inView.length, nb, shown: allStars ? inView : thinStars(inView, nb) }
  }, [overlays, x0, cy, half, allStars, zoom])
  useEffect(() => {
    const c = cv.current
    if (!c || !img) return
    if (isShift) {
      if (rend.img2) drawShift(c, canvasOf(off), { img, img2: rend.img2, n, x0, ytop, half, g2: geo2, smooth, invert: br.invert, ref, v, tgPasses: tg && ov.target ? tg.passes : null, kb })
      return
    }
    const o = canvasOf(off)
    o.width = n; o.height = n; o.getContext('2d').putImageData(img, 0, 0)
    const { W, s, off: m0, u } = geo
    if (c.width !== W || c.height !== W) { c.width = W; c.height = W }
    const g = c.getContext('2d'), D = 2 * half * s
    g.imageSmoothingEnabled = smooth; g.imageSmoothingQuality = 'high'
    g.fillStyle = br.invert ? '#fff' : '#000'; g.fillRect(0, 0, W, W)
    g.drawImage(o, x0 + 0.5, ytop + 0.5, 2 * half, 2 * half, m0, m0, D, D)
    if (fimg) {
      const o2 = canvasOf(offF)
      o2.width = n; o2.height = n; o2.getContext('2d').putImageData(fimg, 0, 0)
      g.drawImage(o2, x0 + 0.5, ytop + 0.5, 2 * half, 2 * half, m0, m0, D, D)
    }
    const X = (x) => m0 + (x - x0) * s, Y = (y) => m0 + (n - 1 - y - ytop) * s
    const kNow = view.mode === 'diff' ? view.a : view.mode === 'all' ? null : view.a
    const mjdNow = kNow == null ? (passMjd(0) + passMjd(P - 1)) / 2 : passMjd(kNow)
    if (gaiaIn && ov.gaia) {
      for (const st of gaiaIn.shown) {
        const dt = (mjdNow - st.mjd0) / 365.25, x = st.x + st.pmx * dt, y = st.y + st.pmy * dt
        const fast = fastStar(st)
        g.strokeStyle = fast ? '#ffb547' : 'rgba(110,195,255,.55)'; g.lineWidth = (fast ? 2 : 1) * u
        g.beginPath(); g.arc(X(x), Y(y), Math.max(4 * u, 1.6 * s), 0, 7); g.stroke()
        if (fast) { // 20-year motion arrow
          const ex = X(x + st.pmx * 20), ey = Y(y + st.pmy * 20)
          g.beginPath(); g.moveTo(X(x), Y(y)); g.lineTo(ex, ey); g.stroke()
        }
      }
    }
    if (overlays && ov.wise) {
      g.strokeStyle = 'rgba(239,111,108,.7)'; g.lineWidth = u
      const wise = allStars ? overlays.catwise : thinStars(overlays.catwise.filter((st) => st.x >= x0 - 2 && st.x <= x0 + 2 * half + 2 && st.y >= cy - half - 2 && st.y <= cy + half + 2), gaiaIn?.nb ?? 150)
      for (const st of wise) {
        const dt = (mjdNow - st.mjd0) / 365.25, x = st.x + st.pmx * dt, y = st.y + st.pmy * dt
        if (x < x0 - 2 || x > x0 + 2 * half + 2) continue
        const r = Math.max(4 * u, 1.6 * s)
        g.beginPath(); g.moveTo(X(x), Y(y) - r); g.lineTo(X(x) + r, Y(y)); g.lineTo(X(x), Y(y) + r); g.lineTo(X(x) - r, Y(y)); g.closePath(); g.stroke()
      }
    }
    if (movers?.length) {               // automatic proper-motion candidates: ring where it is now, arrow = 10x its motion
      for (const c of movers) {
        const t = c.track.find((q) => q.k === kNow) || c.track[0], a = c.track[0], z = c.track.at(-1)
        g.strokeStyle = c.status === 'known' ? '#5fd39a' : c.status === 'static' ? 'rgba(200,200,200,.6)' : '#ff4fd8'; g.lineWidth = 2 * u
        g.beginPath(); g.arc(X(t.x), Y(t.y), Math.max(9 * u, 2 * s), 0, 7); g.stroke()
        const ex = X(a.x + (z.x - a.x) * 10), ey = Y(a.y + (z.y - a.y) * 10)
        g.beginPath(); g.moveTo(X(a.x), Y(a.y)); g.lineTo(ex, ey); g.stroke()
      }
    }
    if (tg && ov.target) {
      tg.passes.forEach((p, j) => {
        g.fillStyle = PASS_C[j % PASS_C.length]
        if (j === kNow) { g.strokeStyle = g.fillStyle; g.lineWidth = 2 * u; g.beginPath(); g.arc(X(p.x), Y(p.y), Math.max(12 * u, 2.6 * s), 0, 7); g.stroke() }
        else { g.beginPath(); g.arc(X(p.x), Y(p.y), 3 * u, 0, 7); g.fill() }
      })
    }
    if (pick) {
      g.strokeStyle = '#fff'; g.lineWidth = 2 * u; const px = X(pick.x), py = Y(pick.y), a = 16 * u, b = 6 * u
      g.beginPath(); g.moveTo(px - a, py); g.lineTo(px - b, py); g.moveTo(px + b, py); g.lineTo(px + a, py); g.moveTo(px, py - a); g.lineTo(px, py - b); g.moveTo(px, py + b); g.lineTo(px, py + a); g.stroke()
    }
    if (kb) {                              // keyboard cross: dashed, until Enter measures there
      g.strokeStyle = '#ffb547'; g.lineWidth = 2 * u; g.setLineDash([4 * u, 4 * u]); const qx = X(kb.x), qy = Y(kb.y), a = 18 * u
      g.beginPath(); g.moveTo(qx - a, qy); g.lineTo(qx + a, qy); g.moveTo(qx, qy - a); g.lineTo(qx, qy + a); g.stroke(); g.setLineDash([])
    }
  }, [rend, fimg, half, cx, cy, overlays, gaiaIn, ov, tg, pick, view, n, P, movers, kb, geo.W, geo.s, allStars, zoom, smooth, isShift, geo2, ref, v, br.invert]) // eslint-disable-line react-hooks/exhaustive-deps
  // canvas -> field pixel (inverse of X and Y in the draw effect)
  const toPixFixed = (e) => {
    if (isShift) { const p = shiftPix(e, geo2, x0, cy, half); return { x: p.x, y: p.y } }
    const r = e.target.getBoundingClientRect(), k = geo.W / r.width
    return { x: x0 + ((e.clientX - r.left) * k - geo.off) / geo.s, y: cy + half - ((e.clientY - r.top) * k - geo.off) / geo.s }
  }
  const arc = zoom >= 4 ? 30 : zoom >= 2 ? 120 : 300, barCss = (arc / PIX) * G2.s / G2.u
  // shift view: press on a star and drag the way it moves (the drag is ten years of motion); a click picks the star
  const onDown = (e) => {
    if (!isShift || e.button > 0) return
    drag.current = { p: shiftPix(e, geo2, x0, cy, half), cx: e.clientX, cy: e.clientY, moved: false }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }
  const onDrag = (e) => {
    const d = drag.current
    if (!isShift || !d || (!d.moved && Math.hypot(e.clientX - d.cx, e.clientY - d.cy) < 5)) return
    d.moved = true
    const q = shiftPix(e, geo2, x0, cy, half, d.p.panel), m = pixToMotion(J, (q.x - d.p.x) / 10, (q.y - d.p.y) / 10)
    setRef({ x: d.p.x, y: d.p.y }); setMot({ east: +m.east.toFixed(1), north: +m.north.toFixed(1) })
  }
  const onUp = () => { const d = drag.current; drag.current = null; if (isShift && d && !d.moved) setRef({ x: d.p.x, y: d.p.y }) }
  // keyboard: arrows move a cross (Shift = 5 px), Enter or Space measures there, Escape hides it
  const onKey = (e) => {
    const step = e.shiftKey ? 5 : 1, cur = kb || (isShift && ref) || pick || centre
    const mv = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key]
    if (mv) { e.preventDefault(); setKb({ x: Math.min(n - 1, Math.max(0, cur.x + mv[0])), y: Math.min(n - 1, Math.max(0, cur.y + mv[1])) }) }
    else if ((e.key === 'Enter' || e.key === ' ') && (kb || pick)) { e.preventDefault(); if (isShift) setRef({ ...(kb || pick) }); else onPick(kb || pick); setKb(null) }
    else if (e.key === 'Escape') setKb(null)
  }
  // derived lists, memoised: hovering re-renders the view on every mouse move
  const bands = useMemo(() => [0, 1, 2, 3, 4, 5, 6].filter((d) => pr?.passes.some((p) => p.dets.includes(d))), [pr])
  const frames = useMemo(() => field.exposures.map((e) => ({ mjd: e.mjd, lam: e.lam_um, det: e.detector, iso: e.iso })), [field.exposures])
  const passN = useMemo(() => (pr?.passes || []).map((p) => field.exposures.filter((e) => e.mjd >= p.mjd0 - 1 && e.mjd <= p.mjd1 + 1).length), [pr, field.exposures])
  if (err || !pr) return <p className="hint">{L('這個天區還沒有工作台資料。', 'This field has no lab products yet.')}</p>
  const world = hover ? pix2world(field, hover.x, hover.y) : null
  const hoverFlags = hover && fmask && ov.flags ? flagNames(fmask[Math.min(n - 1, Math.max(0, Math.round(hover.y))) * n + Math.min(n - 1, Math.max(0, Math.round(hover.x)))]) : []
  const curPass = mode === 'blink' ? blinkK : mode === 'all' || isShift ? null : a
  const nLayers = [ov.gaia, ov.wise, tg && ov.target, ov.flags].filter(Boolean).length
  const passChip = (j, on, set) => { const p = pr.passes[j]; return (
    <button key={j} type="button" className="pass-chip" aria-pressed={on} style={{ '--c': PASS_C[j % PASS_C.length] }} onClick={set}>
      <i aria-hidden="true" /><b>{L(`第 ${j + 1} 輪`, `Pass ${j + 1}`)}</b><span>{mjdToIso(p.mjd0).slice(0, 7)} · {passN[j]} {L('張', 'exp.')}</span>
    </button>) }
  return (
    <div className="tool-stage" ref={stage} style={wide ? { gridTemplateColumns: `${geo.css}px minmax(0, 1fr)` } : undefined}>
      {/* one toolbar: what time, which detector, how close, which layers */}
      <div className="stage-main">
        <div className="toolbar" role="toolbar" aria-label={L('影像控制', 'Image controls')}>
          <div className="seg" role="group" aria-label={L('時間', 'Time')}>
            {P > 1 && <button aria-pressed={mode === 'blink'} onClick={() => setMode('blink')}>{L('輪播', 'Blink')}</button>}
            <button aria-pressed={mode === 'one'} onClick={() => setMode('one')}>{L('單一輪', 'One pass')}</button>
            {P > 1 && <button aria-pressed={mode === 'all'} onClick={() => setMode('all')}>{L('全部相加', 'Add all')}</button>}
            {P > 1 && <button aria-pressed={mode === 'diff'} onClick={() => setMode('diff')}>{L('差分', 'Difference')}</button>}
            {P > 1 && <button aria-pressed={isShift} onClick={() => setMode('shift')} title={L('沿著假設的運動把各輪平移後相加（WiseView 的 shift-and-add）', 'Shift the passes along a trial motion and add them (WiseView’s shift-and-add)')}>{L('平移相加', 'Shift and add')}</button>}
          </div>
          <label className="tb-select"><span>{L('偵測器', 'Detector')}</span>
            <select className="tb-det" aria-label={L('偵測器', 'Detector')} value={String(band)} onChange={(e) => setBand(e.target.value === 'rgb' ? 'rgb' : +e.target.value)}>
              {bands.map((d) => <option key={d} value={d}>{d ? `D${d} · ${DET[d].r}` : L('全部（6 個疊加）', 'All six stacked')}</option>)}
              {mode !== 'diff' && [1, 3, 6].every((d) => bands.includes(d)) && <option value="rgb">{L('假彩色（D6 紅、D3 綠、D1 藍）', 'False colour (D6 red, D3 green, D1 blue)')}</option>}
            </select>
          </label>
          <div className="seg" role="group" aria-label={L('視野', 'View')}>{[1, 2, 4].map((z) => <button key={z} aria-pressed={zoom === z} onClick={() => setZoom(z)}>{(field.size_deg * 60 / z).toFixed(z === 4 ? 1 : 0)}′</button>)}</div>
          <details className="pop">
            <summary className="btn small">{L('圖層', 'Layers')}{nLayers ? ` · ${nLayers}` : ''}</summary>
            <div className="pop-panel">
              <label><input type="checkbox" name="gaia" checked={ov.gaia} onChange={() => setOv({ ...ov, gaia: !ov.gaia })} /> <i style={{ background: COL.known }} />Gaia DR3 {L('星表', 'catalogue')}</label>
              <label><input type="checkbox" name="wise" checked={ov.wise} onChange={() => setOv({ ...ov, wise: !ov.wise })} /> <i style={{ background: COL.det[5] }} />CatWISE2020</label>
              {tg && <label><input type="checkbox" name="target" checked={ov.target} onChange={() => setOv({ ...ov, target: !ov.target })} /> <i style={{ background: COL.accent }} />{L('目標在各輪的位置', 'The target in each pass')}</label>}
              {pr.pass_flags && <label><input type="checkbox" name="flags" checked={ov.flags} disabled={!F} onChange={() => setOv({ ...ov, flags: !ov.flags })} /> <i style={{ background: COL.bad }} />{L('污染旗標', 'Contamination flags')}</label>}
              <label><input type="checkbox" name="allstars" checked={allStars} onChange={() => setAllStars(!allStars)} /> {L('畫出全部的星（預設只畫最亮的和移動快的）', 'Draw every star (default: the brightest and the fast movers)')}</label>
              <label><input type="checkbox" name="smooth" checked={smooth} onChange={() => setSmooth(!smooth)} /> {L('平滑顯示（預設一個像素一格）', 'Smooth (default: one block per pixel)')}</label>
              {(ov.gaia || ov.wise) && gaiaIn && gaiaIn.all > gaiaIn.shown.length && <p className="pop-note lab-thin">{L(`顯示 ${gaiaIn.shown.length}／${gaiaIn.all.toLocaleString()} 顆 Gaia 星`, `Showing ${gaiaIn.shown.length} of ${gaiaIn.all.toLocaleString()} Gaia stars`)}</p>}
              {overlays && (overlays.errors?.gaia || overlays.errors?.catwise) && <p className="pop-note">{L('部分星表暫時查不到', 'Some catalogues could not be reached')}</p>}
              {ov.flags && F && <ul className="lab-flags">{PFLAG.map(([bit, c, t], j) => <li key={bit}><i style={{ background: `rgb(${c.join(',')})` }} />{L(...t)} <small>{flagCount ? `${(100 * flagCount[j] / (n * n)).toFixed(1)}%` : ''}</small></li>)}</ul>}
            </div>
          </details>
          <BrightnessPop br={br} setBr={setBr} vals={rend?.vals} mode={mode} />
        </div>
        <div className="lab-canvas" style={{ width: G2.css }}>
          <canvas ref={cv} tabIndex={0} role="application" onKeyDown={onKey} className={isShift ? 'sa-canvas' : undefined} style={isShift ? { aspectRatio: `${geo2.W} / ${geo2.H}` } : undefined}
            aria-label={isShift ? L('左：直接相加；右：沿著運動平移後相加。在星上按住往它移動的方向拖曳來設定運動，點一下選星。', 'Left: plain sum; right: shifted along the motion and added. Press on a star and drag the way it moves to set the motion; click to choose a star.')
              : L('疊加影像。點一下量測該點的光譜與光變曲線；鍵盤：方向鍵移動十字（Shift 一次 5 像素），Enter 量測。', 'Stacked image. Click to measure a spectrum and light curve there; keyboard: arrow keys move the cross (Shift for 5 pixels), Enter measures.')}
            onPointerDown={onDown} onPointerMove={onDrag} onPointerUp={onUp} onPointerCancel={() => { drag.current = null }}
            onClick={(e) => { if (isShift) return; setKb(null); onPick(toPixFixed(e)) }} onMouseMove={(e) => setHover(toPixFixed(e))} onMouseLeave={() => setHover(null)} />
          {!S && <>
            {/* while the data arrives: the ready-made picture of this pass, and how much is in */}
            <img className="lab-preview" src={`${dataBase(field.id)}/pass/p${view.a ?? 0}_d${band === 'rgb' ? 0 : band}.webp`} alt="" />
            <div className="lab-progress" role="progressbar" aria-label={L('下載疊加資料', 'Downloading the stacks')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(prog * 100)}>
              <span>{L('下載疊加資料', 'Downloading the stacks')} {Math.round(prog * 100)}%</span><i style={{ width: `${Math.round(prog * 100)}%` }} />
            </div>
          </>}
          <span className="lab-badge">{mode === 'blink' ? L(`第 ${blinkK + 1} 輪 · ${mjdToIso(pr.passes[blinkK].mjd0).slice(0, 7)}`, `Pass ${blinkK + 1} · ${mjdToIso(pr.passes[blinkK].mjd0).slice(0, 7)}`)
            : mode === 'all' ? L(`${P} 輪合併`, `${P} passes combined`) : isShift ? L('直接相加', 'Plain sum') : mode === 'diff' ? L(`第 ${a + 1} 輪 − 第 ${b + 1} 輪`, `Pass ${a + 1} − pass ${b + 1}`) : L(`第 ${a + 1} 輪`, `Pass ${a + 1}`)}</span>
          {isShift && <span className="lab-badge sa-tag">{L('平移相加', 'Shifted and added')}<span className="sa-tag-v"> · {Math.hypot(mot.east, mot.north).toFixed(1)}″/{L('年', 'yr')}</span></span>}
          <span className="lab-scale" aria-hidden="true"><i style={{ width: barCss }} />{arc}″</span>
          {(world || kb) && <span className="lab-coord">{(() => { const w = world || pix2world(field, kb.x, kb.y); return `RA ${w[0].toFixed(4)}° Dec ${w[1].toFixed(4)}°` })()}{hoverFlags.length ? ` · ${hoverFlags.join(L('、', ', '))}` : ''}</span>}
        </div>
        {/* the survey passes as a strip: when each one was, how many exposures; click one to look at it */}
        {isShift ? <div style={{ width: '100%', maxWidth: geo.css }}><ShiftPanel field={field} tg={tg} mot={mot} setMot={setMot} how={how} setHow={setHow} read={read} refPt={ref} /></div>
          : <div className="pass-row" role="group" aria-label={L('巡天輪次', 'Survey passes')} style={{ maxWidth: geo.css }}>
          {mode === 'blink' && <PlayButton playing={run} onClick={blink.toggle} />}
          {pr.passes.map((_, j) => passChip(j, curPass === j, () => { if (mode === 'blink' || mode === 'all') setMode('one'); setA(j) }))}
        </div>}
        {mode === 'diff' && <div className="pass-row" role="group" aria-label={L('減去哪一輪', 'Pass to subtract')} style={{ maxWidth: geo.css }}>
          <span className="lab-k">{L('減去', 'minus')}</span>{pr.passes.map((_, j) => passChip(j, b === j, () => setB(j)))}
        </div>}
        <p className="stage-note hint" style={{ maxWidth: geo.css }}>{band === 'rgb' ? L('假彩色：紅 = D6（4.4–5.0 µm）、綠 = D3、藍 = D1：越紅越冷。', 'False colour: red = D6 (4.4–5.0 µm), green = D3, blue = D1: redder is colder. ') : band ? `${DET[band].r} · ${L('只疊加這個偵測器的影像。', 'stacked from this detector only. ')}` : ''}
          {isShift ? L('在星上按住，往它移動的方向拖曳（箭頭是 10 年的移動）。每一輪依這個運動平移後相加：照這個速度移動的天體會疊成一點，不動的星會拉成短線。SPHEREx 目前約一年的資料，最快的星也移動不到 2 個像素，所以只會清楚一些。', 'Press on a star and drag the way it moves (the arrow is 10 years of motion). Each pass is shifted by that motion and the passes are added: something moving at that rate piles up into one point, while still stars smear into short lines. SPHEREx has about a year of data so far, so even the fastest star moves under 2 pixels and the gain is modest.')
            : mode === 'all' ? L('全部相加：把每一輪的疊加影像平均，雜訊最低，最暗的星也看得到。', 'Add all: every pass stack averaged, for the lowest noise and the faintest stars.') : mode === 'diff' ? L('橘色：A 比 B 亮；藍色：A 比 B 暗。移動的星會變成一對橘藍點。', 'Orange: brighter in A; blue: brighter in B. A moving star becomes an orange-blue pair.')
            : L('藍圈是 Gaia 星表位置（已依自行推到這一輪）；橘圈加箭頭是移動快的星（箭頭為 20 年的移動）。點任何位置量測它。', 'Blue circles are Gaia positions moved to this pass by their proper motion; orange circles with arrows move fast (arrow = 20 years). Click anywhere to measure it.')}</p>
      </div>
      <aside className="stage-side">
        {chart && <ChartCard level={3} title={L('什麼時候、用哪個波長拍這裡', 'When, and at what wavelength, SPHEREx looked here')}
          take={L(`${field.exposures.length} 張影像、${P} 輪巡天。同一個位置每次落在偵測器的不同地方，所以每張的波長都不同。`, `${field.exposures.length} exposures in ${P} survey passes. The source lands on a different part of the detector each time, so every exposure has its own wavelength.`)}>
          <TimeWave frames={frames} passes={pr.passes} pass={curPass} height={300} hint={L('點一下：看這一輪', 'Click: show this pass')} onPick={(f) => { if (f.g < P) { setMode('one'); setA(f.g) } }} />
        </ChartCard>}
        {typeof side === 'function' ? side({ pass: curPass, showPass: (k) => { setMode('one'); setA(k) } }) : side}
      </aside>
    </div>
  )
}

/** Axis labels with one style: 1 µJy, 10 µJy, 100 µJy, 1 mJy … (no "10.0 mJy" next to "100 mJy"). */
const fmtTick = (f) => (Math.abs(f) >= 1000 ? `${+(f / 1000).toPrecision(3)} mJy` : `${+f.toPrecision(3)} µJy`)
/** Absorption bands of cool atmospheres, as reference positions on a spectrum (µm). */
const MOLECULES = [['H₂O', 1.4], ['H₂O', 1.9], ['H₂O', 2.7], ['CH₄', 3.3], ['CO₂', 4.26], ['CO', 4.67]]
/**
 * Measurements as points on the chart kit: hover or tap a point for its value, date and band; error bars on request;
 * a point with an `mjd` asks the image player on the page to show that exposure (event 'sx:seek').
 * deco({X, Y, m, h, w}) draws extra marks under the points (detector strip, molecule marks).
 */
function Scatter({ pts, xlab, xfmt = (v) => v, yfmt = fmtTick, logy, label, height = 260, deco, xDomain, compact }) {
  const [err, setErr] = useState(false)
  if (!pts.length) return <p className="empty-line">{L('這裡沒有可用的測光點（太暗、在壞像素上或在影像邊緣）。', 'No usable photometry here (too faint, on bad pixels, or at the edge).')}</p>
  logy = logy && pts.every((p) => p.y > 0)
  const hasPlayer = typeof document !== 'undefined' && !!document.querySelector('.qp')
  const points = pts.map((p) => ({ x: p.x, y: p.y, r: 7, p, tip: `${p.t}${p.e > 0 ? ` ± ${fmtFlux(p.e)}` : ''}`, hint: p.mjd && hasPlayer ? L('點一下：在播放器看這一張', 'Click: show this exposure in the player') : undefined }))
  return (
    <div className="plotbox">
      <Plot label={label} height={height} points={points} onPick={hasPlayer ? (q) => q.p.mjd && window.dispatchEvent(new CustomEvent('sx:seek', { detail: { mjd: q.p.mjd } })) : undefined}
        x={{ domain: xDomain || extent(pts.map((p) => p.x), 0.04), label: xlab, fmt: xfmt }}
        y={{ domain: extent(pts.map((p) => p.y), 0.1, logy), log: logy, fmt: yfmt, gutter: compact ? 58 : 64 }}>
        {(g) => <>
          {deco?.(g)}
          {pts.map((p, k) => (
            <g key={k}>
              {err && p.e > 0 && <line x1={g.X(p.x)} x2={g.X(p.x)} y1={g.Y(Math.max(p.y - p.e, logy ? p.y * 0.05 : p.y - p.e))} y2={g.Y(p.y + p.e)} stroke={p.c} strokeOpacity=".5" />}
              <circle cx={g.X(p.x)} cy={g.Y(p.y)} r={compact ? 2.6 : 3.2} fill={p.c} fillOpacity=".88" />
            </g>
          ))}
        </>}
      </Plot>
      {!compact && pts.some((p) => p.e > 0) && <label className="plot-err"><input type="checkbox" checked={err} onChange={(e) => setErr(e.target.checked)} /> {L('誤差棒（1σ）', 'Error bars (1σ)')}</label>}
    </div>
  )
}
/** Spectrum decorations: which detector array covers which wavelengths (strip on the axis), and where cool atmospheres absorb. */
const spectrumDeco = ({ X, Y, m, h }) => <>
  {DET_RANGE.map(([lo, hi], d) => <rect key={d} x={X(lo)} y={h - m.b - 3} width={Math.max(0, X(hi) - X(lo) - 1)} height="6" rx="2" fill={COL.det[d]} />)}
  {MOLECULES.map(([name, lam], k) => <g key={k}><line x1={X(lam)} x2={X(lam)} y1={m.t + 16} y2={h - m.b - 4} stroke="rgb(255 255 255 / .14)" strokeDasharray="2 4" /><text className="mark-note" x={X(lam)} y={m.t + 10} textAnchor="middle">{name}</text></g>)}
</>
/** One small light curve per detector array: inside one array the wavelengths are close, so a real change shows. */
function DetCurves({ lc }) {
  const dets = [1, 2, 3, 4, 5, 6].filter((d) => lc.some((p) => p.det === d))
  if (!dets.length) return <p className="empty-line">{L('這裡沒有可用的測光點（太暗、在壞像素上或在影像邊緣）。', 'No usable photometry here (too faint, on bad pixels, or at the edge).')}</p>
  const xd = extent(lc.map((p) => p.x), 0.04)
  return (
    <div className="det-curves">
      {dets.map((d) => (
        <div key={d}>
          <p className="det-name" style={{ '--c': DET[d].c }}><i aria-hidden="true" />D{d} · {DET[d].r}</p>
          <Scatter pts={lc.filter((p) => p.det === d)} logy compact height={132} xDomain={xd} xfmt={(v) => mjdToIso(v).slice(2, 7)} label={L(`D${d} 的光變曲線`, `Light curve in D${d}`)} />
        </div>
      ))}
    </div>
  )
}

/** Relative light curve from the PSF wings, for targets whose cores saturate. Each detector is scaled to its own median. */
function WingCurve({ field, points }) {
  const sat = points.filter((p) => (p.flag ?? 0) & 1).length
  const w = points.filter((p) => p.w != null && isFinite(p.w) && p.w > 0)
  if (sat < points.length * 0.4 || w.length < 10) return null
  const med = {}
  for (const d of [1, 2, 3, 4, 5, 6]) { const v = w.filter((p) => p.det === d).map((p) => p.w).sort((a, b) => a - b); med[d] = v.length >= 3 ? v[v.length >> 1] : null }
  const pts = w.filter((p) => med[p.det]).map((p) => ({ x: p.mjd, y: p.w / med[p.det], e: 0, d: p.det, c: DET[p.det].c, t: `${mjdToIso(p.mjd)} · D${p.det} · ×${(p.w / med[p.det]).toFixed(2)}` }))
  // per detector: the brightest pass over the faintest pass
  const passes = field.products?.passes || []
  const ratios = [1, 2, 3, 4, 5, 6].map((d) => {
    const pm = passes.map((q) => { const v = pts.filter((p) => p.d === d && p.x >= q.mjd0 - 1e-6 && p.x <= q.mjd1 + 1e-6).map((p) => p.y).sort((a, b) => a - b); return v.length >= 3 ? v[v.length >> 1] : null }).filter((v) => v != null)
    return pm.length >= 2 ? [d, Math.max(...pm) / Math.min(...pm)] : null
  }).filter(Boolean)
  return (
    <ChartCard level={4} className="lab-wing" title={L('相對光變曲線（用 PSF 外圍量）', 'Relative light curve (from the PSF wings)')}
      take={ratios.length > 0 ? `${L('最亮一輪 ÷ 最暗一輪：', 'Brightest pass ÷ faintest pass: ')}${ratios.map(([d, r]) => `D${d} ×${r.toFixed(2)}`).join(' · ')}` : null}
      legend={[1, 2, 3, 4, 5, 6].filter((d) => med[d]).map((d) => ({ c: DET[d].c, label: `D${d}` }))}
      more={<>
        <p>{L(`核心在 ${sat} 張影像中飽和，所以改量 4.5–7.5 像素環上的光：PSF 形狀固定時，外圍的光和總亮度成正比。每個偵測器除以自己的中位數。`, `The core saturates in ${sat} exposures, so this measures the light in a 4.5–7.5 pixel ring instead: with a fixed PSF the wings scale with the total brightness. Each detector is divided by its own median.`)}</p>
        <p>{L('對照：同樣方法用在不變的巴納德星上會得到 ×1.05–1.37，所以小於約 ×1.4 的差異可能只是方法誤差。', 'Control: the same method on Barnard’s Star, which is steady, gives ×1.05–1.37, so changes below about ×1.4 may be method error.')}</p>
      </>}>
      <Scatter pts={pts} xlab={L('日期', 'Date')} xfmt={(v) => mjdToIso(v).slice(0, 7)} yfmt={(v) => `×${(+v).toFixed(1)}`} label={L('相對光變曲線', 'Relative light curve')} />
    </ChartCard>
  )
}

// what a visitor can say about a position; stored with /api/report and listed for others on #/movers
const SPOT_KINDS = [['moving', ['好像在移動', 'Seems to move']], ['variable', ['亮度在變', 'Brightness changes']], ['spectrum', ['光譜很特別', 'Unusual spectrum']], ['other', ['其他', 'Something else']]]
function SpotReport({ field, at }) {
  const [kind, setKind] = useState(null), [st, setSt] = useState(null)
  useEffect(() => { setKind(null); setSt(null) }, [at.x, at.y])
  const send = (k) => {
    setKind(k); setSt('sending')
    postJson('/api/report', { field: field.id, x: +at.x.toFixed(2), y: +at.y.toFixed(2), kind: k, verdict: 'real' })
      .then((r) => setSt(r._duplicate ? 'dup' : 'ok')).catch((e) => setSt(String(e).includes(': 429') ? 'limit' : 'error'))
  }
  return (
    <div className="lab-spot">
      <span className="lab-k">{L('覺得這裡有東西？回報給大家看：', 'Something here? Flag it for others:')}</span>
      <div className="seg" role="group" aria-label={L('回報這個位置', 'Flag this position')}>
        {SPOT_KINDS.map(([k, t]) => <button key={k} aria-pressed={kind === k} disabled={st === 'ok' || st === 'dup' || st === 'sending'} onClick={() => send(k)}>{L(...t)}</button>)}
      </div>
      <span className="hint" role="status">{st === 'ok' || st === 'dup' ? <>{st === 'dup' ? L('你已經回報過這個位置。', 'You already flagged this position. ') : L('已回報。', 'Flagged. ')}{L('其他人會在', 'Others will see it in ')}<a href="#/movers">{L('「找移動星」', 'Find movers')}</a>{L('的「大家回報的位置」看到並投票。', ' under “Positions people flagged”, and vote.')}</>
        : st === 'limit' ? L('今天回報的次數已達上限。', 'Daily limit reached.') : st === 'error' ? L('送出失敗，請再試一次。', 'Could not send; try again.') : ''}</span>
    </div>
  )
}

// flags of the measured point in each exposure (cube bits: 1 unusable, 4 ghost, 8 outlier, 16 saturated, 32 persistence)
function PointFlags({ points }) {
  const sat = points.filter((p) => (p.flag ?? 0) & 16).length, per = points.filter((p) => (p.flag ?? 0) & 32).length
  const gh = points.filter((p) => (p.flag ?? 0) & 4).length, out = points.filter((p) => (p.flag ?? 0) & 8).length
  const bad = points.filter((p) => ((p.flag ?? 0) & 1) && !((p.flag ?? 0) & 48)).length
  const FC = [COL.bad, COL.distant, '#ff4fd8', COL.det[4], COL.ink3]
  const all = [[sat, L('飽和', 'saturated')], [per, L('殘影', 'persistence')], [gh, L('鬼影', 'ghost')], [out, L('離群', 'outlier')], [bad, L('不可用', 'unusable')]].map(([v, t], k) => ({ v, t, c: FC[k] })).filter((q) => q.v)
  const clean = Math.max(0, points.length - all.reduce((a, q) => a + q.v, 0))
  return (
    <div className="flagbar" role="img" aria-label={`${L('這個位置的 SPHEREx 旗標', 'SPHEREx flags at this position')}: ${all.map((q) => `${q.t} ${q.v}`).join(', ')} / ${points.length}`}>
      <b>{L('這個位置的 SPHEREx 旗標', 'SPHEREx flags at this position')}</b>
      <div className="flagbar-bar">{all.map((q) => <i key={q.t} style={{ flexGrow: q.v, background: q.c }} title={`${q.t} ${q.v}`} />)}{clean > 0 && <i style={{ flexGrow: clean }} className="clean" />}</div>
      <ul className="legend">{all.map((q) => <li key={q.t}><i className="sq" style={{ '--c': q.c }} />{q.t} {q.v}</li>)}<li><i className="sq" style={{ '--c': 'rgb(255 255 255 / .16)' }} />{L(`沒有旗標 ${clean}`, `no flag ${clean}`)}</li></ul>
    </div>
  )
}

/** Compare a measured spectrum with a reference: a blackbody at a temperature the visitor sets, or one of the spectra
 *  the brown-dwarf classifier is trained on (spec_templates.json). Only the shape is compared: the reference is scaled
 *  to the measured points (median ratio), and the typical deviation is shown. */
const H_K = 14387.77                                     // hc/k in µm K
const planck = (T, lam) => lam ** -3 / Math.expm1(Math.min(H_K / (lam * T), 700))   // f_nu, arbitrary units
function useComparison(sp) {
  const [cmp, setCmp] = useState('none'), [T, setT] = useState(900)
  const ref = useMemo(() => {
    if (cmp === 'none' || !sp.length) return null
    const grid = cmp === 'bb' ? SPEC_T.lam.map((l) => [l, planck(T, l)]) : SPEC_T.lam.map((l, k) => [l, SPEC_T.templates.find((t) => t.id === cmp).f[k]])
    const at = (lam) => { const k = Math.min(grid.length - 2, Math.max(0, Math.floor((lam - grid[0][0]) / 0.02))), [l0, f0] = grid[k], [l1, f1] = grid[k + 1]; return f0 + ((f1 - f0) * (lam - l0)) / (l1 - l0) }
    // align only where the reference has light (within a factor 1000 of its peak): a 400 K dwarf has almost none
    // below 2 µm, and whatever is measured there (often a neighbouring star) must not set its brightness
    const peak = Math.max(...grid.map((g) => g[1])), use = sp.filter((p) => p.y > 0 && at(p.x) > peak * 1e-3)
    if (use.length < 5) return null
    const r = use.map((p) => Math.log10(p.y / at(p.x))).sort((a, b) => a - b)
    const k = r[r.length >> 1], dev = r.map((v) => Math.abs(v - k)).sort((a, b) => a - b)[r.length >> 1]
    const lo = Math.min(...use.map((p) => p.x)), hi = Math.max(...use.map((p) => p.x))
    return { line: grid.map(([l, f]) => [l, f * 10 ** k]), dev, lo, hi }
  }, [cmp, T, sp])
  const label = cmp === 'bb' ? L(`${Math.round(T).toLocaleString()} K 黑體`, `${Math.round(T).toLocaleString()} K blackbody`) : cmp === 'none' ? '' : L(...(([t]) => [t.zh, t.en])(SPEC_T.templates.filter((t) => t.id === cmp)))
  const controls = (
    <div className="cmp-row">
      <label className="tb-select"><span>{L('比較', 'Compare with')}</span>
        <select value={cmp} aria-label={L('和哪一種光譜比較', 'Compare with')} onChange={(e) => setCmp(e.target.value)}>
          <option value="none">{L('不比較', 'Nothing')}</option>
          <option value="bb">{L('黑體（可調溫度）', 'A blackbody (set its temperature)')}</option>
          {SPEC_T.templates.map((t) => <option key={t.id} value={t.id}>{L(t.zh, t.en)}</option>)}
        </select>
      </label>
      {cmp === 'bb' && <label className="cmp-t"><span className="num">{Math.round(T).toLocaleString()} K</span>
        <input type="range" min={Math.log10(250)} max={Math.log10(12000)} step="0.005" value={Math.log10(T)} onChange={(e) => setT(10 ** +e.target.value)} aria-label={L('黑體溫度', 'Blackbody temperature')} /></label>}
      {ref && <span className="cmp-fit">{L(`在 ${ref.lo.toFixed(1)}–${ref.hi.toFixed(1)} µm 對齊；和資料典型相差 ×${(10 ** ref.dev).toFixed(2)}`, `Aligned on ${ref.lo.toFixed(1)}–${ref.hi.toFixed(1)} µm; typically off by ×${(10 ** ref.dev).toFixed(2)}`)}</span>}
    </div>
  )
  // drawn under the points, clipped to the plot area
  const deco = (g) => ref && <g>
    <clipPath id="cmp-clip"><rect x={g.m.l} y={g.m.t} width={g.w - g.m.l - g.m.r} height={g.h - g.m.t - g.m.b} /></clipPath>
    <polyline clipPath="url(#cmp-clip)" points={ref.line.map(([l, f]) => `${g.X(l).toFixed(1)},${g.Y(f).toFixed(1)}`).join(' ')} fill="none" stroke="#f1f2f5" strokeOpacity=".8" strokeWidth="2" strokeDasharray="6 4" />
  </g>
  return { controls, deco, legend: ref ? [{ c: '#f1f2f5', line: true, label }] : [] }
}

/** Open the assistant about a measured point, with what was measured there: where, how many exposures were usable,
 *  the median brightness per detector array, saturation, the brown-dwarf score. */
function askPoint(field, at, points, good, bd) {
  const [ra, dec] = pix2world(field, at.x, at.y)
  const med = (v) => { const s = [...v].sort((a, b) => a - b); return s.length ? s[s.length >> 1] : null }
  const flux = {}
  for (const d of [1, 2, 3, 4, 5, 6]) { const m = med(good.filter((p) => p.det === d).map((p) => p.f)); if (m != null) flux[`D${d}_${DET[d].r.replace(/\s/g, '')}`] = +m.toPrecision(3) }
  askAbout({ kind: 'star', id: `${field.id}@${at.x},${at.y}`, name: `RA ${ra.toFixed(4)}°, Dec ${dec.toFixed(4)}°`, ra: +ra.toFixed(5), dec: +dec.toFixed(5),
    facts: { field: fieldName(field), exposures_used: good.length, exposures_total: points.length, saturated_or_bad: points.filter((p) => (p.flag ?? 0) & 1).length,
      median_flux_uJy: Object.keys(flux).length ? Object.entries(flux).map(([k, v]) => `${k} ${v}`).join('; ') : null,
      brown_dwarf_score: bd != null ? +bd.toFixed(2) : null } })
}

function Measure({ field, title, points, note, neighbours, bd, at }) {
  const pr = field.products
  // drop flagged pixels (bad, ghost, transient outlier such as a cosmic ray) and low S/N
  // The outlier bit marks pixels that disagree with the other exposures: cosmic rays, but also a star that really
  // changed. Keep an outlier-flagged point unless it is far (x3) from the median of its own detector.
  // Memoised: the comparison below keys on `sp`.
  const { good, lc, sp } = useMemo(() => {
  const passOf = (m) => Math.max(0, (pr?.passes || []).findIndex((q) => m >= q.mjd0 - 1e-6 && m <= q.mjd1 + 1e-6))
  const base = points.filter((p) => p.f != null && isFinite(p.f) && p.e > 0 && p.f > 3 * p.e && !((p.flag ?? 0) & 5))
  const med = {}
  for (const d of [1, 2, 3, 4, 5, 6]) { const v = base.filter((p) => p.det === d && !((p.flag ?? 0) & 8)).map((p) => p.f).sort((a, b) => a - b); med[d] = v.length ? v[v.length >> 1] : null }
  const good = base.filter((p) => !((p.flag ?? 0) & 8) || (med[p.det] != null && p.f < 3 * med[p.det] && p.f > med[p.det] / 3))
  const lc = good.map((p) => ({ x: p.mjd, mjd: p.mjd, det: p.det, y: p.f, e: p.e, c: DET[p.det].c, t: `${mjdToIso(p.mjd)} · ${p.lam.toFixed(2)} µm · ${fmtFlux(p.f)}` }))
  const sp = good.map((p) => { const j = passOf(p.mjd); return { x: p.lam, mjd: p.mjd, y: p.f, e: p.e, c: PASS_C[j % PASS_C.length], t: `${p.lam.toFixed(3)} µm · ${mjdToIso(p.mjd)} · ${fmtFlux(p.f)}` } })
  return { good, lc, sp }
  }, [points, pr])
  const cmp = useComparison(sp)
  const csv = () => {
    const rows = ['exposure,obs_id,mjd,iso_utc,detector,lambda_um,flux_uJy,err_uJy,flag'].concat(points.map((p) => {
      const e = field.exposures[p.i]
      return [p.i, e?.obs_id, p.mjd, mjdToIso(p.mjd), p.det, p.lam, p.f ?? '', p.e ?? '', p.flag ?? ''].join(',')
    }))
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([rows.join('\n')], { type: 'text/csv' }))
    a.download = `${field.id}_${title.replace(/[^\w.-]+/g, '_')}.csv`; a.click()
  }
  return (
    <div className="lab-measure">
      <div className="lab-mhead"><h3>{title}</h3>
        {at && <button className="btn small" onClick={() => askPoint(field, at, points, good, bd)}>{L('問問這個點 →', 'Ask about this point →')}</button>}
        <button className="btn small" onClick={csv}>{L('下載 CSV', 'Download CSV')}</button></div>
      {good.length === 0 ? <p className="empty-line">{L('這個位置沒有可用的測光點（核心飽和、太暗或在影像邊緣），所以沒有光譜和一般的光變曲線。', 'No usable photometry at this position (saturated core, too faint, or at the edge), so there is no spectrum or ordinary light curve.')}</p> : <div className="chart-grid">
        <ChartCard level={4} title={L('光譜（即時組合 102 個波段）', 'Spectrum (the 102 bands, on the fly)')}
          take={L(`${good.length} 張影像各量一個波長；顏色是巡天輪次，底下的色帶是六個偵測器。`, `One wavelength from each of ${good.length} exposures; colour is the survey pass, the strip below marks the six detector arrays.`)}
          legend={[...(pr?.passes || []).map((q, k) => ({ c: PASS_C[k % PASS_C.length], label: `${L(`第 ${k + 1} 輪`, `Pass ${k + 1}`)} · ${mjdToIso(q.mjd0).slice(0, 7)}` })), ...cmp.legend]}>
          {cmp.controls}
          <Scatter pts={sp} xlab={L('波長（µm）', 'Wavelength (µm)')} xfmt={(v) => `${v}`} logy height={300} xDomain={[0.6, 5.15]} deco={(g) => <>{spectrumDeco(g)}{cmp.deco(g)}</>} label={L('光譜', 'Spectrum')} />
          {bd !== undefined && bd !== null && <Meter value={bd} mark={0.8} c={bd >= 0.8 ? COL.distant : COL.known} label={L('AI 光譜判斷：像冷棕矮星的程度', 'AI spectrum check: how much it looks like a cold brown dwarf')} text={`${Math.round(bd * 100)}%`} />}
          {bd !== undefined && <details className="chart-more"><summary>{bd === null ? L('AI 光譜判斷：光譜資料不足', 'AI spectrum check: not enough spectrum') : L('這個分數怎麼來的', 'Where this score comes from')}</summary>
            <p><Suspense fallback={null}><BdText s={bd} /></Suspense>{L('。自己訓練的小型模型，只用合成光譜訓練；在真實資料上，2 顆已知棕矮星分數 ≥ 0.999，420 顆一般恆星只有 2 顆超過 0.8。直線是門檻 0.8。', '. A small self-trained model, trained on synthetic spectra only; on real data the 2 known brown dwarfs score ≥ 0.999 and 2 of 420 ordinary stars exceed 0.8. The tick marks the 0.8 threshold.')}</p></details>}
        </ChartCard>
        <ChartCard level={4} title={L('光變曲線（每個偵測器一格）', 'Light curve (one panel per detector)')}
          take={L('同一個偵測器裡波長接近，亮度才能互相比較；整格一起升降才是真的在變。', 'Inside one detector the wavelengths are close, so brightness can be compared; a real change moves a whole panel.')}>
          <DetCurves lc={lc} />
        </ChartCard>
      </div>}
      <WingCurve field={field} points={points} />
      <PointFlags points={points} />
      <p className="hint">{L(`${points.length} 張影像中 ${good.length} 張列入（訊噪比 ≥ 3、不在壞像素或邊緣）。2 像素孔徑；附近的星可能混入。`, `${good.length} of ${points.length} exposures used (S/N ≥ 3, not on bad pixels or the edge). 2-pixel aperture; a close neighbour can leak in.`)}{note ? ' ' + note : ''}</p>
      {(() => {
        const sat = points.filter((p) => (p.flag ?? 0) & 1)
        if (sat.length < Math.max(3, points.length * 0.1)) return null
        const byDet = [1, 2, 3, 4, 5, 6].map((d) => [d, sat.filter((p) => p.det === d).length]).filter(([, n]) => n).map(([d, n]) => `D${d} ${n}`).join(', ')
        return <p className="note lab-warn">{L(`${sat.length} 張影像沒有列入，因為目標中心落在飽和或壞像素上（${byDet}）。很亮的星在 SPHEREx 長波段會飽和，所以這些波段的點會缺。`, `${sat.length} exposures are left out because the target's core is on saturated or bad pixels (${byDet}). Bright stars saturate SPHEREx's long-wavelength detectors, so those bands are missing.`)}</p>
      })()}
      {at && <SpotReport field={field} at={at} />}
      {neighbours?.length > 0 && <p className="note lab-warn">{L(`注意：${neighbours.length} 顆 Gaia 星在 24″ 內（最近 ${neighbours[0].sep}″，G = ${neighbours[0].g ?? '?'}），它的光會混進孔徑，特別是在短波長。`, `Caution: ${neighbours.length} Gaia star${neighbours.length > 1 ? 's' : ''} within 24″ (nearest ${neighbours[0].sep}″, G = ${neighbours[0].g ?? '?'}); its light leaks into the aperture, most at short wavelengths.`)}</p>}
    </div>
  )
}

function DataPanel({ field }) {
  const [fr, setFr] = useState(null), [job, setJob] = useState(null)
  const stop = useRef(() => {})
  useEffect(() => () => stop.current(), [])
  const check = () => { setFr('loading'); api(`/api/field/${field.id}/fresh`).then(setFr).catch(() => setFr('error')) }
  const watch = () => { stop.current = poll(`/api/jobs/${field.id}`, { every: 4000, retry: 8000, onUpdate: (j) => { setJob(j); if (j.status === 'done') { forgetField(field.id); location.reload() } }, done: jobFinished }) }
  const update = () => api(`/api/field/${field.id}/refresh`, { method: 'POST' }).then((j) => { setJob(j); if (j.status !== 'up_to_date') watch() })
    .catch((e) => setJob({ status: 'error', error: jobError(e) }))
  return (
    <FieldFacts field={field}>
      <div className="lab-fresh">
        {!fr && <button className="btn small" onClick={check}>{L('檢查有沒有新的 SPHEREx 資料', 'Check for new SPHEREx data')}</button>}
        {fr === 'loading' && <span className="hint">{L('查詢 IRSA…', 'Asking IRSA…')}</span>}
        {fr === 'error' && <span className="hint">{L('暫時查不到 IRSA。', 'IRSA could not be reached.')}</span>}
        {fr && typeof fr === 'object' && (fr.n_new ? <>
          <p>{L(`IRSA 上有 ${fr.n_new} 張更新的影像（到 ${mjdToIso(fr.available_to).slice(0, 10)}）。`, `IRSA has ${fr.n_new} newer exposures (to ${mjdToIso(fr.available_to).slice(0, 10)}).`)}</p>
          <button className="btn small primary" onClick={update} disabled={job && ['queued', 'running'].includes(job.status)}>{L('用最新資料重新分析', 'Re-analyse with the newest data')}</button>
        </> : <p className="hint">{L(`已是最新：IRSA 上的 ${fr.n_total} 張影像都分析過了。`, `Up to date: all ${fr.n_total} exposures on IRSA are analysed.`)}</p>)}
        {job && <p className="hint" role="status">{job.status === 'error' ? job.error : job.status === 'up_to_date' ? L('已是最新。', 'Already up to date.') : job.status === 'queued' ? L(`排隊中（第 ${job.position || 1} 位）`, `Queued (position ${job.position || 1})`) : L('分析中…（目前版本在完成前會繼續顯示）', 'Analysing… (this version stays up until the new one is ready)')}</p>}
      </div>
      <div className="lab-links">
        <button className="btn small" onClick={() => go(field.id)}>{L('逐張播放 →', 'Play every exposure →')}</button>
        <a className="btn small" href="#lab-aladin" onClick={(e) => { e.preventDefault(); document.getElementById('lab-aladin')?.scrollIntoView({ behavior: scrollBehavior() }) }}>{L('其他望遠鏡 ↓', 'Other telescopes ↓')}</a>
        <a className="btn small" href={`https://irsa.ipac.caltech.edu/applications/spherex/?__action=layout.showDropDown&view=MultiTableSearchCmd&searchTarget=${field.ra}%20${field.dec}`} target="_blank" rel="noopener">IRSA ↗</a>
      </div>
    </FieldFacts>
  )
}

/** Aladin Lite under the field: WISE / 2MASS / DSS / Pan-STARRS images with the SPHEREx footprint, the target's
 *  position in each pass and our Gaia / CatWISE overlay. Loaded only when scrolled into view (the library is large). */
function LabAladin({ field, tg }) {
  const box = useRef()
  const [seen, setSeen] = useState(false), [ov, setOv] = useState(null)
  useEffect(() => {
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect() } }, { rootMargin: '200px' })
    if (box.current) io.observe(box.current)
    return () => io.disconnect()
  }, [])
  useEffect(() => { if (seen && field.products) loadOverlays(field.id).then(setOv).catch(() => setOv(NO_OVERLAYS)) }, [seen, field])
  const markers = useMemo(() => (tg?.passes || []).map((p, j) => { const [ra, dec] = pix2world(field, p.x, p.y); return { ra, dec, label: `${targetName(tg)} · ${L('第', 'pass ')}${j + 1}${L(' 輪', '')} ${mjdToIso(p.mjd0).slice(0, 7)}` } }), [field, tg])
  const catalogs = useMemo(() => {
    if (!ov) return []
    const sky = (s) => { const [ra, dec] = pix2world(field, s.x, s.y); return { ra, dec } }
    return [
      { name: L('Gaia DR3（最亮 150 顆＋移動快的星）', 'Gaia DR3 (brightest 150 + fast movers)'), c: '#6ec3ff', src: thinStars(ov.gaia).map(sky) },
      { name: L(`Gaia DR3（全部 ${ov.gaia.length} 顆）`, `Gaia DR3 (all ${ov.gaia.length})`), c: '#6ec3ff', hidden: true, src: ov.gaia.map(sky) },
      { name: 'CatWISE2020', c: '#ef6f6c', shape: 'rhomb', hidden: true, src: thinStars(ov.catwise).map(sky) },
    ]
  }, [ov, field])
  return (
    <section className="lab-aladin sec-anchor" id="lab-aladin" ref={box}>
      <h2>{L('和其他望遠鏡比較', 'Compare with other telescopes')}</h2>
      {seen && (!field.products || ov) ? <AladinView ra={field.ra} dec={field.dec} size={field.size_deg} markers={markers} catalogs={catalogs} />
        : <div className="sx-aladin-map" />}
      <ElsewhereLinks ra={field.ra} dec={field.dec} size={field.size_deg} pm={tg?.kind === 'pm' ? tg : null} />
      <NeossatCoverage ra={field.ra} dec={field.dec} />
    </section>
  )
}

const scrollBehavior = () => (reducedMotion() ? 'auto' : 'smooth')
/** The measured point carried by a shared link (?x=&y=), when it lies inside the field. */
function pickFromLink(f) {
  const u = hashParams(), x = +u.get('x'), y = +u.get('y')
  return u.get('x') != null && isFinite(x) && isFinite(y) && x >= 0 && y >= 0 && x < f.shape[1] && y < f.shape[0] ? { x, y } : null
}
/** The picked point; setPick measures at the same 0.1-pixel position the link records, so a shared link reproduces
 *  the measurement exactly. */
function useLinkedPick() {
  const [pick, setPickRaw] = useState(null)
  const setPick = useCallback((p) => { const q = p ? { x: +p.x.toFixed(1), y: +p.y.toFixed(1) } : null; setPickRaw(q); setHashParams({ x: q?.x ?? null, y: q?.y ?? null }) }, [])
  return [pick, setPickRaw, setPick]
}
/** Photometry of the picked point from the server; the answer appears under the image, so it is scrolled into view
 *  instead of leaving the reader to look for it. */
function usePoint(field, pick, result) {
  const [pt, setPt] = useState(null)
  useEffect(() => {
    if (!pick || !field) return
    let live = true
    setPt('loading')
    api(`/api/field/${field.id}/point?x=${pick.x.toFixed(2)}&y=${pick.y.toFixed(2)}`).then((r) => { if (live) setPt(r) }).catch(() => live && setPt('error'))
    return () => { live = false }
  }, [pick, field])
  useEffect(() => {
    if (pt && pt !== 'loading' && result.current) result.current.scrollIntoView({ behavior: scrollBehavior(), block: 'nearest' })
  }, [pt, result])
  return [pt, setPt]
}
/** What the measurement section shows for the picked point: loading, an error, or the measurement. */
const pointResult = (field, pick, pt, world) => (pt === 'loading' ? <div className="route-loading lab-loading" role="status"><i aria-hidden="true" /><span>{L('量測這個位置…', 'Measuring that position…')}</span></div>
  : pt === 'error' ? <p className="hint" role="alert">{L('量測失敗，請再點一次。', 'The measurement failed; click again.')}</p>
  : pt && pt !== 'loading' && <Measure field={field} points={pt.points} bd={pt.bd_score ?? null} at={pick} title={L(`你點的位置：RA ${world[0].toFixed(4)}°, Dec ${world[1].toFixed(4)}°`, `Your point: RA ${world[0].toFixed(4)}°, Dec ${world[1].toFixed(4)}°`)} />)

export default function Lab({ id }) {
  useLanguage()
  const mode = useMode()
  const [help, setHelp] = useState(null)
  const [field, setField] = useState(null), [err, setErr] = useState(false)
  const [pick, setPickRaw, setPick] = useLinkedPick()
  const [movers, setMovers] = useState(null), [vars, setVars] = useState(null)
  const result = useRef()
  const [pt, setPt] = usePoint(field, pick, result)
  useEffect(() => { setMovers(null); fetchProduct(id, 'pm_candidates.json').then(setMovers).catch(() => {}) }, [id])
  useEffect(() => { setVars(null); fetchProduct(id, 'var_candidates.json').then(setVars).catch(() => {}) }, [id])
  useEffect(() => {
    setField(null); setErr(false); setPickRaw(null); setPt(null)
    getField(id).then((f) => {
      setField(f)
      const p = pickFromLink(f)          // a shared link can carry the measured point
      if (p) setPickRaw(p)
    }).catch(() => setErr(true))
  }, [id, setPickRaw, setPt])
  const tg = field?.target
  // the assistant's default: this target (catalogue motion, distance, what SPHEREx measured) or this field
  useEffect(() => {
    if (!field) return undefined
    const m = tg?.motion
    setPageContext(tg
      ? { kind: 'target', id: field.id, name: targetName(tg), ra: +tg.ra.toFixed(5), dec: +tg.dec.toFixed(5), facts: { type: tg.kind === 'pm' ? 'moving star' : 'variable star',
        proper_motion_arcsec_yr: tg.pm_total != null ? +tg.pm_total.toFixed(3) : null, parallax_mas: tg.plx != null ? +tg.plx.toFixed(2) : null,
        distance_pc: tg.plx ? +(1000 / tg.plx).toFixed(2) : null, measured_shift_arcsec: m ? +m.measured_arcsec.toFixed(2) : null,
        predicted_shift_arcsec: m ? +m.predicted_arcsec.toFixed(2) : null, over_days: m ? Math.round(m.days) : null, exposures: tg.points?.length, catalogue: tg.source || null } }
      : { kind: 'field', id: field.id, name: fieldName(field), ra: field.ra, dec: field.dec, facts: { exposures: field.exposures?.length, size_deg: field.size_deg, passes: field.products?.passes?.length ?? null } })
    return () => setPageContext(null)
  }, [field, tg])
  useEffect(() => { if (field) document.title = `SPHEREx Sky Change · ${tg ? targetName(tg) : fieldName(field)}`; else if (err) document.title = 'SPHEREx Sky Change · ' + L('找不到這片天空', 'Field not found') }, [field, tg, err])
  if (err) {
    return (
      <div className="object target">
        <header className="tg-listhead">
          <h1>{L('找不到這片天空', 'Field not found')}</h1>
          <p className="lead">{L(`「${id}」不是已分析的天區或測試目標。可以從五個測試目標開始，或輸入任何座標。`, `“${id}” is not an analysed field or a test target. Start from the five test targets, or enter any position.`)}</p>
          <div className="ms-actions"><a className="btn primary" href="#/targets">{L('五個測試目標', 'The five test targets')}</a><a className="btn" href="#/">{L('回到首頁', 'Back to the start')}</a></div>
        </header>
        <div style={{ maxWidth: 760, marginTop: 24 }}><SkySearch id="nf-q" /></div>
      </div>
    )
  }
  if (!field) return <div className="route-loading" role="status"><i aria-hidden="true" /><span>{L('載入中…', 'Loading…')}</span></div>
  const world = pick ? pix2world(field, pick.x, pick.y) : null
  const dist = tg ? 1000 / tg.plx : null
  const helpOn = help ?? mode === 'research'
  return (
    <div className={`object target lab tool ${helpOn ? 'help-on' : ''}`}>
      <nav className="crumb" aria-label={L('位置', 'Breadcrumb')}>
        {tg ? <button onClick={() => { location.hash = '#/targets' }}>{L('挑戰測試目標', 'Challenge test targets')}</button> : <button onClick={() => go(field.id)}>{fieldName(field)}</button>}
        <span aria-hidden="true">/</span><span>{tg ? targetName(tg) : L('天區工作台', 'Field lab')}</span>
      </nav>
      {/* one header row (sticky on wide screens): the name, one line about it, the section links and the notes switch */}
      <header className="lab-head tool-head">
        <h1>{tg && <span className={`tag ${tg.kind === 'pm' ? 'distant' : 'known'}`}>{tg.kind === 'pm' ? L('移動的恆星', 'Moving star') : L('變星', 'Variable star')}</span>}{tg ? targetName(tg) : fieldName(field)}</h1>
        <p className="verdict-line" title={tg ? targetAbout(tg) : fieldDesc(field)}>{tg ? targetAbout(tg) : fieldDesc(field)}</p>
        <SectionNav items={[
        { id: 'lab-img', label: L('影像', 'Image') },
        { id: 'sec-measure', label: L('量測', 'Measure') },
        ...(tg ? [{ id: 'lab-target', label: L('目標', 'Target') }] : []),
        { id: 'lab-movers', label: L('移動星與變星', 'Movers and variables') },
        { id: 'lab-aladin', label: L('其他望遠鏡', 'Other telescopes') },
        { id: 'sec-share', label: L('分享', 'Share') },
      ]} />
        <button type="button" className="btn small helpbtn" aria-pressed={helpOn} onClick={() => setHelp(!helpOn)} title={L('顯示或隱藏每個區塊的說明', 'Show or hide the notes under each part')}>？ {L('說明', 'Notes')}</button>
      </header>
      {/* first screen: the image with its toolbar, and beside it the charts that explain it */}
      {field.products ? (
        <div className="sec-anchor" id="lab-img">
          <StackView field={field} tg={tg} pick={pick} onPick={setPick} movers={movers?.candidates} side={({ pass, showPass }) => <>
            {tg && <ChartCard level={3} className="sec-anchor" id="lab-target"
              title={tg.motion ? L(`${Math.round(tg.motion.days)} 天移動 ${tg.motion.measured_arcsec.toFixed(2)}″`, `It moved ${tg.motion.measured_arcsec.toFixed(2)}″ in ${Math.round(tg.motion.days)} days`) : targetName(tg)}
              take={tg.motion ? L(`SPHEREx 量到 ${tg.motion.measured_arcsec.toFixed(2)}″ ± ${tg.motion.err_arcsec.toFixed(2)}″，星表（自行加視差）預測 ${tg.motion.predicted_arcsec.toFixed(2)}″。`, `SPHEREx measures ${tg.motion.measured_arcsec.toFixed(2)}″ ± ${tg.motion.err_arcsec.toFixed(2)}″; the catalogue (proper motion plus parallax) predicts ${tg.motion.predicted_arcsec.toFixed(2)}″.`) : LOOK[tg.id] ? L(...LOOK[tg.id]) : null}
              more={<>
                {tg.motion && LOOK[tg.id] && <p>{L(...LOOK[tg.id])}</p>}
                {tg.motion && <p>{L(`在每一輪的${tg.motion.band ? ` D${tg.motion.band} ` : '全波段'}疊加影像上，對目標做高斯擬合（飽和的核心不用，只擬合外圍）量出位置。擬合誤差約 ${tg.motion.err_arcsec.toFixed(2)}″，不含系統誤差。虛線方框是一個 SPHEREx 像素（6.15″）。`,
                  `A Gaussian is fitted to the target in each pass stack (${tg.motion.band ? `D${tg.motion.band}` : 'all bands'}; a saturated core is left out and only the wings are fitted). Fit error about ${tg.motion.err_arcsec.toFixed(2)}″, systematics not included. The dashed square is one SPHEREx pixel (6.15″).`)}</p>}
                <p>{`${L('星表：', 'Catalogue: ')}${tg.source}`}</p>
              </>}>
              {tg.motion && <MotionPlot field={field} tg={tg} pass={pass} onPickPass={showPass} />}
              <dl className="tg-facts">
                {tg.kind === 'pm' && <div><dt>{L('自行（星表）', 'Proper motion (catalogue)')}</dt><dd>{tg.pm_total.toFixed(2)}″/{L('年', 'yr')}</dd></div>}
                <div><dt>{L('距離', 'Distance')}</dt><dd>{dist < 20 ? dist.toFixed(2) : Math.round(dist)} pc</dd></div>
                <div><dt>{L('視差（星表）', 'Parallax (catalogue)')}</dt><dd>{tg.plx.toFixed(1)} mas</dd></div>
                <div><dt>{L('影像', 'Exposures')}</dt><dd>{tg.points.length}</dd></div>
              </dl>
            </ChartCard>}
            <DataPanel field={field} />
          </>} />
        </div>
      ) : <><p className="hint">{L('這個天區還沒有工作台資料（疊加影像、資料立方體）；仍可逐張播放。', 'No lab products for this field yet; you can still play every exposure.')}</p><DataPanel field={field} /></>}
      <section ref={result} id="sec-measure" className="lab-result sec sec-anchor">
        <h2>{L('量測：光譜與光變曲線', 'Measure: spectrum and light curve')}</h2>
        {pick && world && <StarCard ra={world[0]} dec={world[1]} mjd={field.exposures[field.exposures.length >> 1]?.mjd} />}
        {!pick && !tg && <p className="empty-line">{L('點上面影像的任何一點，這裡會出現那個位置的光譜和光變曲線。', 'Click any point of the image above: its spectrum and light curve appear here.')}</p>}
        {pick && pointResult(field, pick, pt, world)}
        {tg && <Measure field={field} points={tg.points} bd={tg.bd_score ?? null} title={L(`${targetName(tg)}（沿著星表運動追蹤）`, `${targetName(tg)} (tracked along its catalogue motion)`)}
          neighbours={tg.neighbours}
          note={tg.kind === 'pm' ? L('每張影像都在依自行與視差預測的位置量測，所以移動中的天體也量得到。', 'Each exposure is measured where proper motion and parallax put it, so a moving object is followed.') : ''} />}
      </section>
      {field.products && <Tour kind="lab" />}
      <div className="two-col sec">
        <div id="lab-movers" className="sec-anchor"><Suspense fallback={null}>
          {movers && <MoverList data={movers} fieldId={field.id} onPick={(c) => { setPick({ x: c.track[0].x, y: c.track[0].y }); window.scrollTo({ top: 0, behavior: scrollBehavior() }) }} />}
          {vars && <VariableList data={vars} onPick={(c) => { setPick({ x: c.x, y: c.y }); window.scrollTo({ top: 0, behavior: scrollBehavior() }) }} />}
        </Suspense></div>
        <LabAladin field={field} tg={tg} />
      </div>
      <details id="sec-share" className="tool-more lab-share sec-anchor">
        <summary>{L('分享與嵌入', 'Share and embed')}</summary>
        <EmbedCode ra={field.ra} dec={field.dec} target={field.target?.id} />
      </details>
      <p className="hint lab-src">{tg && `${L('星表：', 'Catalogue: ')}${tg.source}. RA ${tg.ra.toFixed(5)}°, Dec ${tg.dec.toFixed(5)}° (${L('曆元', 'epoch')} ${tg.epoch}). `}{L('影像：NASA/IPAC IRSA SPHEREx Level 2；星表：ESA Gaia DR3、CatWISE2020。', 'Images: NASA/IPAC IRSA SPHEREx Level 2; catalogues: ESA Gaia DR3, CatWISE2020.')}</p>
    </div>
  )
}

/** A finished quick look is reused by the next visitor; this checks IRSA for newer images and makes it again. */
function QuickFresh({ field }) {
  const [fr, setFr] = useState(null), [st, setSt] = useState(null)
  const last = field.exposures.at(-1)
  const check = () => { setFr('loading'); api(`/api/quick/${field.id}/fresh`).then(setFr).catch(() => setFr('error')) }
  const redo = () => {
    setSt('sending')
    postJson('/api/quick', { ra: field.ra, dec: field.dec, size: field.size_deg, refresh: true })
      .then(() => location.reload()).catch((e) => setSt(String(e).includes(': 429') ? 'busy' : 'error'))
  }
  return (
    <div className="lab-fresh">
      <p className="hint">{L(`這個預覽做於 ${field.created?.slice(0, 10) || '—'}，用到 ${last.iso.slice(0, 10)} 的影像。`, `Made on ${field.created?.slice(0, 10) || '—'}, with images up to ${last.iso.slice(0, 10)}.`)}</p>
      {!fr && <button className="btn small" onClick={check}>{L('檢查有沒有新的 SPHEREx 資料', 'Check for new SPHEREx data')}</button>}
      {fr === 'loading' && <span className="hint">{L('查詢 IRSA…', 'Asking IRSA…')}</span>}
      {fr === 'error' && <span className="hint">{L('暫時查不到 IRSA。', 'IRSA could not be reached.')}</span>}
      {fr && typeof fr === 'object' && (fr.n_new ? <>
        <p>{L(`IRSA 上有 ${fr.n_new} 張更新的影像（到 ${mjdToIso(fr.available_to).slice(0, 10)}）。`, `IRSA has ${fr.n_new} newer exposures (to ${mjdToIso(fr.available_to).slice(0, 10)}).`)}</p>
        <button className="btn small primary" onClick={redo} disabled={st === 'sending'}>{L('用最新資料重做預覽', 'Make the preview again with the newest data')}</button>
        {st === 'busy' && <p className="hint">{L('伺服器正忙或今天的次數已用完，請稍後再試。', 'The server is busy or the daily limit is reached; try later.')}</p>}
        {st === 'error' && <p className="hint">{L('送出失敗，請再試一次。', 'Could not send; try again.')}</p>}
      </> : <p className="hint">{L(`已是最新：IRSA 上沒有比 ${last.iso.slice(0, 10)} 更新的影像。`, `Up to date: IRSA has nothing newer than ${last.iso.slice(0, 10)}.`)}</p>)}
    </div>
  )
}

/** The field lab for any position: shown on the quick-look page once its products are written. Same tools as an
 *  analysed field (add / subtract / blink passes, detector arrays and false colour, Gaia / CatWISE, contamination
 *  flags, spectra and light curves on the fly, flagging a position for others); the player and Aladin are above it. */
export function QuickLab({ id }) {
  useLanguage()
  const [field, setField] = useState(null), [err, setErr] = useState(false)
  const [pick, setPickRaw, setPick] = useLinkedPick()
  const [movers, setMovers] = useState(null), [vars, setVars] = useState(null)
  const result = useRef()
  const [pt, setPt] = usePoint(field, pick, result)
  useEffect(() => {
    setField(null); setErr(false); setPt(null)
    getField(id).then((f) => {
      setField(f)
      const p = pickFromLink(f)
      if (p) setPickRaw(p)
    }).catch(() => setErr(true))
    fetchProduct(id, 'pm_candidates.json').then(setMovers).catch(() => {})
    fetchProduct(id, 'var_candidates.json').then(setVars).catch(() => {})
  }, [id, setPickRaw, setPt])
  if (err) return null
  if (!field) return <div className="route-loading" role="status"><i aria-hidden="true" /><span>{L('載入工作台…', 'Loading the lab…')}</span></div>
  const world = pick ? pix2world(field, pick.x, pick.y) : null
  return (
    <section className="quick-lab lab" aria-labelledby="ql-h">
      <h2 id="ql-h" className="sec-anchor">{L('工作台：相加、相減、假彩色、星表、旗標與即時光譜', 'Lab: add, subtract, false colour, catalogues, flags and spectra on the fly')}</h2>
      <p className="hint">{L('用上面同一批影像做的：每一輪巡天、每個偵測器各自疊加。點影像上任何一點，會從每一張影像量出它的光譜和光變曲線。', 'Made from the same images as the player above: every survey pass stacked, per detector array. Click any point to measure its spectrum and light curve from every exposure.')}</p>
      <StackView field={field} pick={pick} onPick={setPick} movers={movers?.candidates} chart={false} side={<>
        <p className="empty-line">{L('這是把上面同一批影像依巡天輪次疊加的結果：可以相加、相減、換偵測器、看假彩色。點影像上任何一點量它的光譜。', 'The same exposures as above, stacked per survey pass: add them, subtract them, switch detector, see false colour. Click any point to measure its spectrum.')}</p>
        <FieldFacts field={field} title={L('這片天空', 'This patch of sky')}>
          <QuickFresh field={field} />
        </FieldFacts>
      </>} />
      <section ref={result} id="sec-measure" className="lab-result sec sec-anchor">
        <h3 className="sec-h">{L('量測：光譜與光變曲線', 'Measure: spectrum and light curve')}</h3>
        {pick && world && <StarCard ra={world[0]} dec={world[1]} mjd={field.exposures[field.exposures.length >> 1]?.mjd} />}
        {!pick && <p className="empty-line">{L('點上面影像的任何一點，這裡會出現那個位置的光譜和光變曲線。', 'Click any point of the image above: its spectrum and light curve appear here.')}</p>}
        {pick && pointResult(field, pick, pt, world)}
      </section>
      {vars && <Suspense fallback={null}><VariableList data={vars} onPick={(c) => setPick({ x: c.x, y: c.y })} /></Suspense>}
    </section>
  )
}
