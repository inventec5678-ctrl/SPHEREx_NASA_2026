// The evidence page of one moving object (#/field/<id>/track/<n>). The first screen is the evidence as pictures
// (UPGRADE_PLAN.md §9.5): the detections playing on the left; on the right where it went on the sky against the
// model and JPL's prediction, how close JPL is, and the body the model predicts. The three checks are meters with
// their thresholds. Every chart shares the player's frame: the frame on screen is ringed, a click shows that frame.
// Below, "why believe it" keeps the deeper charts in tabs, drawn with the site's chart kit.
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { L, t, translate } from '@sx/i18n/core.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { DET, PIX, api, blitFrame, drawCrop, evidenceChecks, frameImg, getField, mjdDate, mjdToIso, pct, ready, sbdbUrl, tangent, trackTitle } from './lib.js'
import { usePlayback } from './play.js'
import { PlayBar } from './playbar.jsx'
import { useMode } from './mode.js'
import { ICON } from './icons.jsx'
import { fieldName } from './fields_text.js'
import { go, goUniverse } from './nav.js'
import { COL, DET_RANGE, ChartCard, Legend, Meter, Plot, extent } from './charts.jsx'
import { TimeWave } from './timewave.jsx'
import { trackGeom } from './viewer_parts.jsx'
import { setPageContext } from './ask/store.js'
import './object.css'

const MAX_COLS = 14
const JPL_MATCH = 5            // arcsec: a detection "matches" JPL within this distance
const JPL_SHARE = 0.75         // the share of detections that must match
const RMS_LIMIT = 5            // arcsec: the path check's rms limit
const PLAY_HZ = 1 / 0.45
const DETECTORS = [1, 2, 3, 4, 5, 6]
const FRAME_KINDS = [['diff', '變化'], ['sci', '天空']]
const MATRIX_ROWS = [['sci', '天空'], ['ref', '參考'], ['diff', '變化']]
const KIND_TAG = { distant: '視差候選', known: '已知天體', unknown: '未確認' }
// sunlight as a 5778 K black body per unit frequency (unnormalised), divided out of the measured brightness
const C_UM = 2.998e14, H_PLANCK = 6.626e-34, K_BOLTZ = 1.381e-23, T_SUN = 5778
const sunNu = (l) => { const nu = C_UM / l, x = H_PLANCK * nu / (K_BOLTZ * T_SUN); return nu ** 3 / Math.expm1(x) }
let evidence = null            // /paper/research/evidence.json, fetched once per visit
const loadEvidence = () => (evidence ||= api('/paper/research/evidence.json').catch((e) => { evidence = null; throw e }))
const detCol = (d) => COL.det[(d - 1) % COL.det.length]
const passCol = (g) => COL.pass[g % COL.pass.length]
const clampv = (v, a, b) => Math.min(b, Math.max(a, v))
/** Colour key for the detector arrays that appear: one entry each. */
const detLegend = (ds) => [...new Set(ds)].sort().map((d) => ({ c: detCol(d), label: L(`D${d} 的偵測`, `Detection, D${d}`) }))
/** A point beyond the chart's scale, drawn as a triangle at its edge. */
const offTri = (x, y) => `M${x} ${y - 6}L${x + 6} ${y + 5}L${x - 6} ${y + 5}Z`
/** The ring round the frame on screen in the player. */
const curRing = (x, y, r = 9) => <circle cx={x} cy={y} r={r} fill="none" stroke={COL.accent} strokeWidth="2.5" />

/** The body as the model predicts it (from JPL parameters and the measured reflectance), slowly turning. */
function BodyPreview({ mover, size, className = '' }) {
  const ref = useRef()
  useEffect(() => {
    if (!mover) return
    let prev = null, dead = false
    Promise.all([import('./universe/scene.js'), import('./universe/presets.js')]).then(([{ Preview }, { predicted }]) => {
      if (dead || !ref.current) return
      try { prev = new Preview(ref.current) } catch { return }
      const pr = predicted({ ...mover, group: 'mover' })
      prev.show(pr.type, pr.p, 101 + mover.track)
    })
    return () => { dead = true; prev?.destroy() }
  }, [mover])
  if (!mover) return null
  return <canvas ref={ref} className={`body3d ${className}`} style={size ? { width: size, height: size } : undefined} aria-label="模型預測的天體外觀（3D）" />
}

// ---- the three checks, as meters with their thresholds -------------------------------------------------------

const CheckMeters = memo(function CheckMeters({ field, tr }) {
  useLanguage()
  const thr = field.cnn_threshold_prob || 0.5
  const rows = evidenceChecks(field, tr).map((c) => {
    const col = c.ok === true ? COL.good : c.ok === false ? COL.bad : COL.ink3
    if (c.key === 'psf') return { c, col, m: { value: tr.mean_p, lo: 0, hi: 1, mark: thr, text: pct(tr.mean_p) }, scale: L(`AI 平均分數，門檻 ${pct(thr)}`, `Mean AI score; threshold ${pct(thr)}`) }
    if (c.key === 'path') return { c, col, m: { value: Math.min(tr.rms_arcsec, 10), lo: 0, hi: 10, mark: RMS_LIMIT, text: `${tr.rms_arcsec}″` }, scale: L('均方根殘差，門檻 5″', 'rms residual; limit 5″') }
    if (c.key === 'jpl' && tr.jpl) return { c, col, m: { value: tr.jpl.n_match / tr.jpl.n, lo: 0, hi: 1, mark: JPL_SHARE, text: `${tr.jpl.n_match}/${tr.jpl.n}` }, scale: L('5″ 內的比例，門檻 75%', 'Share within 5″; needs 75%') }
    return { c, col, m: null, scale: c.note }
  })
  return (
    <div className="ob-checks" role="list" aria-label={L('三項檢查', 'Three checks')}>
      {rows.map(({ c, col, m, scale }) => (
        <div key={c.key} className="ob-check" role="listitem" data-ok={c.ok === true ? 'yes' : c.ok === false ? 'no' : 'na'} style={{ '--c': col }}>
          <i aria-hidden="true">{c.ok === true ? ICON.check : c.ok === false ? ICON.alert : ICON.dot}</i>
          <div className="ob-check-body">
            {m ? <Meter label={c.label} value={m.value} lo={m.lo} hi={m.hi} mark={m.mark} c={col} text={m.text} />
              : <div className="ob-check-plain"><span>{c.label}</span></div>}
            <span className="ob-check-scale">{scale}</span>
          </div>
        </div>
      ))}
    </div>
  )
})

// ---- the player and the charts that share its frame -------------------------------------------------------------

function Player({ field, mem, pb }) {
  const ref = useRef()
  const [kind, setKind] = useState('diff')
  const { k } = pb
  // a fixed window around the whole path, so the object visibly crosses it (rather than a crop that follows it)
  const box = useMemo(() => {
    const xs = mem.map((c) => c.x), ys = mem.map((c) => c.y)
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2
    const half = Math.min(Math.min(field.shape[0], field.shape[1]) / 2 - 1, Math.max(14, (Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 2) + 12))
    return { cx, cy, half }
  }, [mem, field])
  useEffect(() => {
    const cv = ref.current, c = mem[k]; if (!cv || !c) return
    const im = frameImg(field, kind, c.i)
    const draw = () => {
      const g = cv.getContext('2d'), H = field.shape[0], n = 2 * Math.round(box.half) + 1, S = cv.width / n
      g.imageSmoothingEnabled = false; g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, cv.height)
      const W = field.shape[1], hh = Math.round(box.half)
      const sx = Math.min(Math.max(Math.round(box.cx) - hh, 0), W - n), sy = Math.min(Math.max(H - 1 - Math.round(box.cy) - hh, 0), H - n)
      blitFrame(g, im, kind, sx, sy, n, n, cv.width, cv.height)
      // onion skin of earlier detections
      const P = (q) => [(q.x - sx + 0.5) * S, (H - 1 - q.y - sy + 0.5) * S]
      const [x, y] = P(c), ring = Math.max(16, 4 * S)
      for (let j = 0; j < k; j++) {
        const [px, py] = P(mem[j]); if (Math.hypot(px - x, py - y) < ring + 6) continue     // never cover the object itself
        g.globalAlpha = 0.3 + 0.6 * (j / Math.max(k, 1)); g.fillStyle = '#6ec3ff'; g.beginPath(); g.arc(px, py, 4, 0, 7); g.fill()
      }
      g.globalAlpha = 1; g.strokeStyle = '#f2e6c9'; g.lineWidth = 3; g.beginPath(); g.arc(x, y, ring, 0, 7); g.stroke()
    }
    if (ready(im)) draw(); else frameImg(field, kind, c.i, (ok) => ok && draw())
  }, [k, kind, field, mem, box])
  const c = mem[k], e = field.exposures[c.i]
  return (
    <div className="ob-player">
      <div className="ob-frame">
        <canvas ref={ref} width={680} height={680} tabIndex={0} onKeyDown={(ev) => pb.onKey(ev)} role="img" aria-label="這個天體每次被偵測到的影像，依時間播放；黃點是它之前的位置" />
        <p className="ob-frame-tag num" aria-live="off">{e.iso} UTC · <span style={{ color: DET[e.detector].c }}>D{e.detector}</span> {e.lam_um.toFixed(2)} µm</p>
      </div>
      <PlayBar pb={pb} n={mem.length} label={L('偵測依時間播放', 'Detections in time order')}>
        <div className="seg" role="group" aria-label="影像種類">
          {FRAME_KINDS.map(([m, l]) => <button key={m} aria-pressed={kind === m} onClick={() => setKind(m)}>{l}</button>)}
        </div>
      </PlayBar>
    </div>
  )
}

/** Where it went on the sky (arcsec from its first detection; east left, north up), the fitted model, and JPL. */
function SkyPath({ g, tr, k, onPick, height = 236 }) {
  const distant = tr.kind === 'distant'
  const xs = [...g.dets.map((d) => d.east), ...g.path.map((p) => p[0])], ys = [...g.dets.map((d) => d.north), ...g.path.map((p) => p[1])]
  const cur = g.dets[k]
  const pts = g.dets.map((d) => ({
    x: d.east, y: d.north, r: 9, j: d.j,
    tip: `${d.e.iso} UTC · ${distant ? L(`第 ${d.pass + 1} 輪`, `Pass ${d.pass + 1}`) : `D${d.e.detector} · ${d.e.lam_um.toFixed(2)} µm`}`,
    hint: [d.fit != null && (distant ? L(`離擬合路徑 ${d.fit.toFixed(2)}″`, `${d.fit.toFixed(2)}″ from the fitted path`) : L(`離直線 ${d.fit.toFixed(2)}″`, `${d.fit.toFixed(2)}″ from the line`)),
      d.jpl && L(`離 JPL 預測 ${d.jpl.r.toFixed(2)}″`, `${d.jpl.r.toFixed(2)}″ from JPL's prediction`), L('點一下：播放器跳到這一張', 'Click: show it in the player')].filter(Boolean).join(' · '),
  }))
  const legend = [
    ...(distant ? g.groups.map((q, j) => ({ c: passCol(j), label: L(`第 ${j + 1} 輪 · ${mjdToIso(q.t0).slice(0, 7)}`, `Pass ${j + 1} · ${mjdToIso(q.t0).slice(0, 7)}`) }))
      : detLegend(g.dets.map((d) => d.e.detector))),
    ...(g.path.length > 1 ? [{ c: distant ? COL.distant : COL.ink3, line: true, label: distant ? L('擬合的路徑（視差＋軌道運動）', 'Fitted path (parallax + orbit)') : L('等速直線擬合', 'Constant-speed fit') }] : []),
    ...(tr.jpl ? [{ c: COL.known, hollow: true, label: L('JPL 預測的位置', "JPL's predicted position") }] : []),
  ]
  return (
    <>
      <Legend items={legend} />
      <Plot equal height={height} points={pts} onPick={(p) => onPick(p.j)}
        label={L(`${trackTitle(tr)} 在天空的路徑`, `Path of ${trackTitle(tr)} on the sky`)}
        x={{ domain: extent(xs, 0.06), reverse: true, grid: true, fmt: (v) => `${v}″`, label: L('往東（角秒）', 'East (arcsec)') }}
        y={{ domain: extent(ys, 0.08), fmt: (v) => `${v}″`, label: L('往北（角秒）', 'North (arcsec)'), gutter: 54 }}>
        {({ X, Y, w, h, m }) => {
          const inside = (x, y) => x >= m.l && x <= w - m.r && y >= m.t && y <= h - m.b
          const last = g.path.at(-1), prev = g.path.at(-2)
          let head = null
          if (!distant && last && prev) {
            const ax = X(last[0]), ay = Y(last[1]), a = Math.atan2(ay - Y(prev[1]), ax - X(prev[0])), s = 9
            head = <path d={`M${ax + 4 * Math.cos(a)} ${ay + 4 * Math.sin(a)}L${ax - s * Math.cos(a - 0.45)} ${ay - s * Math.sin(a - 0.45)}L${ax - s * Math.cos(a + 0.45)} ${ay - s * Math.sin(a + 0.45)}Z`} fill={COL.ink3} />
          }
          return <>
            {g.path.length > 1 && <polyline points={g.path.map(([e, n]) => `${X(e)},${Y(n)}`).join(' ')} fill="none" stroke={distant ? COL.distant : COL.ink3} strokeOpacity={distant ? 0.75 : 1} strokeWidth="1.6" strokeDasharray="6 5" />}
            {head}
            {g.dets.map((d) => <circle key={d.j} cx={X(d.east)} cy={Y(d.north)} r={distant ? 3 : 4.2} fill={distant ? passCol(d.pass) : detCol(d.e.detector)} />)}
            {g.dets.filter((d) => d.jpl).map((d) => { const x = X(d.east - d.jpl.dx), y = Y(d.north - d.jpl.dy); return inside(x, y) && <path key={`j${d.j}`} d={`M${x - 6} ${y}L${x} ${y - 6}L${x + 6} ${y}L${x} ${y + 6}Z`} fill="none" stroke={COL.known} strokeWidth="1.5" /> })}
            {cur && curRing(X(cur.east), Y(cur.north), 10)}
          </>
        }}
      </Plot>
    </>
  )
}

/** Our position minus JPL's, for every detection, around the bull's-eye: the pale disc is one pixel, dashed 5″. */
function JplTarget({ g, k, onPick }) {
  const R = 8
  const ds = g.dets.filter((d) => d.jpl)
  const pts = ds.map((d) => ({
    x: clampv(d.jpl.dx, -R, R), y: clampv(d.jpl.dy, -R, R), r: 8, j: d.j, d, off: d.jpl.r > R,
    tip: `${d.jpl.r.toFixed(2)}″ · ${d.e.iso} UTC`,
    hint: L(`偏東 ${d.jpl.dx}″、偏北 ${d.jpl.dy}″${d.jpl.r <= 5 ? '：在 5″ 以內' : '：超過 5″，不符'}`, `${d.jpl.dx}″ east, ${d.jpl.dy}″ north${d.jpl.r <= 5 ? ': within 5″' : ': beyond 5″, no match'}`),
  }))
  const cur = pts.find((p) => p.j === k)
  return (
    <Plot square equal points={pts} onPick={(p) => onPick(p.j)} label={L('每次偵測和 JPL 預測位置的偏差', 'Offset of each detection from the JPL prediction')}
      x={{ domain: [-R, R], ticks: [-5, 0, 5], reverse: true, grid: true, fmt: (v) => `${v}″`, label: L('偏東（角秒）', 'East (arcsec)') }}
      y={{ domain: [-R, R], ticks: [-5, 0, 5], fmt: (v) => `${v}″`, label: L('偏北（角秒）', 'North (arcsec)'), gutter: 40 }}>
      {({ X, Y }) => {
        const r = (v) => Math.abs(X(v) - X(0))
        return <>
          <circle className="ob-pixel" cx={X(0)} cy={Y(0)} r={r(PIX)} />
          <circle className="ob-ring5" cx={X(0)} cy={Y(0)} r={r(JPL_MATCH)} />
          <text className="mark-label" x={X(0) + r(JPL_MATCH) * 0.72 + 4} y={Y(0) - r(JPL_MATCH) * 0.72 - 4}>5″</text>
          {pts.map((p) => p.off
            ? <path key={p.j} d={offTri(X(p.x), Y(p.y))} fill={COL.bad} />
            : <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="4.5" fill={p.d.jpl.r <= JPL_MATCH ? COL.known : COL.bad} />)}
          {cur && curRing(X(cur.x), Y(cur.y))}
        </>
      }}
    </Plot>
  )
}

/** The time axis the residual charts share: hours since the first detection, or one panel per survey pass. */
function timeAxis(g, tr) {
  if (tr.kind === 'distant') {
    return { at: (d) => d.px, axis: { domain: [0, g.groups.length], ticks: g.groups.map((_, j) => j + 0.5), fmt: (v, narrow) => { const q = g.groups[Math.floor(v)]; return q ? (narrow ? mjdToIso(q.t0).slice(2, 7) : `${mjdToIso(q.t0).slice(0, 7)} · ${q.n}`) : '' }, label: L('巡天輪次（每格一輪）', 'Survey pass (one panel each)') } }
  }
  return { at: (d) => d.h, axis: { domain: [-g.hmax * 0.03, g.hmax * 1.03], fmt: (v) => `${v}`, label: t`第一次偵測後的時數（共 ${g.hmax.toFixed(1)} 小時）` } }
}

/** One value per detection against the shared time axis, with a threshold line. */
function TimeChart({ g, tr, k, onPick, value, max = 10, line, lineLabel, colorOf, label, yLabel, height = 260, band }) {
  const ta = timeAxis(g, tr)
  const lo = 0
  const pts = g.dets.filter((d) => value(d) != null).map((d) => { const v = value(d); return { x: ta.at(d), y: clampv(v, lo, max), v, r: 8, j: d.j, d, off: Math.abs(v) > max,
    tip: `${v.toFixed(2)}″ · ${d.e.iso} UTC`, hint: `D${d.e.detector} · ${d.e.lam_um.toFixed(2)} µm${Math.abs(v) > max ? L(`（超出圖的範圍 ${max}″）`, ` (off the scale of ${max}″)`) : ''}` } })
  const cur = pts.find((p) => p.j === k)
  return (
    <Plot height={height} points={pts} onPick={(p) => onPick(p.j)} label={label}
      x={ta.axis} y={{ domain: [lo, max * 1.04], fmt: (v) => `${v}″`, label: yLabel, gutter: 44 }}>
      {({ X, Y, m, h }) => <>
        {tr.kind === 'distant' && g.groups.slice(1).map((_, j) => <line key={`s${j}`} className="grid" x1={X(j + 1)} x2={X(j + 1)} y1={m.t} y2={h - m.b} />)}
        {band != null && <><rect className="ob-pixel" x={X(ta.axis.domain[0])} width={Math.abs(X(ta.axis.domain[1]) - X(ta.axis.domain[0]))} y={Y(band)} height={Y(0) - Y(band)} />
          <text className="mark-label ob-band-label" x={X(ta.axis.domain[0]) + 8} y={Y(band) + 18}>{L('一個像素', 'one pixel')}</text></>}
        {line != null && <><line className="ob-limit" x1={X(ta.axis.domain[0])} x2={X(ta.axis.domain[1])} y1={Y(line)} y2={Y(line)} />
          <text className="mark-label" x={X(ta.axis.domain[1]) - 4} y={Y(line) - 8} textAnchor="end">{lineLabel}</text></>}
        {pts.map((p) => p.off
          ? <path key={p.j} d={offTri(X(p.x), Y(p.y))} fill={COL.bad} />
          : <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r={tr.kind === 'distant' ? 3 : 4.5} fill={colorOf(p.d, p.v)} />)}
        {cur && curRing(X(cur.x), Y(cur.y))}
      </>}
    </Plot>
  )
}

/** A distant body: its east and north offsets against time, with the fitted path; the parallax swings between passes. */
function ParallaxTime({ g, tr, k, onPick, comp }) {
  const ta = timeAxis(g, tr)
  const val = (d) => (comp === 'e' ? d.east : d.north)
  const curve = useMemo(() => {
    if (!g.at) return []
    return g.groups.map((q, j) => {
      const out = []
      for (let s = 0; s <= 24; s++) {
        const [a, dd] = g.at(q.t0 + ((q.t1 - q.t0) * s) / 24), [e, n] = tangent(a, dd, g.ra0, g.dec0)
        out.push([j + 0.08 + 0.84 * (q.t1 > q.t0 ? s / 24 : 0.5), comp === 'e' ? e : n])
      }
      return out
    })
  }, [g, comp])
  const ys = [...g.dets.map(val), ...curve.flat().map((p) => p[1])]
  const pts = g.dets.map((d) => ({ x: ta.at(d), y: val(d), r: 8, j: d.j, tip: `${val(d).toFixed(1)}″ · ${d.e.iso} UTC`, hint: L(`第 ${d.pass + 1} 輪 · 點一下：播放器跳到這一張`, `Pass ${d.pass + 1} · click: show it in the player`) }))
  const cur = pts.find((p) => p.j === k)
  return (
    <Plot height={220} points={pts} onPick={(p) => onPick(p.j)} label={comp === 'e' ? L('往東的位移對時間', 'Offset east against time') : L('往北的位移對時間', 'Offset north against time')}
      x={ta.axis} y={{ domain: extent(ys, 0.1), fmt: (v) => `${v}″`, label: comp === 'e' ? L('往東（角秒）', 'East (arcsec)') : L('往北（角秒）', 'North (arcsec)'), gutter: 54 }}>
      {({ X, Y, m, h }) => <>
        {g.groups.slice(1).map((_, j) => <line key={`s${j}`} className="grid" x1={X(j + 1)} x2={X(j + 1)} y1={m.t} y2={h - m.b} />)}
        {curve.map((c, j) => <polyline key={j} points={c.map(([x, y]) => `${X(x)},${Y(y)}`).join(' ')} fill="none" stroke={COL.distant} strokeWidth="1.6" strokeDasharray="6 5" />)}
        {g.dets.map((d) => <circle key={d.j} cx={X(ta.at(d))} cy={Y(val(d))} r="3" fill={passCol(d.pass)} />)}
        {cur && curRing(X(cur.x), Y(cur.y))}
      </>}
    </Plot>
  )
}

// ---- the deeper evidence (tabs) ---------------------------------------------------------------------------------

/** Relative reflectance from the brightness SPHEREx measured at each detection's wavelength. */
const Spectrum = memo(function Spectrum({ mover }) {
  useLanguage()
  if (!mover?.photometry?.length) return null
  const raw = mover.photometry.filter(([, f]) => f > 0).map(([l, f]) => [l, f / sunNu(l)])
  const ref = raw.filter(([l]) => l >= 0.85 && l <= 1.3).map(([, r]) => r).sort((a, b) => a - b)
  const norm = ref.length ? ref[Math.floor(ref.length / 2)] : raw.map(([, r]) => r).sort((a, b) => a - b)[Math.floor(raw.length / 2)]
  if (!norm || raw.length < 3) return null
  const y1 = Math.min(4, Math.max(2, ...raw.map(([, r]) => r / norm)) * 1.1)
  const tax = mover.sbdb?.spec_B || mover.sbdb?.spec_T
  const detOf = (l) => Math.max(1, DET_RANGE.findIndex(([a, b]) => l >= a && l < b) + 1 || 6)
  const pts = raw.map(([l, r]) => ({ x: l, y: Math.min(r / norm, y1), r: 8, tip: `${l.toFixed(2)} µm · ${(r / norm).toFixed(2)}`, hint: L(`D${detOf(l)} · 相對反射率，0.85–1.3 µm 歸一為 1`, `D${detOf(l)} · relative reflectance, 1 at 0.85–1.3 µm`) }))
  return (
    <ChartCard className="ob-wide" title="SPHEREx 量到的反射光譜"
      take={tax ? L(`往紅外變亮代表偏紅的表面；JPL 記錄的光譜分類是 ${tax}。`, `Brighter towards the infrared means a redder surface; JPL lists its spectral class as ${tax}.`) : L('往紅外變亮代表偏紅的表面；2.6 µm 以上混入它自己的熱輻射。', 'Brighter towards the infrared means a redder surface; above 2.6 µm its own heat mixes in.')}
      more={<p>{t`每一點是一次偵測的亮度除以太陽光譜，以 0.85–1.3 µm 的中位數歸一。往紅外變亮代表偏紅的表面；2.6 µm 以上會混入小行星自己的熱輻射。不同時間的偵測也受自轉與距離影響，所以這是粗略的光譜。`}{tax ? t` JPL 記錄的光譜分類：${tax}。` : ''}</p>}
      legend={[...detLegend(raw.map(([l]) => detOf(l))), { c: COL.ink3, line: true, label: L('和 0.85–1.3 µm 一樣亮', 'As bright as at 0.85–1.3 µm') }]}>
      <Plot height={300} points={pts} label="各波長的相對反射率"
        x={{ domain: [0.7, 5.2], log: true, ticks: [0.75, 1, 1.5, 2, 3, 4, 5], fmt: (v) => `${v}`, label: L('波長（µm）', 'Wavelength (µm)') }}
        y={{ domain: [0, y1], fmt: (v) => v.toFixed(1), label: L('相對反射率', 'Relative reflectance'), gutter: 40 }}>
        {({ X, Y, m }) => <>
          <rect className="ob-thermal" x={X(2.6)} y={m.t} width={X(5.2) - X(2.6)} height={Y(0) - m.t} />
          <text className="mark-label ob-thermal-label" x={X(5.2) - 8} y={m.t + 18} textAnchor="end">熱輻射開始混入</text>
          <line className="ob-ref" x1={X(0.7)} x2={X(5.2)} y1={Y(1)} y2={Y(1)} />
          {DET_RANGE.map(([a, b], d) => <rect key={d} x={X(a)} y={Y(0) - 5} width={Math.max(1, X(b) - X(a) - 1)} height="4" fill={COL.det[d]} />)}
          {pts.map((p, j) => <circle key={j} cx={X(p.x)} cy={Y(p.y)} r="4.5" fill={COL.det[detOf(p.x) - 1]} />)}
        </>}
      </Plot>
    </ChartCard>
  )
})

/** Where the object is in the field: its path over the deep image. */
const Locator = memo(function Locator({ field, mem, tr, className = '', level = 3 }) {
  useLanguage()
  const ref = useRef()
  useEffect(() => {
    const cv = ref.current, g = cv.getContext('2d'), W = field.shape[1], H = field.shape[0]
    cv.width = W * 2; cv.height = H * 2
    const im = new Image()
    im.onload = () => draw(im); im.onerror = () => draw(null)
    im.src = `/data/fields/${field.id}/deep_rgb.webp`
    function draw(img) {
      g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, cv.height)
      if (img) { g.globalAlpha = 0.75; g.imageSmoothingEnabled = false; g.drawImage(img, 0, 0, cv.width, cv.height); g.globalAlpha = 1 }
      g.strokeStyle = tr.sim ? '#ff4fd8' : tr.kind === 'distant' ? '#c08bff' : tr.known ? '#6ec3ff' : '#ffb547'; g.lineWidth = 4
      g.beginPath(); mem.forEach((c, k) => { const x = (c.x + 0.5) * 2, y = (H - 0.5 - c.y) * 2; k ? g.lineTo(x, y) : g.moveTo(x, y) }); g.stroke()
      const c0 = mem[0]; g.fillStyle = '#fff'; g.beginPath(); g.arc((c0.x + 0.5) * 2, (H - 0.5 - c0.y) * 2, 7, 0, 7); g.fill()
    }
  }, [field, mem, tr])
  return (
    <ChartCard level={level} className={`ob-locator ${className}`} title="它在這片天空的哪裡" take={t`天區寬 ${field.size_deg}°；白點是第一次偵測。`}>
      <canvas ref={ref} className="ob-locator-img" role="img" aria-label="天區影像上的軌跡位置，白點是第一次偵測" />
    </ChartCard>
  )
})

/** The evidence crops side by side. Memoised: its canvases redraw on every render (ref callbacks), and the page
 *  re-renders on every frame of the player. */
const Matrix = memo(function Matrix({ field, mem }) {
  useLanguage()
  const step = Math.max(1, Math.ceil(mem.length / MAX_COLS))
  const cols = mem.filter((_, k) => k % step === 0)
  return (
    <ChartCard className="ob-wide" title="證據並排：天空 / 參考 / 變化"
      take={L('真的移動天體：天空有、參考沒有、變化是亮點。', 'A real mover is in the sky, missing from the reference, and a bright spot in the change.')}
      more={t`每欄是一次偵測（共 ${mem.length} 次，顯示 ${cols.length} 次），21×21 像素，以最近鄰放大，同一欄的天空與參考使用相同亮度拉伸。真的移動天體：天空有、參考沒有、變化是亮點。`}>
      <div className="matrix" tabIndex={0} role="region" aria-label="證據小圖矩陣（可橫向捲動）" style={{ gridTemplateColumns: `56px repeat(${cols.length}, 112px)` }}>
        <span />
        {cols.map((c) => { const e = field.exposures[c.i]; return <span key={c.id} className="colhead">{e.iso.slice(5, 16)}<br /><span style={{ color: DET[e.detector].c }}>D{e.detector}</span> {e.lam_um.toFixed(2)}µm</span> })}
        {MATRIX_ROWS.map(([kind, label]) => [
          <span key={kind} className="rowlabel">{label}</span>,
          ...cols.map((c) => <canvas key={kind + c.id} width={112} height={112} ref={(el) => el && drawCrop(el, field, kind, c)} aria-label={`${translate(label)} · ${field.exposures[c.i].iso} UTC`} />),
        ])}
      </div>
    </ChartCard>
  )
})

function MotionTab({ g, tr, k, onPick }) {
  if (tr.kind === 'distant') {
    return (
      <ChartCard className="ob-wide" title="視差：位置隨地球公轉而移動"
        take={<>{t`擬合距離 ${tr.d_au} AU · 殘差 ${tr.rms_arcsec}″`}{tr.pm_arcsec_yr ? t` · 自行 ${Math.hypot(...tr.pm_arcsec_yr).toFixed(0)}″/年` : ''}</>}
        more="點的顏色代表不同輪巡天；虛線是用擬合的距離與自行算出的路徑（視差加上天體自身的軌道運動）。距離只對注入的模擬天體做過驗證。"
        legend={[...g.groups.map((q, j) => ({ c: passCol(j), label: L(`第 ${j + 1} 輪`, `Pass ${j + 1}`) })), { c: COL.distant, line: true, label: L('擬合的路徑', 'Fitted path') }]}>
        <div className="ob-stack">
          <ParallaxTime g={g} tr={tr} k={k} onPick={onPick} comp="e" />
          <ParallaxTime g={g} tr={tr} k={k} onPick={onPick} comp="n" />
          {g.at && <TimeChart g={g} tr={tr} k={k} onPick={onPick} height={200} value={(d) => d.fit} max={Math.max(4, Math.ceil(Math.max(...g.dets.map((d) => d.fit || 0)) * 1.1))}
            line={tr.rms_arcsec} lineLabel={L(`均方根 ${tr.rms_arcsec}″`, `rms ${tr.rms_arcsec}″`)} colorOf={(d) => passCol(d.pass)}
            label={L('每次偵測離擬合路徑的距離', 'Distance of each detection from the fitted path')} yLabel={L('離路徑（角秒）', 'Off the path (arcsec)')} />}
        </div>
      </ChartCard>
    )
  }
  if (!g.at) return null
  return (
    <ChartCard className="ob-wide" title="運動：等速直線檢查"
      take={L(`每次偵測離最佳擬合直線多遠；均方根 ${tr.rms_arcsec}″，約 ${(tr.rms_arcsec / PIX).toFixed(1)} 個像素。`, `How far each detection sits from the best-fitting straight line; rms ${tr.rms_arcsec}″, about ${(tr.rms_arcsec / PIX).toFixed(1)} pixels.`)}
      more={t`每一點是一次偵測和最佳擬合直線的距離。速度 ${tr.rate_arcsec_h}″/小時，方位角 ${tr.pa_deg}°，均方根殘差 ${tr.rms_arcsec}″。點的顏色代表偵測器。`}
      legend={[...detLegend(g.dets.map((d) => d.e.detector)), { c: COL.warn, line: true, label: '容差 8″' }]}>
      <TimeChart g={g} tr={tr} k={k} onPick={onPick} value={(d) => d.fit} max={10} line={8} lineLabel="容差 8″" colorOf={(d) => detCol(d.e.detector)}
        label="各次偵測與直線模型的偏差" yLabel={L('離直線（角秒）', 'Off the line (arcsec)')} />
    </ChartCard>
  )
}

function JplTab({ g, tr, k, onPick }) {
  const j = tr.jpl
  return (
    <ChartCard className="ob-wide" title="和 JPL 預測位置比較"
      take={j.consistent ? L(`${j.n_match}/${j.n} 次偵測在 5″ 以內，偏差沒有隨時間漂移。`, `${j.n_match} of ${j.n} detections within 5″, with no drift over time.`) : L(`只有 ${j.n_match}/${j.n} 次偵測在 5″ 以內：紅色的不符。`, `Only ${j.n_match} of ${j.n} detections within 5″: the red ones do not match.`)}
      more={j.consistent
        ? t`${j.n_match} / ${j.n} 次偵測落在 JPL 預測位置 5″ 以內，中位數偏差 ${j.median_arcsec}″（約 ${(j.median_arcsec / PIX).toFixed(2)} 個像素）。預測是以 SPHEREx 太空船本身為觀測者，由 JPL Horizons 計算。淡色圓是一個像素的大小。`
        : t`只有 ${j.n_match} / ${j.n} 次偵測落在 JPL 預測位置 5″ 以內（紅點不符）。這條軌跡很可能混入了其他天體或假訊號，「${tr.known}」這個名字只適用於藍點。`}
      legend={[{ c: COL.known, label: L('在 5″ 以內', 'Within 5″') }, { c: COL.bad, label: L('超過 5″', 'Beyond 5″') }]}>
      <TimeChart g={g} tr={tr} k={k} onPick={onPick} value={(d) => d.jpl?.r ?? null} max={10} line={JPL_MATCH} band={PIX} lineLabel="5″" colorOf={(d) => (d.jpl.r <= JPL_MATCH ? COL.known : COL.bad)}
        label={L('每次偵測離 JPL 預測位置的距離，對時間', 'Distance of each detection from the JPL prediction, against time')} yLabel={L('離 JPL（角秒）', 'Off JPL (arcsec)')} />
    </ChartCard>
  )
}

const TechTab = memo(function TechTab({ field, tr, mem, ev }) {
  useLanguage()
  const ps = mem.map((c) => c.p), nrefs = mem.map((c) => field.exposures[c.i].nref)
  const dets = [...new Set(mem.map((c) => field.exposures[c.i].detector))].sort()
  const thr = field.cnn_threshold_prob || 0.5
  return (
    <ChartCard className="ob-wide" title="技術細節"
      take={<span className="num">{tr.kind === 'distant' ? t`${mem.length} 次偵測 · ${tr.n_passes} 輪巡天 · 擬合距離 ${tr.d_au} AU` : t`${mem.length} 次偵測 · ${tr.span_h} 小時 · ${tr.rate_arcsec_h}″/小時 · 從 ${tr.start} UTC 開始`}{tr.known && <> · <a href={sbdbUrl(tr.known)} target="_blank" rel="noreferrer">JPL 小天體資料庫 ↗</a></>}</span>}>
      <div className="ob-tech">
        <Meter label={L(`AI 分數平均（範圍 ${pct(Math.min(...ps))}–${pct(Math.max(...ps))}；標記＝門檻）`, `Mean AI score (range ${pct(Math.min(...ps))}–${pct(Math.max(...ps))}; mark = threshold)`)} value={tr.mean_p} mark={thr} c={tr.mean_p >= thr ? COL.good : COL.bad} text={pct(tr.mean_p)} />
        <Meter label={L('SPHEREx 離群旗標', 'SPHEREx outlier flag')} value={tr.l2_frac || 0} c={COL.known} text={`${Math.round((tr.l2_frac || 0) * 100)}%`} />
        <Meter label={L('每次偵測的參考影像（標記＝2 張）', 'Reference images per detection (mark = 2)')} value={Math.min(...nrefs)} lo={0} hi={Math.max(10, ...nrefs)} mark={2} c={Math.min(...nrefs) >= 2 ? COL.good : COL.warn} text={`${Math.min(...nrefs)}–${Math.max(...nrefs)}`} />
        <div className="ob-dets" role="img" aria-label={t`波段：${dets.map((d) => 'D' + d).join('、')}`}>
          {DETECTORS.map((d) => <span key={d} className={dets.includes(d) ? 'on' : ''} style={{ '--c': DET[d].c }}>D{d}</span>)}
        </div>
      </div>
      {tr.blind === false && <p className="note">這條軌跡是靠 JPL 星表位置輔助才串起來的，只看 AI 分數不會出現。</p>}
      <details><summary>{t`AI 分數：平均 ${pct(tr.mean_p)}（${pct(Math.min(...ps))}–${pct(Math.max(...ps))}）`}</summary>
        <p>{ev ? t`卷積神經網路看 21×21 像素的四種圖（天空、參考、變化、星表/鬼影遮罩），判斷是不是真的點光源。它只用模擬天體訓練，在 ${ev.known_asteroids.n_known} 個真實已知小行星上的 AUROC 是 ${ev.known_asteroids.auroc.toFixed(3)}。分數經過溫度校準，是「這張小圖是不是真的點光源」的判斷，不是「這是新天體」的機率。` : '卷積神經網路看 21×21 像素的四種圖（天空、參考、變化、星表/鬼影遮罩），判斷是不是真的點光源。分數經過溫度校準，但仍只是模型的判斷。'}</p></details>
      <details><summary>{t`SPHEREx 離群旗標：${Math.round((tr.l2_frac || 0) * 100)}% 的偵測`}</summary>
        <p>SPHEREx 官方處理管線會把「和其他觀測不一致」的像素標成 MP_OUTLIER；真實的移動天體幾乎都會被標到。這個旗標沒有給 AI 看，所以是一個獨立的證據。0% 不代表一定是假的，但值得懷疑。</p></details>
      <details><summary>{t`參考影像：每次偵測 ${Math.min(...nrefs)}–${Math.max(...nrefs)} 張`}</summary>
        <p>參考影像來自同一個偵測器、同一個波長（3% 內）、至少相隔 3 小時的影像中位數。只有 1 張參考影像時，變化圖等於兩張影像相減，比較容易受到單張影像的瑕疵影響。</p></details>
      <details><summary>{t`波段：${dets.map((d) => 'D' + d).join('、')}`}</summary>
        <p>同一天體在不同偵測器（不同顏色）都被偵測到，比只出現在單一偵測器更可信。</p></details>
    </ChartCard>
  )
})

function exportRows(field, mem) {
  return mem.map((c) => { const e = field.exposures[c.i]; return { obs_id: e.obs_id, detector: e.detector, mjd: e.mjd, utc: e.iso, ra_deg: c.ra, dec_deg: c.dec, lambda_um: e.lam_um, snr: c.snr, ai_prob: c.p, l2_outlier: c.l2 } })
}
function download(name, text, type) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

export default function ObjectPage({ fieldId, trackId }) {
  useLanguage()
  const [field, setField] = useState(null)
  const [votes, setVotes] = useState({})
  const [voted, setVoted] = useState(false)
  const [ev, setEv] = useState(null)
  const [uni, setUni] = useState(undefined)          // undefined while loading, so the first screen is laid out once
  const [tab, setTab] = useState('shape')
  const research = useMode() === 'research'
  useEffect(() => { loadEvidence().then(setEv).catch(() => {}) }, [])
  useEffect(() => { setUni(undefined); api(`/data/fields/${encodeURIComponent(fieldId)}/universe.json`).then(setUni).catch(() => setUni(null)) }, [fieldId])
  useEffect(() => { getField(fieldId).then(setField).catch(() => setField(false)); api(`/api/reports/${encodeURIComponent(fieldId)}`).then(setVotes).catch(() => {}) }, [fieldId])
  const tr = field ? field.tracks[trackId] : null
  useEffect(() => { if (field && tr) document.title = `SPHEREx Sky Change · ${trackTitle(tr)}` }, [field, tr])
  // the assistant asks about this track: what kind it is, how many detections, how well they line up
  useEffect(() => {
    if (!field || !tr) return undefined
    setPageContext({ kind: 'object', id: `${fieldId}/${trackId}`, name: trackTitle(tr), ra: field.ra, dec: field.dec,
      facts: { field: fieldName(field), track_kind: tr.sim ? 'simulated planet (injected)' : tr.kind, known_as: tr.known || null, detections: tr.members.length, passes: tr.n_passes ?? null,
        rms_arcsec: tr.rms_arcsec, rate_arcsec_per_h: tr.rate_arcsec_h ?? null, distance_au: tr.d_au ?? null, mean_ai_score: tr.mean_p != null ? +tr.mean_p.toFixed(2) : null } })
    return () => setPageContext(null)
  }, [field, tr, fieldId, trackId])
  const mem = useMemo(() => tr ? tr.members.map((m) => field.cand.get(m)).sort((a, b) => field.exposures[a.i].mjd - field.exposures[b.i].mjd) : [], [field, tr])
  const g = useMemo(() => (tr && mem.length ? trackGeom(field, tr, mem) : null), [field, tr, mem])
  const frames = useMemo(() => (field ? mem.map((c) => { const e = field.exposures[c.i]; return { mjd: e.mjd, lam: e.lam_um, det: e.detector, iso: e.iso } }) : []), [field, mem])
  const nDet = useMemo(() => new Set(frames.map((f) => f.det)).size, [frames])
  const pb = usePlayback(mem.length, { hz: PLAY_HZ })
  if (field === false || (field && !tr)) return <section className="band"><h1>找不到這個天體</h1><p className="lead">這個天區裡沒有這個編號的軌跡；軌跡可能在重新分析後改變了編號。</p><button className="btn" onClick={() => go(fieldId)}>回到天空檢視器</button></section>
  if (!field || uni === undefined || !g) return <section className="band ob-loading"><p className="lead">載入中…</p></section>

  const kind = tr.kind === 'distant' ? 'distant' : tr.known ? 'known' : 'unknown'
  const v = votes[String(tr.id)]
  const isSim = !!tr.sim
  const mover = uni?.movers?.find((m) => m.track === tr.id)
  const seek = (j) => pb.seek(j)
  const verdict = isSim
    ? t`這是注入真實影像的模擬行星。管線只靠視差與軌道運動把 ${mem.length} 次偵測串起來，擬合距離 ${tr.d_au} AU（注入值 ${Math.round(tr.sim_d)} AU）。`
    : tr.kind === 'distant'
      ? t`${mem.length} 次偵測在 ${tr.n_passes} 輪巡天之間的位置，符合距離 ${tr.d_au} AU 的視差（殘差 ${tr.rms_arcsec}″）。`
      : t`${mem.length} 次偵測落在一條等速直線上，殘差 ${tr.rms_arcsec}″（約 ${(tr.rms_arcsec / PIX).toFixed(1)} 個像素）。`
  const verdict2 = tr.jpl ? (tr.jpl.consistent ? t`和 JPL 預測位置的中位數偏差 ${tr.jpl.median_arcsec}″。` : t`但只有 ${tr.jpl.n_match}/${tr.jpl.n} 次偵測和 JPL 預測位置相符，軌跡可能混入其他偵測。`) : ''
  const verdict3 = tr.blind === false ? '這條軌跡是靠 JPL 星表位置輔助才串起來的，只看 AI 分數不會出現。' : ''
  async function vote(verdict) {
    try {
      const r = await api('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ field: field.id, track: tr.id, verdict }) })
      const { _duplicate, ...rest } = r
      setVotes(rest); setVoted(_duplicate ? 'dup' : true)
    } catch { setVoted('err') }
  }
  const base = `spherex_${field.id}_track${tr.id}`
  const tabs = [['shape', '形狀'], ['motion', tr.kind === 'distant' ? '視差' : '運動'], ...(tr.jpl ? [['jpl', '和 JPL 比對']] : []),
    ...(!isSim && mover?.photometry?.length ? [['spec', '光譜']] : []), ['where', '在天空的位置'], ...(mover ? [['look', '它的樣子']] : []), ...(research ? [['tech', '技術細節'], ['data', '下載']] : [])]
  const cur = tabs.some(([k]) => k === tab) ? tab : 'shape'
  const rows = cur === 'data' ? exportRows(field, mem) : null      // only the download tab needs them
  const moved = tr.kind === 'distant' ? null : Math.round(tr.rate_arcsec_h * tr.span_h)

  // the first screen's second row: JPL's bull's-eye (or where it is in the sky) and the body the model predicts
  const jplCard = tr.jpl && (
    <ChartCard key="jpl" level={2} className="ob-tile" title="和 JPL 預測位置比較"
      take={tr.jpl.consistent ? L(`${tr.jpl.n_match}/${tr.jpl.n} 次在 5″ 內，中位數 ${tr.jpl.median_arcsec}″；淡色圓＝一個像素`, `${tr.jpl.n_match} of ${tr.jpl.n} within 5″, median ${tr.jpl.median_arcsec}″; pale disc = one pixel`) : L(`只有 ${tr.jpl.n_match}/${tr.jpl.n} 次在 5″ 內；紅色的不符`, `Only ${tr.jpl.n_match} of ${tr.jpl.n} within 5″; red ones do not match`)}>
      <JplTarget g={g} k={pb.k} onPick={seek} />
    </ChartCard>
  )
  const bodyCard = mover && (
    <figure key="body" className="ob-body">
      <BodyPreview mover={mover} className="ob-body3d" />
      <figcaption>{isSim ? '模擬行星依注入的距離建成冰巨行星。' : '模型依 JPL 的直徑、反照率、自轉與光譜分類，加上 SPHEREx 量到的反射光譜，預測它的樣子。'} <button className="link" onClick={() => goUniverse(field.id, `m${tr.id}`)}>換參數重建 →</button></figcaption>
    </figure>
  )
  const second = [jplCard, bodyCard, !(jplCard && bodyCard) && <Locator key="loc" field={field} mem={mem} tr={tr} className="ob-tile" level={2} />].filter(Boolean).slice(0, 2)

  return (
    <div className="object ob">
      <nav className="crumb" aria-label="位置"><button onClick={() => go(field.id)}>天空檢視器</button><span aria-hidden="true">/</span><button onClick={() => go(field.id)}>{fieldName(field)}</button></nav>
      <header className="ob-top">
        <div className="ob-head">
          <h1>{trackTitle(tr)}</h1>
          <p className="ob-verdict">{isSim ? <span className="tag sim">模擬資料</span> : <span className={`tag ${kind}`}>{KIND_TAG[kind]}</span>} {verdict} {verdict2} {research ? verdict3 : ''}</p>
          {/* a known small body: every SPHEREx image of it, not only this field's (#/follow, follow.jsx) */}
          {tr.known && !isSim && <p className="ob-verdict"><a className="btn small" href={`#/follow/${encodeURIComponent((tr.known.match(/^(\d+ [^(]+?)\s*\(/) || tr.known.match(/^(\d+)\s*\(/) || tr.known.match(/\(([^)]+)\)/) || [0, tr.known])[1])}`}>{L('跟著它看 SPHEREx 拍到它的每一張影像 →', 'Follow it through every SPHEREx image of it →')}</a></p>}
        </div>
        <CheckMeters field={field} tr={tr} />
      </header>

      <div className="ob-stage">
        <div className="ob-left">
          <Player field={field} mem={mem} pb={pb} />
          <ChartCard level={2} className="ob-when" title={L('每次偵測的時間和波長', 'When, and at what wavelength, each detection was made')}
            take={L(`${mem.length} 次偵測，${nDet} 個偵測器；白圈是播放中的那張。`, `${mem.length} detections on ${nDet} detectors; the ring is the frame in the player.`)}>
            <TimeWave frames={frames} current={pb.k} onPick={(_, j) => seek(j)} height={170} hint={L('點一下：播放器跳到這一張', 'Click: show it in the player')} />
          </ChartCard>
        </div>
        <div className="ob-right">
          <ChartCard className="ob-wide ob-path" level={2}
            title={tr.kind === 'distant' ? '視差：位置隨地球公轉而移動' : tr.jpl ? L('它怎麼走：實測對 JPL 預測', 'How it moved: measured against JPL') : L('它怎麼走', 'How it moved')}
            take={tr.kind === 'distant'
              ? <>{t`擬合距離 ${tr.d_au} AU · 殘差 ${tr.rms_arcsec}″`}{tr.pm_arcsec_yr ? t` · 自行 ${Math.hypot(...tr.pm_arcsec_yr).toFixed(0)}″/年` : ''}</>
              : L(`${tr.span_h} 小時走了 ${moved}″（${tr.rate_arcsec_h}″/小時）${tr.jpl ? '；◇ 是 JPL 預測它該在的位置' : '；虛線是等速直線'}。`, `${moved}″ in ${tr.span_h} h (${tr.rate_arcsec_h}″/h)${tr.jpl ? "; ◇ is where JPL predicts it" : '; dashed: a constant-speed line'}.`)}
            >
            <SkyPath g={g} tr={tr} k={pb.k} onPick={seek} />
          </ChartCard>
          {second}
          {isSim && <p className="ob-wide note sim ob-simnote">這是我們注入的模擬行星，用來檢驗方法；它不是真實的天體，也不是發現。注入和擬合都包含行星自身的軌道運動。</p>}
          <section className="ob-wide ob-vote" aria-label={L('你的判斷', 'Your call')}>
            <span className="ob-vote-q">這看起來像真的移動天體嗎？</span>
            <div className="vote">
              <button className="btn small real" onClick={() => vote('real')} disabled={!!voted}>真的</button>
              <button className="btn small artifact" onClick={() => vote('artifact')} disabled={!!voted}>假訊號</button>
              <button className="btn small" onClick={() => vote('unsure')} disabled={!!voted}>不確定</button>
            </div>
            <small className="muted num">{voted === 'err' ? '送出失敗，請稍後再試。' : voted === 'dup' ? '你已經投過這一個了。' : null}{v ? t`${voted === true ? '謝謝！' : ''}目前：真的 ${v.real} · 假訊號 ${v.artifact} · 不確定 ${v.unsure}` : voted ? '' : '投票只用來排序候選，不會把任何東西標成已確認。'}</small>
          </section>
        </div>
      </div>

      <section className="evidence ob-evidence" aria-label="為什麼相信它">
        <h2>為什麼相信它</h2>
        <div className="otabs" role="tablist">
          {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={cur === k} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        <div className="ob-panel">
          {cur === 'shape' && <Matrix field={field} mem={mem} />}
          {cur === 'motion' && <MotionTab g={g} tr={tr} k={pb.k} onPick={seek} />}
          {cur === 'jpl' && <JplTab g={g} tr={tr} k={pb.k} onPick={seek} />}
          {cur === 'spec' && <Spectrum mover={mover} />}
          {cur === 'where' && <Locator field={field} mem={mem} tr={tr} className="ob-wide ob-where" />}
          {cur === 'look' && (
            <ChartCard className="ob-wide ob-look" title="模型預測它長什麼樣子"
              take={isSim ? '模擬行星依注入的距離建成一顆冰巨行星。' : L('依 JPL 的直徑、反照率、自轉、光譜分類和 SPHEREx 的光譜斜率建成；可以換參數重建。', "Built from JPL's diameter, albedo, rotation and spectral class with SPHEREx's spectral slope; you can rebuild it with other values.")}
              more={isSim ? null : '我們依 JPL 記錄的直徑、反照率、自轉週期與光譜分類，加上 SPHEREx 量到的反射光譜斜率，預測這顆小行星的顏色、坑洞和形狀，再用 3D 把它建出來；也可以換一個預設或拖動參數重建。'}>
              <div className="ob-look-grid">
                <BodyPreview mover={mover} className="ob-look3d" />
                <div>
                  {mover?.preset && <dl className="kv">{Object.entries(mover.preset).filter(([, x]) => x != null && typeof x !== 'object').slice(0, 6).map(([key, x]) => [<dt key={'k' + key}>{key}</dt>, <dd key={'v' + key}>{String(x)}</dd>])}</dl>}
                  <button className="btn primary" onClick={() => goUniverse(field.id, `m${tr.id}`)}>在星體重建裡打開它 →</button>
                </div>
              </div>
            </ChartCard>
          )}
          {cur === 'tech' && <TechTab field={field} tr={tr} mem={mem} ev={ev} />}
          {cur === 'data' && (
            <ChartCard className="ob-wide" title="下載量測" take="ADES 草稿是依 MPC ADES 欄位排好的文字，但天文台代碼與太空船位置欄位需要依 MPC 規定補上，不能直接投稿。">
              <div className="toolbar">
                <button className="btn small" onClick={() => download(`${base}.json`, JSON.stringify({ field: field.id, track: tr, detections: rows }, null, 1), 'application/json')}>JSON</button>
                <button className="btn small" onClick={() => download(`${base}.csv`, [Object.keys(rows[0]).join(','), ...rows.map((r) => Object.values(r).join(','))].join('\n'), 'text/csv')}>CSV</button>
                <button className="btn small" onClick={() => download(`${base}_ades_draft.psv`, adesDraft(field, tr, rows), 'text/plain')}>ADES 草稿</button>
              </div>
            </ChartCard>
          )}
        </div>
      </section>
    </div>
  )
}

function adesDraft(field, tr, rows) {
  const head = '# version=2022\n# DRAFT - stn, astCat and the space-based sys/ctr/pos fields must be completed per MPC rules\npermID |provID     |trkSub  |mode|stn |obsTime                 |ra          |dec         |astCat|band|remarks'
  const trk = `SX${field.id.slice(0, 3).toUpperCase()}${tr.id}`.slice(0, 8).padEnd(8)
  const lines = rows.map((r) => {
    const t0 = mjdDate(r.mjd).toISOString().replace('Z', '').slice(0, 23) + 'Z'
    return `${(tr.known?.match(/^(\d+)\s/)?.[1] || '').padEnd(7)}|${''.padEnd(11)}|${trk}|CCD |XXX |${t0.padEnd(24)}|${r.ra_deg.toFixed(6).padStart(12)}|${(r.dec_deg >= 0 ? '+' : '') + r.dec_deg.toFixed(6)}|????  |D${r.detector}  |SPHEREx L2 ${r.obs_id}`
  })
  return [head, ...lines].join('\n') + '\n'
}
