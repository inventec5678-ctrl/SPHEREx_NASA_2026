// When, and at what wavelength, SPHEREx looked at this place (UPGRADE_PLAN.md §9, D1).
// SPHEREx has no filter wheel: the wavelength an exposure records depends on where the source falls on the
// detector, so every visit samples a different wavelength. One dot per exposure: time across (one panel per survey
// pass, so the months between passes do not squash the days inside one), wavelength up, colour = detector array.
// The exposure being shown is ringed; clicking a dot shows that exposure (or that pass).
import { useMemo } from 'react'
import { L, mjdToIso } from './lib.js'
import { COL, DET_RANGE, Plot } from './charts.jsx'

/** frames: [{ mjd, lam, det, ... }] in any order. Returns the frames sorted by time with their pass panel `g` and x. */
export function layoutFrames(frames, passes) {
  const fs = frames.filter((f) => isFinite(f.mjd) && isFinite(f.lam)).map((f, j) => ({ ...f, j })).sort((a, b) => a.mjd - b.mjd)
  let groups = []
  if (passes?.length) {
    // the survey passes as the analysis defined them
    groups = passes.map((p) => ({ t0: p.mjd0, t1: p.mjd1, n: 0 }))
    for (const f of fs) {
      let g = groups.findIndex((q) => f.mjd >= q.t0 - 1 && f.mjd <= q.t1 + 1)
      if (g < 0) g = groups.reduce((best, q, k) => (Math.abs(f.mjd - (q.t0 + q.t1) / 2) < Math.abs(f.mjd - (groups[best].t0 + groups[best].t1) / 2) ? k : best), 0)
      f.g = g; groups[g].n++
    }
  } else {
    // no pass table (frames still streaming in): a gap of two months starts a new pass
    for (const f of fs) {
      const g = groups.at(-1)
      if (!g || f.mjd - g.t1 > 60) groups.push({ t0: f.mjd, t1: f.mjd, n: 1 }); else { g.t1 = f.mjd; g.n++ }
      f.g = groups.length - 1
    }
  }
  for (const f of fs) { const g = groups[f.g]; f.x = f.g + 0.08 + 0.84 * (g.t1 > g.t0 ? Math.min(1, Math.max(0, (f.mjd - g.t0) / (g.t1 - g.t0))) : 0.5) }
  return { fs, groups }
}

/**
 * frames   [{ mjd, lam, det, iso? }]
 * passes   [{ mjd0, mjd1 }] the analysis's survey passes (optional)
 * current  index into `frames` of the exposure on screen (or null)
 * pass     index of the survey pass on screen (shades that panel), or null
 * onPick   (frame, indexInFrames) => void
 */
export function TimeWave({ frames, passes, current = null, pass = null, onPick, height = 230, hint }) {
  const { fs, groups } = useMemo(() => layoutFrames(frames, passes), [frames, passes])
  if (fs.length < 2) return null
  const pts = fs.map((f) => ({ x: f.x, y: f.lam, r: 7, f,
    tip: `${f.iso ? f.iso.slice(0, 16).replace('T', ' ') : mjdToIso(f.mjd)} UTC · D${f.det} · ${f.lam.toFixed(2)} µm`, hint }))
  const cur = current != null ? fs.find((f) => f.j === current) : null
  return (
    <Plot label={L('每張影像的拍攝時間與波長', 'Time and wavelength of every exposure')} height={height} points={pts} onPick={onPick ? (p) => onPick(p.f, p.f.j) : undefined}
      x={{ domain: [0, groups.length], ticks: groups.map((_, g) => g + 0.5), fmt: (v, narrow) => { const g = groups[Math.floor(v)]; return !g ? '' : narrow ? `${mjdToIso(g.t0).slice(2, 7)} · ${g.n}` : `${mjdToIso(g.t0).slice(0, 7)} · ${g.n} ${L('張', 'exp.')}` } }}
      y={{ domain: [0.6, 5.15], ticks: [1, 2, 3, 4, 5], fmt: (v) => `${v} µm`, gutter: 50 }}>
      {({ X, Y, m, w }) => <>
        {pass != null && groups[pass] && <rect x={X(pass) + 2} y={m.t} width={X(pass + 1) - X(pass) - 4} height={Y(0.6) - m.t} fill="rgb(255 255 255 / .05)" rx="4" />}
        {groups.slice(1).map((_, g) => <line key={g} className="grid" x1={X(g + 1)} x2={X(g + 1)} y1={m.t} y2={Y(0.6)} />)}
        {DET_RANGE.map(([lo, hi], d) => <g key={d}><rect x={w - m.r + 2} y={Y(hi)} width="5" height={Y(lo) - Y(hi) - 1} fill={COL.det[d]} rx="2" /></g>)}
        {fs.map((f) => <circle key={f.j} cx={X(f.x)} cy={Y(f.lam)} r="3.2" fill={COL.det[(f.det - 1) % 6]} fillOpacity={cur && cur !== f ? 0.6 : 0.9} />)}
        {cur && <><line x1={X(cur.x)} x2={X(cur.x)} y1={m.t} y2={Y(0.6)} stroke={COL.ink} strokeOpacity=".5" />
          <circle cx={X(cur.x)} cy={Y(cur.lam)} r="7" fill="none" stroke={COL.ink} strokeWidth="2" /></>}
      </>}
    </Plot>
  )
}
