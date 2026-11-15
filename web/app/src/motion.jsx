// How a star moved on the sky, measured against what the catalogue predicts (UPGRADE_PLAN.md §9, D2 and D9).
//   MotionPlot    a challenge target: the position fitted in each survey pass (with its error) on the path the
//                 catalogue's proper motion and parallax predict; east is left, north is up, offsets in arcseconds.
//   MoverVectors  a search candidate: the shift each detector array measured, as arrows from one origin
//                 (the search only keeps a star when the arrows agree).
import { useMemo } from 'react'
import { L, PIX, mjdToIso, pix2world, tangent } from './lib.js'
import { COL, Legend, Plot, extent } from './charts.jsx'

/** Earth's barycentric position (au, equatorial), low precision (0.01 au): enough for a parallax drawn in arcseconds. */
function earth(mjd) {
  const n = mjd + 2400000.5 - 2451545.0, d2r = Math.PI / 180
  const g = (357.528 + 0.9856003 * n) * d2r, lam = (280.46 + 0.9856474 * n + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * d2r
  const eps = (23.439 - 4e-7 * n) * d2r, R = 1.00014 - 0.01671 * Math.cos(g) - 0.00014 * Math.cos(2 * g)
  return [-R * Math.cos(lam), -R * Math.sin(lam) * Math.cos(eps), -R * Math.sin(lam) * Math.sin(eps)]
}
/** Catalogue offset (arcsec east, north) at `mjd` relative to the catalogue position at its own epoch. */
export function predicted(tg, mjd) {
  const d2r = Math.PI / 180, a = tg.ra * d2r, d = tg.dec * d2r
  const yr = (mjd - (51544.5 + (tg.epoch - 2000) * 365.25)) / 365.25
  const [X, Y, Z] = earth(mjd), p = (tg.plx || 0) / 1000
  return [tg.pmra / 1000 * yr + p * (X * Math.sin(a) - Y * Math.cos(a)), tg.pmdec / 1000 * yr + p * (X * Math.cos(a) * Math.sin(d) + Y * Math.sin(a) * Math.sin(d) - Z * Math.cos(d))]
}

export function MotionPlot({ field, tg, pass = null, onPickPass, height = 300 }) {
  const d = useMemo(() => {
    const ps = (tg.passes || []).filter((p) => p.fit)
    if (ps.length < 2) return null
    const t = (p) => (p.mjd0 + p.mjd1) / 2
    const [ra0, dec0] = pix2world(field, ps[0].fit.x, ps[0].fit.y), o0 = predicted(tg, t(ps[0]))
    const meas = ps.map((p) => { const [ra, dec] = pix2world(field, p.fit.x, p.fit.y), [e, n] = tangent(ra, dec, ra0, dec0), o = predicted(tg, t(p)); return { k: p.k, mjd: t(p), e, n, err: (p.fit.err || 0) * PIX, pe: o[0] - o0[0], pn: o[1] - o0[1] } })
    const path = []
    for (let m = t(ps[0]) - 20; m <= t(ps.at(-1)) + 20; m += 4) { const o = predicted(tg, m); path.push([o[0] - o0[0], o[1] - o0[1]]) }
    return { meas, path }
  }, [field, tg])
  if (!d) return null
  const xs = [...d.meas.map((p) => p.e), ...d.path.map((p) => p[0])], ys = [...d.meas.map((p) => p.n), ...d.path.map((p) => p[1])]
  const pts = d.meas.map((p) => ({ x: p.e, y: p.n, r: 10, p,
    tip: `${L(`第 ${p.k + 1} 輪`, `Pass ${p.k + 1}`)} · ${mjdToIso(p.mjd).slice(0, 10)}`,
    hint: L(`量到：東 ${p.e.toFixed(2)}″、北 ${p.n.toFixed(2)}″（±${p.err.toFixed(2)}″）；星表預測：東 ${p.pe.toFixed(2)}″、北 ${p.pn.toFixed(2)}″`, `Measured: ${p.e.toFixed(2)}″ E, ${p.n.toFixed(2)}″ N (±${p.err.toFixed(2)}″); catalogue: ${p.pe.toFixed(2)}″ E, ${p.pn.toFixed(2)}″ N`) }))
  return (
    <div className="motion">
      <Plot label={L('各輪巡天量到的位置，對星表預測的路徑', 'Position measured in each survey pass against the path the catalogue predicts')} height={height} equal points={pts}
        onPick={onPickPass ? (q) => onPickPass(q.p.k) : undefined}
        x={{ domain: extent(xs, 0.18), reverse: true, label: L('往東的位移（角秒）', 'Offset east (arcsec)'), grid: true, fmt: (v) => `${v}″` }}
        y={{ domain: extent(ys, 0.18), label: L('往北的位移（角秒）', 'Offset north (arcsec)'), fmt: (v) => `${v}″`, gutter: 44 }}>
        {({ X, Y }) => <>
          {/* one SPHEREx pixel, for scale */}
          <rect x={X(PIX / 2)} y={Y(PIX / 2)} width={Math.abs(X(-PIX / 2) - X(PIX / 2))} height={Math.abs(Y(-PIX / 2) - Y(PIX / 2))} fill="none" stroke="rgb(255 255 255 / .16)" strokeDasharray="3 4" />
          <polyline points={d.path.map(([e, n]) => `${X(e)},${Y(n)}`).join(' ')} fill="none" stroke={COL.ink3} strokeWidth="2" strokeDasharray="6 5" />
          {d.meas.map((p) => <path key={`p${p.k}`} d={`M${X(p.pe) - 6} ${Y(p.pn)}L${X(p.pe)} ${Y(p.pn) - 6}L${X(p.pe) + 6} ${Y(p.pn)}L${X(p.pe)} ${Y(p.pn) + 6}Z`} fill="none" stroke={COL.ink2} strokeWidth="1.5" />)}
          {d.meas.map((p, j) => { const c = COL.pass[p.k % COL.pass.length], e = Math.max(2, Math.abs(X(p.err) - X(0)))
            return <g key={p.k} opacity={pass == null || pass === p.k ? 1 : 0.55}>
              <path d={`M${X(p.e) - e} ${Y(p.n)}H${X(p.e) + e}M${X(p.e)} ${Y(p.n) - e}V${Y(p.n) + e}`} stroke={c} strokeWidth="2" />
              <circle cx={X(p.e)} cy={Y(p.n)} r={pass === p.k ? 8 : 6} fill={c} />
              <text className="mark-label" x={X(p.e) + 12} y={Y(p.n) - 12} style={{ fill: c }}>{L(`第 ${p.k + 1} 輪`, `Pass ${p.k + 1}`)}</text>
            </g> })}
        </>}
      </Plot>
      <Legend items={[{ c: COL.ink, label: L('SPHEREx 量到的位置（十字是誤差）', 'Measured by SPHEREx (cross = error)') }, { c: COL.ink3, line: true, label: L('星表預測的路徑（自行＋視差）', 'Catalogue path (proper motion + parallax)') }, { c: COL.ink2, hollow: true, label: L('星表在那一輪的預測位置', 'Catalogue position at that pass') }]} />
    </div>
  )
}

/** The shift each detector array measured between the first and the last pass, as arrows from one origin. */
export function MoverVectors({ c, size = 132 }) {
  const bands = (c.bands || []).filter((b) => isFinite(b.dx) && isFinite(b.dy) && b.dx != null && b.dy != null)
  if (!bands.length) return null
  const max = Math.max(...bands.map((b) => Math.hypot(b.dx, b.dy) + (b.err || 0)), Math.hypot(c.dx || 0, c.dy || 0), 1e-6)
  const R = size / 2 - 14, s = R / max, o = size / 2
  const tip = bands.map((b) => `D${b.d}: ${(Math.hypot(b.dx, b.dy) * PIX).toFixed(2)}″`).join(' · ')
  return (
    <svg className="mv-vec" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={L(`各偵測器量到的位移：${tip}`, `Shift measured by each detector: ${tip}`)}>
      <title>{tip}</title>
      <circle cx={o} cy={o} r={R} fill="none" stroke="rgb(255 255 255 / .12)" />
      {s * 0.5 < R && <circle cx={o} cy={o} r={s * 0.5} fill="none" stroke="rgb(255 255 255 / .18)" strokeDasharray="2 3" />}
      {bands.map((b) => { const x = o + b.dx * s, y = o - b.dy * s, a = Math.atan2(y - o, x - o), h = 6, col = COL.det[(b.d - 1) % 6]
        return <g key={b.d} opacity={b.agree === false ? 0.35 : 1}>
          <line x1={o} y1={o} x2={x} y2={y} stroke={col} strokeWidth="2.2" strokeLinecap="round" />
          <path d={`M${x} ${y}L${x - h * Math.cos(a - 0.5)} ${y - h * Math.sin(a - 0.5)}L${x - h * Math.cos(a + 0.5)} ${y - h * Math.sin(a + 0.5)}Z`} fill={col} />
        </g> })}
      <circle cx={o} cy={o} r="2.5" fill={COL.ink} />
    </svg>
  )
}
