// Features taken from WiseView, the Backyard Worlds blink tool the challenge suggests as a template (UPGRADE_PLAN.md
// §10, R7): brightness controls for the lab image, shift-and-add along a trial motion (the lab's fifth view), and
// "spot the fake mover", a practice round with a synthetic moving star hidden in real pass stacks (#/movers).
import { useEffect, useMemo, useRef, useState } from 'react'
import { L, PASS_C, PIX, api, dataBase, getField, pix2world } from './lib.js'
import { BRIGHT0, histogram, jacobian, loadBright, loadGroup, makePuzzle, moments, passTimes, peakNear, pixToMotion, rng, saveBright, shiftAdd, stretchMap, trackDistance } from './shiftadd.js'
import { wiseviewUrl } from './elsewhere.jsx'
import { dpr, useBoxWidth } from './canvas.js'
import { usePlayback } from './play.js'
import { PlayBar } from './playbar.jsx'
import './wiseview.css'

// ---- brightness -----------------------------------------------------------------------------------------------
/** The visitor's brightness settings, remembered in this browser. */
export function useBright() {
  const [br, setBrRaw] = useState(loadBright)
  return [br, (b) => { setBrRaw(b); saveBright(b) }]
}
const same = (a, b) => a.lo === b.lo && a.hi === b.hi && a.stretch === b.stretch && a.invert === b.invert

/** The histogram of the picture's pixel values, the two limits, and the curve that turns a value into a grey. */
function Hist({ vals, br }) {
  const h = useMemo(() => (vals ? histogram(vals, 48, 0.5, 99.8) : null), [vals])
  const map = useMemo(() => (vals ? stretchMap(vals, br) : null), [vals, br])
  if (!h) return null
  const W = 300, H = 92, top = Math.log1p(Math.max(...h.h)), X = (v) => Math.min(W, Math.max(0, ((v - h.x0) / (h.x1 - h.x0)) * W))
  const xl = X(h.at(br.lo)), xh = X(h.at(br.hi)), bw = W / h.h.length
  const curve = Array.from({ length: 61 }, (_, k) => { const v = h.x0 + ((h.x1 - h.x0) * k) / 60; return `${X(v).toFixed(1)},${(H - 4 - (map(v) / 255) * (H - 8)).toFixed(1)}` }).join(' ')
  return (
    <svg className="bp-hist" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={L(`像素亮度分布；暗端 ${br.lo}%，亮端 ${br.hi}%`, `Pixel values; dark end ${br.lo}%, bright end ${br.hi}%`)}>
      {h.h.map((c, k) => <rect key={k} x={k * bw + 0.5} width={bw - 1} y={H - (Math.log1p(c) / top) * (H - 8)} height={(Math.log1p(c) / top) * (H - 8)} fill="rgb(255 255 255 / .28)" />)}
      <rect x="0" y="0" width={xl} height={H} fill="rgb(0 0 0 / .45)" />
      <rect x={xh} y="0" width={W - xh} height={H} fill="rgb(0 0 0 / .45)" />
      <line x1={xl} x2={xl} y1="0" y2={H} stroke="#6ec3ff" strokeWidth="2" />
      <line x1={xh} x2={xh} y1="0" y2={H} stroke="#ffb547" strokeWidth="2" />
      <polyline points={curve} fill="none" stroke="#f2e6c9" strokeWidth="2" />
    </svg>
  )
}

/** "Brightness" in the lab toolbar: low / high limits as percentiles, linear or asinh, invert. */
export function BrightnessPop({ br, setBr, vals, mode }) {
  const [open, setOpen] = useState(false)
  const set = (k, v) => setBr({ ...br, [k]: v })
  return (
    <details className="bpop" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="btn small">{L('亮度', 'Brightness')}{same(br, BRIGHT0) ? '' : ' ·'}</summary>
      <div className="bpop-panel">
        {mode === 'diff' ? <p className="pop-note">{L('差分影像用自己的對稱色階（橘＝變亮、藍＝變暗）；這裡的設定用在其他畫面。', 'The difference view keeps its own two-sided scale (orange brighter, blue fainter); these settings apply to the other views.')}</p>
          : open && <Hist vals={vals} br={br} />}
        <label className="bp-range"><span>{L('暗端', 'Dark end')}</span>
          <input type="range" min="0" max="90" step="0.5" value={br.lo} onChange={(e) => set('lo', +e.target.value)} aria-label={L('暗端（百分位）', 'Dark end (percentile)')} />
          <b className="num">{br.lo}%</b></label>
        <label className="bp-range"><span>{L('亮端', 'Bright end')}</span>
          <input type="range" min="95" max="100" step="0.05" value={br.hi} onChange={(e) => set('hi', +(+e.target.value).toFixed(2))} aria-label={L('亮端（百分位）', 'Bright end (percentile)')} />
          <b className="num">{br.hi}%</b></label>
        <div className="seg" role="group" aria-label={L('亮度曲線', 'Stretch')}>
          <button type="button" aria-pressed={br.stretch === 'linear'} onClick={() => set('stretch', 'linear')}>{L('線性', 'Linear')}</button>
          <button type="button" aria-pressed={br.stretch === 'asinh'} onClick={() => set('stretch', 'asinh')}>{L('asinh：暗處加亮', 'asinh: lifts faint light')}</button>
        </div>
        <label><input type="checkbox" name="invert" checked={br.invert} onChange={() => set('invert', !br.invert)} /> {L('反相：白底黑星（WiseView 的預設）', 'Invert: black stars on white (WiseView’s default)')}</label>
        <p className="pop-note">{L(`比「暗端」暗的像素畫成${br.invert ? '白' : '黑'}，比「亮端」亮的畫成${br.invert ? '黑' : '白'}；百分位是在這張圖的所有像素裡排第幾。`, `Pixels below the dark end show ${br.invert ? 'white' : 'black'}, above the bright end ${br.invert ? 'black' : 'white'}; a percentile is the rank among this picture’s pixels.`)}</p>
        {!same(br, BRIGHT0) && <button type="button" className="btn small" onClick={() => setBr({ ...BRIGHT0 })}>{L('回到預設', 'Back to the default')}</button>}
      </div>
    </details>
  )
}

// ---- shift-and-add in the lab ---------------------------------------------------------------------------------
/** Two square panels side by side (plain sum | shifted sum), a whole number of device pixels per SPHEREx pixel. */
export function shiftGeometry(avail, half) {
  const u = dpr(), gap = Math.round(10 * u)
  const s = Math.max(1, Math.floor((avail * u - gap) / 2 / (2 * half))), Wp = Math.round(s * 2 * half), W = 2 * Wp + gap
  return { W, H: Wp, Wp, gap, s, u, off: 0, css: W / u }
}
/** Canvas event -> field pixel and panel (0 plain, 1 shifted); `force` reads it in a given panel (a drag that crosses over). */
export function shiftPix(e, g2, x0, cy, half, force = null) {
  const r = e.currentTarget.getBoundingClientRect(), k = g2.W / r.width
  let px = (e.clientX - r.left) * k
  const panel = force ?? (px >= g2.Wp + g2.gap / 2 ? 1 : 0)
  if (panel) px -= g2.Wp + g2.gap
  return { x: x0 + px / g2.s, y: cy + half - ((e.clientY - r.top) * k) / g2.s, panel }
}
/**
 * The plain sum and the shifted sum of the visible part of the field, per channel (one band, or D6 / D3 / D1 for
 * false colour). frames are taken from S (the lab's stacks); `box` limits the work to what is on screen.
 */
export function useShiftAdd({ on, S, chans, times, v, how, box }) {
  const frames = useMemo(() => (on && S ? chans.map((d) => Array.from({ length: S.P }, (_, p) => S.get(p, d))) : null), [on, S, chans])
  const bk = box.join(',')
  const plain = useMemo(() => (frames ? frames.map((fr) => shiftAdd(fr, S.n, times, { vx: 0, vy: 0 }, how, box)) : null), [frames, times, how, bk]) // eslint-disable-line react-hooks/exhaustive-deps
  const shifted = useMemo(() => (frames ? frames.map((fr) => shiftAdd(fr, S.n, times, v, how, box)) : null), [frames, times, how, bk, v.vx, v.vy]) // eslint-disable-line react-hooks/exhaustive-deps
  return plain && shifted ? { plain, shifted } : null
}

/** Draw both panels and their marks: the reference star (dashed ring), the trial motion over 10 years (arrow), and
 *  on the plain sum the target's catalogue position in each pass. */
export function drawShift(c, o, { img, img2, n, x0, ytop, half, g2, smooth, invert, ref, v, tgPasses, kb }) {
  const { W, H, Wp, gap, s, u } = g2
  if (c.width !== W || c.height !== H) { c.width = W; c.height = H }
  const g = c.getContext('2d')
  g.fillStyle = '#05070c'; g.fillRect(0, 0, W, H)
  g.imageSmoothingEnabled = smooth; g.imageSmoothingQuality = 'high'
  if (o.width !== n || o.height !== n) { o.width = n; o.height = n }
  ;[[img, 0], [img2, Wp + gap]].forEach(([im, ox], panel) => {
    g.save(); g.beginPath(); g.rect(ox, 0, Wp, H); g.clip()
    g.fillStyle = invert ? '#fff' : '#000'; g.fillRect(ox, 0, Wp, H)
    o.getContext('2d').putImageData(im, 0, 0)
    g.drawImage(o, x0 + 0.5, ytop + 0.5, 2 * half, 2 * half, ox, 0, Wp, Wp)
    const X = (x) => ox + (x - x0) * s, Y = (y) => (n - 1 - y - ytop) * s
    if (panel === 0 && tgPasses) tgPasses.forEach((p, j) => { g.fillStyle = PASS_C[j % PASS_C.length]; g.beginPath(); g.arc(X(p.x), Y(p.y), 3 * u, 0, 7); g.fill() })
    if (ref) {
      const px = X(ref.x), py = Y(ref.y)
      g.strokeStyle = '#ffb547'; g.lineWidth = 2 * u; g.setLineDash([5 * u, 4 * u])
      g.beginPath(); g.arc(px, py, Math.max(12 * u, 2.6 * s), 0, 7); g.stroke(); g.setLineDash([])
      const ex = X(ref.x + v.vx * 10), ey = Y(ref.y + v.vy * 10), L2 = Math.hypot(ex - px, ey - py)
      if (L2 > 3 * u) {                       // the trial motion over ten years
        const a = Math.atan2(ey - py, ex - px), hh = 10 * u
        g.strokeStyle = '#ff4fd8'; g.fillStyle = '#ff4fd8'; g.lineWidth = 2.5 * u
        g.beginPath(); g.moveTo(px, py); g.lineTo(ex, ey); g.stroke()
        g.beginPath(); g.moveTo(ex, ey); g.lineTo(ex - hh * Math.cos(a - 0.45), ey - hh * Math.sin(a - 0.45)); g.lineTo(ex - hh * Math.cos(a + 0.45), ey - hh * Math.sin(a + 0.45)); g.closePath(); g.fill()
      }
    }
    if (kb) {                              // keyboard cross: dashed, until Enter picks that star
      const qx = X(kb.x), qy = Y(kb.y), a = 18 * u
      g.strokeStyle = '#ffb547'; g.lineWidth = 2 * u; g.setLineDash([4 * u, 4 * u])
      g.beginPath(); g.moveTo(qx - a, qy); g.lineTo(qx + a, qy); g.moveTo(qx, qy - a); g.lineTo(qx, qy + a); g.stroke(); g.setLineDash([])
    }
    g.restore()
  })
}

const DIRS = [['北', 'north'], ['東北', 'north-east'], ['東', 'east'], ['東南', 'south-east'], ['南', 'south'], ['西南', 'south-west'], ['西', 'west'], ['西北', 'north-west']]
/** Compass word for a motion (east, north): position angle measured from north through east. */
export const dirWord = (east, north) => L(...DIRS[Math.round(((Math.atan2(east, north) * 180) / Math.PI + 360) % 360 / 45) % 8])
/** A compass with the motion as an arrow (north up, east left, as on the sky and on the lab image). */
function Compass({ east, north, size = 76 }) {
  const sp = Math.hypot(east, north), c = size / 2, r = c - 12, k = sp > 0 ? Math.min(1, sp / 15) * r / sp : 0
  const ex = c - east * k, ey = c - north * k
  return (
    <svg className="sa-compass" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={sp > 0 ? L(`每年 ${sp.toFixed(1)}″，往${dirWord(east, north)}`, `${sp.toFixed(1)}″ per year toward the ${dirWord(east, north)}`) : L('不移動', 'No motion')}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="rgb(255 255 255 / .25)" />
      <text x={c} y="10" textAnchor="middle" className="sa-nesw">N</text><text x="5" y={c + 4} textAnchor="middle" className="sa-nesw">E</text>
      {sp > 0 && <><line x1={c} y1={c} x2={ex} y2={ey} stroke="#ff4fd8" strokeWidth="3" strokeLinecap="round" /><circle cx={ex} cy={ey} r="3.5" fill="#ff4fd8" /></>}
      <circle cx={c} cy={c} r="3" fill="#ffb547" />
    </svg>
  )
}
/** Plain sum against shifted sum at the reference star: its brightest pixel and how spread out its light is (the
 *  light-weighted width within 4 pixels, as a full width at half maximum). Elongation is left out: on faint stars it
 *  is mostly noise (WISE 0855 in D6 reads 1.04 plain, 1.21 shifted, although the shifted star is the sharper one). */
function SharpBars({ m }) {
  const rows = [
    { k: L('最亮像素', 'Brightest pixel'), a: m.p0, b: m.p1, fmt: (v) => v.toPrecision(3), better: m.p1 > m.p0, note: `×${(m.p1 / m.p0).toFixed(2)}` },
    { k: L('光散開的寬度（越小越清楚）', 'How spread out the light is (smaller is sharper)'), a: m.w0, b: m.w1, fmt: (v) => `${v.toFixed(1)}″`, better: m.w1 < m.w0 },
  ].filter((r) => Number.isFinite(r.a) && Number.isFinite(r.b) && r.a > 0 && r.b > 0)
  return (
    <div className="sa-bars" role="table" aria-label={L('直接相加和平移相加的比較', 'Plain sum against shifted sum')}>
      {rows.map((r) => { const top = Math.max(r.a, r.b); return (
        <div key={r.k} className="sa-bar" role="row">
          <span role="rowheader">{r.k}</span>
          <span role="cell" className="sa-pair">
            <i style={{ width: `${(r.a / top) * 100}%` }} className="plain"><b>{r.fmt(r.a)}</b></i>
            <i style={{ width: `${(r.b / top) * 100}%` }} className={`shift ${r.better ? 'better' : ''}`}><b>{r.fmt(r.b)}{r.note ? ` · ${r.note}` : ''}</b></i>
          </span>
        </div>) })}
      <p className="sa-key"><i className="plain" />{L('直接相加', 'Plain sum')}<i className="shift" />{L('平移相加', 'Shifted and added')}</p>
    </div>
  )
}
/** The numbers at the reference star from the two sums (first channel: the band shown, or D6 in false colour). */
export function sharpness(sa, n, ref) {
  if (!sa || !ref) return null
  const a = sa.plain[0], b = sa.shifted[0]
  const p0 = peakNear(a, n, ref.x, ref.y), p1 = peakNear(b, n, ref.x, ref.y)
  const m0 = moments(a, n, ref.x, ref.y), m1 = moments(b, n, ref.x, ref.y)
  if (!(p0 > 0) || !m0 || !m1) return null
  return { p0, p1, w0: m0.size * 2.355 * PIX, w1: m1.size * 2.355 * PIX }
}

/** Controls under the two panels: the motion as numbers and a compass, shortcuts, and the comparison. */
export function ShiftPanel({ field, tg, mot, setMot, how, setHow, read, refPt }) {
  const sp = Math.hypot(mot.east, mot.north)
  const num = (k) => (
    <label className="sa-num"><span>{k === 'east' ? L('向東', 'East') : L('向北', 'North')}</span>
      <input type="number" inputMode="decimal" step="0.5" min="-60" max="60" value={mot[k]} onChange={(e) => { const v = +e.target.value; if (Number.isFinite(v)) setMot({ ...mot, [k]: Math.max(-60, Math.min(60, v)) }) }}
        aria-label={k === 'east' ? L('向東的速度（角秒／年）', 'Speed toward the east (arcsec per year)') : L('向北的速度（角秒／年）', 'Speed toward the north (arcsec per year)')} />
      <small>″/{L('年', 'yr')}</small></label>
  )
  const at = refPt ? pix2world(field, refPt.x, refPt.y) : [field.ra, field.dec]
  return (
    <div className="sa-panel">
      <div className="sa-row">
        <Compass east={mot.east} north={mot.north} />
        <div className="sa-motion">
          <p className="sa-speed"><b className="num">{sp.toFixed(1)}″</b>/{L('年', 'yr')}{sp > 0 ? L(`，往${dirWord(mot.east, mot.north)}`, ` toward the ${dirWord(mot.east, mot.north)}`) : ''}</p>
          <div className="sa-nums">{num('east')}{num('north')}</div>
        </div>
      </div>
      <div className="sa-row">
        {tg?.kind === 'pm' && tg.pmra != null && <button type="button" className="btn small" onClick={() => setMot({ east: +(tg.pmra / 1000).toFixed(2), north: +(tg.pmdec / 1000).toFixed(2) })}>{L('用星表裡的運動', 'Use the catalogue motion')}</button>}
        <button type="button" className="btn small" disabled={!sp} onClick={() => setMot({ east: -mot.east, north: -mot.north })}>{L('反方向', 'Reverse it')}</button>
        <button type="button" className="btn small" disabled={!sp} onClick={() => setMot({ east: 0, north: 0 })}>{L('歸零', 'Zero')}</button>
        <div className="seg" role="group" aria-label={L('怎麼合併各輪', 'How the passes are combined')}>
          <button type="button" aria-pressed={how === 'mean'} onClick={() => setHow('mean')}>{L('平均', 'Mean')}</button>
          <button type="button" aria-pressed={how === 'median'} onClick={() => setHow('median')}>{L('中位數', 'Median')}</button>
        </div>
      </div>
      {read ? <SharpBars m={read} /> : <p className="hint" role="status">{L('點一顆星：下面會比較它在兩張圖裡的亮度和寬度。', 'Click a star: its brightness and width in the two pictures are compared here.')}</p>}
      <a className="btn small sa-wv" href={wiseviewUrl({ ra: at[0], dec: at[1], ...(sp > 0 ? { pmra: mot.east * 1000, pmdec: mot.north * 1000 } : {}) })} target="_blank" rel="noopener noreferrer">
        {sp > 0 ? L('在 WiseView 用這個運動平移相加（WISE 十多年）↗', 'Shift-and-add this motion in WiseView (10+ years of WISE) ↗') : L('在 WiseView 打開這裡（WISE 十多年）↗', 'Open this spot in WiseView (10+ years of WISE) ↗')}</a>
    </div>
  )
}

// ---- spot the fake mover (#/movers) ---------------------------------------------------------------------------
const SKEY = 'sx:fake-score:v1'
const loadScore = () => { try { const s = JSON.parse(localStorage.getItem(SKEY) || 'null'); if (s && s.n >= 0 && s.hit >= 0) return { n: +s.n, hit: +s.hit } } catch { /* no storage */ } return { n: 0, hit: 0 } }
const saveScore = (s) => { try { localStorage.setItem(SKEY, JSON.stringify(s)) } catch { /* no storage */ } }
const HIT_PX = 2          // a click within 2 pixels (12″) of the star's path counts

/** A synthetic moving star hidden in real pass stacks: blink, click where it is, see the answer and the numbers. */
export function FakeMover() {
  const [level, setLevel] = useState('easy')
  const [seed, setSeed] = useState(() => (Date.now() ^ Math.floor(Math.random() * 1e9)) >>> 0)
  const [pz, setPz] = useState(null), [err, setErr] = useState(false)
  const [guess, setGuess] = useState(null), [gaveUp, setGaveUp] = useState(false)
  const [score, setScore] = useState(loadScore)
  const [seen, setSeen] = useState(false)
  const box = useRef(), cv = useRef(), off = useRef(null)
  const bw = useBoxWidth(box)
  // start only when the section comes near the screen: it downloads a field's stacks (~0.2-0.5 MB)
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') { setSeen(true); return }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setSeen(true); io.disconnect() } }, { rootMargin: '300px' })
    if (box.current) io.observe(box.current)
    return () => io.disconnect()
  }, [])
  useEffect(() => {
    if (!seen) return
    let live = true
    setPz(null); setGuess(null); setGaveUp(false); setErr(false)
    const R = rng(seed)
    ;(async () => {
      let ids = []
      try { ids = (await api('/api/fields')).filter((f) => !f.simulated && !f.user).map((f) => f.id) } catch { /* fall through */ }
      for (let t = ids.length - 1; t > 0; t--) { const j = Math.floor(R() * (t + 1)); [ids[t], ids[j]] = [ids[j], ids[t]] }
      for (const id of ids) {
        try {
          const f = await getField(id), pr = f.products
          if (!pr?.passes || pr.passes.length < 2) continue
          const n = f.shape[0], P = pr.passes.length
          const G = await loadGroup(dataBase(id), 0, P, n)
          const times = passTimes(pr.passes, f.exposures)
          // keep a real fast mover (the field's target) out of the picture: it would be a second answer
          const avoid = (f.target?.passes || []).map((q) => ({ x: q.x, y: q.y, r: 10 }))
          const p = makePuzzle(R, Array.from({ length: P }, (_, k) => G.get(k)), n, times, level, { avoid })
          if (p) { if (live) setPz({ f, p, times }); return }
        } catch { /* try the next field */ }
      }
      if (live) setErr(true)
    })()
    return () => { live = false }
  }, [seed, level, seen])
  const P = pz?.p.frames.length || 0
  const pb = usePlayback(P, { hz: 1 / 0.8, active: !!pz })
  const k = Math.min(pb.k, Math.max(0, P - 1))
  // one brightness scale for every pass (the visitor's lab settings), so only the mover changes between frames
  const imgs = useMemo(() => {
    if (!pz) return null
    const { C, frames } = pz.p, all = new Float32Array(C * C * frames.length)
    frames.forEach((f, j) => all.set(f, j * C * C))
    const m = stretchMap(all, loadBright())
    return frames.map((f) => {
      const out = new Uint8ClampedArray(C * C * 4)
      for (let y = 0; y < C; y++) for (let x = 0; x < C; x++) { const v = m(f[y * C + x]), o = ((C - 1 - y) * C + x) * 4; out[o] = out[o + 1] = out[o + 2] = v; out[o + 3] = 255 }
      return new ImageData(out, C, C)
    })
  }, [pz])
  const done = !!guess || gaveUp
  const css = Math.min(480, bw || 360)
  useEffect(() => {
    const c = cv.current
    if (!c || !imgs) return
    const { C, track } = pz.p, u = dpr(), s = Math.max(1, Math.floor((css * u) / C)), W = s * C
    if (c.width !== W || c.height !== W) { c.width = W; c.height = W }
    if (!off.current) off.current = document.createElement('canvas')
    const o = off.current; o.width = C; o.height = C; o.getContext('2d').putImageData(imgs[k], 0, 0)
    const g = c.getContext('2d')
    g.imageSmoothingEnabled = false
    g.drawImage(o, 0, 0, W, W)
    const X = (x) => (x + 0.5) * s, Y = (y) => (C - 1 - y + 0.5) * s
    if (done) {
      g.lineWidth = 2 * u
      g.strokeStyle = 'rgba(255,79,216,.9)'; g.beginPath(); track.forEach((q, j) => (j ? g.lineTo(X(q.x), Y(q.y)) : g.moveTo(X(q.x), Y(q.y)))); g.stroke()
      track.forEach((q, j) => { g.strokeStyle = PASS_C[j % PASS_C.length]; g.lineWidth = (j === k ? 3 : 1.5) * u; g.beginPath(); g.arc(X(q.x), Y(q.y), Math.max(9 * u, 1.8 * s), 0, 7); g.stroke() })
    }
    if (guess) {
      const gx = X(guess.x), gy = Y(guess.y), a = 12 * u
      g.strokeStyle = '#fff'; g.lineWidth = 2.5 * u
      g.beginPath(); g.moveTo(gx - a, gy - a); g.lineTo(gx + a, gy + a); g.moveTo(gx + a, gy - a); g.lineTo(gx - a, gy + a); g.stroke()
    }
  }, [imgs, k, css, done, guess, pz])
  const onClick = (e) => {
    if (!pz || done) return
    const r = e.currentTarget.getBoundingClientRect(), C = pz.p.C
    const x = ((e.clientX - r.left) / r.width) * C - 0.5, y = C - 1 - (((e.clientY - r.top) / r.height) * C - 0.5)
    const d = trackDistance(pz.p.track, x, y)
    setGuess({ x, y, d })
    const s = { n: score.n + 1, hit: score.hit + (d <= HIT_PX ? 1 : 0) }
    setScore(s); saveScore(s)
  }
  const giveUp = () => { if (!pz || done) return; setGaveUp(true); const s = { n: score.n + 1, hit: score.hit }; setScore(s); saveScore(s) }
  const next = () => setSeed((x) => (x * 1664525 + 1013904223) >>> 0)
  const p = pz?.p
  // the motion on the sky (arcsec/yr toward the east and the north), through the field's own projection
  const sky = p ? pixToMotion(jacobian((x, y) => pix2world(pz.f, x, y), p.x0 + p.C / 2, p.y0 + p.C / 2), p.vx, p.vy) : { east: 0, north: 0 }
  const speed = Math.hypot(sky.east, sky.north), east = sky.east, north = sky.north
  const hit = guess && guess.d <= HIT_PX
  const centre = p ? pix2world(pz.f, p.x0 + p.C / 2, p.y0 + p.C / 2) : null
  return (
    <section className="fk sec" id="fake-mover" aria-labelledby="fk-h">
      <h2 id="fk-h">{L('練眼力：找出假的移動星', 'Practice: spot the fake mover')}</h2>
      <p className="lead fk-lead">{L('我們在真的 SPHEREx 影像裡藏了一顆假的、會移動的星。看輪播，點它在哪裡。', 'We hid one made-up moving star in real SPHEREx images. Watch the blink and click where it is.')}</p>
      <div className="fk-stage">
        <div className="fk-main" ref={box}>
          <div className="fk-frame" style={{ width: css, height: css }}>
            <canvas ref={cv} role="img" tabIndex={0} onClick={onClick} onKeyDown={(e) => pb.onKey(e)} className={done ? '' : 'pick'}
              aria-label={L('各輪巡天的一小塊天空輪流顯示；點你認為在移動的那顆星', 'A small patch of sky in each survey pass, in turn; click the star you think is moving')} />
            {!pz && <div className="fk-wait" role="status">{err ? L('暫時拿不到影像，請再試一次。', 'Could not get the images; try again.') : L('準備題目…', 'Setting up a puzzle…')}</div>}
            {pz && <span className="blink-tag" style={{ '--c': PASS_C[k % PASS_C.length] }} aria-hidden="true">{L(`第 ${k + 1} 輪`, `Pass ${k + 1}`)}<small>{L(` / 共 ${P} 輪`, ` of ${P}`)}</small></span>}
          </div>
          {pz && <PlayBar pb={pb} n={P} slider={false} label={L('輪播各輪巡天', 'Blink the survey passes')} />}
        </div>
        <div className="fk-side">
          <div className="seg" role="group" aria-label={L('難度', 'Difficulty')}>
            <button type="button" aria-pressed={level === 'easy'} onClick={() => setLevel('easy')}>{L('簡單', 'Easy')}</button>
            <button type="button" aria-pressed={level === 'hard'} onClick={() => setLevel('hard')}>{L('困難', 'Hard')}</button>
          </div>
          <p className="fk-score" aria-live="polite"><b className="num">{score.hit}</b><span>/ {score.n}</span><small>{L('答對', 'found')}</small></p>
          {!done ? <>
            <p className="fk-ask">{L('哪一顆在動？點它。', 'Which one moves? Click it.')}</p>
            <button type="button" className="btn small" disabled={!pz} onClick={giveUp}>{L('放棄，看答案', 'Give up, show me')}</button>
          </> : <>
            <p className={`fk-verdict ${hit ? 'ok' : ''}`} role="status">{hit ? L('找到了！', 'Found it!') : guess ? L(`差一點：它在 ${(guess.d * PIX).toFixed(0)}″ 外（${guess.d.toFixed(1)} 像素）。`, `Not quite: it was ${(guess.d * PIX).toFixed(0)}″ away (${guess.d.toFixed(1)} pixels).`) : L('答案在這裡。', 'Here it is.')}</p>
            <dl className="fk-facts">
              <div><dt>{L('速度', 'Speed')}</dt><dd><Compass east={east} north={north} size={64} /><span><b className="num">{speed.toFixed(1)}″</b>/{L('年', 'yr')}{L(`，往${dirWord(east, north)}`, ` toward the ${dirWord(east, north)}`)}</span></dd></div>
              <div><dt>{L('移動', 'Moved')}</dt><dd>{L(`第 1 輪到第 ${P} 輪移動 ${p.shift.toFixed(1)} 像素（${(p.shift * PIX).toFixed(0)}″）`, `${p.shift.toFixed(1)} pixels (${(p.shift * PIX).toFixed(0)}″) from pass 1 to pass ${P}`)}</dd></div>
              <div><dt>{L('亮度', 'Brightness')}</dt><dd>{L(`最亮的像素是雜訊的 ${p.snr.toFixed(0)} 倍`, `Brightest pixel ${p.snr.toFixed(0)}× the noise`)}</dd></div>
              <div><dt>{L('天空', 'Sky')}</dt><dd>{L(`${pz.f.name}；RA ${centre[0].toFixed(3)}°, Dec ${centre[1].toFixed(3)}°`, `${pz.f.name}; RA ${centre[0].toFixed(3)}°, Dec ${centre[1].toFixed(3)}°`)}</dd></div>
            </dl>
            <button type="button" className="btn small primary" onClick={next}>{L('下一題', 'Next puzzle')}</button>
          </>}
          <p className="hint fk-note">{L('假星是寬度和 SPHEREx 星點一樣的高斯光點，沿直線等速移動。SPHEREx 目前只有約一年的資料，所以只有很快的星看得出移動；WiseView 有 WISE 十多年的影像，慢的也看得到。', 'The fake star is a Gaussian as wide as a SPHEREx star, moving in a straight line at a steady speed. SPHEREx has about a year of data so far, so only fast movers show; WiseView’s ten-plus years of WISE show slow ones too.')}</p>
        </div>
      </div>
    </section>
  )
}
