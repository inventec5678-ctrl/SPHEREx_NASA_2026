// The home page (UPGRADE_PLAN.md §9: D7, D11): the search and a live example on the first screen, then three real
// results as charts that move (a moving star, a variable star, a cold brown dwarf), the all-sky map, the analysed
// fields. Results are shown, not described: every card draws the measurement itself and links to its target.
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { paperUrl } from '@sx/i18n/core.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { DET, L, PASS_C, api, forgetField, getField, mjdDate } from './lib.js'
import { fieldDesc, fieldName } from './fields_text.js'
import { go } from './nav.js'
import { SkySearch, openSky } from './search.jsx'
import { Blink } from './blink.jsx'
import { useBoxWidth } from './canvas.js'
import { usePlayback } from './play.js'
import { useReveal } from './reveal.js'
import { EXAMPLES, TARGET_IDS, parseSky, sep, skyHash, skyPlace, skyPath, invHammer, P9_PATH, P9_HALF_WIDTH } from './sky.js'
import { jobError, jobFinished, poll, startAnalysis } from './jobs.js'
import './home.css'
import { SPHEREX_ACK } from './credits_text.js'

// The chart kit is its own download: it arrives with the second screen, not with the search box.
const kit = () => import('./charts.jsx')
const Plot = lazy(() => kit().then((m) => ({ default: m.Plot })))
const Bars = lazy(() => kit().then((m) => ({ default: m.Bars })))
const Meter = lazy(() => kit().then((m) => ({ default: m.Meter })))
const Legend = lazy(() => kit().then((m) => ({ default: m.Legend })))
/** A chart from the kit, with its height reserved while the kit loads (nothing below it jumps). */
const Chart = ({ h, children }) => <div className="hm-chart" style={{ minHeight: h }}><Suspense fallback={null}>{children}</Suspense></div>

const getJson = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null)
/** True once the element is on screen (or within `margin` of it): data and pictures below the first screen wait for that. */
function useSeen(margin = '120px') {
  const ref = useRef(), [seen, setSeen] = useState(false)
  useEffect(() => {
    if (seen || !ref.current) return
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) setSeen(true) }, { rootMargin: margin })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [seen, margin])
  return [ref, seen]
}
/** The catalogued star that moves fastest among a field's automatic proper-motion candidates, as a Blink subject. */
const fastest = (d, field) => {
  const c = (d?.candidates || []).filter((x) => x.status === 'known' && x.track?.length >= 2).sort((a, b) => b.pm_arcsec_yr - a.pm_arcsec_yr)[0]
  return c ? { ...c, field, source: 'field' } : null
}
const ymd = (mjd) => mjdDate(mjd).toISOString().slice(0, 10)
const passName = (k) => L(`第 ${k + 1} 輪`, `Pass ${k + 1}`)
/** The short name of a challenge target (the one on the search box's example chips). */
const targetName = (id) => { const x = EXAMPLES.find((e) => parseSky(e.q)?.id === id); return x ? L(x.zh, x.en) : id }

// The live example beside the search box: Teegarden's Star, a nearby red dwarf that is not saturated in SPHEREx
// (Barnard's Star is, so its core is masked and looks like a hole), found by the blind proper-motion search.
const DEMO_FIELD = 'q043p280+16p853s15'

/** First screen: what the challenge asks for. A position goes in, an image sequence comes out. */
// The first screen: the 3D cosmos journey (galaxy to SPHEREx sky) behind the search; the search steps aside once you fly in.
const Cosmos = lazy(() => import('./cosmos/Cosmos.jsx'))
function Hero() {
  const [deep, setDeep] = useState(false)
  return (
    <section className={`hm-hero hm-hero-cz${deep ? ' is-deep' : ''}`} aria-labelledby="hero-h">
      <Suspense fallback={<div className="cz" />}><Cosmos onDeep={setDeep} /></Suspense>
      <div className="hm-hero-main hm-hero-panel">
        <p className="hm-kicker">SPHEREx · NASA Space Apps 2026</p>
        <h1 id="hero-h">{L('輸入座標，', 'Enter a position.')} <em>{L('看這片天空怎麼變', 'Watch that sky change.')}</em></h1>
        <p className="hm-lead">{L('輸入赤經赤緯或天體名稱，SPHEREx 拍過那片天空的每一張紅外線影像會依時間播放，像一段影片。或者往下捲動，從銀河一路飛到 SPHEREx 和它看見的天空。', 'Type an RA and Dec or an object name, and every SPHEREx infrared image of that patch plays in time order, like a video. Or scroll to fly in: from the Milky Way to SPHEREx and the sky it sees.')}</p>
        <SkySearch id="hero-q" />
        <nav className="hm-links" aria-label={L('捷徑', 'Shortcuts')}>
          <a href="#/guide/requirements">{L('題目要求在哪裡 →', 'Where each requirement is met →')}</a>
          <a href="#/guide">{L('怎麼看、有多可靠 →', 'How to read it, how far to trust it →')}</a>
        </nav>
      </div>
    </section>
  )
}

// ---- three kinds of result ----------------------------------------------------------------------------------------
function Seg({ label, items, value, onChange }) {
  return <div className="seg hm-seg" role="group" aria-label={label}>{items.map(([v, text]) => <button key={v} type="button" aria-pressed={value === v} onClick={() => onChange(v)}>{text}</button>)}</div>
}
/** One result: what kind, which object, the one-sentence finding, the picture, the way in. */
function Card({ box, kind, id, take, children }) {
  return (
    <figure className="hm-card reveal" ref={box}>
      <figcaption>
        <span className="hm-kind">{kind}</span>
        <h3>{targetName(id)}</h3>
        <p className="hm-take">{take}</p>
      </figcaption>
      {children}
      <a className="btn hm-open" href={`#/target/${id}`}>{L('打開這個目標 →', 'Open this target →')}</a>
    </figure>
  )
}

const MOVERS = ['epsindi', 'barnard', 'wise0855']
/** A moving star: the survey passes blink, and the measured shift sits next to what the catalogue predicts. */
function MoverCard({ by }) {
  const [ref, seen] = useSeen()
  const [id, setId] = useState(MOVERS[0])
  const [cands, setCands] = useState({})
  const box = useRef(), w = useBoxWidth(box)
  useEffect(() => {
    if (seen && !cands[id]) getJson(`/data/fields/${id}/pm_candidates.json`).then((d) => { const c = fastest(d, id); if (c) setCands((m) => ({ ...m, [id]: c })) })
  }, [seen, id]) // eslint-disable-line react-hooks/exhaustive-deps
  const m = by.get(id)?.target?.motion, c = cands[id]
  const top = m ? Math.max(m.measured_arcsec + m.err_arcsec, m.predicted_arcsec) * 1.08 : 1
  return (
    <Card box={ref} id={id} kind={L('移動的恆星', 'A moving star')}
      take={m ? L(`${Math.round(m.days)} 天裡移動了 ${m.measured_arcsec.toFixed(2)}″（± ${m.err_arcsec.toFixed(2)}″），星表預測 ${m.predicted_arcsec.toFixed(2)}″。`, `It moved ${m.measured_arcsec.toFixed(2)}″ (± ${m.err_arcsec.toFixed(2)}″) in ${Math.round(m.days)} days; the catalogue predicts ${m.predicted_arcsec.toFixed(2)}″.`) : L('各輪巡天之間，它在影像上換了位置。', 'Between survey passes it changes place on the image.')}>
      <Seg label={L('選一個移動的目標', 'Choose a moving target')} value={id} onChange={setId} items={MOVERS.map((x) => [x, targetName(x)])} />
      <div className="hm-blink" ref={box}>
        {c && w > 0 ? <Blink key={id} c={c} size={25} px={w} trail label={L('各輪巡天的疊加影像，輪流顯示', 'Stacks of each survey pass, shown in turn')} /> : <div className="hm-ph" />}
      </div>
      <Chart h={96}>
        {seen && m && <>
          <Meter label={L('SPHEREx 量到的位移', 'Shift measured by SPHEREx')} value={m.measured_arcsec} hi={top} mark={m.predicted_arcsec} c="var(--sx-accent)" text={`${m.measured_arcsec.toFixed(2)}″ ± ${m.err_arcsec.toFixed(2)}″`} />
          <Meter label={L('星表預測（自行加視差）', 'Catalogue prediction (motion + parallax)')} value={m.predicted_arcsec} hi={top} c="var(--sx-known)" text={`${m.predicted_arcsec.toFixed(2)}″`} />
        </>}
      </Chart>
    </Card>
  )
}

const VARS = ['rdra', 'rwaur']
/** A variable star: its brightness in each survey pass, on the AAVSO ephemeris where there is one. */
function VariableCard() {
  const [ref, seen] = useSeen()
  const [id, setId] = useState(VARS[0])
  const [data, setData] = useState({})
  const [mira, setMira] = useState(null)
  const [user, setUser] = useState(null)
  useEffect(() => {
    if (!seen) return
    if (!data[id]) getJson(`/data/fields/${id}/var_candidates.json`).then((d) => { const c = (d?.candidates || []).filter((x) => x.L?.length > 1).sort((a, b) => b.sig - a.sig)[0]; if (c) setData((m) => ({ ...m, [id]: c })) })
    if (!mira) getJson('/api/validation').then((v) => v?.mira && setMira(v.mira))
  }, [seen, id]) // eslint-disable-line react-hooks/exhaustive-deps
  const c = data[id], lc = c?.L || []
  const pb = usePlayback(lc.length, { hz: 0.7, active: seen && user == null })
  // the AAVSO ephemeris (period and date of maximum) as a cosine; only its height and mean are fitted to the passes
  const eph = useMemo(() => {
    const v = id === 'rdra' && mira?.vsx
    if (!v || lc.length < 3) return null
    const ph = (mjd) => (((mjd - (v.epoch_max_jd - 2400000.5)) / v.period_d) % 1 + 1) % 1
    const cs = lc.map((p) => Math.cos(2 * Math.PI * ph(p.mjd))), n = lc.length
    const cm = cs.reduce((a, b) => a + b, 0) / n, ym = lc.reduce((a, p) => a + p.rel, 0) / n
    const b = cs.reduce((a, x, j) => a + (x - cm) * (lc[j].rel - ym), 0) / cs.reduce((a, x) => a + (x - cm) ** 2, 0)
    return { ph, at: (mjd) => ym - b * cm + b * Math.cos(2 * Math.PI * ph(mjd)), period: v.period_d }
  }, [id, mira, lc])
  const x0 = lc.length ? lc[0].mjd - 45 : 0, x1 = lc.length ? lc.at(-1).mjd + 45 : 1
  const ys = lc.flatMap((p) => [p.rel - p.err, p.rel + p.err]).concat(eph ? [eph.at(lc[0].mjd - 45), eph.at(lc.at(-1).mjd + 45)] : [])
  const y0 = Math.min(0.6, ...ys) - 0.08, y1 = Math.max(1.4, ...ys) + 0.14
  const rel = lc.map((p) => `×${p.rel.toFixed(2)}`), now = user ?? (pb.playing ? pb.k : null)        // the pass the ring is on
  const amp = c?.amp_det || {}, pair = c?.pair || [0, 2]
  return (
    <Card box={ref} id={id} kind={L('變星', 'A variable star')}
      take={!c ? L('各輪巡天量到的亮度不一樣。', 'Its brightness differs from one survey pass to the next.')
        : id === 'rdra' ? L(`三輪巡天量到平均亮度的 ${rel.join('、')}，高低順序和 AAVSO 的 ${eph ? Math.round(eph.period) : 246} 天週期一致。`, `Three passes measured ${rel.join(', ')} of its mean brightness, in the order the ${eph ? Math.round(eph.period) : 246}-day AAVSO period predicts.`)
        : L(`第 ${pair[0] + 1} 輪到第 ${pair[1] + 1} 輪，最長波段（D6）的亮度差了 ${(amp.D6 ?? 0).toFixed(1)} 倍，最短波段（D1）幾乎沒變（×${(amp.D1 ?? 0).toFixed(2)}）。`, `From pass ${pair[0] + 1} to pass ${pair[1] + 1} the longest band (D6) changed ${(amp.D6 ?? 0).toFixed(1)}-fold while the shortest (D1) barely moved (×${(amp.D1 ?? 0).toFixed(2)}).`)}>
      <Seg label={L('選一顆變星', 'Choose a variable star')} value={id} onChange={(v) => { setId(v); setUser(null) }} items={VARS.map((x) => [x, targetName(x)])} />
      <Chart h={232}>
        {lc.length > 0 && <Plot height={232} label={L('各輪巡天的相對亮度', 'Relative brightness in each survey pass')}
          x={{ domain: [x0, x1], ticks: lc.map((p) => p.mjd), fmt: (v) => mjdDate(v).toISOString().slice(0, 7) }}
          y={{ domain: [y0, y1], label: L('相對亮度（平均 = 1）', 'Brightness (mean = 1)'), fmt: (v) => `×${v}`, gutter: 44 }}
          hovered={user} onHover={(_, j) => setUser(j)}
          points={lc.map((p) => ({ x: p.mjd, y: p.rel, r: 11, tip: `${passName(p.k)} · ${ymd(p.mjd)} · ×${p.rel.toFixed(2)} ± ${p.err.toFixed(2)}`, hint: eph ? L(`AAVSO 相位 ${eph.ph(p.mjd).toFixed(2)}（0 = 最亮）`, `AAVSO phase ${eph.ph(p.mjd).toFixed(2)} (0 = maximum)`) : undefined }))}>
          {({ X, Y }) => <>
            {eph && <path className="hm-eph" d={Array.from({ length: 81 }, (_, j) => x0 + ((x1 - x0) * j) / 80).map((v, j) => `${j ? 'L' : 'M'}${X(v).toFixed(1)} ${Y(eph.at(v)).toFixed(1)}`).join('')} />}
            {lc.map((p, j) => <g key={p.k} style={{ color: PASS_C[p.k % PASS_C.length] }}>
              <line className="hm-err" x1={X(p.mjd)} x2={X(p.mjd)} y1={Y(p.rel - p.err)} y2={Y(p.rel + p.err)} />
              {j === now && <circle className="hm-ring" cx={X(p.mjd)} cy={Y(p.rel)} r="13" />}
              <circle cx={X(p.mjd)} cy={Y(p.rel)} r="7" fill="currentColor" />
              <text className="mark-label" x={X(p.mjd)} y={Y(p.rel + p.err) - 12} textAnchor="middle">{passName(p.k)}</text>
              <text className="mark-label" x={X(p.mjd)} y={Y(p.rel - p.err) + 24} textAnchor="middle" fill="currentColor">×{p.rel.toFixed(2)}</text>
            </g>)}
          </>}
        </Plot>}
      </Chart>
      <p className="hm-cap">{eph ? <><i className="hm-dash" aria-hidden="true" />{L('AAVSO 的週期與極大日期（高度配合這三點）', 'AAVSO period and date of maximum (height fitted to these points)')}</> : L('沒有固定週期：亮度不規則地變', 'No fixed period: it varies irregularly')}</p>
      <h4 className="hm-h4">{L(`第 ${pair[0] + 1} 輪 ÷ 第 ${pair[1] + 1} 輪的亮度，六個偵測器`, `Pass ${pair[0] + 1} ÷ pass ${pair[1] + 1} brightness, six detectors`)}</h4>
      <Chart h={168}>
        {c && <Bars height={168} label={L('各偵測器的亮度變化', 'Brightness change in each detector')} fmt={(v) => `×${(+v).toFixed(1)}`}
          bars={Object.entries(amp).map(([d, v]) => ({ label: d, value: v, c: DET[d.slice(1)]?.c, tip: `${d} · ${DET[d.slice(1)]?.r} · ×${v.toFixed(2)}` }))} />}
      </Chart>
    </Card>
  )
}

// wavelength range of each detector array (µm), and the spectral classifier's decision threshold (models/bd_spec_metrics.json)
const DET_UM = [[0.75, 1.11], [1.10, 1.64], [1.63, 2.42], [2.42, 3.82], [3.81, 4.42], [4.41, 5.0]]
const BD_THRESHOLD = 0.8
/** A cold brown dwarf: WISE 0855's spectrum, where the dwarf itself only shows past 4 µm. */
function DwarfCard() {
  const id = 'wise0855'
  const [ref, seen] = useSeen()
  const [tg, setTg] = useState(null)
  const [pass, setPass] = useState(-1)
  useEffect(() => { if (seen) getField(id).then((f) => setTg(f.target)).catch(() => {}) }, [seen])
  const s = useMemo(() => {
    if (!tg) return null
    // as in the lab (lab.jsx, Measure): pixels flagged unusable, ghost or outlier are left out; S/N of 3 or more is a
    // solid point, anything fainter a hollow one
    const ok = tg.points.filter((p) => p.f != null && isFinite(p.f) && p.e > 0 && !((p.flag ?? 0) & 13))
    const good = ok.filter((p) => p.f > 3 * p.e), weak = ok.filter((p) => p.f <= 3 * p.e)
    // the neighbour's falling spectrum: a straight line in log-log through 1.6-3.6 µm, extended to 5 µm
    const fit = good.filter((p) => p.lam >= 1.6 && p.lam <= 3.6).map((p) => [Math.log(p.lam), Math.log(p.f)])
    const mx = fit.reduce((a, v) => a + v[0], 0) / fit.length, my = fit.reduce((a, v) => a + v[1], 0) / fit.length
    const k = fit.reduce((a, v) => a + (v[0] - mx) * (v[1] - my), 0) / fit.reduce((a, v) => a + (v[0] - mx) ** 2, 0)
    const long = good.filter((p) => p.lam >= 4.2 && p.lam <= 4.8).map((p) => p.f).sort((a, b) => a - b)
    const of = (p) => tg.passes.findIndex((q) => p.mjd >= q.mjd0 - 1 && p.mjd <= q.mjd1 + 1)
    const fs = good.map((p) => p.f).sort((a, b) => a - b)
    return { good, weak, of, star: (lam) => Math.exp(my + k * (Math.log(lam) - mx)), bump: long[long.length >> 1], top: fs[Math.floor(fs.length * 0.97)] * 1.3 }
  }, [tg])
  const dim = (p) => (pass < 0 || s.of(p) === pass ? 1 : 0.12)
  return (
    <Card box={ref} id={id} kind={L('冷棕矮星', 'A cold brown dwarf')}
      take={L(`流量在 3.5 µm 附近最低，過了 4 µm 又升到約 ${s?.bump ? Math.round(s.bump / 10) * 10 : 600} µJy：那是已知最冷的棕矮星。短波長的光來自旁邊的星。`, `The flux bottoms out near 3.5 µm and climbs back to about ${s?.bump ? Math.round(s.bump / 10) * 10 : 600} µJy past 4 µm: that is the coldest brown dwarf known. The short-wavelength light is a neighbouring star.`)}>
      <Seg label={L('選一輪巡天', 'Choose a survey pass')} value={pass} onChange={setPass} items={[[-1, L('三輪全部', 'All passes')], ...(tg?.passes || [0, 1, 2]).map((_, k) => [k, passName(k)])]} />
      <Chart h={336}>
        {s && <Plot height={336} label={L('WISE 0855 的 SPHEREx 光譜', 'SPHEREx spectrum of WISE 0855')}
          x={{ domain: [0.6, 5.1], ticks: [1, 2, 3, 4, 5], label: L('波長（µm）', 'Wavelength (µm)') }}
          y={{ domain: [0, s.top], label: L('流量（µJy）', 'Flux (µJy)') }}
          points={s.good.filter((p) => dim(p) === 1 && p.f <= s.top).map((p) => ({ x: p.lam, y: p.f, r: 7, tip: `${p.lam.toFixed(2)} µm · ${Math.round(p.f)} ± ${Math.round(p.e)} µJy`, hint: `D${p.det} · ${ymd(p.mjd)}` }))}>
          {({ X, Y, h, m }) => <>
            {DET_UM.map(([a, b], j) => <rect key={j} x={X(a)} width={Math.max(0, X(b) - X(a))} y={h - m.b - 5} height="5" fill={DET[j + 1].c} />)}
            <path className="hm-eph" d={`M${X(1.6)} ${Y(s.star(1.6))}` + [2, 2.5, 3, 3.5, 4, 4.5, 5].map((v) => `L${X(v)} ${Y(s.star(v))}`).join('')} />
            {s.weak.filter((p) => p.f <= s.top).map((p) => <circle key={p.i} cx={X(p.lam)} cy={Y(Math.max(0, p.f))} r="3.5" fill="none" stroke={DET[p.det].c} opacity={0.6 * dim(p)} />)}
            {s.good.map((p) => (p.f <= s.top ? <circle key={p.i} cx={X(p.lam)} cy={Y(p.f)} r="4" fill={DET[p.det].c} opacity={dim(p)} />
              : <path key={p.i} d={`M${X(p.lam) - 5} ${m.t + 9}l5 -9l5 9z`} fill={DET[p.det].c} opacity={dim(p)}><title>{L(`超出刻度：${Math.round(p.f)} µJy`, `Off the scale: ${Math.round(p.f)} µJy`)}</title></path>))}
            <text className="mark-label" x={X(2.05)} y={Y(0.66 * s.top)}>{L('← 旁邊的星', '← Neighbour star')}</text>
            <text className="mark-label" x={X(4.95)} y={Y(Math.min(0.9 * s.top, 1.9 * s.bump))} textAnchor="end">{L('棕矮星 ↓', 'Brown dwarf ↓')}</text>
          </>}
        </Plot>}
      </Chart>
      <Chart h={56}>
        {seen && <Legend items={[...DET_UM.map((_, j) => ({ c: DET[j + 1].c, label: `D${j + 1}` })), { c: 'var(--sx-ink-2)', hollow: true, label: L('訊噪比不到 3', 'S/N below 3') }, { c: 'var(--sx-known)', line: true, label: L('旁邊那顆星的趨勢，往長波長延伸', "The neighbour's trend, extended") }]} />}
      </Chart>
      <Chart h={40}>
        {tg?.bd_score != null && <Meter label={L(`光譜 AI 的棕矮星分數（門檻 ${BD_THRESHOLD}）`, `Spectral AI score (threshold ${BD_THRESHOLD})`)} value={tg.bd_score} mark={BD_THRESHOLD} c="var(--sx-good)" text={tg.bd_score.toFixed(3)} />}
      </Chart>
    </Card>
  )
}

function Results({ fields }) {
  const by = useMemo(() => new Map(fields.map((f) => [f.id, f])), [fields])
  return (
    <section className="hm-sec" aria-labelledby="res-h">
      <h2 id="res-h" className="reveal">{L('三種看得出來的變化', 'Three kinds of change you can see')}</h2>
      <div className="hm-cards">
        <MoverCard by={by} />
        <VariableCard />
        <DwarfCard />
      </div>
      <nav className="hm-targets reveal" aria-label={L('挑戰指定的五個測試目標', 'The five test targets named by the challenge')}>
        <span>{L('挑戰指定的五個測試目標', 'The five test targets named by the challenge')}</span>
        {TARGET_IDS.map((id) => <a key={id} className="chip" href={`#/target/${id}`}>{targetName(id)}</a>)}
        <a href="#/targets">{L('五個一起比較 →', 'Compare all five →')}</a>
      </nav>
      <nav className="hm-targets reveal" aria-label={L('其他看法', 'Other ways in')}>
        <span>{L('還可以', 'Also')}</span>
        <a className="chip" href="#/follow">{L('跟著一顆小行星', 'Follow an asteroid')}</a>
        <a className="chip" href="#/comet">{L('星際彗星 3I/ATLAS', 'Interstellar comet 3I/ATLAS')}</a>
        <a className="chip" href="#/movers">{L('練眼力：找出假的移動星', 'Practice: spot the fake mover')}</a>
      </nav>
    </section>
  )
}

// ---- all-sky map ---------------------------------------------------------------------------------------------------
// Hammer–Aitoff (RA increases to the left, as on the sky; centre RA 180°). The background picture is made in the
// same projection by scripts/allsky_map.py, with the ellipse filling the picture, so markers line up.
const S2 = Math.SQRT2
const place = skyPlace
const at = ([x, y]) => ({ left: `${x}%`, top: `${y}%` })
/** A floating box 264 px wide next to a place on the map: kept inside the map, above or below the place. */
const float = ([x, y]) => ({ left: `clamp(0px, calc(${x}% - 132px), calc(100% - 264px))`, ...(y < 50 ? { top: `calc(${y}% + 20px)` } : { bottom: `calc(${100 - y}% + 20px)` }) })
const span = (a, b, step) => Array.from({ length: Math.round((b - a) / step) + 1 }, (_, j) => a + j * step)
const GRID_RA = [60, 120, 180, 240, 300], GRID_DEC = [-60, -30, 0, 30, 60], EPS = (23.4393 * Math.PI) / 180
const GRID = GRID_DEC.map((d) => skyPath(span(0.01, 359.99, 4.4997).map((r) => [r, d]))).concat(GRID_RA.map((r) => skyPath(span(-90, 90, 5).map((d) => [r, d])))).join('')
// Planet Nine: the band of most likely positions (densely sampled so the band edges follow the projection)
const P9_DENSE = P9_PATH.slice(1).flatMap(([r1, d1], j) => { const [r0, d0] = P9_PATH[j]; return span(0, 1, 0.125).slice(j ? 1 : 0).map((t) => [r0 + (r1 - r0) * t, d0 + (d1 - d0) * t]) })
const P9_BAND = skyPath([...P9_DENSE.map(([r, d]) => [r, d + P9_HALF_WIDTH]), ...P9_DENSE.slice().reverse().map(([r, d]) => [r, d - P9_HALF_WIDTH])], true)
const P9_LINE = skyPath(P9_DENSE)
const ECLIPTIC = skyPath(span(0, 360, 3).map((v) => { const l = (v * Math.PI) / 180; return [((Math.atan2(Math.sin(l) * Math.cos(EPS), Math.cos(l)) * 180) / Math.PI + 360) % 360, (Math.asin(Math.sin(EPS) * Math.sin(l)) * 180) / Math.PI] }))
const fieldThumb = (f) => `/data/fields/${f.id}/${f.target ? 'pass/p0_d0.webp' : f.has_universe ? 'deep_rgb.webp' : `sci/${String(f.thumb ?? 0).padStart(4, '0')}.${f.frame_ext || 'png'}`}`
const KINDS = { target: () => L('挑戰測試目標', 'Challenge target'), field: () => L('完整分析過', 'Analysed in full'), sim: () => L('模擬行星測試', 'Simulated-planet test'), quick: () => L('快速預覽', 'Quick look') }

function SkyMap({ fields, pick, onPick }) {
  const [ref, seen] = useSeen('400px')
  const [quick, setQuick] = useState([])
  const [tip, setTip] = useState(null)             // { ids: [marker index, ...], sticky } : markers under the pointer
  const [picked, setPicked] = useState(false)
  // finished quick looks (the review queue lists the ones the automatic search has run on)
  useEffect(() => {
    if (seen) getJson('/api/movers').then((d) => setQuick([...new Map((d || []).filter((c) => c.source === 'quick' && c.centre).map((c) => [c.field, { id: c.field, ...c.centre }])).values()]))
  }, [seen])
  const marks = useMemo(() => {
    const m = fields.map((f) => ({ id: f.id, ra: f.ra, dec: f.dec, kind: f.target ? 'target' : f.simulated ? 'sim' : 'field', name: f.target ? targetName(f.id) : fieldName(f), n: f.n_exposures,
      href: f.target ? `#/target/${f.id}` : `#/field/${encodeURIComponent(f.id)}`, img: fieldThumb(f) }))
    for (const q of quick) {
      if (m.some((x) => sep(x.ra, x.dec, q.ra, q.dec) < 0.05)) continue
      const ex = EXAMPLES.find((x) => { const v = parseSky(x.q); return v && !v.id && sep(v.ra, v.dec, q.ra, q.dec) < 0.05 })
      m.push({ ...q, kind: 'quick', name: ex ? L(ex.zh, ex.en) : `RA ${q.ra.toFixed(2)}°, Dec ${q.dec.toFixed(2)}°`, href: skyHash(`${q.ra} ${q.dec}`, q.size), img: `/data/quick/${q.id}/stack/p0_d1.webp` })
    }
    return m.map((x) => ({ ...x, at: place(x.ra, x.dec) }))
  }, [fields, quick])
  /** Markers within r px of the pointer, nearest first (close fields overlap, so the DOM cannot tell them apart). */
  const hit = (e, r) => {
    const b = ref.current.getBoundingClientRect()
    return marks.map((m, j) => [Math.hypot((m.at[0] / 100) * b.width - (e.clientX - b.left), (m.at[1] / 100) * b.height - (e.clientY - b.top)), j]).filter((v) => v[0] <= r).sort((a, c) => a[0] - c[0]).map((v) => v[1])
  }
  const hover = (e) => { if (tip?.sticky) return; const h = hit(e, 14); if (h.join() !== (tip?.ids || []).join()) setTip(h.length ? { ids: h } : null) }
  const click = (e) => {
    const mouse = window.matchMedia('(hover: hover)').matches, h = hit(e, mouse ? 14 : 22)
    if (h.length) { if (mouse) location.hash = marks[h[0]].href; else setTip({ ids: h.slice(0, 4), sticky: true }) }
    else if (tip?.sticky) setTip(null)
    else {
      const b = ref.current.getBoundingClientRect()
      const v = invHammer(((e.clientX - b.left) / b.width - 0.5) * 4 * S2, (0.5 - (e.clientY - b.top) / b.height) * 2 * S2)
      if (v) { onPick(v); setPicked(true) }
    }
  }
  const shown = tip ? tip.ids.map((j) => marks[j]).filter(Boolean) : []
  const here = pick && isFinite(pick[0]) && isFinite(pick[1]) ? place(pick[0], pick[1]) : null
  return (
    <div className="hm-mapwrap reveal">
      <div ref={ref} className={`hm-map ${shown.length ? 'on-mark' : ''}`} role="group" aria-label={L('全天圖：點標記打開那片天空，點其他地方選一個位置', 'All-sky map: click a marker to open that field, anywhere else to pick a position')}
        onMouseMove={hover} onMouseLeave={() => !tip?.sticky && setTip(null)} onClick={click}>
        {seen && <img src="/media/allsky.webp" width="1600" height="800" decoding="async" draggable="false" alt={L('SPHEREx 拍的全天紅外線影像，銀河是橫過畫面的亮帶', 'The whole sky in infrared as SPHEREx saw it; the Milky Way is the bright band')} />}
        <svg viewBox="0 0 200 100" preserveAspectRatio="none" aria-hidden="true">
          <ellipse className="hm-rim" cx="100" cy="50" rx="100" ry="50" /><path className="hm-grid" d={GRID} /><path className="hm-p9band" d={P9_BAND} /><path className="hm-p9" d={P9_LINE} /><path className="hm-ecl" d={ECLIPTIC} />
        </svg>
        {GRID_RA.filter((r) => r !== 180).map((r) => <span key={r} className="hm-tick ra" style={at(place(r, 0))} aria-hidden="true">{r}°</span>)}
        {GRID_DEC.filter(Boolean).map((d) => <span key={d} className="hm-tick" style={at(place(180, d))} aria-hidden="true">{d > 0 ? '+' : '−'}{Math.abs(d)}°</span>)}
        <span className="hm-line ecl" style={at(place(214, -13.6))} aria-hidden="true">{L('黃道', 'Ecliptic')}</span>
        <span className="hm-line" style={at(place(318, 48))} aria-hidden="true">{L('銀河平面', 'Galactic plane')}</span>
        <span className="hm-line p9" style={at(place(78, 38))} aria-hidden="true">{L('Planet Nine 預測帶', 'Planet Nine band')}</span>
        {marks.map((m, j) => <a key={m.id} className={`hm-mark ${m.kind} ${tip?.ids[0] === j ? 'on' : ''}`} style={at(m.at)} href={m.href} aria-label={`${m.name}: ${KINDS[m.kind]()}${m.n ? L(`，${m.n} 張影像`, `, ${m.n} exposures`) : ''}`}
          onFocus={() => setTip({ ids: [j] })} onBlur={() => setTip(null)} />)}
        {marks.filter((m) => m.kind === 'target').map((m) => <span key={m.id} className={`hm-name ${m.at[0] > 70 ? 'left' : ''}`} style={at(m.at)} aria-hidden="true">{m.name}</span>)}
        {here && <i className="hm-pick" style={at(here)} aria-hidden="true" />}
        {here && picked && !shown.length && (
          <div className="hm-float hm-pop" style={float(here)} onClick={(e) => e.stopPropagation()}>
            <b className="num">RA {pick[0].toFixed(3)}°, Dec {pick[1].toFixed(3)}°</b>
            <button type="button" className="btn primary" onClick={() => openSky(`${pick[0].toFixed(3)} ${pick[1].toFixed(3)}`)}>{L('播放這片天空', 'Play this sky')}</button>
          </div>
        )}
        {shown.length > 0 && (
          <div className={`hm-float hm-tip ${tip.sticky ? 'sticky' : ''}`} style={float(shown[0].at)} role="status" onClick={(e) => e.stopPropagation()}>
            {shown.map((m) => (
              <a key={m.id} href={m.href} tabIndex={tip.sticky ? 0 : -1}>
                <img src={m.img} alt="" width="72" height="72" />
                <span><b>{m.name}</b>{m.n ? L(`${m.n} 張影像`, `${m.n} exposures`) : `${m.size}°`}<small>{KINDS[m.kind]()}</small></span>
              </a>
            ))}
          </div>
        )}
      </div>
      <ul className="hm-key">
        {['target', 'field', 'sim', 'quick'].filter((k) => marks.some((m) => m.kind === k)).map((k) => <li key={k}><i className={`hm-mark ${k}`} />{KINDS[k]()}</li>)}
        <li><i className="hm-dash" />{L('黃道（小行星集中處）', 'Ecliptic (where asteroids are)')}</li>
        <li><i className="hm-band" />{L('Planet Nine 最可能在的帶狀區（Brown & Batygin 2021 預測軌道 ±12°）', 'Where Planet Nine is most likely (Brown & Batygin 2021 predicted orbit ±12°)')} <a href="#/discovery">{L('我們的搜尋 →', 'Our search →')}</a></li>
        <li className="hm-credit">{L('背景：SPHEREx 第一次資料釋出的全天影像，1.1、2.2、4.5 µm 合成（NASA/IPAC IRSA）', 'Background: the SPHEREx DR1 all-sky image at 1.1, 2.2 and 4.5 µm (NASA/IPAC IRSA)')}</li>
      </ul>
    </div>
  )
}

function Explore({ fields, refresh }) {
  const [q, setQ] = useState('183.2 -1.4'), [size, setSize] = useState('0.3')
  const [job, setJob] = useState(null)
  const stop = useRef(() => {})
  useEffect(() => () => stop.current(), [])
  const pos = parseSky(q)
  async function analyse() {
    if (!pos || pos.id) { setJob({ status: 'error', error: L('完整分析需要座標：請先在全天圖上點一個位置，或輸入赤經和赤緯。', 'The full analysis needs a position: click the map or type an RA and Dec first.') }); return }
    let j
    try { j = await startAnalysis(pos.ra, pos.dec, +size) } catch (e) { setJob({ status: 'error', error: jobError(e) }); return }
    if (j.status === 'done') { go(j.id); return }
    setJob({ ...j, log: [] })
    stop.current()
    stop.current = poll(`/api/jobs/${j.id}`, {
      onUpdate: async (r) => { setJob(r); if (r.status === 'done') { forgetField(j.id); await refresh(); go(j.id) } },
      done: jobFinished,
      onMissing: () => setJob({ status: 'error', error: L('伺服器找不到這個工作（可能剛重新啟動），請重新送出。', 'The server no longer has this job (it may have restarted); please submit again.') }),
    })
  }
  const log = job?.log || []
  const stage = Math.max(0, ...log.map((l) => +((l.match(/^\[(\d)\/6\]/) || [0, 0])[1])))
  const m = log.map((l) => l.match(/exposure (\d+)\/(\d+)/)).filter(Boolean).at(-1)
  const frac = job?.status === 'done' ? 1 : stage >= 4 && m ? (3 + m[1] / m[2]) / 6 : stage / 6
  const busy = job && ['queued', 'running'].includes(job.status)
  return (
    <section className="hm-sec" aria-labelledby="explore">
      <h2 id="explore" className="reveal">{L('在全天圖上選一片天空', 'Pick a patch on the all-sky map')}</h2>
      <p className="hm-sub reveal">{L('點標記打開已經算好的天空，點其他地方選一個新位置。', 'Click a marker to open a field that is ready; click anywhere else to pick a new position.')}</p>
      <SkyMap fields={fields} pick={pos && !pos.id ? [pos.ra, pos.dec] : null} onPick={([r, d]) => setQ(`${r.toFixed(3)} ${d.toFixed(3)}`)} />
      <div className="hm-mapform reveal">
        <SkySearch id="explore-q" value={q} onValue={setQ} examples={false} label={L('播放全天圖上選的位置', 'Play the position picked on the map')} />
        <details className="full-run">
          <summary>{L('完整分析：讓 AI 找小行星（20 到 40 分鐘）', 'Full analysis: let the AI look for asteroids (20 to 40 minutes)')}</summary>
          <p className="hint">{L('完整分析另外跑神經網路、軌跡連結和已知小行星比對，找出移動快的小行星與彗星。工作台（相加相減、假彩色、即時光譜、星表疊圖、污染旗標）在快速預覽跑完時就有了。一次處理一個請求，每人每天 2 片天空；完成後自動打開。只想看影像的話，用上面的播放就好。', 'The full analysis also runs the neural network, the track linking and the match to known asteroids, to find fast asteroids and comets. The lab (add and subtract, false colour, spectra on the fly, catalogue overlays, contamination flags) is there as soon as a quick look finishes. One request at a time, two fields per person per day; it opens by itself when done. To just watch the images, use Play above.')}</p>
          <div className="full-row">
            <label>{L('視野', 'Field')} <select value={size} onChange={(e) => setSize(e.target.value)} aria-label={L('完整分析的視野大小', 'Field of view of the full analysis')}>
              <option value="0.15">0.15° (9′)</option><option value="0.3">0.3° (18′)</option><option value="0.6">0.6° (36′)</option>
            </select></label>
            <button className="btn" type="button" onClick={analyse} disabled={busy}>{L('開始完整分析', 'Start the full analysis')}</button>
          </div>
        </details>
        {job && (
          <div className="job" role="status" aria-live="polite">
            <strong>{job.status === 'error' ? job.error || L('失敗', 'Failed') : job.status === 'done' ? L('完成！', 'Done!') : job.status === 'queued' ? L(`排隊中（第 ${job.position || 1} 位，每位約 30 分鐘）`, `Queued (position ${job.position || 1}, about 30 minutes each)`) : L('分析中…', 'Analysing…')}</strong>
            <div className="bar"><div style={{ width: `${Math.round(frac * 100)}%` }} /></div>
            <pre>{log.slice(-4).join('\n')}</pre>
          </div>
        )}
      </div>
    </section>
  )
}

function Fields({ fields }) {
  return (
    <section className="hm-sec" aria-labelledby="fields">
      <h2 id="fields" className="reveal">{L('已經完整分析過的天空', 'Fields already analysed in full')}</h2>
      <p className="hm-sub reveal">{L('神經網路、軌跡連結、已知小行星比對都跑過；點進去看每個天體的證據。', 'The neural network, track linking and the match to known asteroids have all run; open one to see the evidence for every object.')}</p>
      <div className="hm-fields">
        {fields.filter((f) => !TARGET_IDS.includes(f.id)).map((f) => (
          <a key={f.id} className="hm-field reveal" href={`#/field/${encodeURIComponent(f.id)}`}>
            <img src={fieldThumb(f)} alt="" loading="lazy" decoding="async" width="400" height="300" />
            <div>
              <h3>{fieldName(f)}</h3>
              <p>{fieldDesc(f)}</p>
              <div className="hm-counts">
                <div><b>{f.n_exposures}</b><span>{L('張影像', 'exposures')}</span></div>
                <div><b>{f.n_known}</b><span>{L('已知天體', 'known')}</span></div>
                {f.n_simulated ? <div><b>{f.n_simulated}</b><span>{L('模擬行星', 'simulated')}</span></div> : <div><b>{f.n_unknown}</b><span>{L('未辨識', 'unidentified')}</span></div>}
              </div>
              <div className="hm-go">{L('打開這片天空 →', 'Open this sky →')}</div>
            </div>
          </a>
        ))}
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="footer hm-sec">
      <div className="wordmark reveal">SPHEREx Sky <span>Change</span></div>
      <nav className="links" aria-label={L('了解更多', 'Learn more')}>
        <a href="#/guide">{L('說明與驗證', 'Guide and validation')}</a>
        <a href="#/features">{L('功能介紹', 'Features')}</a>
        <a href={paperUrl('paper')}>{L('論文全文', 'Full paper')}</a>
        <a href="/paper/research/evidence.json">{L('證據資料（JSON）', 'Evidence data (JSON)')}</a>
        <a href="#/credits">{L('資料來源與致謝', 'Data credits')}</a>
        <a href="https://irsa.ipac.caltech.edu/Missions/spherex.html">NASA/IPAC IRSA · SPHEREx</a>
        <a href="https://ssd-api.jpl.nasa.gov/doc/sb_ident.html">JPL Small-Body Identification</a>
        <a href="https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/">{L('Space Apps 題目', 'Space Apps challenge')}</a>
      </nav>
      <p lang="en">{SPHEREX_ACK}</p>
      <p>{L('這是 NASA Space Apps 2026 的黑客松原型，不是 NASA 官方產品。AI 候選只是值得再看一次的提示，不等於發現；本網站沒有發現新的行星。', 'A NASA Space Apps 2026 hackathon prototype, not an official NASA product. An AI candidate is a prompt to look again, not a discovery; this site has not found a new planet.')}</p>
    </footer>
  )
}

export default function Landing() {
  const [fields, setFields] = useState([])
  const lang = useLanguage()
  const refresh = () => api('/api/fields').then(setFields).catch(() => {})
  useEffect(() => { refresh() }, [])
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + L('輸入座標，看天空怎麼變', 'Enter a position, watch the sky change') }, [lang])
  useReveal()
  // the home page is the tool the challenge asks for; the research story (parallax, method, validation, paper) is #/story
  return (
    <div key={lang} className="home">
      <Hero />
      <Results fields={fields} />
      <Explore fields={fields} refresh={refresh} />
      <Fields fields={fields} />
      <section className="hm-sec hm-story" aria-labelledby="story-h">
        <div>
          <h2 id="story-h" className="reveal">{L('它怎麼運作', 'How it works')}</h2>
          <p className="hm-sub reveal">{L('相減找變化、只用模擬資料訓練的神經網路、三輪巡天量視差，以及每一步怎麼驗證。', 'Difference imaging, a network trained only on simulations, parallax from three survey passes, and how each step was checked.')}</p>
        </div>
        <a className="btn reveal" href="#/story">{L('看研究故事 →', 'Read the research story →')}</a>
      </section>
      <Footer />
    </div>
  )
}
