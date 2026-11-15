// The site's one chart kit (UPGRADE_PLAN.md §9, S3). Every chart is drawn at its real pixel size (so 13 px ticks are
// 13 px on every screen), in the dark theme, with the same colour meanings, a hover / tap tooltip and an optional
// click (onPick), e.g. "show this exposure in the player". Use these instead of hand-made SVG:
//   <Plot x={{domain, label, fmt, log}} y={{...}} points={[{x, y, tip, hint, data}]} onPick={(p) => ...}>
//     {({ X, Y, w, h, m }) => <>…your marks, in SVG, using X(v) and Y(v)…</>}
//   </Plot>
//   <Bars bars={[{label, value, c, tip}]} unit="%" max={100} />     <Legend items={[{c, label, hollow, line}]} />
//   <ChartCard title take more legend>…</ChartCard>                  <Meter value label lo hi mark c />
import { useRef, useState } from 'react'
import { useBoxWidth } from './canvas.js'
import { L } from './lib.js'
import './charts.css'

/** Colour meanings, the same on every page. */
export const COL = {
  pass: ['#7aa8ff', '#f2d46b', '#ef6f6c', '#5fd39a', '#c08bff', '#6fe0d4'],      // survey pass 1, 2, 3 …
  det: ['#7aa8ff', '#6fe0d4', '#9be37a', '#f2d46b', '#f5a25d', '#ef6f6c'],       // detector arrays D1 … D6 (short to long wavelength)
  good: '#5fd39a', bad: '#ff6b6b', known: '#6ec3ff', distant: '#c08bff', accent: '#f2e6c9', warn: '#ffb28a',
  ink: '#f1f2f5', ink2: '#c9ccd3', ink3: '#a3a8b2',
}
/** Wavelength ranges of the six detector arrays (µm). */
export const DET_RANGE = [[0.75, 1.11], [1.10, 1.64], [1.63, 2.42], [2.42, 3.82], [3.81, 4.42], [4.41, 5.0]]

const DEFAULT_W = 640          // px, before the box has been measured
const NARROW_W = 460           // px: fewer ticks below this width
const SQUARE_MAX = 460         // px: the most a `square` plot grows
const PICK_R = 28              // px: how close the pointer must be to a point to hover or pick it
const TIP_EDGE = 130           // px from either side where the tooltip turns inwards

export function niceTicks(a, b, n = 5) {
  if (!(b > a)) return [a]
  const step = Math.pow(10, Math.floor(Math.log10((b - a) / n)))
  const m = ([1, 2, 5, 10].find((x) => (b - a) / (step * x) <= n) || 10) * step
  const out = []
  for (let v = Math.ceil(a / m - 1e-9) * m; v <= b + 1e-9; v += m) out.push(+v.toPrecision(10))
  return out
}
export function linear([d0, d1], [r0, r1]) {
  const f = (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0)
  f.invert = (p) => d0 + ((p - r0) / (r1 - r0 || 1)) * (d1 - d0)
  f.ticks = (n) => niceTicks(Math.min(d0, d1), Math.max(d0, d1), n)
  f.domain = [d0, d1]
  return f
}
export function log([d0, d1], [r0, r1]) {
  const l0 = Math.log10(d0), l1 = Math.log10(d1)
  const f = (v) => r0 + ((Math.log10(Math.max(v, 1e-300)) - l0) / (l1 - l0 || 1)) * (r1 - r0)
  f.invert = (p) => 10 ** (l0 + ((p - r0) / (r1 - r0 || 1)) * (l1 - l0))
  f.ticks = () => {
    const out = []
    for (let e = Math.floor(l0); e <= Math.ceil(l1); e++) for (const k of l1 - l0 < 1.3 ? [1, 2, 5] : [1]) { const v = k * 10 ** e; if (v >= d0 * 0.999 && v <= d1 * 1.001) out.push(v) }
    return out
  }
  f.domain = [d0, d1]
  return f
}
/** [min, max] of values, padded by a fraction of the span (multiplicative when `isLog`). */
export function extent(values, pad = 0.06, isLog = false) {
  const v = values.filter((x) => isFinite(x) && (!isLog || x > 0))
  if (!v.length) return isLog ? [1, 10] : [0, 1]
  let a = Math.min(...v), b = Math.max(...v)
  if (isLog) { const k = Math.max(1.12, (b / a) ** pad); return [a / k, b * k] }
  const p = (b - a) * pad || Math.abs(a) * 0.1 || 1
  return [a - p, b + p]
}

/**
 * A plot frame: axes, grid, tick labels, axis titles, and the hover / tap / click handling for `points`.
 * x, y    { domain: [a, b], label, fmt(v), log, ticks: [values], grid: false }
 * points  [{ x, y, tip, hint, ... }]  the things that can be hovered; tip is a string or JSX, hint a second small line
 * onPick  (point) => void             click or tap on the nearest point
 * equal   same units per pixel on both axes (sky-plane plots): the domains are widened to fit
 * height  px (or `square`: as tall as wide, at most 460)
 */
export function Plot({ x, y, points = [], onPick, children, label, height = 280, square = false, equal = false, hovered, onHover, className = '' }) {
  const box = useRef()
  const w = useBoxWidth(box) || DEFAULT_W
  const h = square ? Math.min(w, SQUARE_MAX) : height
  const narrow = w < NARROW_W
  const m = { l: (y.label ? 22 : 0) + (y.gutter ?? 46), r: 14, t: 12, b: (x.label ? 26 : 0) + 26 }
  let xd = x.domain, yd = y.domain
  if (equal) {
    const iw = w - m.l - m.r, ih = h - m.t - m.b, u = Math.max((xd[1] - xd[0]) / iw, (yd[1] - yd[0]) / ih)
    const cx = (xd[0] + xd[1]) / 2, cy = (yd[0] + yd[1]) / 2
    xd = [cx - (u * iw) / 2, cx + (u * iw) / 2]; yd = [cy - (u * ih) / 2, cy + (u * ih) / 2]
  }
  const X = (x.log ? log : linear)(x.reverse ? [xd[1], xd[0]] : xd, [m.l, w - m.r]), Y = (y.log ? log : linear)(yd, [h - m.b, m.t])
  const xt = x.ticks || X.ticks(narrow ? 4 : 6), yt = y.ticks || Y.ticks(narrow ? 4 : 5)
  const [own, setOwn] = useState(null)
  const hov = hovered !== undefined ? hovered : own
  const setHov = (j) => { setOwn(j); onHover?.(j == null ? null : points[j], j) }
  const near = (e) => {
    const r = box.current.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top
    let best = null, bd = PICK_R * PICK_R
    points.forEach((p, j) => { const d = (X(p.x) - mx) ** 2 + (Y(p.y) - my) ** 2; if (d < bd) { bd = d; best = j } })
    return best
  }
  const hp = hov != null ? points[hov] : null
  const tipX = hp ? X(hp.x) : 0
  return (
    <div ref={box} className={`plot ${onPick ? 'pickable' : ''} ${className}`}>
      <svg width={w} height={h} role="img" aria-label={label}
        /* hover is for a mouse only: after a tap, touch browsers send a mouse-leave that would close the tooltip the tap opened */
        onPointerMove={points.length ? (e) => { if (e.pointerType !== 'mouse') return; const j = near(e); if (j !== hov) setHov(j) } : undefined}
        onPointerLeave={points.length ? (e) => { if (e.pointerType === 'mouse') setHov(null) } : undefined}
        onClick={points.length ? (e) => { const j = near(e); setHov(j); if (j != null) onPick?.(points[j], j) } : undefined}>
        {y.grid !== false && yt.map((v) => <line key={`gy${v}`} className="grid" x1={m.l} x2={w - m.r} y1={Y(v)} y2={Y(v)} />)}
        {x.grid && xt.map((v) => <line key={`gx${v}`} className="grid" y1={m.t} y2={h - m.b} x1={X(v)} x2={X(v)} />)}
        <line className="axis" x1={m.l} x2={w - m.r} y1={h - m.b} y2={h - m.b} />
        {yt.map((v) => <text key={`ty${v}`} className="tick" x={m.l - 8} y={Y(v) + 4} textAnchor="end">{y.fmt ? y.fmt(v) : v}</text>)}
        {xt.map((v) => <text key={`tx${v}`} className="tick" x={X(v)} y={h - m.b + 18} textAnchor="middle">{x.fmt ? x.fmt(v, narrow) : v}</text>)}
        {x.label && <text className="axis-label" x={(m.l + w - m.r) / 2} y={h - 6} textAnchor="middle">{x.label}</text>}
        {y.label && <text className="axis-label" transform={`translate(14 ${(m.t + h - m.b) / 2}) rotate(-90)`} textAnchor="middle">{y.label}</text>}
        {children?.({ X, Y, w, h, m, hov, narrow })}
        {hp && <circle className="plot-hov" cx={X(hp.x)} cy={Y(hp.y)} r={hp.r ?? 8} />}
      </svg>
      {hp && (hp.tip || hp.hint) && <div className={`plot-tip ${tipX < TIP_EDGE ? 'right' : tipX > w - TIP_EDGE ? 'left' : ''}`} style={{ left: tipX, top: Y(hp.y) }} role="status">
        {hp.tip}{hp.hint && <small>{hp.hint}</small>}
      </div>}
    </div>
  )
}

/** Vertical bars with the value written on each: bars = [{ label, value, c, tip, hint, group }]. */
export function Bars({ bars, unit = '', max, height = 260, yLabel, xLabel, onPick, label, fmt = Math.round }) {
  const top = max ?? Math.max(...bars.map((b) => b.value)) * 1.12
  const pts = bars.map((b, j) => ({ ...b, x: j, y: b.value, r: 0, tip: b.tip ?? `${b.label}: ${fmt(b.value)}${unit}` }))
  return (
    <Plot label={label} height={height} points={pts} onPick={onPick}
      x={{ domain: [-0.6, bars.length - 0.4], ticks: bars.map((_, j) => j), fmt: (j) => bars[j]?.label ?? '', label: xLabel }}
      y={{ domain: [0, top * 1.1], ticks: niceTicks(0, top, 4), fmt: (v) => `${fmt(v)}${unit}`, label: yLabel, gutter: 50 }}>
      {({ X, Y, hov, narrow }) => {
        const bw = Math.max(6, Math.abs(X(1) - X(0)) * 0.68)
        return bars.map((b, j) => (
          <g key={j} opacity={hov == null || hov === j ? 1 : 0.55}>
            <rect x={X(j) - bw / 2} y={Y(b.value)} width={bw} height={Math.max(1, Y(0) - Y(b.value))} rx="3" fill={b.c || COL.known} />
            {(!narrow || bars.length <= 6) && <text className="mark-label" x={X(j)} y={Y(b.value) - 7} textAnchor="middle">{fmt(b.value)}{unit}</text>}
          </g>
        ))
      }}
    </Plot>
  )
}

/** Colour key: items = [{ c, label, hollow, line, sq }]. */
export function Legend({ items }) {
  return <ul className="legend">{items.map((it, j) => <li key={j}><i className={it.hollow ? 'hollow' : it.line ? 'line' : it.sq ? 'sq' : ''} style={{ '--c': it.c }} />{it.label}</li>)}</ul>
}

/** A chart with its headline: the title says what it is, `take` is the one-sentence result, `more` the folded detail. */
export function ChartCard({ title, take, more, moreLabel, legend, children, level = 3, className = '', id }) {
  const H = `h${level}`
  return (
    <figure className={`chart-card ${className}`} id={id}>
      <figcaption><H>{title}</H>{take && <p className="chart-take">{take}</p>}</figcaption>
      {legend && <Legend items={legend} />}
      {children}
      {more && <details className="chart-more"><summary>{moreLabel || L('詳細說明', 'Details')}</summary>{typeof more === 'string' ? <p>{more}</p> : more}</details>}
    </figure>
  )
}

/** A value on a scale from lo to hi, with an optional threshold mark. */
export function Meter({ value, lo = 0, hi = 1, mark, c, label, text }) {
  const f = (v) => `${Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * 100}%`
  return (
    <div className="meter">
      <div className="meter-row"><span>{label}</span><strong>{text ?? value}</strong></div>
      <div className="meter-bar" role="meter" aria-valuemin={lo} aria-valuemax={hi} aria-valuenow={value} aria-label={label}>
        <i style={{ width: f(value), '--c': c }} />{mark != null && <b style={{ left: f(mark) }} />}
      </div>
    </div>
  )
}
