// Parts of the sky viewer that do not depend on its state: the cards of the side panel (a clicked point, a star, the
// selected object, a loose AI candidate), the name tag on a moving object, the first-visit hint bubble.
import { memo, useEffect, useMemo, useState } from 'react'
import { t } from '@sx/i18n/core.js'
import { DET, L, PIX, api, drawCrop, evidenceChecks, mjdToIso, pct, tangent, trackTitle } from './lib.js'
import { Checks } from './checks.jsx'
import { Bars, COL, Plot, extent } from './charts.jsx'
import { layoutFrames } from './timewave.jsx'
import { ICON } from './icons.jsx'
import { fieldDesc } from './fields_text.js'
import { go, goUniverse } from './nav.js'

export const trackColor = (tr) => (tr.kind === 'distant' ? '#c08bff' : tr.known ? '#6ec3ff' : '#ffb547')
// A track's detections in exposure order. Fields are immutable once loaded, so the list is built once per track and
// shared (callers only read it); the viewer asks for it on every drawn frame.
const memCache = new WeakMap()
export const membersOf = (field, tr) => {
  let e = memCache.get(tr)
  if (!e || e.f !== field) memCache.set(tr, (e = { f: field, m: tr.members.map((m) => field.cand.get(m)).sort((a, b) => a.i - b.i) }))
  return e.m
}
/** The AI score at which a detection may join a track. */
export const pLink = (field) => field.p_link || 0.5
const DETS = [1, 2, 3, 4, 5, 6]

/** One plain sentence for a track. */
export function plain(tr) {
  if (tr.sim) return t`注入真實影像的模擬天體；管線靠視差與軌道運動找回，擬合距離 ${tr.d_au} AU`
  if (tr.kind === 'distant') return t`${tr.n_passes} 輪巡天之間只靠視差移動，擬合距離 ${tr.d_au} AU`
  const moved = tr.rate_arcsec_h * tr.span_h
  return t`${tr.span_h} 小時內移動了 ${Math.round(moved)}″，約 ${Math.round(moved / PIX)} 個像素`
}

// ---- a track as numbers to draw (shared with the object page) ----------------

/**
 * Per-detection geometry of a track, in time order: offsets on the sky (arcsec east / north of the first
 * detection), hours since the first detection, the survey pass (panel layout of timewave.jsx), the distance from the
 * fitted model (a constant-speed line, or the parallax + orbit path of a distant body) and JPL's offset
 * (ours minus JPL, arcsec east / north) where JPL Horizons has one. `path` is the model on the sky.
 */
export function trackGeom(field, tr, mem) {
  const ex = field.exposures
  if (!mem?.length) return null
  const ms = [...mem].sort((a, b) => ex[a.i].mjd - ex[b.i].mjd)
  const ra0 = ms[0].ra, dec0 = ms[0].dec, t0 = ex[ms[0].i].mjd
  const m = tr.model
  let at = null
  if (m?.mjd?.length > 1) {
    at = (mjd) => {
      let k = m.mjd.findIndex((v) => v >= mjd)
      if (k < 0) k = m.mjd.length - 1
      if (k < 1) k = 1
      const f = (mjd - m.mjd[k - 1]) / (m.mjd[k] - m.mjd[k - 1] || 1)
      let da = m.ra[k] - m.ra[k - 1]; if (da > 180) da -= 360; if (da < -180) da += 360
      return [m.ra[k - 1] + da * f, m.dec[k - 1] + (m.dec[k] - m.dec[k - 1]) * f]
    }
  } else if (m && m.dra_dt != null) at = (mjd) => [m.ra0 + m.dra_dt * (mjd - m.mjd0), m.dec0 + m.ddec_dt * (mjd - m.mjd0)]
  const lay = layoutFrames(ms.map((c) => ({ mjd: ex[c.i].mjd, lam: ex[c.i].lam_um, det: ex[c.i].detector })), null)
  const byJ = new Map(lay.fs.map((f) => [f.j, f]))
  const jres = new Map((tr.jpl?.resid || []).map(([id, dx, dy]) => [id, { dx, dy, r: Math.hypot(dx, dy) }]))
  const dets = ms.map((c, j) => {
    const e = ex[c.i], [east, north] = tangent(c.ra, c.dec, ra0, dec0), f = byJ.get(j)
    let fit = null
    if (at) { const [a, d] = at(e.mjd); fit = Math.hypot(...tangent(c.ra, c.dec, a, d)) }
    return { j, c, e, east, north, h: (e.mjd - t0) * 24, fit, jpl: jres.get(c.id) || null, pass: f?.g ?? 0, px: f?.x ?? 0.5 }
  })
  const path = []
  if (at && tr.kind === 'distant' && m.mjd) m.mjd.forEach((_, k) => path.push(tangent(m.ra[k], m.dec[k], ra0, dec0)))
  else if (at) { const tb = ex[ms.at(-1).i].mjd; for (let k = 0; k <= 12; k++) { const [a, d] = at(t0 + ((tb - t0) * k) / 12); path.push(tangent(a, d, ra0, dec0)) } }
  return { dets, path, groups: lay.groups, at, ra0, dec0, t0, hmax: Math.max(...dets.map((d) => d.h), 1e-3) }
}

/** The direction it travels in the image (north up, east left, as the stage draws it) and, by its length, how fast. */
export const TrackGlyph = memo(function TrackGlyph({ field, tr, size = 40 }) {
  const mem = membersOf(field, tr)
  const o = size / 2, R = size / 2 - 4, col = trackColor(tr)
  if (mem.length < 2) return null
  let body
  if (tr.kind === 'distant') {
    // the measured positions themselves, scaled to fit: the back-and-forth of the parallax between passes
    const xs = mem.map((c) => c.x), ys = mem.map((c) => c.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
    const k = (2 * R - 4) / Math.max(x1 - x0, y1 - y0, 1e-6)
    const P = (c) => [o + (c.x - (x0 + x1) / 2) * k, o - (c.y - (y0 + y1) / 2) * k]
    body = <>
      <polyline points={mem.map((c) => P(c).join(',')).join(' ')} fill="none" stroke={col} strokeOpacity=".55" strokeWidth="1.5" />
      {mem.filter((_, j) => j % Math.max(1, Math.floor(mem.length / 24)) === 0).map((c) => { const [x, y] = P(c); return <circle key={c.id} cx={x} cy={y} r="1.6" fill={col} /> })}
    </>
  } else {
    const a = mem[0], b = mem.at(-1), dx = b.x - a.x, dy = b.y - a.y, n = Math.hypot(dx, dy) || 1
    // 1″/h is the shortest arrow, 60″/h and faster the longest (log scale)
    const f = Math.min(1, Math.max(0, Math.log(Math.max(tr.rate_arcsec_h || 1, 1)) / Math.log(60)))
    const len = 5 + (R - 5) * f, ux = dx / n, uy = -dy / n
    const x1 = o - ux * len, y1 = o - uy * len, x2 = o + ux * len, y2 = o + uy * len, ang = Math.atan2(uy, ux), h = 6
    body = <>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={col} strokeWidth="2.2" strokeLinecap="round" />
      <path d={`M${x2 + ux * 2} ${y2 + uy * 2}L${x2 - h * Math.cos(ang - 0.5)} ${y2 - h * Math.sin(ang - 0.5)}L${x2 - h * Math.cos(ang + 0.5)} ${y2 - h * Math.sin(ang + 0.5)}Z`} fill={col} />
    </>
  }
  return (
    <svg className="vglyph" width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      <circle className="vglyph-ring" cx={o} cy={o} r={R + 2} />
      {body}
    </svg>
  )
})

/** The three evidence checks as three marks: filled green passed, red failed, hollow not applicable. */
export const CheckPips = memo(function CheckPips({ field, tr }) {
  const cs = useMemo(() => evidenceChecks(field, tr), [field, tr])
  const say = cs.map((c) => `${c.label}: ${c.ok === true ? '✓' : c.ok === false ? '✗' : '–'}`).join(' · ')
  return (
    <svg className="vpips" width={cs.length * 12} height="12" viewBox={`0 0 ${cs.length * 12} 12`} role="img" aria-label={say}>
      <title>{say}</title>
      {cs.map((c, k) => c.ok == null
        ? <circle key={c.key} cx={6 + k * 12} cy="6" r="3.6" fill="none" stroke={COL.ink3} strokeWidth="1.4" />
        : <circle key={c.key} cx={6 + k * 12} cy="6" r="4.4" fill={c.ok ? COL.good : COL.bad} />)}
    </svg>
  )
})

/**
 * The selected object's own chart: a mover, how far it has gone against the hours (on one straight line = constant
 * speed); a distant body, where it sat on the sky in each survey pass with the fitted parallax path. The image on
 * the stage is ringed; a click shows that detection's image (or the nearest one playing).
 */
export function TrackChart({ field, tr, current, frames, onPick }) {
  const g = useMemo(() => trackGeom(field, tr, membersOf(field, tr)), [field, tr])
  if (!g || g.dets.length < 2) return null
  const playing = new Set(frames || [])
  const cur = g.dets.find((d) => d.c.i === current)
  const hintOf = (d) => (frames && !playing.has(d.c.i) ? L('不在目前播放的偵測器；點一下跳到時間最近的那張', 'Not in the detector now playing; click for the nearest image') : L('點一下：看這張影像', 'Click: show this image'))
  if (tr.kind === 'distant') {
    const xs = [...g.dets.map((d) => d.east), ...g.path.map((p) => p[0])], ys = [...g.dets.map((d) => d.north), ...g.path.map((p) => p[1])]
    const pts = g.dets.map((d) => ({ x: d.east, y: d.north, r: 7, d, tip: `${L(`第 ${d.pass + 1} 輪`, `Pass ${d.pass + 1}`)} · ${d.e.iso} UTC`, hint: hintOf(d) }))
    return (
      <div className="vchart">
        <Plot equal height={168} points={pts} onPick={onPick ? (p) => onPick(p.d.c.i) : undefined}
          label={L(`${trackTitle(tr)} 在各輪巡天的位置和擬合的視差路徑`, `${trackTitle(tr)}: position in each survey pass and the fitted parallax path`)}
          x={{ domain: extent(xs, 0.1), reverse: true, fmt: (v) => `${v}″`, grid: true }} y={{ domain: extent(ys, 0.1), fmt: (v) => `${v}″`, gutter: 52 }}>
          {({ X, Y }) => <>
            {g.path.length > 1 && <polyline points={g.path.map(([e, n]) => `${X(e)},${Y(n)}`).join(' ')} fill="none" stroke={COL.distant} strokeOpacity=".7" strokeWidth="1.5" strokeDasharray="5 4" />}
            {g.dets.map((d) => <circle key={d.j} cx={X(d.east)} cy={Y(d.north)} r="2.6" fill={COL.pass[d.pass % COL.pass.length]} fillOpacity={frames && !playing.has(d.c.i) ? 0.35 : 0.95} />)}
            {cur && <circle cx={X(cur.east)} cy={Y(cur.north)} r="7" fill="none" stroke={COL.accent} strokeWidth="2" />}
          </>}
        </Plot>
        <p className="vchart-cap">{L('顏色＝巡天輪次，虛線＝擬合的視差路徑，東在左', 'Colour = survey pass; dashed = fitted parallax path; east left')}</p>
      </div>
    )
  }
  const moved = (d) => Math.hypot(d.east, d.north)
  const ys = g.dets.map(moved), rate = tr.rate_arcsec_h || 0
  const y0 = ys.reduce((s, y, k) => s + y - rate * g.dets[k].h, 0) / ys.length
  const pts = g.dets.map((d) => ({ x: d.h, y: moved(d), r: 7, d, tip: `${d.e.iso} UTC · D${d.e.detector}`, hint: `${L(`已移動 ${Math.round(moved(d))}″`, `moved ${Math.round(moved(d))}″`)} · ${hintOf(d)}` }))
  return (
    <div className="vchart">
      <Plot height={152} points={pts} onPick={onPick ? (p) => onPick(p.d.c.i) : undefined}
        label={L(`${trackTitle(tr)}：每次偵測離第一次的距離，對時間`, `${trackTitle(tr)}: distance from the first detection against time`)}
        x={{ domain: [-g.hmax * 0.04, g.hmax * 1.04], fmt: (v) => `${v}`, label: L('第一次偵測後的小時數', 'Hours since the first detection') }}
        y={{ domain: [0, Math.max(...ys) * 1.08 || 1], fmt: (v) => `${v}″`, gutter: 52 }}>
        {({ X, Y }) => <>
          <line x1={X(0)} y1={Y(Math.max(0, y0))} x2={X(g.hmax)} y2={Y(Math.max(0, y0 + rate * g.hmax))} stroke={COL.ink3} strokeWidth="1.5" strokeDasharray="5 4" />
          {g.dets.map((d) => <circle key={d.j} cx={X(d.h)} cy={Y(moved(d))} r="3.6" fill={COL.det[(d.e.detector - 1) % 6]} fillOpacity={frames && !playing.has(d.c.i) ? 0.35 : 0.95} />)}
          {cur && <circle cx={X(cur.h)} cy={Y(moved(cur))} r="7.5" fill="none" stroke={COL.accent} strokeWidth="2" />}
        </>}
      </Plot>
      <p className="vchart-cap">{L(`在虛線上＝等速移動（${rate}″/小時）`, `On the dashed line = constant speed (${rate}″/h)`)}</p>
    </div>
  )
}

// ---- side panel ------------------------------------------------------------

export function Strip({ field, track, n }) {
  const mem = membersOf(field, track)
  const step = n ? Math.max(1, Math.floor(mem.length / n)) : 1
  const pick = n ? mem.filter((_, k) => k % step === 0).slice(0, n) : mem
  return <span className={`strip ${n ? '' : 'all'}`} {...(n ? {} : { tabIndex: 0, role: 'img', 'aria-label': t`${pick.length} 張偵測小圖（可橫向捲動）` })}>{pick.map((c) => <canvas key={c.id} width={63} height={63} ref={(el) => el && drawCrop(el, field, 'sci', c)} aria-hidden="true" />)}</span>
}

/** What a clicked point is, in plain words, from /api/probe. */
export function verdictOf(field, r) {
  const tr = r.track ? field.tracks[r.track.id] : null
  if (tr) {
    if (tr.sim) return { kind: 'sim', head: '這是注入的模擬行星', body: t`它屬於一條跨 ${tr.n_passes} 輪巡天的視差軌跡，擬合距離 ${tr.d_au} AU。這是我們放進真實影像的測試，不是發現。` }
    if (tr.kind === 'distant') return { kind: 'planet', head: '可能是遠方的天體', body: t`它屬於一條符合視差的軌跡，擬合距離 ${tr.d_au} AU。需要後續觀測才能確認。` }
    if (tr.known) return { kind: 'known', head: t`這是小行星 ${tr.known}`, body: t`它在 ${tr.span_h} 小時內移動，速度 ${tr.rate_arcsec_h}″/小時：太快了，不可能是遠方的行星。` }
    return { kind: 'unknown', head: '這是一個移動中的天體（未確認）', body: t`速度 ${tr.rate_arcsec_h}″/小時，在太陽系內側移動，比較像小行星而不是遠方的行星。` }
  }
  const d = r.distant
  if (d?.ok) return { kind: 'planet', head: '可能是遠方的天體', body: t`以這個點出發，${d.n_passes} 輪巡天裡的偵測符合同一個距離的視差加上軌道運動：約 ${d.d_au} AU，殘差 ${d.rms_arcsec}″。這只是候選，需要後續觀測確認。` }
  if (r.here && r.here.p >= pLink(field)) {
    if (r.same_spot.passes >= 2) return { kind: 'static', head: '不是行星：它不會動', body: t`同一個位置在 ${r.same_spot.passes} 輪巡天都亮起來，像是會變亮的恆星或相減留下的殘差。行星會因視差在巡天之間移動。` }
    if (d?.reason === 'few_passes') return { kind: 'open', head: '還無法判斷', body: t`這片天空只有 ${d.n_passes_field} 輪巡天；要分開距離和軌道運動，至少需要三輪。` }
    return { kind: 'single', head: '不像行星', body: '這是一次可信的偵測，但在其他巡天輪次找不到符合視差的搭檔，也沒有串成軌跡。可能是短暫的變化，或太暗而沒被其他影像偵測到。' }
  }
  if (r.here) return { kind: 'bogus', head: '多半是假訊號', body: t`這裡有一個變化，但 AI 認為它像點光源的機率只有 ${pct(r.here.p)}。` }
  if (r.source) return { kind: 'star', head: r.source.kind === 'galaxy' ? '這是一個星系' : '這是一顆恆星', body: r.source.kind === 'galaxy' ? '它的光譜比較像星系（冪律），不會動，相減之後就消失了。' : (r.source.distance_pc ? t`光譜擬合溫度約 ${r.source.T} K，若是主序星距離約 ${Math.round(r.source.distance_pc)} 秒差距。恆星不會在影像之間移動，相減之後就消失了。` : t`光譜擬合溫度約 ${r.source.T} K。恆星不會在影像之間移動，相減之後就消失了。`) }
  return { kind: 'none', head: '這裡在這張影像沒有變化', body: '換一張影像（播放或時間軸）再點一次，或點有亮點的地方。' }
}

export function SourceCard({ field, src, onClose, onProbe }) {
  const [Spec, setSpec] = useState(null)
  useEffect(() => { import('./universe/Universe.jsx').then((m) => setSpec(() => m.Spectrum)) }, [])
  const star = src.kind !== 'galaxy'
  return (
    <section className="now probe v-star" aria-live="polite">
      <p className="now-k">{star ? '恆星' : '星系候選'} <button className="link" onClick={onClose}>關閉</button></p>
      <h2>{star ? t`一顆約 ${Math.round(src.fit.T)} K 的恆星` : '一個星系候選'}</h2>
      <p>{star ? (src.distance_pc ? t`模型從它的 SPHEREx 光譜判定：黑體溫度約 ${Math.round(src.fit.T)} K；若是主序星，距離約 ${Math.round(src.distance_pc)} 秒差距。它不會在影像之間移動，所以不是行星。` : t`模型從它的 SPHEREx 光譜判定：黑體溫度約 ${Math.round(src.fit.T)} K。它不會在影像之間移動，所以不是行星。`) : '它的光譜比較像冪律而不是黑體，像是遙遠的星系；不會移動，所以不是行星。'}</p>
      {Spec && <Spec b={{ group: 'source', src }} />}
      <div className="probe-actions">
        <button className="btn primary small" onClick={() => goUniverse(field.id, `s${src.id}`)}>看模型把它建成什麼樣子 →</button>
        <button className="btn small" onClick={() => onProbe(src.x, src.y)}>檢查這個位置</button>
      </div>
    </section>
  )
}

export function ProbeCard({ field, probe, onClose, onSelect }) {
  if (probe === 'loading') return <section className="now probe"><p className="now-k">檢查這個點</p><h2>分析中…</h2></section>
  if (probe.error) return <section className="now probe"><p className="now-k">檢查這個點</p><h2>無法檢查</h2><p>{probe.error}</p><button className="link" onClick={onClose}>關閉</button></section>
  const v = verdictOf(field, probe)
  const checks = [
    { ok: probe.here ? probe.here.p >= pLink(field) : null, label: probe.here ? t`這張影像有偵測（AI ${pct(probe.here.p)}）` : '這張影像在這裡沒有偵測' },
    { ok: probe.same_spot.passes >= 2 ? false : probe.here ? true : null, label: probe.same_spot.passes >= 2 ? t`同一位置出現在 ${probe.same_spot.passes} 輪巡天（不會動）` : '沒有固定出現在同一位置' },
    { ok: probe.distant ? probe.distant.ok : probe.track?.kind === 'distant' ? true : null,
      label: probe.distant?.ok || probe.track?.kind === 'distant' ? '符合視差＋軌道運動（行星的特徵）' : probe.distant ? '找不到符合視差的搭檔' : '沒有做視差測試（需要可信的未知偵測）' },
  ]
  return (
    <section className={`now probe v-${v.kind}`} aria-live="polite">
      <p className="now-k">檢查這個點 <button className="link" onClick={onClose}>關閉</button></p>
      <h2>{v.head}</h2>
      <p>{v.body}</p>
      <ul className="checks">{checks.map((c, k) => <li key={k} className={c.ok === true ? 'ok' : c.ok === false ? 'no' : 'na'}><i aria-hidden="true">{c.ok === true ? ICON.check : c.ok === false ? ICON.alert : ICON.dot}</i><span><b>{c.label}</b></span></li>)}</ul>
      <div className="probe-actions">
        {probe.track && <button className="btn primary small" onClick={() => onSelect(probe.track.id)}>選取這個天體</button>}
        {probe.source && <button className="btn small" onClick={() => goUniverse(field.id, `s${probe.source.id}`)}>看它的光譜與樣子 →</button>}
        {probe.track && field.tracks[probe.track.id].kind === 'fast' && <button className="btn small" onClick={() => goUniverse(field.id, `m${probe.track.id}`)}>看模型預測它的樣子 →</button>}
      </div>
      <p className="hint">判斷行星的方法：遠方的行星幾乎不動，但會隨地球繞太陽在巡天之間來回擺動（視差），再加上自己緩慢的軌道運動；至少要三輪巡天才分得開。</p>
    </section>
  )
}

export const KIND_LABEL = { sim: '模擬', distant: '遠距候選', known: '已知', unknown: '未確認' }
export const kindOf = (tr) => (tr.sim ? 'sim' : tr.kind === 'distant' ? 'distant' : tr.known ? 'known' : 'unknown')

/** A small speech bubble that teaches one step by pointing at the real control. */
export function Hint({ children, onSkip, onNext, next = '下一步', className = '' }) {
  return (
    <div className={`vhint ${className}`} role="note">
      <p>{children}</p>
      <div>{onNext && <button className="link" onClick={onNext}>{next}</button>}{onSkip && <button className="link muted" onClick={onSkip}>略過導覽</button>}</div>
    </div>
  )
}

/** The name tag that sits on a moving object in the sky (3D and image views). */
export const ObjLabel = memo(function ObjLabel({ tr, on, hint, onPick, onSkip }) {
  const kind = kindOf(tr)
  return (
    <span className={`olabel ${kind} ${on ? 'on' : ''} ${hint ? 'pulse' : ''}`}>
      <button onClick={(e) => { e.stopPropagation(); onPick(tr.id) }} onPointerDown={(e) => e.stopPropagation()} aria-label={t`選取 ${trackTitle(tr)}`}>
        <i aria-hidden="true" /><span>{tr.known ? tr.known.replace(/\s*\(.*\)/, '') : trackTitle(tr)}</span>
      </button>
      {hint && <Hint className="at-label" onSkip={onSkip}>{tr.known || tr.sim ? L('這顆在動，點它看看', 'This one moves. Click it.') : L('這個可能在動（未確認），點它看證據', 'This one may be moving (unconfirmed). Click it for the evidence.')}</Hint>}
    </span>
  )
})

/** One row of the object list: a glyph of its track (direction; length = speed), name, rate, the three checks as
 *  marks, status. Several tracks of the same known body share a row. */
export const Row = memo(function Row({ field, group, sel, onSelect, onHover, glow }) {
  const tr = group.find((g) => g.id === sel) || group[0]
  const on = group.some((g) => g.id === sel)
  const kind = kindOf(tr)
  const n = group.reduce((s, g) => s + g.members.length, 0)
  const sub = tr.kind === 'distant'
    ? L(`${tr.d_au} AU · ${tr.n_passes} 輪巡天 · ${n} 次偵測`, `${tr.d_au} AU · ${tr.n_passes} passes · ${n} detections`)
    : L(`${tr.rate_arcsec_h}″/小時 · ${n} 次偵測`, `${tr.rate_arcsec_h}″/h · ${n} detections`)
  return (
    <li className={`tcard ${kind} ${on ? 'on' : ''} ${glow ? 'glow' : ''}`} onMouseEnter={() => onHover(tr.id)} onMouseLeave={() => onHover(null)}>
      <button className="thead vrow" onClick={() => onSelect(on ? null : tr.id)} aria-pressed={on}>
        {field ? <TrackGlyph field={field} tr={tr} /> : <i className="dot" style={{ background: trackColor(tr) }} aria-hidden="true" />}
        <span className="vrow-text">
          <span className="tname">{trackTitle(tr)}{group.length > 1 && <span className="segs">{t` · ${group.length} 段`}</span>}</span>
          <span className="vrow-sub num">{sub}</span>
        </span>
        <span className="vrow-end">
          <span className={`badge ${kind}`}>{KIND_LABEL[kind]}</span>
          {field && <CheckPips field={field} tr={tr} />}
        </span>
      </button>
    </li>
  )
})

/** Everything about the selected object, once: verdict, the three checks, its detections, the way to the evidence. */
export function Detail({ field, group, sel, research, onSelect, onClose, hint, onHintNext, onSkip, current, frames, onSeek }) {
  const tr = field.tracks[sel]
  const kind = kindOf(tr)
  return (
    <section className={`vdetail ${kind}`} aria-label="現在在看什麼" aria-live="polite">
      <p className="now-k"><span>{{ sim: '模擬行星', distant: '遠距候選', known: '已知小行星', unknown: '未確認的移動天體' }[kind]}</span>
        <button className="iconbtn small" onClick={onClose} aria-label="取消選取">{ICON.close}</button></p>
      <h2>{trackTitle(tr)}</h2>
      <TrackChart field={field} tr={tr} current={current} frames={frames} onPick={onSeek} />
      <p className="plain">{plain(tr)}</p>
      {group.length > 1 && (
        <div className="seg segs-pick" role="group" aria-label="選擇軌跡段">
          {group.map((g, k) => <button key={g.id} aria-pressed={g.id === tr.id} onClick={() => onSelect(g.id)}>{t`第 ${k + 1} 段`}</button>)}
        </div>
      )}
      <Checks field={field} tr={tr} compact />
      <Strip field={field} track={tr} n={5} />
      {research && <dl className="kv">
        <dt>偵測次數</dt><dd>{tr.members.length}</dd>
        {tr.kind === 'distant'
          ? <><dt>擬合距離</dt><dd>{tr.d_au} AU</dd><dt>巡天輪數</dt><dd>{tr.n_passes}</dd></>
          : <><dt>速度</dt><dd>{t`${tr.rate_arcsec_h}″/小時`}</dd><dt>時間跨度</dt><dd>{t`${tr.span_h} 小時`}</dd></>}
        <dt>AI 信心度</dt><dd>{pct(tr.mean_p)}</dd>
        {tr.kind !== 'distant' && <><dt>SPHEREx 離群旗標</dt><dd>{t`${Math.round((tr.l2_frac || 0) * 100)}% 的偵測（獨立證據）`}</dd></>}
        {tr.blind === false && <><dt>連結方式</dt><dd>星表輔助（盲連結不會出現）</dd></>}
        {tr.jpl && !tr.jpl.consistent && <><dt>JPL</dt><dd className="warn">部分偵測和 JPL 位置不符</dd></>}
      </dl>}
      {tr.kind === 'distant' && <ParallaxCalc />}
      {hint && <Hint className="at-evidence" onNext={onHintNext} onSkip={onSkip}>它通過了這幾項檢查——按下面的按鈕看完整證據</Hint>}
      <button className="btn primary small" onClick={() => { onHintNext?.(); go(field.id, tr.id) }}>看完整證據 →</button>
    </section>
  )
}

/** A single AI detection that did not join a track (fields with nothing linked). */
export function CandCard({ field, c, on, onPick }) {
  const [v, setV] = useState(null)
  const ex = field.exposures[c.i]
  async function vote(verdict) {
    try { await api('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ field: field.id, cand: c.id, verdict }) }); setV(verdict) } catch { setV('err') }
  }
  return (
    <li className={`tcard cand ${on ? 'on' : ''}`}>
      <button className="thead" onClick={onPick}>
        <span className="tname">{t`候選 #${c.id}`}</span>
        <span className="tkind">{t`AI ${pct(c.p)}`}<svg className="vai" width="64" height="8" viewBox="0 0 64 8" aria-hidden="true"><rect className="vai-bg" width="64" height="8" rx="4" /><rect width={Math.max(4, 64 * c.p)} height="8" rx="4" fill={c.p >= pLink(field) ? COL.good : COL.warn} /><rect x={64 * pLink(field) - 1} y="0" width="2" height="8" fill={COL.ink} /></svg></span>
        <span className="tplain">{t`${ex.iso.slice(0, 10)} · D${ex.detector} ${ex.lam_um.toFixed(2)} µm · S/N ${c.snr}`}</span>
        <span className="strip"><canvas width={63} height={63} ref={(el) => el && drawCrop(el, field, 'diff', c)} aria-hidden="true" /><canvas width={63} height={63} ref={(el) => el && drawCrop(el, field, 'sci', c)} aria-hidden="true" /></span>
      </button>
      {on && <div className="cvote">
        {v ? <span className="hint">{v === 'err' ? '送出失敗，請稍後再試。' : '謝謝！你的判斷已記錄。'}</span> : <>
          <span className="hint">你覺得這是？</span>
          <button className="btn small" onClick={() => vote('real')}>真的</button>
          <button className="btn small" onClick={() => vote('artifact')}>假訊號</button>
          <button className="btn small" onClick={() => vote('unsure')}>不確定</button>
        </>}
      </div>}
    </li>
  )
}

export function ParallaxCalc() {
  const [d, setD] = useState(400)
  const shift = (2 * 206265) / d
  return (
    <div className="calc">
      <label htmlFor="dsl">{t`距離 ${d} AU`}</label>
      <input id="dsl" type="range" min="30" max="3000" step="10" value={d} onChange={(e) => setD(+e.target.value)} />
      <p className="num">{t`相隔半年的兩次觀測最多相差 ${shift.toFixed(0)}″，約 ${(shift / PIX).toFixed(0)} 個 SPHEREx 像素。`}</p>
    </div>
  )
}

export function SkyPanel({ field }) {
  const ex = field.exposures
  const byDet = DETS.map((d) => ex.filter((e) => e.detector === d).length)
  const passes = new Set(ex.map((e) => e.iso.slice(0, 7))).size
  const nref = ex.map((e) => e.nref).sort((a, b) => a - b)
  const low = ex.filter((e) => e.nref < 2).length
  const alphas = ex.map((e) => e.alpha).sort((a, b) => a - b)
  const q = (a, p) => a[Math.min(a.length - 1, Math.floor(p * a.length))]
  const bins = [[0.5, 1.01], [0.2, 0.5], [0.05, 0.2]].map(([lo, hi]) => field.candidates.filter((c) => c.p >= lo && c.p < hi).length)
  const known = [...field.known_bodies].filter((b) => b.V != null).sort((a, b) => a.V - b.V).slice(0, 12)
  return (
    <div className="panel">
      <p>{fieldDesc(field)}</p>
      <dl className="kv">
        <dt>影像</dt><dd>{t`${ex.length} 張，${passes} 個月份`}</dd>
        <dt>各偵測器</dt><dd>{byDet.map((n, k) => <span key={k} style={{ color: DET[k + 1].c, marginRight: 8 }}>D{k + 1} {n}</span>)}</dd>
        <dt>參考影像數</dt><dd>{t`中位數 ${q(nref, 0.5)}；${low} 張少於 2 張`}</dd>
        <dt>測光比例 α</dt><dd>{q(alphas, 0.05).toFixed(2)} – {q(alphas, 0.95).toFixed(2)} (5–95%)</dd>
        <dt>候選（AI 分數）</dt><dd>{t`≥0.5：${bins[0]} · 0.2–0.5：${bins[1]} · 0.05–0.2：${bins[2]}`}</dd>
        <dt>已知小天體</dt><dd>{t`${field.known_bodies.length} 個（V ≤ 21.5）`}</dd>
      </dl>
      <div className="vbars" aria-label={L('各偵測器的影像張數', 'Exposures per detector')}>
        <Bars height={150} label={L('各偵測器的影像張數', 'Exposures per detector')} bars={byDet.map((n, k) => ({ label: `D${k + 1}`, value: n, c: COL.det[k], tip: `D${k + 1} · ${DET[k + 1].r}: ${n}` }))} />
      </div>
      <h3>最亮的已知天體</h3>
      <ul className="plainlist">{known.map((b) => <li key={b.name}>{b.name} · V {b.V}</li>)}</ul>
      <p className="note">參考影像少於 2 張的影像，變化圖比較不可靠：可能只是和單一張影像相減。這些影像在播放時會顯示警告。</p>
    </div>
  )
}

/** The viewer's "more settings" dialog: which exposures play, which layers are drawn, the speed, the keys. */
export function ViewerSettings({ field, onClose, band, setBand, oneDet, setOneDet, dets, setDets, hasSel, show, setShow, sim, revealSim, setRevealSim, hz, setHz, maxHz, onReplayTour }) {
  return (
    <div className="settings" role="dialog" aria-label="更多設定">
      <button className="iconbtn close" onClick={onClose} aria-label="關閉">{ICON.close}</button>
      <h3>播放哪些影像</h3>
      <div className="seg" role="group" aria-label="波段">
        <button aria-pressed={band === 'one'} onClick={() => setBand('one')}>一次一個偵測器</button>
        <button aria-pressed={band === 'all'} onClick={() => setBand('all')}>全部偵測器</button>
      </div>
      <p className="hint">{band === 'one' ? '相鄰影像的波長接近，閃爍時看到的是位置在移動，而不是亮度在跳。' : '所有波段依時間播放；不同波長的亮度差異會一起閃爍。'}</p>
      <div className="dets" role="group" aria-label="偵測器（波段）">
        {DETS.map((d) => {
          const on = band === 'one' ? oneDet === d : dets.has(d)
          return <button key={d} aria-pressed={on} title={DET[d].r} style={{ '--c': DET[d].c }}
            onClick={() => band === 'one' ? setOneDet(d) : setDets((s1) => { const n = new Set(s1); if (n.has(d) && n.size > 1) n.delete(d); else n.add(d); return n })}>
            <b>D{d}</b><span>{DET[d].r}</span></button>
        })}
      </div>
      {hasSel && <p className="hint">選取天體時，只播放有偵測到它的影像。</p>}
      <h3>圖層</h3>
      <div className="toggles">
        <label><input type="checkbox" checked={show.cands} onChange={(e) => setShow({ ...show, cands: e.target.checked })} /> AI 偵測</label>
        <label><input type="checkbox" checked={show.known} onChange={(e) => setShow({ ...show, known: e.target.checked })} /> 已知天體</label>
        {field.products && <label><input type="checkbox" checked={show.flags} onChange={(e) => setShow({ ...show, flags: e.target.checked })} /> 污染旗標</label>}
        {field.products && <label><input type="checkbox" checked={show.gaia} onChange={(e) => setShow({ ...show, gaia: e.target.checked })} /> Gaia DR3</label>}
        {field.products && <label><input type="checkbox" checked={show.wise} onChange={(e) => setShow({ ...show, wise: e.target.checked })} /> CatWISE</label>}
        {sim && <label><input type="checkbox" checked={revealSim} onChange={(e) => setRevealSim(e.target.checked)} /> 模擬行星的注入位置</label>}
      </div>
      <h3>速度</h3>
      <div className="toggles">
        <label><input type="checkbox" checked={hz === 'auto'} onChange={(e) => setHz(e.target.checked ? 'auto' : 2)} /> 自動</label>
        {hz !== 'auto' && <label>{t`${hz} 張/秒`} <input type="range" min="0.5" max={maxHz} step="0.5" value={hz} onChange={(e) => setHz(+e.target.value)} aria-label="播放速度" /></label>}
      </div>
      <h3>鍵盤</h3>
      <p className="hint">← → 逐張 · 空白鍵 播放 · + − 縮放 · 0 重設 · M 切換模式 · Esc 取消選取</p>
      <h3>導覽</h3>
      <button className="btn small" onClick={onReplayTour}>重新看一次導覽</button>
    </div>
  )
}
