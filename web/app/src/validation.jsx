// The honest numbers, drawn: does the search work, and how often does it cry wolf? (/api/validation)
// Six chart cards, shown in the guide (#/guide/trust). Each card is a chart first, then one sentence with the result;
// the longer explanation and the limits are folded behind "Details". Every number comes from the API.
//   <Validation />                      the whole dashboard
//   <RecoveryChart data height legend />   the "how fast must it move" bars alone, without a card (the movers page)
//   useValidation()                     the /api/validation document (fetched once per page load), null while loading
import { useEffect, useRef, useState } from 'react'
import { L, PIX, api, mjdDate } from './lib.js'
import { COL, ChartCard, Legend, Meter, Plot as KitPlot, extent, niceTicks } from './charts.jsx'
import './validation.css'
import ValDr1 from './val_dr1.jsx'
import ValSpectro from './val_spectro.jsx'
import ValGaia from './val_gaia.jsx'
import ValByw from './val_byw.jsx'
import ValNeossat from './val_neossat.jsx'
import ValStreak from './val_streak.jsx'

let pending = null
const load = () => (pending ||= api('/api/validation').catch((e) => { pending = null; throw e }))
/** The validation document: null while loading, false if it could not be read. `skip` when the caller already has it. */
export function useValidation(skip = false) {
  const [v, setV] = useState(null)
  useEffect(() => {
    if (skip) return
    let on = true
    load().then((d) => on && setV(d)).catch(() => on && setV(false))
    return () => { on = false }
  }, [skip])
  return v
}

/** The kit's Plot, with a tooltip that survives a tap. On a touch screen the browser sends mouseleave right after the
 *  click of a tap, which would close the tooltip the tap has just opened; a tap on an empty part still closes it. */
function Plot(props) {
  const [hov, setHov] = useState(null)
  const tap = useRef({ t: 0, hit: false }), box = useRef()
  useEffect(() => {            // a touch or click anywhere else closes it
    if (hov == null) return
    const away = (e) => { if (!box.current?.contains(e.target)) setHov(null) }
    document.addEventListener('pointerdown', away, true)
    return () => document.removeEventListener('pointerdown', away, true)
  }, [hov])
  return (
    <div ref={box} className="vd-plot" onTouchStart={() => { tap.current = { t: Date.now(), hit: false } }}>
      <KitPlot {...props} hovered={hov} onHover={(_, j) => {
        const recent = Date.now() - tap.current.t < 700
        if (j != null) { if (recent) tap.current.hit = true; setHov(j) } else if (!(recent && tap.current.hit)) setHov(null)
      }} />
    </div>
  )
}

const f2 = (v, n = 2) => (v == null || !isFinite(v) ? '—' : Number(v).toFixed(n))
const pc = (f) => `${Math.round(100 * f)}%`
const perYr = () => L('″/年', '″/yr')
/** Tick labels along the x axis that a chart sets itself (categories, or labels that depend on the width). */
function XTicks({ X, h, m, at, labels }) {
  return at.map((x, j) => <text key={j} className="tick" x={X(x)} y={h - m.b + 18} textAnchor="middle">{labels[j]}</text>)
}
/** What was clicked, in words, with a link to the real thing. */
function Picked({ children, idle }) {
  return <p className={`vd-pick ${children ? '' : 'idle'}`} aria-live="polite">{children || idle}</p>
}
const TARGET = () => ({ barnard: L('巴納德星', "Barnard's Star"), epsindi: L('天苑增三 B', 'Epsilon Indi B'), wise0855: 'WISE 0855', rdra: L('天龍座 R', 'R Draconis'), rwaur: L('御夫座 RW', 'RW Aurigae') })
const FIELD = () => ({ ...TARGET(), cybele: '65 Cybele', planetx: L('Planet X 測試', 'Planet X test'), taurus: L('金牛座黃道', 'Taurus ecliptic') })
const fieldLabel = (id, f) => FIELD()[id] || (f ? `${f.ra.toFixed(1)}°, ${f.dec >= 0 ? '+' : '−'}${Math.abs(f.dec).toFixed(1)}°` : id)

// ---- (a) 45 known high-proper-motion stars: measured against predicted ----------------------------------------
function KnownStars({ ks }) {
  const [sel, setSel] = useState(null)
  const stars = ks.stars || []
  const drawn = stars.filter((s) => s.meas != null && s.pred != null)
  const nFound = stars.filter((s) => s.found).length
  const lim = ks.min_shift_arcsec
  const top = Math.max(1, Math.ceil(Math.max(...drawn.map((s) => Math.max(s.pred, s.meas)), 1) * 1.04))
  const res = ks.astrometry_resid_arcsec
  const points = drawn.map((s) => ({
    x: s.pred, y: s.meas, r: 9, s,
    tip: <><b>Gaia DR3 {s.id}</b><br />{L('預測', 'predicted')} {f2(s.pred)}″ · {L('量到', 'measured')} {f2(s.meas)}″</>,
    hint: `G ${f2(s.g, 1)} · ${s.found ? L(`搜尋有找到（${f2(s.sig, 1)}σ）`, `found by the search (${f2(s.sig, 1)}σ)`) : L('搜尋沒有找到', 'missed by the search')}`,
  }))
  const running = ks.n_done < ks.n_total
  return (
    <ChartCard
      title={L(`${ks.n_usable} 顆已知會移動的星`, `${ks.n_usable} stars known to move`)}
      take={<>{L('不看星表，自動找到', 'Without looking at a catalogue, the search found')} <b>{nFound} / {ks.n_usable}</b>{L(' 顆；位置量測和 Gaia 預測的差，中位數 ', '; the measured position differs from Gaia’s prediction by a median of ')}<b>{f2(res.median)}″</b>{res.median > 0 && L(`（約 1/${Math.round(PIX / res.median)} 像素）`, ` (about 1/${Math.round(PIX / res.median)} of a pixel)`)}{L('。', '.')}</>}
      legend={[
        { c: COL.good, label: L(`搜尋有找到（${nFound}）`, `Found by the search (${nFound})`) },
        { c: COL.bad, hollow: true, label: L(`沒找到（${stars.length - nFound}）`, `Missed (${stars.length - nFound})`) },
        { c: 'rgb(var(--c-bad) / .3)', sq: true, label: L(`位移小於 ${f2(lim)}″：低於偵測極限`, `Shift under ${f2(lim)}″: below the detection limit`) },
        { line: true, label: L('量到 = 預測', 'Measured = predicted') },
      ]}
      more={<>
        <p>{L(`從 Gaia 隨機抽出、每年移動 0.5″ 以上的星。每顆星用 ${ks.field_deg}° 的天空、每輪 ${ks.per_pass_exposures} 張影像，量它在第一輪和最後一輪之間移動了多少（橫軸是 Gaia 的預測，縱軸是實測）。`, `Stars drawn at random from Gaia, moving at least 0.5″ a year. For each: a ${ks.field_deg}° field, ${ks.per_pass_exposures} exposures per pass, and the shift between the first and last pass (Gaia's prediction across, the measurement up).`)}</p>
        <p>{L(`實測位移減 Gaia 預測：中位數 ${f2(res.median, 3)}″、90% 在 ${f2(res.p90, 3)}″ 以內。找到的星，量到的自行是星表的 ${f2(ks.pm_ratio_median)} 倍（中位數）。同一片天空裡多出來的「新」候選共 ${ks.false_new_candidates} 個。`, `Measured shift minus Gaia's prediction: median ${f2(res.median, 3)}″, 90% within ${f2(res.p90, 3)}″. For the stars found, the measured proper motion is ${f2(ks.pm_ratio_median)} times the catalogue's (median). Extra "new" candidates in these fields: ${ks.false_new_candidates}.`)}</p>
        <p>{L(`限制：位移小於 ${f2(lim)}″（0.12 像素，大約是每年 0.7″）的星低於偵測極限；極限以上也有沒找到的，多半是太靠近別的星。`, `Limits: a shift under ${f2(lim)}″ (0.12 pixel, about 0.7″ a year) is below the detection limit; some stars above it are missed too, mostly those too close to another star.`)}{stars.length > drawn.length && L(` 有 ${stars.length - drawn.length} 顆的位置量測失敗，圖上沒有畫。`, ` ${stars.length - drawn.length} had no usable position fit and is not drawn.`)}{running && L(` 測試還在跑（${ks.n_done} / ${ks.n_total}），數字會再變。`, ` The test is still running (${ks.n_done} / ${ks.n_total}); the numbers will change.`)}</p>
      </>}>
      <Plot height={340} points={points} onPick={(p) => setSel(p.s)} label={L('已知移動星：實測位移對 Gaia 預測位移', 'Known movers: measured shift against the shift Gaia predicts')}
        x={{ domain: [0, top], label: L('Gaia 預測的位移（角秒）', 'Shift predicted by Gaia (arcsec)'), fmt: (v) => `${v}″` }}
        y={{ domain: [0, top], label: L('SPHEREx 量到的位移（角秒）', 'Shift measured by SPHEREx (arcsec)'), fmt: (v) => `${v}″` }}>
        {({ X, Y, m, h }) => <>
          {lim > 0 && <rect className="vd-band" x={X(0)} y={m.t} width={X(lim) - X(0)} height={h - m.b - m.t} />}
          <line className="vd-ref" x1={X(0)} y1={Y(0)} x2={X(top)} y2={Y(top)} />
          {drawn.map((s) => (s.found
            ? <circle key={s.id} cx={X(s.pred)} cy={Y(s.meas)} r="5.5" fill={COL.good} />
            : <circle key={s.id} cx={X(s.pred)} cy={Y(s.meas)} r="5" fill="none" stroke={COL.bad} strokeWidth="2" />))}
          {sel && sel.meas != null && <circle className="vd-sel" cx={X(sel.pred)} cy={Y(sel.meas)} r="10" />}
        </>}
      </Plot>
      <Picked idle={L('點一顆星，看它的數字，也可以打開那片天空。', 'Click a star for its numbers and a link to that patch of sky.')}>
        {sel && <>
          <b>Gaia DR3 {sel.id}</b>
          <span>G {f2(sel.g, 1)} · {L('星表', 'catalogue')} {f2(sel.pm)}{perYr()}</span>
          <span>{L('預測', 'predicted')} {f2(sel.pred)}″ · {L('量到', 'measured')} {f2(sel.meas)}″ · {L('差', 'off by')} {f2(sel.resid)}″</span>
          <span>{sel.found ? L(`搜尋量到 ${f2(sel.meas_pm)}″/年`, `the search measured ${f2(sel.meas_pm)}″/yr`) : L('搜尋沒有找到', 'missed by the search')}</span>
          <a href={`#/sky/${sel.ra}%20${sel.dec}?fov=0.15`}>{L('打開這片天空 →', 'Open this sky →')}</a>
        </>}
      </Picked>
    </ChartCard>
  )
}

// ---- (b) how fast must it move to be found --------------------------------------------------------------------
/**
 * Recovery against proper motion, two methods in two colours: SPHEREx alone over one year (real stars) and SPHEREx
 * against CatWISE positions about 10.5 years older (static stars displaced by a known motion: an injected test).
 * data: the /api/validation document (fetched here when not given); height in px; legend: show the colour key.
 */
export function RecoveryChart({ data, height = 200, legend = true }) {
  const own = useValidation(!!data)
  const v = data || own
  const inj = v?.xepoch?.injected_isolated || [], str = v?.known_stars?.strata || []
  if (!inj.length && !str.length) return null
  const C_X = COL.known, C_S = COL.accent
  const bars = [
    ...inj.map((r, j) => ({ at: j, c: C_X, value: (100 * r.found) / r.n, label: `${r.pm}`, short: `${r.pm}`.replace(/^0\./, '.'), n: r.n, found: r.found, inj: true })),
    ...str.map((g, j) => {
      const label = g.pm_hi > 50 ? `${g.pm_lo}+` : `${g.pm_lo}–${g.pm_hi}`
      return { at: inj.length + (inj.length ? 0.6 : 0) + j * 1.25, c: C_S, value: g.n ? (100 * g.found) / g.n : 0, label, short: label.replace(/^0\./, '.'), n: g.n, found: g.found }
    }),
  ]
  const points = bars.map((b) => ({
    x: b.at, y: b.value, r: 0,
    tip: `${b.label}${perYr()}${L('：', ': ')}${L(`找回 ${Math.round(b.value)}%`, `${Math.round(b.value)}% recovered`)}`,
    hint: b.inj ? L(`把 ${b.n} 顆靜止的星人為位移，找回 ${b.found} 顆（注入測試）`, `${b.found} of ${b.n} static stars displaced by this much (injected test)`) : L(`${b.n} 顆真實的星裡找到 ${b.found} 顆`, `${b.found} of ${b.n} real stars`),
  }))
  const last = bars[bars.length - 1].at
  return (
    <div className="vd-recovery">
      {legend && <Legend items={[
        ...(inj.length ? [{ c: C_X, sq: true, label: L('SPHEREx 對照 10.5 年前的 CatWISE（注入測試）', 'SPHEREx vs CatWISE 10.5 years earlier (injected test)') }] : []),
        ...(str.length ? [{ c: C_S, sq: true, label: L('只用 SPHEREx 一年（真實的星）', 'One year of SPHEREx alone (real stars)') }] : []),
      ]} />}
      <Plot height={height} points={points} label={L('自行多大才找得到：回收率', 'How fast a star must move to be found: recovery')}
        x={{ domain: [-0.65, last + 0.65], ticks: [], label: L('每年移動（角秒）', 'Motion per year (arcsec)') }}
        y={{ domain: [0, 118], ticks: [0, 25, 50, 75, 100], fmt: (t) => `${t}%`, gutter: 44 }}>
        {({ X, Y, h, m, hov, narrow }) => {
          const bw = Math.max(6, Math.abs(X(1) - X(0)) * 0.7)
          return <>
            {inj.length > 0 && str.length > 0 && <line className="vd-sep" x1={X(inj.length - 0.2)} x2={X(inj.length - 0.2)} y1={m.t} y2={h - m.b} />}
            {bars.map((b, j) => (
              <g key={j} opacity={hov == null || hov === j ? 1 : 0.55}>
                <rect x={X(b.at) - bw / 2} y={Y(b.value)} width={bw} height={Math.max(1, Y(0) - Y(b.value))} rx="3" fill={b.c} />
                <text className={narrow ? 'mark-note' : 'mark-label'} x={X(b.at)} y={Y(b.value) - 6} textAnchor="middle">{Math.round(b.value)}{narrow ? '' : '%'}</text>
              </g>
            ))}
            <XTicks X={X} h={h} m={m} at={bars.map((b) => b.at)} labels={bars.map((b) => (narrow ? b.short : b.label))} />
          </>
        }}
      </Plot>
    </div>
  )
}
function Recovery({ v }) {
  const xe = v.xepoch, ks = v.known_stars
  const fast = ks?.strata?.[ks.strata.length - 1]
  const i15 = xe?.injected_isolated?.find((r) => r.pm === 0.15), i10 = xe?.injected_isolated?.find((r) => r.pm === 0.1)
  const real = xe?.recall?.[0]
  return (
    <ChartCard
      title={L('移動多快才找得到', 'How fast must it move to be found')}
      take={<>
        {fast && <>{L(`只用 SPHEREx 一年，每年 ${fast.pm_lo}″ 以上的星找到 `, `One year of SPHEREx alone finds `)}<b>{pc(fast.found / fast.n)}</b>{L('', ` of stars above ${fast.pm_lo}″ a year`)}</>}
        {i15 && <>{L('；對照 10.5 年前的 CatWISE，每年 0.15″ 的注入測試找回 ', '; against CatWISE from 10.5 years earlier, an injected 0.15″ a year is recovered ')}<b>{pc(i15.frac)}</b>{L('', ' of the time')}</>}{L('。', '.')}
      </>}
      more={xe && <>
        <p>{L(`SPHEREx 自己只有 1 年。拿它的位置去比約 10.5 年前 CatWISE 的位置，就能量到小一個數量級的自行：每軸的量測散佈是每年 ${xe.scatter_per_axis_mas_yr} mas（和 Gaia 比較，${xe.n_measured} 顆星）${i10 ? `，每年 0.1″ 的注入測試找回 ${pc(i10.frac)}` : ''}。`, `SPHEREx alone spans one year. Comparing its positions with CatWISE's from about 10.5 years earlier measures motions ten times smaller: the scatter is ${xe.scatter_per_axis_mas_yr} mas a year per axis (against Gaia, ${xe.n_measured} stars)${i10 ? `, and an injected 0.1″ a year is recovered ${pc(i10.frac)} of the time` : ''}.`)}</p>
        <p>{L(`限制：藍色長條是把靜止的星人為位移後找回的比例，不是真實的移動星。這 8 片天空裡真實的移動星很少${real ? `（每年 ${real.gaia_pm_lo}″ 以上的 ${real.n} 顆裡只有 ${real.n_isolated} 顆夠孤立，找到 ${real.found} 顆）` : ''}。視差擬合有做，但雜訊太大（靜止的星散佈 70–135 mas），所以不宣稱任何視差。`, `Limits: the blue bars come from displacing static stars by a known motion, not from real movers. These 8 fields hold few real ones${real ? ` (of ${real.n} above ${real.gaia_pm_lo}″ a year only ${real.n_isolated} is isolated enough; ${real.found} found)` : ''}. A parallax fit is run but is too noisy (static stars scatter by 70–135 mas), so no parallax is claimed.`)}</p>
      </>}>
      <RecoveryChart data={v} height={264} />
      {xe?.isolated_fraction != null && <Meter value={xe.isolated_fraction} c={COL.known} text={pc(xe.isolated_fraction)}
        label={L('夠孤立、能和 CatWISE 比對的星只有', 'Stars isolated enough to compare with CatWISE: only')} />}
    </ChartCard>
  )
}

// ---- (c) spectrum AI: every real star's score -----------------------------------------------------------------
const lg = (p) => Math.log(p / (1 - p))
const fmtScore = (s) => (s > 0.9995 ? '>\u00a00.999' : s < 0.0005 ? '<\u00a00.001' : s.toFixed(3))
function SpectrumScores({ sp, fields }) {
  const sc = sp.scores
  const thr = sp.threshold ?? 0.8, rn = sp.real_negatives
  const fpr = rn.false_positive_rate[String(thr)] ?? rn.false_positive_rate['0.8']
  const nFalse = Math.round(fpr * rn.n)
  const names = TARGET()
  const nTrain = parseInt(sp.training, 10)
  const take = <>
    {L(`${rn.n} 顆真實的一般恆星裡，分數超過門檻 ${thr} 的只有 `, `Of ${rn.n} real ordinary stars only `)}<b>{nFalse}{L(' 顆（', ' (')}{(fpr * 100).toFixed(1)}%{L('）', ')')}</b>{L('，兩顆真的棕矮星都過了門檻；訓練只用合成光譜。', ` score above the ${thr} threshold and both real brown dwarfs do; training used synthetic spectra only.`)}
  </>
  const more = <>
    <p>{L(`訓練資料全部是合成光譜${nTrain ? `（${nTrain.toLocaleString()} 條）` : ''}：一半是 T／Y 型棕矮星，另一半是一般恆星、M 巨星和米拉變星、L 型矮星、年輕恆星和星系；沒有用任何真實資料。合成驗證集的正確率 ${(sp.synthetic_val_accuracy * 100).toFixed(1)}%。`, `Training: ${sp.training}. Accuracy on the synthetic validation set: ${(sp.synthetic_val_accuracy * 100).toFixed(1)}%.`)}</p>
    <p>{L(`限制：真實的正樣本只有 ${Object.keys(sp.real_positive_scores).length} 顆（${Object.entries(sp.real_positive_scores).map(([k, s]) => `${names[k] || k} ${s.toFixed(3)}`).join('、')}），所以分數高代表「值得再看」，不是確認。分數最高的一般恆星：${rn.highest.slice(0, 2).map((r) => `${fieldLabel(r.field, fields?.[r.field])} G ${r.g}（${r.score.toFixed(3)}）`).join('、')}。`, `Limit: there are only ${Object.keys(sp.real_positive_scores).length} real positives (${Object.entries(sp.real_positive_scores).map(([k, s]) => `${names[k] || k} ${s.toFixed(3)}`).join(', ')}), so a high score means "worth another look", not a confirmation. The highest-scoring ordinary stars: ${rn.highest.slice(0, 2).map((r) => `${fieldLabel(r.field, fields?.[r.field])} G ${r.g} (${r.score.toFixed(3)})`).join(', ')}.`)}</p>
    {sc && <p>{L('橫軸是模型輸出的對數勝算，所以 0 和 1 兩端被拉開；每個點是一顆星。這些分數是用存下來的模型對同一批星重算的', 'The axis is the model’s log-odds, which stretches the two ends near 0 and 1; each dot is one star. The scores were recomputed for the same stars with the stored model')}{sc.matches_metrics ? L('，和原本的統計一致。', ' and agree with the stored summary.') : L('。', '.')}</p>}
  </>
  if (!sc?.negatives?.length) {
    // no per-star scores on this server: the two real brown dwarfs on a 0-1 scale, and the summary in words
    return (
      <ChartCard title={L('光譜 AI：會不會把一般恆星當成棕矮星', 'Spectrum AI: does it mistake ordinary stars for brown dwarfs')} take={take} more={more}>
        {Object.entries(sp.real_positive_scores).map(([k, s]) => <Meter key={k} value={s} mark={thr} c={COL.good} label={names[k] || k} text={s.toFixed(3)} />)}
      </ChartCard>
    )
  }
  const BW = 0.5
  const count = new Map()
  const stars = [...sc.negatives].sort((a, b) => a.z - b.z).map((r) => {
    const k = Math.floor(r.z / BW), n = count.get(k) || 0
    count.set(k, n + 1)
    return { ...r, bx: (k + 0.5) * BW, by: n + 0.5 }
  })
  const tallest = Math.max(...count.values())
  const zs = [...stars.map((r) => r.z), ...sc.positives.map((p) => p.z)]
  const dom = [Math.floor(Math.min(...zs)) - 1.5, Math.ceil(Math.max(...zs)) + 1.5]
  const zt = lg(thr)
  const pos = sc.positives.map((p, j) => ({ ...p, by: tallest * (0.72 - 0.26 * j), name: names[p.id] || p.id }))
  const ticks = [[1e-9, '10⁻⁹'], [1e-6, '10⁻⁶'], [1e-3, '0.001'], [0.5, '0.5'], [0.999, '0.999']].map(([p, t]) => [lg(p), t]).filter(([z]) => z > dom[0] && z < dom[1])
  const points = [
    ...stars.map((r) => ({ x: r.bx, y: r.by, r: 6, tip: `${L('一般恆星', 'Ordinary star')} · ${L('分數', 'score')} ${fmtScore(r.score)}`, hint: `${fieldLabel(r.field, fields?.[r.field])} · G ${f2(r.g, 1)}${r.score >= thr ? L(' · 假警報', ' · false alarm') : ''}` })),
    ...pos.map((p) => ({ x: p.z, y: p.by, r: 11, tip: `${p.name} · ${L('分數', 'score')} ${fmtScore(p.score)}`, hint: L('真實的棕矮星', 'a real brown dwarf') })),
  ]
  return (
    <ChartCard title={L('光譜 AI：會不會把一般恆星當成棕矮星', 'Spectrum AI: does it mistake ordinary stars for brown dwarfs')} take={take} more={more}
      legend={[
        { c: COL.known, label: L(`真實的一般恆星（${stars.length}）`, `Real ordinary stars (${stars.length})`) },
        { c: COL.bad, label: L(`過了門檻的一般恆星：假警報（${stars.filter((r) => r.score >= thr).length}）`, `Ordinary stars over the threshold: false alarms (${stars.filter((r) => r.score >= thr).length})`) },
        { c: COL.good, sq: true, label: L(`真實的棕矮星（${pos.length}）`, `Real brown dwarfs (${pos.length})`) },
        { line: true, c: COL.ink2, label: L(`門檻 ${thr}`, `Threshold ${thr}`) },
      ]}>
      <Plot height={296} points={points} label={L('光譜 AI 的分數分布：一般恆星和棕矮星', 'Spectrum AI score distribution: ordinary stars and brown dwarfs')}
        x={{ domain: dom, ticks: ticks.map((t) => t[0]), fmt: (z) => ticks.find((t) => t[0] === z)?.[1] ?? '', label: L('AI 分數（越右越像冷棕矮星）', 'AI score, from 0 to 1') }}
        y={{ domain: [0, tallest * 1.06], ticks: [], grid: false, gutter: 12 }}>
        {({ X, Y, m, h }) => {
          const r = Math.max(1.3, Math.min((X(BW) - X(0)) / 2, (Y(0) - Y(1)) / 2) - 0.3)
          return <>
            <rect className="vd-zone" x={X(zt)} y={m.t} width={X(dom[1]) - X(zt)} height={h - m.b - m.t} />
            <line className="vd-thr" x1={X(zt)} x2={X(zt)} y1={m.t} y2={h - m.b} />
            <text className="mark-note" x={X(zt) - 8} y={m.t + 12} textAnchor="end">{L(`門檻 ${thr}`, `threshold ${thr}`)}</text>
            <text className="mark-note" x={X(zt) + 8} y={m.t + 12}>{L('判成棕矮星', 'flagged')}</text>
            {stars.map((s, j) => <circle key={j} cx={X(s.bx)} cy={Y(s.by)} r={s.score >= thr ? Math.max(r, 4.5) : r} fill={s.score >= thr ? COL.bad : COL.known} />)}
            {pos.map((p) => (
              <g key={p.id}>
                <line className="vd-stem" x1={X(p.z)} x2={X(p.z)} y1={Y(p.by)} y2={h - m.b} />
                <rect x={X(p.z) - 6} y={Y(p.by) - 6} width="12" height="12" rx="2" fill={COL.good} transform={`rotate(45 ${X(p.z)} ${Y(p.by)})`} />
                <text className="mark-label vd-halo" x={X(p.z) - 14} y={Y(p.by) + 5} textAnchor="end">{p.name}</text>
              </g>
            ))}
          </>
        }}
      </Plot>
    </ChartCard>
  )
}

// ---- (d) variable stars: brightness per pass, and R Draconis against the AAVSO ephemeris -----------------------
function Variables({ va, mira }) {
  const ids = ['rdra', 'rwaur', 'barnard'].filter((k) => va.targets[k]?.passes?.length)
  const short = { rdra: L('天龍座 R', 'R Dra'), rwaur: L('御夫座 RW', 'RW Aur'), barnard: L('巴納德星', 'Barnard’s') }
  const full = TARGET()
  const month = (mjd) => mjdDate(mjd).toISOString().slice(0, 7)
  const found = ['rdra', 'rwaur'].filter((k) => va.targets[k]?.flagged).length
  const control = va.targets.barnard
  const nPass = Math.max(0, ...ids.map((k) => va.targets[k].passes.length), ...(mira?.passes || []).map((q) => q.pass + 1))
  // left: one column per star, one dot per survey pass
  const dots = ids.flatMap((k, j) => va.targets[k].passes.map((p) => ({
    x: j + (p.k - (va.targets[k].passes.length - 1) / 2) * 0.22, y: p.rel, err: p.err, k: p.k, r: 9,
    tip: `${full[k]} · ${L(`第 ${p.k + 1} 輪`, `pass ${p.k + 1}`)}${L('：', ': ')}×${f2(p.rel)}`,
    hint: `${month(p.mjd)} · ±${f2(p.err)}${k === 'barnard' ? L(' · 對照組，本來就不變', ' · the control: it does not vary') : ''}`,
  })))
  const yd = extent(dots.flatMap((d) => [d.y - d.err, d.y + d.err]), 0.12, true)
  const yt = [0.5, 0.6, 0.7, 0.8, 1, 1.2, 1.4, 1.7, 2].filter((t) => t > yd[0] && t < yd[1])
  // right: R Draconis, pulsation phase from the AAVSO / VSX ephemeris
  const fits = Object.entries(mira?.sinusoid || {})
  const amp = Math.max(0.3, ...fits.map(([, s]) => s.amplitude), ...(mira?.passes || []).map((q) => Math.abs(q.rel_brightness - 1)))
  const curve = (s, X, Y) => Array.from({ length: 61 }, (_, i) => { const ph = i / 60; return `${i ? 'L' : 'M'}${X(ph).toFixed(1)} ${Y(1 + s.amplitude * Math.cos(2 * Math.PI * (ph - s.phase_of_max))).toFixed(1)}` }).join(' ')
  const phasePts = mira ? [
    ...mira.passes.filter((q) => q.rel_brightness != null).map((q) => ({
      x: q.phase, y: q.rel_brightness, k: q.pass, r: 10,
      tip: `${L(`第 ${q.pass + 1} 輪`, `Pass ${q.pass + 1}`)} · ${L('相位', 'phase')} ${f2(q.phase)}${L('：', ': ')}×${f2(q.rel_brightness)}`, hint: month(q.mjd) })),
    ...fits.map(([d, s]) => ({ x: s.phase_of_max, y: 1 + s.amplitude, fit: d, r: 8,
      tip: `${d} ${L('的正弦擬合', 'sinusoid fit')}`, hint: L(`最亮在相位 ${f2(s.phase_of_max)}，振幅 ±${Math.round(s.amplitude * 100)}%`, `brightest at phase ${f2(s.phase_of_max)}, amplitude ±${Math.round(s.amplitude * 100)}%`) })),
  ] : []
  return (
    <ChartCard
      title={L('變星：程式自己找到的', 'Variable stars, found by the program')}
      take={<>
        {L('兩顆目標變星找到 ', 'Of the two variable targets, ')}<b>{found} / 2</b>{L('，不變的對照組巴納德星', ' were found; the steady control, Barnard’s Star, was ')}{control?.flagged ? L('被誤判', 'wrongly flagged') : L('沒有被誤判', 'not flagged')}{L('；但星表上檢查得到的 ', '; but of the ')}{va.catalogued.searched}{L(' 顆變星只找回 ', ' catalogued variables that could be checked, only ')}<b>{va.catalogued.flagged}</b>{L(' 顆。', ' were recovered.')}
      </>}
      legend={[
        ...Array.from({ length: nPass }, (_, k) => ({ c: COL.pass[k], label: L(`第 ${k + 1} 輪巡天`, `Survey pass ${k + 1}`) })),
        ...(fits.length ? [{ line: true, c: COL.ink3, label: L('各偵測器的正弦擬合（▼ 最亮處）', 'Sinusoid fit per detector (▼ its maximum)') }] : []),
      ]}
      more={<>
        <p>{L(`沒有告訴程式變星在哪裡。${va.fields} 片天空共檢查 ${va.n_searched} 顆星，候選 ${va.n_candidates} 個，其中星表說不變的（假警報）${va.by_status.catalogued_constant} 個。`, `The program was not told where the variables are. ${va.n_searched} stars checked in ${va.fields} fields; ${va.n_candidates} candidates, of which the catalogues call ${va.by_status.catalogued_constant} constant (false alarms).`)}</p>
        <p>{L(`限制：沒找回的那些是變化幅度不到約 8% 或週期很短的星，3 到 4 輪巡天量不出來。很亮的星會飽和，亮度改用 PSF 外圍的光量。`, `Limit: the ones not recovered vary by under about 8% or on short periods, which 3 or 4 passes cannot show. Very bright stars saturate, so their brightness comes from the wings of the PSF.`)}</p>
        {mira && <p>{L(`天龍座 R 的相位圖：VSX 週期 ${mira.vsx.period_d} 天，相位 0 是可見光最亮。最接近極大的一輪最亮、接近極小的一輪最暗${mira.order_agrees ? '（順序一致）' : '（順序不一致）'}；灰線是各偵測器對 SPHEREx 資料的正弦擬合，紅外線極大在相位 ${fits.map(([, s]) => f2(s.phase_of_max)).join('、')}。兩張圖的量法不同（各輪亮度：各偵測器加權平均；相位圖：各偵測器的中位數），所以數值不完全一樣。`, `The phase plot of R Draconis: the VSX period is ${mira.vsx.period_d} d and phase 0 is the visual maximum. The pass nearest maximum is brightest and the one nearest minimum faintest (${mira.order_agrees ? 'the order agrees' : 'the order disagrees'}); grey lines are sinusoid fits to the SPHEREx points of each detector, with the infrared maximum at phase ${fits.map(([, s]) => f2(s.phase_of_max)).join(', ')}. The two plots measure brightness differently (per-pass plot: weighted mean of the detectors; phase plot: their median), so the values differ a little.`)}</p>}
      </>}>
      <div className="vd-two">
        {ids.length > 0 && <div>
          <p className="vd-sub">{L('每一輪的亮度（相對於自己的平均）', 'Brightness in each pass (relative to its own mean)')}</p>
          <Plot height={240} points={dots} label={L('三顆星各輪巡天的相對亮度', 'Relative brightness of three stars in each survey pass')}
            x={{ domain: [-0.6, ids.length - 0.4], ticks: ids.map((_, j) => j), fmt: (j) => short[ids[j]] ?? '' }}
            y={{ domain: yd, log: true, ticks: yt, fmt: (t) => `×${t}`, gutter: 44 }}>
            {({ X, Y, m, w }) => <>
              <line className="vd-ref" x1={m.l} x2={w - m.r} y1={Y(1)} y2={Y(1)} />
              {ids.includes('barnard') && <text className="mark-note" x={X(ids.indexOf('barnard'))} y={m.t + 12} textAnchor="middle">{L('對照組', 'control')}</text>}
              {dots.map((d, j) => (
                <g key={j}>
                  <line className="vd-err" x1={X(d.x)} x2={X(d.x)} y1={Y(d.y - d.err)} y2={Y(d.y + d.err)} />
                  <circle cx={X(d.x)} cy={Y(d.y)} r="6" fill={COL.pass[d.k]} />
                </g>
              ))}
            </>}
          </Plot>
        </div>}
        {mira && <div>
          <p className="vd-sub">{L('天龍座 R 對照 AAVSO 星曆', 'R Draconis against the AAVSO ephemeris')}</p>
          <Plot height={240} points={phasePts} label={L('天龍座 R：亮度對脈動相位', 'R Draconis: brightness against pulsation phase')}
            x={{ domain: [0, 1], ticks: [0, 0.25, 0.5, 0.75, 1], label: L('相位（0 = 可見光最亮）', 'Phase (0 = visual maximum)') }}
            y={{ domain: [1 - amp * 1.12, 1 + amp * 1.12], ticks: niceTicks(1 - amp, 1 + amp, 4), fmt: (t) => `×${t}`, gutter: 44 }}>
            {({ X, Y }) => <>
              {fits.map(([d, s]) => <path key={d} className="vd-curve" d={curve(s, X, Y)} />)}
              {phasePts.filter((p) => p.fit).map((p) => <path key={p.fit} d={`M${X(p.x) - 5} ${Y(p.y) - 9}h10l-5 8z`} fill={COL.ink2} />)}
              {phasePts.filter((p) => !p.fit).map((p) => <circle key={p.k} cx={X(p.x)} cy={Y(p.y)} r="7" fill={COL.pass[p.k]} stroke={COL.ink} strokeWidth="1.5" />)}
            </>}
          </Plot>
        </div>}
      </div>
      <Meter value={va.catalogued.flagged} hi={va.catalogued.searched} c={COL.bad} text={`${va.catalogued.flagged} / ${va.catalogued.searched}`}
        label={L('星表列出、而且檢查得到的變星，找回', 'Catalogued variables that could be checked: recovered')} />
    </ChartCard>
  )
}

// ---- (e) false alarms, field by field -------------------------------------------------------------------------
// Unidentified fast tracks per field before bright-star residuals were kept out of the linking step (sxlib/analyze.py,
// static_repeaters): a record of that one run, which no file keeps.
const TRACKS_BEFORE_FIX = { rdra: 14, epsindi: 21, barnard: 2, wise0855: 0, rwaur: 0, cybele: 1, taurus: 0 }
const eclLat = (ra, dec) => { const r = Math.PI / 180, e = 23.4393 * r; return Math.asin(Math.sin(dec * r) * Math.cos(e) - Math.cos(dec * r) * Math.sin(e) * Math.sin(ra * r)) / r }
function FalseAlarms({ v, fields }) {
  const [sel, setSel] = useState(null)
  const veto = v.static_veto || {}, movers = v.false_movers_by_field || {}, vars = v.variables?.by_field || {}
  const rows = Object.keys(veto).map((id) => {
    const f = fields?.[id]
    return { id, f, name: fieldLabel(id, f), lat: f ? eclLat(f.ra, f.dec) : null }
  }).sort((a, b) => Math.abs(b.lat ?? 0) - Math.abs(a.lat ?? 0))
  const cols = [
    { k: 'was', head: [L('修正前', 'Tracks'), L('的軌跡', 'before fix')], name: L('修正前的未辨識軌跡', 'unidentified tracks before the fix'), get: (r) => TRACKS_BEFORE_FIX[r.id] },
    { k: 'now', head: [L('未辨識', 'Tracks'), L('軌跡', 'now')], name: L('現在的未辨識軌跡', 'unidentified tracks now'), get: (r) => veto[r.id] },
    { k: 'pm', head: [L('假的', 'False'), L('移動星', 'movers')], name: L('星表說不動的移動星', 'movers the catalogues call static'), get: (r) => movers[r.id] },
    { k: 'var', head: [L('假的', 'False'), L('變星', 'variables')], name: L('星表說不變的變星候選', 'variable candidates the catalogues call constant'), get: (r) => vars[r.id]?.catalogued_constant },
  ]
  const n = rows.length
  const cells = rows.flatMap((r, i) => cols.map((c, j) => {
    const val = c.get(r)
    return {
      x: j, y: n - 1 - i, r: 14, row: r, col: c, val,
      tip: `${r.name}${L('：', ': ')}${val == null ? L('沒有做這項檢查', 'not checked') : `${val} ${L('個', '')}`.trim()}`,
      hint: `${c.name}${r.lat != null ? ` · ${L('黃緯', 'ecliptic latitude')} ${r.lat.toFixed(0)}°` : ''}${c.k === 'now' && r.f ? ` · ${L(`已知小行星 ${r.f.n_known} 顆`, `${r.f.n_known} known asteroids`)}` : ''}`,
    }
  }))
  const nowTotal = rows.reduce((a, r) => a + (veto[r.id] || 0), 0), wasTotal = rows.reduce((a, r) => a + (TRACKS_BEFORE_FIX[r.id] || 0), 0)
  const onEcliptic = nowTotal > 0 && rows.every((r) => !veto[r.id] || (r.lat != null && Math.abs(r.lat) < 10))
  const st = v.xepoch?.static
  return (
    <ChartCard
      title={L('假警報：一片一片天空數', 'False alarms, field by field')}
      take={<>
        {L(`${n} 片天空裡，未辨識的軌跡從修正前的 ${wasTotal} 條降到 `, `Across ${n} fields, unidentified tracks fell from ${wasTotal} before the fix to `)}<b>{nowTotal}</b>{L(' 條', '')}{onEcliptic && L('（在黃道上，可能是真的小行星）', ' (on the ecliptic, so possibly a real asteroid)')}
        {L('；假的移動星 ', '; false movers: ')}<b>{v.false_movers_in_fields ?? '–'}</b>{L(' 個、假的變星 ', ', false variables: ')}<b>{v.variables?.by_status?.catalogued_constant ?? '–'}</b>{L(' 個。', '.')}
      </>}
      legend={[
        { c: COL.good, hollow: true, label: L('0：一個都沒有', '0: none') },
        { c: COL.bad, label: L('紅底數字：有幾個', 'Red: that many') },
        { c: COL.ink3, line: true, label: L('沒有做這項檢查', 'not checked') },
      ]}
      more={<>
        <p>{L('軌跡：遠離黃道的天空幾乎沒有小行星，所以那裡的「未辨識移動天體」就是假軌跡的實測數量；由上到下，離黃道越來越近。', 'Tracks: fields far from the ecliptic hold almost no asteroids, so "unidentified movers" there measure the false-track rate; from top to bottom the fields get closer to the ecliptic.')}</p>
        <p>{L('修正：亮星和飽和星的相減殘差會在同一個位置反覆出現好幾天。夠快、能被連成軌跡的太陽系天體（每小時至少 0.5″）不可能在 1.6 像素內停留 1.5 天，所以這種偵測不列入連結。65 Cybele 天區的 5 顆已知小行星全部保留。', 'The fix: subtraction residuals of bright and saturated stars recur at one position for days. Nothing in the Solar System fast enough for the linking step (at least 0.5″ per hour) can stay within 1.6 pixels for 1.5 days, so such detections are left out. All five known asteroids of the 65 Cybele field are kept.')}</p>
        {st && <p>{L(`和 CatWISE 比對時，Gaia 說不動的 ${st.n.toLocaleString()} 顆星（其中 ${st.n_isolated.toLocaleString()} 顆夠孤立、可以檢查）被標成移動星的有 ${st.flagged} 顆。`, `Against CatWISE: of ${st.n.toLocaleString()} stars Gaia calls static (${st.n_isolated.toLocaleString()} isolated enough to check), ${st.flagged} were flagged as movers.`)}</p>}
      </>}>
      <Plot height={64 + 32 * n} points={cells} onPick={(p) => setSel(p.row)} label={L('各片天空的假警報數', 'False alarms in each analysed field')}
        x={{ domain: [-0.3, cols.length - 0.65], ticks: [] }}
        y={{ domain: [-0.6, n + 0.75], ticks: rows.map((_, i) => n - 1 - i), fmt: (t) => rows[n - 1 - t]?.name ?? '', gutter: 104 }}>
        {({ X, Y }) => <>
          {cols.map((c, j) => <text key={c.k} className="mark-note" x={X(j)} y={Y(n + 0.15)} textAnchor="middle">{c.head.map((t, q) => <tspan key={q} x={X(j)} dy={q ? 15 : 0}>{t}</tspan>)}</text>)}
          {cells.map((c, j) => (
            <g key={j} className={c.col.k === 'was' ? 'vd-was' : ''}>
              {c.val == null ? <circle className="vd-dot-none" cx={X(c.x)} cy={Y(c.y)} r="11" />
                : c.val > 0 ? <circle cx={X(c.x)} cy={Y(c.y)} r="12" fill={COL.bad} />
                  : <circle className="vd-dot-ring" cx={X(c.x)} cy={Y(c.y)} r="11" />}
              <text className={`vd-count ${c.val == null ? 'none' : c.val > 0 ? 'some' : 'zero'}`} x={X(c.x)} y={Y(c.y) + 5} textAnchor="middle">{c.val == null ? '–' : c.val}</text>
            </g>
          ))}
        </>}
      </Plot>
      <Picked idle={L('點一格，可以打開那片天空。', 'Click a cell to open that field.')}>
        {sel && <>
          <b>{sel.name}</b>
          <span>{cols.map((c) => `${c.head.join(L('', ' '))} ${c.get(sel) ?? '–'}`).join(' · ')}</span>
          {sel.f && <a href={`#/field/${encodeURIComponent(sel.id)}`}>{L('打開這片天空 →', 'Open this field →')}</a>}
        </>}
      </Picked>
    </ChartCard>
  )
}

// ---- (f) the three challenge targets, found blind -------------------------------------------------------------
function Targets({ v }) {
  const [sel, setSel] = useState(null)
  const names = TARGET(), short = { ...names, barnard: L('巴納德星', 'Barnard’s'), epsindi: L('天苑增三 B', 'Eps Indi B') }
  const tg = v.targets || []
  const found = tg.filter((t) => t.found)
  const diffs = found.map((t) => Math.abs(t.pm - t.pm_cat) / t.pm_cat)
  const top = Math.max(1, ...tg.flatMap((t) => [t.pm_cat, t.pm || 0])) * 1.2
  const points = tg.flatMap((t, j) => [
    { x: j - 0.2, y: t.pm_cat, r: 0, t, tip: `${names[t.id] || t.id}${L('：星表 ', ': catalogue ')}${f2(t.pm_cat)}${perYr()}`, hint: L('Gaia／文獻的自行', 'the proper motion from Gaia or the literature') },
    { x: j + 0.2, y: t.found ? t.pm : 0, r: 0, t, tip: `${names[t.id] || t.id}${L('：', ': ')}${t.found ? `${L('量到 ', 'measured ')}${f2(t.pm)}${perYr()}` : L('沒找到', 'missed')}`,
      hint: t.found ? L(`和星表差 ${Math.round(100 * Math.abs(t.pm - t.pm_cat) / t.pm_cat)}%`, `${Math.round(100 * Math.abs(t.pm - t.pm_cat) / t.pm_cat)}% from the catalogue`) + (t.bd_score != null ? L(` · 光譜 AI ${f2(t.bd_score)}`, ` · spectrum AI ${f2(t.bd_score)}`) : '') : '' },
  ])
  return (
    <ChartCard
      title={L('三個挑戰目標：不看星表也找到', 'The three challenge targets, found blind')}
      take={<>
        {L('三個會移動的挑戰目標找到 ', 'Of the three moving challenge targets, ')}<b>{found.length} / {tg.length}</b>
        {diffs.length > 0 && L(`；量到的自行和星表差 ${Math.round(100 * Math.min(...diffs))}–${Math.round(100 * Math.max(...diffs))}%`, ` were found; the measured motion is within ${Math.round(100 * Math.min(...diffs))}–${Math.round(100 * Math.max(...diffs))}% of the catalogue`)}{L('。', '.')}
      </>}
      legend={[{ c: COL.known, sq: true, label: L('星表的自行', 'Catalogue proper motion') }, { c: COL.good, sq: true, label: L('SPHEREx 一年量到的', 'Measured from one year of SPHEREx') }]}
      more={<p>{L(`搜尋時不看星表，之後才拿星表來比對。${v.fields_searched} 片天空裡，星表說不會動、卻被標成移動星的假警報：${v.false_movers_in_fields} 個。${found.filter((t) => t.bd_score != null).length ? `沿著量到的軌跡取光譜，光譜 AI 的分數：${found.filter((t) => t.bd_score != null).map((t) => `${names[t.id]} ${f2(t.bd_score)}`).join('、')}。` : ''}`, `The search does not look at catalogues; they only label the result afterwards. Across ${v.fields_searched} fields, movers the catalogues call static (false alarms): ${v.false_movers_in_fields}. ${found.filter((t) => t.bd_score != null).length ? `Spectrum AI scores along the measured tracks: ${found.filter((t) => t.bd_score != null).map((t) => `${names[t.id]} ${f2(t.bd_score)}`).join(', ')}.` : ''}`)}</p>}>
      <Plot height={264} points={points} onPick={(p) => setSel(p.t)} label={L('三個挑戰目標：量到的自行對星表', 'Three challenge targets: measured proper motion against the catalogue')}
        x={{ domain: [-0.6, tg.length - 0.4], ticks: [] }}
        y={{ domain: [0, top], label: L('每年移動（角秒）', 'Motion per year (arcsec)'), fmt: (t) => `${t}″`, gutter: 44 }}>
        {({ X, Y, h, m, hov, narrow }) => {
          const bw = Math.max(10, Math.abs(X(1) - X(0)) * 0.3)
          return <>
            {points.map((p, j) => (
              <g key={j} opacity={hov == null || hov === j ? 1 : 0.55}>
                <rect x={X(p.x) - bw / 2} y={Y(p.y)} width={bw} height={Math.max(1, Y(0) - Y(p.y))} rx="3" fill={j % 2 ? COL.good : COL.known} />
                <text className={narrow ? 'mark-note' : 'mark-label'} x={X(p.x)} y={Y(p.y) - 6} textAnchor="middle">{j % 2 && !p.t.found ? '—' : f2(p.y, narrow ? 1 : 2)}</text>
              </g>
            ))}
            <XTicks X={X} h={h} m={m} at={tg.map((_, j) => j)} labels={tg.map((t) => (narrow ? short[t.id] : names[t.id]) || t.id)} />
          </>
        }}
      </Plot>
      <Picked idle={L('點一組長條，可以打開那個目標。', 'Click a pair of bars to open that target.')}>
        {sel && <>
          <b>{names[sel.id] || sel.id}</b>
          <span>{L('星表', 'catalogue')} {f2(sel.pm_cat)}{perYr()} · {sel.found ? <>{L('量到', 'measured')} {f2(sel.pm)}{perYr()}</> : L('沒找到', 'missed')}</span>
          <a href={`#/target/${sel.id}`}>{L('打開這個目標 →', 'Open this target →')}</a>
        </>}
      </Picked>
    </ChartCard>
  )
}

/** The dashboard: six chart cards in a grid. */
export function Validation() {
  const v = useValidation()
  const [fields, setFields] = useState(null)
  useEffect(() => { api('/api/fields').then((fs) => setFields(Object.fromEntries(fs.map((f) => [f.id, f])))).catch(() => setFields({})) }, [])
  if (!v) return v === false ? <p className="hint" role="status">{L('驗證資料讀不到，請稍後再試。', 'The validation data could not be loaded; please try again later.')}</p> : null
  return (
    <div className="vd chart-grid">
      {v.known_stars?.stars?.length > 0 && <KnownStars ks={v.known_stars} />}
      {(v.xepoch || v.known_stars) && <Recovery v={v} />}
      {v.spectral && <SpectrumScores sp={v.spectral} fields={fields} />}
      {v.variables && <Variables va={v.variables} mira={v.mira} />}
      {v.static_veto && <FalseAlarms v={v} fields={fields} />}
      {v.targets?.length > 0 && <Targets v={v} />}
      {/* sections added after the challenge's Resources were published (2026-11-13): each in its own file */}
      <ValDr1 />
      <ValSpectro />
      <ValGaia />
      <ValByw />
      <ValNeossat />
      <ValStreak />
    </div>
  )
}
