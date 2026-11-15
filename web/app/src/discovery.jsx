// Discovery: did we really search for a planet? One chart per result (UPGRADE_PLAN.md §9, D8): the search as a
// funnel, the dwarf-planet distances against JPL, the survey map, every track against the eight checks, the chance
// test, the depth reached, and how discoveries are really reported. Each chart carries one sentence; the longer
// explanations are folded under it. New text is written as L(zh, en); the older strings are in the catalogue.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { translate, t } from '@sx/i18n/core.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api, mjdToIso, reducedMotion } from './lib.js'
import { useReveal } from './reveal.js'
import { Accent } from './fx.jsx'
import { useManuscript } from './manuscript.jsx'
import { Bars, ChartCard, COL, Legend, Meter, Plot, extent, niceTicks } from './charts.jsx'
import './discovery.css'
import { P9_PATH } from './sky.js'

// circular-orbit rate (arcsec/yr) at d au, as sxlib.link.circular_pm
const PM = (d) => 206264.8 * 2 * Math.PI * d ** -1.5
const DWARF = { Makemake: '鳥神星 Makemake', Haumea: '妊神星 Haumea', Eris: '鬩神星 Eris' }
const REGION = { A: 'A 銀河面交會', B: 'B 遠日點附近', D: 'D 2025 年 IRAS/AKARI 候選' }
const CHECK = [
  ['passes', '至少三輪巡天', '兩輪分不開距離與軌道運動'],
  ['fit', '視差＋軌道運動擬合良好', '殘差 ≤ 4″'],
  ['bound', '速度符合束縛軌道', '比那個距離的逃逸速度慢'],
  ['not_static', '不是靜止的殘差', '其他輪巡天的同一位置沒有亮'],
  ['range', '距離不在搜尋範圍邊緣', '30–3000 AU'],
  ['flux', '每輪的亮度一致', '同一個天體的亮度不會忽明忽暗'],
  ['excess', '比巧合多', '打亂各輪的時間後，不該也連出一樣多的軌跡'],
  ['not_known', '不是已知天體', 'JPL 已知小行星與彗星，30″ 內'],
]
const CHK = Object.fromEntries(CHECK.map(([k, label, sub]) => [k, { label, sub }]))
// the order the matrix shows them: the seven checks made on one track, then the one made on all tracks together
const ORDER = ['passes', 'fit', 'bound', 'not_static', 'range', 'flux', 'not_known', 'excess']
// why a track stops at a check, in a few words (funnel and map)
const WHY = {
  passes: ['不足三輪', 'under three passes'], fit: ['擬合不好', 'poor fit'], bound: ['速度太快', 'too fast'], not_static: ['靜止的殘差', 'static residual'],
  range: ['在範圍邊緣', 'edge of the range'], flux: ['亮度不一致', 'uneven brightness'], not_known: ['已知天體', 'known object'], excess: ['和巧合一樣多', 'no more than chance'],
}
// Brown & Batygin 2021 median orbit on the sky (DISCOVERY_NEWS.md section 4), shared with the home page's map
const PATH = P9_PATH

const NEWS = [
  ['2019', 'Gennadiy Borisov', '業餘天文學家用自製的 65 公分望遠鏡發現第二個星際天體 2I/Borisov。', '送到國際天文聯合會的小行星中心（MPC）確認頁，全球望遠鏡追蹤後才給編號。'],
  ['2021', 'Bernardinelli 與 Bernstein', '研究生在暗能量巡天（DES）六年的檔案影像裡找到巨型彗星 C/2014 UN271。', '和我們最像：用別人巡天的檔案資料、串多個時間的偵測、定出軌道。'],
  ['2021', '印度中小學生', '「學生發現 18 顆小行星」：用 Pan-STARRS 影像找移動天體。', '其實是 MPC 給的暫定編號；正式編號要好幾年，NASA 只是合作單位。'],
  ['2024', 'Backyard Worlds 志工', '名字裡有「Planet 9」的公民科學計畫，找到一顆超高速棕矮星。', '找到的是太陽系外的棕矮星，不是第九行星；確認靠 Keck 光譜與論文。'],
  ['2025', 'Phan 等（清華大學）', '在 IRAS（1983）與 AKARI（2006）紅外線資料裡找到一個 Planet Nine 候選。', '是真的論文，但只是候選，到現在沒有後續確認——我們的 D 區就是它外推的位置。'],
]

const STEPS = [
  ['先量已知天體', '用已知小行星證明我們量的位置可信。我們的位置和 JPL 預測的中位數差約 0.6″（約 0.1 像素）。'],
  ['排除已知天體', '用 MPC 的 MPChecker 或 JPL 的 sb_ident 確認不是已知的小行星或彗星。'],
  ['準備觀測紀錄', '以 MPC 的 ADES 格式寫下每次觀測的時間、位置、誤差與亮度。SPHEREx 在 MPC 的觀測站代碼是 288；我們是「量測者」，不是觀測者。'],
  ['先聯絡 MPC', 'SPHEREx 不在 MPC 的檔案資料名單上，第三方量測要先透過 MPC 服務台詢問規定。'],
  ['請別的望遠鏡確認', '附上未來的預測位置與誤差範圍。暗的遠方天體需要 4–8 公尺級望遠鏡（例如 DECam、Subaru）；Rubin 天文台 2026 年 6 月開始的巡天也可以比對。'],
  ['寫成論文', '真正被承認的「發現」，是 MPC 編號或同儕審查的論文，而不是新聞稿。'],
]

const BG = 'var(--sx-surface)'      // the card behind every chart: the fill of a hollow mark
const jump = (id) => document.getElementById(id)?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
function useMedia(q) {
  const [on, setOn] = useState(() => typeof window !== 'undefined' && window.matchMedia(q).matches)
  useEffect(() => {
    const m = window.matchMedia(q), f = () => setOn(m.matches)
    f(); m.addEventListener('change', f)
    return () => m.removeEventListener('change', f)
  }, [q])
  return on
}
/** Width of a box that may mount late (after the data arrives): [callback ref, width in px]. */
function useWidth() {
  const [w, setW] = useState(0)
  const ro = useRef(null)
  const ref = useCallback((el) => {
    ro.current?.disconnect(); ro.current = null
    if (!el || typeof ResizeObserver === 'undefined') return
    ro.current = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.current.observe(el)
  }, [])
  return [ref, w]
}
/** The first check (in ORDER) a track fails; ORDER.length when it passes them all. */
const stageOf = (c) => { const j = ORDER.findIndex((k) => c.checks[k] === false); return j < 0 ? ORDER.length : j }
const signed = (v, digits = 2) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}`

// ---- hero: the search as a funnel ---------------------------------------------------------------------------------
function Funnel({ d, side }) {
  const [box, w0] = useWidth()
  const bw = w0 || 640
  const [hov, setHov] = useState(null)
  const H = side ? 440 : 480
  if (!d) return <div ref={box} className="skel-card" style={{ height: H }} aria-hidden="true" />
  const sv = d.survey, raw = d.n_raw, pass = d.n_pass_checks, live = d.candidates.filter((c) => c.survives).length
  const drops = Object.entries(d.rejected_by || {}).filter(([k, n]) => n && WHY[k]).map(([k, n]) => L(`${n} 條${WHY[k][0]}`, `${n} ${WHY[k][1]}`)).join(L('、', ', '))
  // n bodies of `slots` reach the stage; A counts sky fields, the others tracks (so they share one scale)
  const S = [
    { n: sv.n_fields, slots: sv.n_fields, unit: sv.n_fields, c: COL.known, to: 'dx-map', title: L('片天空搜尋完', 'sky fields searched'),
      sub: L(`預測路徑上，共 ${sv.area_deg2} 平方度`, `${sv.area_deg2} deg² along the Planet Nine path`), go: L('看搜尋了哪裡', 'see where we searched') },
    { n: raw, slots: raw, unit: raw, c: COL.accent, to: 'dx-checks', title: L('條疊加軌跡', 'stacked tracks linked'),
      sub: L('三輪巡天的疊加峰值，連成像視差的軌跡', 'stack peaks linked across three passes'), go: L('看每條軌跡的檢查', 'see the checks on every track') },
    { n: pass, slots: raw, unit: raw, c: COL.accent, to: 'dx-matrix', title: L('條通過前七項檢查', 'pass the first seven checks'),
      sub: drops, go: L('看軌跡停在哪一關', 'see where the tracks stop') },
    { n: live, slots: pass, unit: raw, c: COL.good, to: 'dx-chance', title: L('條比巧合多', 'more than chance'),
      sub: d.null ? L(`打亂時間後，平均也連出 ${d.null.total_null_mean} 條`, `shuffled times give ${d.null.total_null_mean} on average`) : '', go: L('看和巧合的比較', 'see the chance test') },
  ]
  // geometry in pixels, from the width of the box (the plot frame has no axes here)
  const x0 = side ? Math.round(bw * 0.38) : 0, W = bw - 2 - x0, rowH = (H - 16) / S.length, barH = side ? 52 : 30
  const top = (k) => 8 + k * rowH, by = (k) => top(k) + (side ? (rowH - barH) / 2 : 68)
  const u = (k) => W / S[k].unit, mark = (k) => (S[k].n === 0 ? Math.max(u(k), 14) : 0)
  const solidW = (k) => (S[k].n === 0 ? mark(k) : S[k].n * u(k))
  const pts = S.map((s, k) => ({ x: (x0 + Math.min(W, Math.max(solidW(k), 200)) / 2) / (bw - 14), y: (H - 26 - by(k)) / (H - 38), r: 0,
    tip: `${s.n} ${s.title}`, hint: `${s.sub ? `${s.sub} · ` : ''}${L('點一下：', 'Click: ')}${s.go}` }))
  return (
    <div ref={box} className="dx-funnel-plot">
      <Plot height={H} points={pts} hovered={hov}
        label={L(`搜尋的漏斗：${sv.n_fields} 片天空，${raw} 條疊加軌跡，${pass} 條通過前七項檢查，${live} 條比巧合多`, `The search as a funnel: ${sv.n_fields} sky fields, ${raw} stacked tracks, ${pass} pass the first seven checks, ${live} more than chance`)}
        x={{ domain: [0, 1], ticks: [] }} y={{ domain: [0, 1], ticks: [], grid: false, gutter: 0 }}>
        {() => <>
          {S.slice(1).map((s, j) => { const k = j + 1
            return <path key={`c${k}`} className="dx-f-flow" d={`M${x0} ${by(k - 1) + barH}H${x0 + solidW(k - 1)}L${x0 + solidW(k)} ${by(k)}H${x0}Z`} /> })}
          {S.map((s, k) => { const un = u(k), gap = un > 8 ? 2 : 1, lost = s.slots - s.n, gx = x0 + mark(k) + (s.n ? s.n * un : mark(k) ? 2 : 0), gw = lost * un
            return (
              <g key={k} className="dx-f-stage" opacity={hov == null || hov === k ? 1 : 0.6} onMouseEnter={() => setHov(k)} onMouseLeave={() => setHov(null)} onClick={() => { setHov(null); jump(s.to) }}>
                <rect x="0" y={top(k)} width={bw} height={rowH} fill="transparent" />
                {side ? <>
                  <text className="dx-f-num" x="104" y={by(k) + barH / 2 + 15} textAnchor="end">{s.n}</text>
                  <text className="dx-f-title" x="120" y={by(k) + barH / 2 - (s.sub ? 4 : -6)}>{s.title}</text>
                  {s.sub && <text className="dx-f-sub" x="120" y={by(k) + barH / 2 + 20}>{s.sub}</text>}
                </> : <>
                  <text x="0" y={top(k) + 32}><tspan className="dx-f-num">{s.n}</tspan><tspan className="dx-f-title" dx="10">{s.title}</tspan></text>
                  {s.sub && <text className="dx-f-sub" x="0" y={top(k) + 56}>{s.sub}</text>}
                </>}
                {Array.from({ length: s.n }, (_, i) => <rect key={i} x={x0 + i * un} y={by(k)} width={Math.max(1, un - gap)} height={barH} rx="2" fill={s.c} opacity={hov === k ? 1 : 0.88} />)}
                {s.n === 0 && <rect className="dx-f-zero" x={x0 + 1} y={by(k) + 1} width={mark(k) - 2} height={barH - 2} rx="2" />}
                {Array.from({ length: lost }, (_, i) => <rect key={`g${i}`} className="dx-f-lost" x={gx + i * un} y={by(k)} width={Math.max(1, un - gap)} height={barH} rx="2" />)}
                {lost > 0 && gw > 44 && <text className="dx-f-drop" x={gx + gw / 2} y={by(k) + barH / 2 + 5} textAnchor="middle">
                  {`−${lost}`}{gw > 260 && k === S.length - 1 ? ` ${translate('和巧合無法區分')}` : ''}</text>}
              </g>
            ) })}
        </>}
      </Plot>
    </div>
  )
}

// ---- step 1: real dwarf planets -----------------------------------------------------------------------------------
const UNIT = 80          // pixels per body row in the two dwarf-planet charts
function dwarfRows(list, ms) {
  return list.map((d) => {
    const s = d.single || {}, st = d.stack, r = s.r_jpl_au ?? st?.r_jpl_au
    const blind = s.blind, seeded = s.seeded?.ok ? s.seeded : null, fit = s.fit_on_body
    const best = blind || seeded || fit
    const how = blind ? '只靠 AI 分數的盲搜尋' : seeded ? '從一個偵測出發的搜尋' : fit ? '只用落在它身上的偵測擬合' : null
    const paper = ms && d.name === 'Makemake' ? { d_au: +ms.mm_d, err: +ms.mm_err, jpl: +ms.mm_jpl } : ms && d.name === 'Haumea' ? { d_au: +ms.hm_d, err: +ms.hm_err, jpl: +ms.hm_jpl } : null
    const fits = [
      blind && { key: 'blind', d_au: blind.d_au, label: '只靠 AI 分數的盲搜尋', more: L(`殘差 ${blind.rms_arcsec}″；${blind.on_body}/${blind.members} 個偵測落在它身上`, `residual ${blind.rms_arcsec}″; ${blind.on_body} of ${blind.members} detections lie on the body`) },
      seeded && { key: 'seeded', d_au: seeded.d_au, label: '從一個偵測出發的搜尋', more: L(`殘差 ${seeded.rms_arcsec}″`, `residual ${seeded.rms_arcsec}″`) },
      fit && { key: 'fit', d_au: fit.d_au, label: '只用落在它身上的偵測擬合', more: L(`殘差 ${fit.rms_arcsec}″`, `residual ${fit.rms_arcsec}″`) },
    ].filter(Boolean).map((f) => ({ ...f, pct: ((f.d_au - r) / r) * 100 }))
    if (paper && isFinite(paper.d_au)) fits.push({ key: 'paper', d_au: paper.d_au, label: L('論文採用的值', 'Value adopted in the paper'), pct: Math.sign(paper.d_au - paper.jpl) * paper.err, more: '' })
    return { d, s, st, r, best, how, fits, stHit: st?.tracks?.find((x) => x.on_body >= 2) }
  })
}
const FIT_DY = { blind: -2, seeded: 10, fit: 22, paper: 34 }     // one lane per way of fitting, so near-equal values stay apart

/** One line per body: how it was measured, or why it could not be. */
function BodyNotes({ rows }) {
  if (!rows.length) return null
  return (
    <ul className="dx-notes">
      {rows.map((x) => (
        <li key={x.d.name}><b>{DWARF[x.d.name] || x.d.name}</b>
          <span>{x.how ? t`${x.how}；${x.s.detections_on_body ?? 0} 次偵測、${(x.s.passes_with_detections || []).length} 輪巡天。` : x.s.detections_on_body === 0 ? '單張影像裡偵測不到它（太暗）。' : '單張影像的偵測不足以定出距離。'}
            {x.st && !x.stHit && !x.best && x.r < 150 && L('', ' ') + t`它在一輪巡天的兩週內，自己的軌道運動就移動約 ${Math.round(PM(x.r) * 14 / 365 / 6.15)} 個像素；目前的疊加只補償視差，是為 150 AU 以外、幾乎不動的天體設計的。`}</span></li>
      ))}
    </ul>
  )
}

function DwarfCharts({ list, loading, ms }) {
  const rows = dwarfRows(list || [], ms)
  const H = 64 + 3 * UNIT
  const intro = '海王星外的矮行星會隨著地球繞太陽而左右晃動（視差），晃得越少就越遠。我們只用 SPHEREx 半年內的三輪巡天，不看任何星表，量出它們的距離，再和 NASA JPL 的軌道比對。'
  if (loading) return <div className="dx-grid" aria-hidden="true"><div className="skel-card dx-c7" style={{ height: H + 220 }} /><div className="skel-card dx-c5" style={{ height: H + 220 }} /></div>
  if (!rows.length) return <p className="dx-note">矮行星測試的結果還在計算中。</p>
  const n = rows.length, got = rows.filter((x) => x.best)
  const worst = Math.max(0, ...rows.flatMap((x) => x.fits.filter((f) => f.key !== 'paper').map((f) => Math.abs(f.pct))))
  const far = Math.ceil(Math.max(...rows.map((x) => x.r)) / 10) * 10 + 10
  const lim = Math.max(1, Math.ceil(worst * 1.2 * 2) / 2)
  const name = (x) => translate(DWARF[x.d.name] || x.d.name)
  const missed = rows.filter((x) => !x.best), faint = missed.every((x) => x.s.detections_on_body === 0)
  const missedNote = !missed.length ? '' : faint ? L(`；${missed.map(name).join('、')} 在單張影像裡太暗，沒有量到`, `; ${missed.map(name).join(', ')} is too faint in single exposures and was not measured`)
    : L(`；${missed.map(name).join('、')} 沒有量到`, `; ${missed.map(name).join(', ')} was not measured`)
  const ways = new Set(rows.flatMap((x) => x.fits.filter((f) => f.key !== 'paper').map((f) => f.key))).size
  const paperMax = ms ? Math.max(+ms.mm_err, +ms.hm_err) : null
  const paperNote = ms ? L(`；論文採用的擬合，誤差最大 ${paperMax}%`, `; the fit adopted in the paper is off by at most ${paperMax}%`) : ''
  const yAxis = { domain: [n - 0.5, -0.5], ticks: [], grid: false, gutter: 8 }
  const ptsD = rows.map((x, k) => ({ x: x.r, y: k + 10 / UNIT, r: 12,
    tip: x.best ? `${name(x)}${L('：量到', ': measured')} ${x.best.d_au.toFixed(2)} au${L('，JPL', ', JPL')} ${x.r.toFixed(2)} au` : `${name(x)}${L('：JPL', ': JPL')} ${x.r.toFixed(2)} au${L('，沒有量到', ', not measured')}`,
    hint: x.best ? `${L('誤差', 'error')} ${x.best.d_err_pct.toFixed(2)}% · ${translate(x.how)}` : translate(x.s.detections_on_body === 0 ? '單張影像裡偵測不到它（太暗）。' : '單張影像的偵測不足以定出距離。') }))
  const ptsE = rows.flatMap((x, k) => x.fits.map((f) => ({ id: `${k}.${f.key}`, x: f.pct, y: k + FIT_DY[f.key] / UNIT, r: 9,
    tip: `${name(x)} · ${translate(f.label)}${L('：', ': ')}${f.d_au.toFixed(2)} au${L('（', ' (')}${signed(f.pct)}%${L('）', ')')}`, hint: f.more })))
  return (
    <div className="dx-grid">
      <ChartCard className="dx-c7 reveal" title={L('量到的距離，對 JPL 的距離', 'Measured distance against JPL')}
        take={L(`${got.map(name).join('、')} 量到的距離和 JPL 的值重疊在一起`, `For ${got.map(name).join(' and ')} the measured distance sits on the JPL value`) + missedNote + L('。', '.')}
        legend={[{ c: COL.known, hollow: true, label: L('JPL 軌道給的距離', 'Distance from the JPL orbit') }, { c: COL.good, label: L('SPHEREx 視差量到的距離', 'Distance from the SPHEREx parallax') }, { c: COL.bad, hollow: true, label: L('沒有量到', 'Not measured') }]}
        more={<>
          <p>{intro}</p>
          {rows.map((x) => x.st && <p key={x.d.name}><b>{DWARF[x.d.name] || x.d.name}</b>{L('：', ': ')}{x.stHit ? t`移位疊加：在 ${x.st.stacked_peaks_on_body.length} 輪巡天的疊加圖上浮現，連成 ${x.stHit.d_au.toFixed(1)} AU 的軌跡。` : x.st.stacked_peaks_on_body?.length ? t`移位疊加：在 ${x.st.stacked_peaks_on_body.length} 輪的疊加圖上出現（S/N ${x.st.stacked_peaks_on_body.map((p) => p[1]).join('、')}），但沒有連成三輪的軌跡。` : '移位疊加：疊加圖上沒有浮現。'}</p>)}
        </>}>
        <Plot height={H} points={ptsD} label={L('三顆矮行星量到的距離和 JPL 的距離', 'Measured and JPL distances of three dwarf planets')}
          x={{ domain: [0, far], label: L('距離（au）', 'Distance (au)'), grid: true }} y={yAxis}>
          {({ X, Y, hov }) => rows.map((x, k) => { const y = Y(k) + 10
            return (
              <g key={x.d.name} opacity={hov == null || hov === k ? 1 : 0.6}>
                <text className="mark-label" x={X(0) + 2} y={Y(k) - 18}>{DWARF[x.d.name] || x.d.name}</text>
                <text className={`mark-label ${x.best ? 'dx-good' : 'dx-bad'}`} x={X(far)} y={Y(k) - 18} textAnchor="end">
                  {x.best ? `${x.best.d_au.toFixed(2)} au · ${L('誤差', 'error')} ${x.best.d_err_pct.toFixed(2)}%` : `JPL ${x.r.toFixed(2)} au · ${L('沒有量到', 'not measured')}`}</text>
                <line x1={X(0)} x2={X(x.r)} y1={y} y2={y} stroke={COL.ink3} strokeOpacity=".45" strokeWidth="2" />
                <circle cx={X(x.r)} cy={y} r="10" fill="none" stroke={COL.known} strokeWidth="2.5" />
                {x.best ? <circle cx={X(x.best.d_au)} cy={y} r="5" fill={COL.good} />
                  : <path d={`M${X(x.r) - 4} ${y - 4}l8 8m0 -8l-8 8`} stroke={COL.bad} strokeWidth="2.5" strokeLinecap="round" />}
              </g>
            ) })}
        </Plot>
        <BodyNotes rows={got} />
      </ChartCard>
      <ChartCard className="dx-c5 reveal" title={L('放大看：差了多少', 'Zoomed in: how far off')}
        take={L(`${ways} 種擬合方式量到的距離，都落在 JPL 值的 ${worst.toFixed(2)}% 以內`, `All ${ways} ways of fitting land within ${worst.toFixed(2)}% of the JPL value`) + paperNote + L('。', '.')}
        legend={[{ c: COL.good, label: '只靠 AI 分數的盲搜尋' }, { c: COL.good, hollow: true, label: '從一個偵測出發的搜尋' }, { c: COL.good, sq: true, label: '只用落在它身上的偵測擬合' },
          ...(ms ? [{ c: COL.accent, label: L('論文採用的值', 'Value adopted in the paper') }] : []), { c: COL.known, line: true, label: L('JPL 的距離', 'JPL distance') }]}>
        <Plot height={H} points={ptsE} label={L('每種擬合方式量到的距離和 JPL 相差的百分比', 'Difference from JPL, in percent, for each way of fitting')}
          x={{ domain: [-lim, lim], label: L('和 JPL 的差（%）', 'Difference from JPL (%)'), grid: true, fmt: (v) => (v ? signed(v, Number.isInteger(v) ? 0 : 1) : '0') }} y={yAxis}>
          {({ X, Y, hov }) => <>
            <line x1={X(0)} x2={X(0)} y1={Y(-0.5)} y2={Y(n - 0.5)} stroke={COL.known} strokeWidth="2" strokeDasharray="6 5" />
            {rows.map((x, k) => (
              <g key={x.d.name}>
                <text className="mark-label" x={X(-lim) + 2} y={Y(k) - 18}>{DWARF[x.d.name] || x.d.name}</text>
                {!x.fits.length && <text className="mark-label dx-bad" x={X(lim)} y={Y(k) - 18} textAnchor="end">{L('沒有量到', 'not measured')}</text>}
                {x.fits.map((f) => { const cx = X(f.pct), cy = Y(k) + FIT_DY[f.key], dim = hov != null && ptsE[hov]?.id !== `${k}.${f.key}`, c = f.key === 'paper' ? COL.accent : COL.good
                  return f.key === 'fit' ? <rect key={f.key} x={cx - 6} y={cy - 6} width="12" height="12" rx="2" fill={c} opacity={dim ? 0.45 : 1} />
                    : <circle key={f.key} cx={cx} cy={cy} r="6" style={{ fill: f.key === 'seeded' ? BG : c }} stroke={c} strokeWidth="2.5" opacity={dim ? 0.45 : 1} /> })}
              </g>
            ))}
          </>}
        </Plot>
        <BodyNotes rows={missed} />
      </ChartCard>
    </div>
  )
}

// ---- step 2: where we searched ------------------------------------------------------------------------------------
const MAP_M = { l: 22 + 44, r: 14, t: 12, b: 52 }      // the plot frame's margins for the axes below (see charts.jsx)
function mapView(key, fields, w, h) {
  if (key === 'all') return { key, equal: false, xOf: (ra) => ra, raOf: (x) => x, xd: [24, 96], yd: [-56, 34] }
  const fs = fields.filter((f) => f.region === key), ras = fs.map((f) => f.ra), decs = fs.map((f) => f.dec)
  const ra0 = (Math.min(...ras) + Math.max(...ras)) / 2, dec0 = (Math.min(...decs) + Math.max(...decs)) / 2, cd = Math.cos((dec0 * Math.PI) / 180)
  const hx = ((Math.max(...ras) - Math.min(...ras)) / 2) * cd + 0.9, hy = (Math.max(...decs) - Math.min(...decs)) / 2 + 0.9
  const iw = Math.max(80, w - MAP_M.l - MAP_M.r), ih = Math.max(80, h - MAP_M.t - MAP_M.b), u = Math.max((2 * hx) / iw, (2 * hy) / ih)
  // degrees on the sky, east offset from the middle of the region: the same scale on both axes
  return { key, equal: true, xOf: (ra) => (ra - ra0) * cd, raOf: (x) => ra0 + x / cd, cd, xd: [(-u * iw) / 2, (u * iw) / 2], yd: [dec0 - (u * ih) / 2, dec0 + (u * ih) / 2] }
}

function SkyMap({ sv, rows, loading, narrow, sel, onTrack }) {
  const [box, w0] = useWidth()
  const bw = w0 || 640
  const [view, setView] = useState('all')
  const H = narrow ? 380 : 480
  const fields = sv?.fields || []
  const stat = useMemo(() => { const m = new Map(); rows.forEach((r) => { const o = m.get(r.c.field) || { n: 0, pass: 0, live: 0 }; o.n++; if (r.s >= 7) o.pass++; if (r.c.survives) o.live++; m.set(r.c.field, o) }); return m }, [rows])
  if (loading) return <div className="skel-card dx-c12" style={{ height: H + 200 }} aria-hidden="true" />
  if (!fields.length) return null
  const v = mapView(view, fields, bw, H), all = view === 'all'
  const regions = Object.entries(sv.by_region || {}).filter(([, n]) => n)
  const ph = sv.phan_2025_extrapolated
  const inView = (ra, dec) => { const x = v.xOf(ra); return x >= v.xd[0] && x <= v.xd[1] && dec >= v.yd[0] && dec <= v.yd[1] }
  const pts = [
    ...fields.filter((f) => inView(f.ra, f.dec)).map((f) => { const s = stat.get(f.id)
      return { kind: 'field', f, x: v.xOf(f.ra), y: f.dec, r: all ? 9 : 0, tip: f.id,
        hint: `${translate(REGION[f.region] || f.region)} · ${L(`${f.n_exposures} 張影像、${f.n_passes} 輪巡天`, `${f.n_exposures} exposures in ${f.n_passes} passes`)} · ${L('遮掉', 'masked')} ${(f.masked_fraction * 100).toFixed(1)}% · ${s ? L(`疊加連出 ${s.n} 條軌跡，${s.pass} 條過前七項`, `${s.n} stacked tracks, ${s.pass} pass seven checks`) : L('沒有連出軌跡', 'no stacked track')}` } }),
    ...(all ? [] : rows.map((r, k) => ({ r, k })).filter(({ r }) => inView(r.c.ra, r.c.dec)).map(({ r, k }) => ({ kind: 'track', k, x: v.xOf(r.c.ra), y: r.c.dec, r: 7,
      tip: `${L('軌跡', 'Track')} ${k + 1} · ${r.c.d_au.toFixed(0)} au`,
      hint: `${r.c.survives ? L('通過全部八項檢查，需要後續觀測', 'passes all eight checks: needs follow-up') : r.c.known ? t`已知：${r.c.known}` : r.s >= 7 ? L('通過前七項，但和巧合無法區分', 'passes seven checks, but no more than chance') : L(`停在：${WHY[ORDER[r.s]][0]}`, `stops at: ${WHY[ORDER[r.s]][1]}`)} · ${L('點一下看它的八項檢查', 'click for its eight checks')}` }))),
    ...(ph && inView(ph[0], ph[1]) ? [{ kind: 'phan', x: v.xOf(ph[0]), y: ph[1], r: 10, tip: L('2025 年 IRAS/AKARI 候選外推到現在的位置', 'The 2025 IRAS/AKARI candidate, extrapolated to today'), hint: `RA ${ph[0].toFixed(2)}° · Dec ${ph[1].toFixed(2)}°` }] : []),
  ]
  const raTicks = all ? undefined : niceTicks(v.raOf(v.xd[0]), v.raOf(v.xd[1]), narrow ? 3 : 6).map(v.xOf)
  const withTracks = fields.filter((f) => stat.get(f.id)).length, hits = fields.filter((f) => stat.get(f.id)?.live).length
  const legend = [
    { c: COL.known, line: true, label: L('Planet Nine 預測軌道的中位數（Brown & Batygin 2021）', 'Median predicted orbit of Planet Nine (Brown & Batygin 2021)') },
    { c: 'rgb(var(--c-known) / .3)', sq: true, label: L('±12° 的高機率帶', 'Its ±12° high-probability band') },
    ...(all ? [{ c: COL.accent, label: L(`搜尋過、疊加後連出軌跡的天空（${withTracks} 片）`, `Searched field with stacked tracks (${withTracks})`) }, { c: COL.accent, hollow: true, label: L(`搜尋過、沒有連出軌跡（${fields.length - withTracks} 片）`, `Searched field without any (${fields.length - withTracks})`) }]
      : [{ c: 'rgb(var(--c-accent) / .35)', sq: true, label: L('一片搜尋過的 0.5° 天空', 'One searched 0.5° field') }, { c: COL.accent, label: L('軌跡：通過前七項檢查', 'Track: passes seven checks') }, { c: COL.bad, label: L('軌跡：前七項有一項沒過', 'Track: fails one of the seven') }, { c: COL.known, label: L('軌跡：已知天體', 'Track: known object') },
        ...(hits ? [{ c: COL.good, label: L('軌跡：通過全部八項檢查', 'Track: passes all eight checks') }] : [])]),
    ...(hits ? [{ c: COL.good, label: L(`留下候選的天空（${hits} 片）`, `Field with a surviving candidate (${hits})`) }] : []),
    { c: COL.distant, label: L('2025 年 IRAS/AKARI 候選外推到現在的位置（十字）', 'The 2025 IRAS/AKARI candidate today (cross)') },
  ]
  const pick = (p) => { if (p.kind === 'field' && all) setView(p.f.region); else if (p.kind === 'track') onTrack(p.k) }
  return (
    <ChartCard className="dx-c12 reveal" title={L('搜尋了哪裡', 'Where we searched')}
      take={L(`沿 Planet Nine 的預測路徑挑了 ${sv.n_fields} 片至少有三輪巡天的天空（共 ${sv.area_deg2} 平方度），其中 ${withTracks} 片在疊加後連出軌跡。`,
        `Along the predicted path of Planet Nine we took ${sv.n_fields} fields with at least three survey passes (${sv.area_deg2} deg² in all); stacking linked tracks in ${withTracks} of them.`)}
      more={<p>Planet Nine 還沒被排除的區域，大多在北銀河面和黃道交會的地方（Brown 等 2024）。我們在 A、B 兩區沿著預測路徑、以及 2025 年 IRAS/AKARI 候選附近（D 區），挑出至少有三輪巡天的天空，每片都跑完整的 AI 管線、單張偵測的視差搜尋，以及移位疊加。</p>}>
      <div className="dx-seg" role="group" aria-label={L('放大哪一區', 'Zoom to a region')}>
        <button type="button" aria-pressed={all} onClick={() => setView('all')}>{L('全部', 'All')}<i>{sv.n_fields}</i></button>
        {regions.map(([g, n]) => <button key={g} type="button" aria-pressed={view === g} onClick={() => setView(g)}>{REGION[g] || g}<i>{n}</i></button>)}
        <span className="dx-note">{all ? L('選一區放大，或直接點一片天空', 'Pick a region to zoom in, or click a field') : L('每個點是一條疊加軌跡，點一下看它的檢查', 'Each dot is one stacked track: click it for its checks')}</span>
      </div>
      <div ref={box}>
        <Plot height={H} points={pts} onPick={pick} equal={v.equal} label="搜尋的天區位置"
          x={{ domain: v.xd, reverse: true, label: L('赤經', 'Right ascension'), grid: true, ticks: raTicks, fmt: (x) => `${+v.raOf(x).toFixed(2)}°` }}
          y={{ domain: v.yd, label: L('赤緯', 'Declination'), fmt: (y) => `${y}°`, gutter: 44 }}>
          {({ X, Y, w, h, m, hov }) => { const px = (ra, dec) => `${X(v.xOf(ra)).toFixed(1)},${Y(dec).toFixed(1)}`, hp = hov != null ? pts[hov] : null
            return <>
              <clipPath id="dx-map-clip"><rect x={m.l} y={m.t} width={w - m.l - m.r} height={h - m.t - m.b} /></clipPath>
              <g clipPath="url(#dx-map-clip)">
                <polygon className="dx-band" points={[...PATH.map(([r, dd]) => px(r, dd + 12)), ...PATH.slice().reverse().map(([r, dd]) => px(r, dd - 12))].join(' ')} />
                <polyline className="dx-p9" points={PATH.map(([r, dd]) => px(r, dd)).join(' ')} />
                {fields.map((f) => { const s = stat.get(f.id), x = X(v.xOf(f.ra)), y = Y(f.dec), on = hp?.f === f, c = s?.live ? COL.good : COL.accent
                  if (all) return <circle key={f.id} cx={x} cy={y} r={on ? 7.5 : narrow ? 4 : 5.5} style={{ fill: s ? c : BG }} stroke={s?.live ? COL.ink : c} strokeWidth="2" />
                  const hw = Math.abs(X(0.25) - X(0)), hh = Math.abs(Y(0.25) - Y(0))
                  return <rect key={f.id} x={x - hw} y={y - hh} width={2 * hw} height={2 * hh} rx="2" fill={c} fillOpacity={on ? 0.2 : 0.08} stroke={c} strokeOpacity={on ? 0.9 : 0.4} strokeWidth="1.5" /> })}
                {!all && rows.map((r, k) => inView(r.c.ra, r.c.dec) && <circle key={k} cx={X(v.xOf(r.c.ra))} cy={Y(r.c.dec)} r={sel === k || hp?.k === k ? 6 : 3.5}
                  fill={r.c.survives ? COL.good : r.c.known ? COL.known : r.s >= 7 ? COL.accent : COL.bad} stroke={sel === k ? COL.ink : 'none'} strokeWidth="2" />)}
                {ph && <path className="dx-phan" d={`M${X(v.xOf(ph[0])) - 9} ${Y(ph[1])}h18m-9 -9v18`} />}
              </g>
              {all && regions.map(([g, n]) => { const fs = fields.filter((f) => f.region === g); if (!fs.length) return null
                const cx = X(v.xOf(fs.reduce((a, f) => a + f.ra, 0) / fs.length)), cy = Y(Math.max(...fs.map((f) => f.dec)))
                return <text key={g} className="mark-label" x={cx} y={cy - 16} textAnchor="middle">{`${g} · ${n}`}</text> })}
            </> }}
        </Plot>
      </div>
      <Legend items={legend} />
    </ChartCard>
  )
}

// ---- step 3: every track against the eight checks -----------------------------------------------------------------
const ROW = 9, HEAD = 3, SUB = [-0.36, -0.18, 0, 0.18, 0.36]     // five hover targets across a cell, so a wide cell has no dead zone
const stateWord = (v) => (v === true ? L('通過', 'passed') : v === false ? L('未通過', 'failed') : L('沒有檢查', 'not checked'))
function checkValue(k, c, nul) {
  if (k === 'passes') return L(`${c.n_passes} 輪巡天`, `${c.n_passes} survey passes`)
  if (k === 'fit') return L(`擬合殘差 ${c.rms_arcsec}″`, `fit residual ${c.rms_arcsec}″`)
  if (k === 'bound') return L(`擬合的軌道運動 ${Math.hypot(...(c.pm_arcsec_yr || [0, 0])).toFixed(1)}″/年`, `fitted orbital motion ${Math.hypot(...(c.pm_arcsec_yr || [0, 0])).toFixed(1)}″/yr`)
  if (k === 'range') return L(`擬合距離 ${c.d_au} au`, `fitted distance ${c.d_au} au`)
  if (k === 'flux') return L(`各輪疊加的 S/N：${(c.points || []).map((p) => p.snr.toFixed(1)).join(' / ')}`, `stack S/N in each pass: ${(c.points || []).map((p) => p.snr.toFixed(1)).join(' / ')}`)
  if (k === 'not_known') return c.known ? t`已知：${c.known}` : ''
  if (k === 'excess') return nul ? L(`真實時間連出 ${nul.total_true} 條，打亂後平均 ${nul.total_null_mean} 條`, `${nul.total_true} tracks with true times, ${nul.total_null_mean} on average when shuffled`) : ''
  return ''
}

function Matrix({ rows, nul, sel, onSel }) {
  const n = rows.length
  const stopped = ORDER.map((_, j) => rows.filter((r) => r.s === j).length)
  const pts = rows.flatMap((r, y) => ORDER.flatMap((k, j) => { const v = r.c.checks[k]
    const tip = `${L('軌跡', 'Track')} ${y + 1} · ${j + 1}. ${translate(CHK[k].label)}${L('：', ': ')}${stateWord(v)}`, hint = [checkValue(k, r.c, nul), translate(CHK[k].sub)].filter(Boolean).join(' · ')
    return SUB.map((dx) => ({ x: j + dx, y, r: 0, row: y, col: j, tip, hint })) }))
  const yt = [...new Set([0, 9, 19, 29, 39, 49, 59, n - 1].filter((v) => v < n && (v === n - 1 || n - 1 - v > 2)))]
  return (
    <Plot height={12 + 26 + (n + HEAD) * ROW} points={pts} onPick={(p) => onSel(p.row)} className="dx-matrix"
      label={L(`${n} 條軌跡各自通過了八項檢查裡的哪幾項`, `Which of the eight checks each of the ${n} tracks passes`)}
      x={{ domain: [-0.5, ORDER.length - 0.5], ticks: ORDER.map((_, j) => j), fmt: (j) => j + 1 }}
      y={{ domain: [n - 0.5, -0.5 - HEAD], ticks: yt, fmt: (v) => v + 1, grid: false, gutter: 30, label: L('軌跡（走得越遠，排越上面）', 'Tracks (the farther one got, the higher)') }}>
      {({ X, Y, hov }) => { const cw = Math.abs(X(1) - X(0)), hp = hov != null ? pts[hov] : null
        return <>
          {ORDER.map((k, j) => stopped[j] > 0 && <text key={k} className="dx-m-stop" x={X(j)} y={Y(-0.5 - HEAD / 2) + 5} textAnchor="middle">{`−${stopped[j]}`}</text>)}
          {rows.map((r, y) => ORDER.map((k, j) => { const v = r.c.checks[k]
            return <rect key={`${y}.${j}`} x={X(j) - cw / 2 + 2} y={Y(y - 0.5) + 1} width={cw - 4} height={ROW - 2} rx="2"
              className={v === true ? 'dx-m-ok' : v === false ? (j === r.s ? 'dx-m-no' : 'dx-m-no dx-m-after') : 'dx-m-na'} /> }))}
          {hp && <rect className="dx-m-hov" x={X(hp.col) - cw / 2 + 1} y={Y(hp.row - 0.5)} width={cw - 2} height={ROW} rx="2" />}
          {sel != null && <rect className="dx-m-sel" x={X(-0.5) - 2} y={Y(sel - 0.5) - 1.5} width={X(ORDER.length - 0.5) - X(-0.5) + 4} height={ROW + 3} rx="3" />}
        </> }}
    </Plot>
  )
}

/** The three stacked positions of one track on the sky: the middle pass sits apart by the parallax. */
function TrackPlot({ c }) {
  const p0 = c.points?.[0]
  if (!p0 || c.points.length < 2) return null
  const cd = Math.cos((p0.dec * Math.PI) / 180)
  const q = c.points.map((p, k) => ({ k, p, e: (p.ra - p0.ra) * cd * 3600, n: (p.dec - p0.dec) * 3600 }))
  const pts = q.map((o) => ({ x: o.e, y: o.n, r: 11, tip: `${L(`第 ${o.k + 1} 輪`, `Pass ${o.k + 1}`)} · ${mjdToIso(o.p.mjd).slice(0, 10)}`,
    hint: `S/N ${o.p.snr.toFixed(1)} · ${L(`往${o.e < 0 ? '西' : '東'} ${Math.abs(o.e).toFixed(0)}″、往${o.n < 0 ? '南' : '北'} ${Math.abs(o.n).toFixed(0)}″`, `${Math.abs(o.e).toFixed(0)}″ ${o.e < 0 ? 'west' : 'east'}, ${Math.abs(o.n).toFixed(0)}″ ${o.n < 0 ? 'south' : 'north'}`)}` }))
  return (
    <Plot equal height={184} points={pts} label={L('這條軌跡在各輪巡天的位置', 'Where this track sits in each survey pass')}
      x={{ domain: extent(q.map((o) => o.e), 0.3), reverse: true, label: L('往東的位移（角秒）', 'Offset east (arcsec)'), grid: true, fmt: (v) => `${v}″` }}
      y={{ domain: extent(q.map((o) => o.n), 0.3), label: L('往北（角秒）', 'North (arcsec)'), fmt: (v) => `${v}″`, gutter: 52 }}>
      {({ X, Y, w }) => <>
        <polyline points={q.map((o) => `${X(o.e)},${Y(o.n)}`).join(' ')} fill="none" stroke={COL.ink3} strokeWidth="1.5" strokeDasharray="5 5" />
        {q.map((o) => { const col = COL.pass[o.k % COL.pass.length], twin = q.some((b) => b.k < o.k && Math.hypot(X(b.e) - X(o.e), Y(b.n) - Y(o.n)) < 14)
          return <g key={o.k}>
            <circle cx={X(o.e)} cy={Y(o.n)} r={twin ? 11 : 6} fill={twin ? 'none' : col} stroke={col} strokeWidth="2.5" />
            <text className="mark-label" x={X(o.e) + (X(o.e) > w * 0.6 ? -16 : 16)} y={Y(o.n) + (twin ? 28 : -10)} textAnchor={X(o.e) > w * 0.6 ? 'end' : 'start'} style={{ fill: col }}>{L(`第 ${o.k + 1} 輪`, `Pass ${o.k + 1}`)}</text>
          </g> })}
      </>}
    </Plot>
  )
}

function TrackPanel({ rows, sel, onSel, vote, voted, panel }) {
  const r = sel != null ? rows[sel] : null, c = r?.c, n = rows.length
  return (
    <div ref={panel} className={`chart-card dx-track dx-c5 ${c ? 'sel' : ''}`} aria-live="polite">
      {c ? <>
        <header>
          <h3>{c.survives ? t`候選 ${sel + 1}` : t`軌跡 ${sel + 1}`}</h3>
          <span className={`dx-pill ${c.survives ? 'warn' : ''}`}>{c.survives ? '需要後續觀測' : c.known ? t`已知：${c.known}` : c.checks.excess === false && Object.entries(c.checks).every(([k, v]) => k === 'excess' || v) ? '和巧合無法區分' : '未通過檢查'}</span>
          <div className="dx-nav">
            <button type="button" onClick={() => onSel((sel + n - 1) % n)} aria-label={L('上一條軌跡', 'Previous track')}>‹</button>
            <button type="button" onClick={() => onSel((sel + 1) % n)} aria-label={L('下一條軌跡', 'Next track')}>›</button>
            <button type="button" onClick={() => onSel(null)} aria-label={L('關掉這條軌跡', 'Close this track')}>×</button>
          </div>
        </header>
        <dl>
          <div><dt>距離</dt><dd>{c.d_au.toFixed(0)} AU</dd></div>
          <div><dt>巡天輪數</dt><dd>{c.n_passes}</dd></div>
          <div><dt>擬合殘差</dt><dd>{c.rms_arcsec.toFixed(1)}″</dd></div>
          <div><dt>方法</dt><dd>{c.method === 'stack' ? '移位疊加' : '單張偵測'}</dd></div>
        </dl>
        <p className="dx-note">{c.field} · <span>{REGION[c.region] || c.region}</span> · S/N {c.snr}</p>
        <TrackPlot c={c} />
      </> : <>
        <h3>{L('八項檢查', 'The eight checks')}</h3>
        <p className="dx-note">{L('點矩陣的任何一列，這裡會換成那條軌跡：距離、三輪巡天的位置，和每一項的結果。', 'Click any row of the matrix and this panel shows that track: its distance, its position in the three passes and the result of each check.')}</p>
      </>}
      <ol className="dx-checks">
        {ORDER.map((k, j) => { const v = c?.checks[k]
          return <li key={k} className={!c ? '' : v === true ? 'ok' : v === false ? 'no' : 'na'}><i aria-hidden="true">{j + 1}</i>
            <span><b>{CHK[k].label}</b><small>{CHK[k].sub}</small></span>{c && <em>{stateWord(v)}</em>}</li> })}
      </ol>
      {c?.survives && <>
        <p className="dx-note">預測位置（給其他望遠鏡確認用）：{Object.entries(c.predicted).map(([day, [ra, dec]]) => `${day} RA ${ra.toFixed(3)}° Dec ${dec.toFixed(3)}°`).join('；')}</p>
        {c.ades && <p className="dx-note"><a href={c.ades} download>下載 MPC ADES 草稿</a>（送出前要補上太空船位置並先聯絡 MPC）</p>}
        <div className="vote" role="group" aria-label="你的判斷">
          {[['real', '值得追蹤'], ['unsure', '不確定'], ['artifact', '假訊號']].map(([verdict, label]) => (
            <button key={verdict} className={`btn ${voted === verdict ? 'primary' : ''}`} onClick={() => vote(c, verdict)}>{label}</button>
          ))}
        </div>
      </>}
    </div>
  )
}

function Chance({ d, ms }) {
  const nul = d.null, live = d.candidates.filter((c) => c.survives).length
  const bars = [[L('真實時間', 'True times'), nul.total_true, COL.accent, '真實的時間'], [L('打亂 1', 'Shuffled 1'), nul.total_null[0], COL.ink3, '打亂時間（第一種）'], [L('打亂 2', 'Shuffled 2'), nul.total_null[1], COL.ink3, '打亂時間（第二種）']]
    .map(([label, value, c, full]) => ({ label, value, c, tip: `${translate(full)}${L('：', ': ')}${value} ${L('條軌跡', 'tracks')}`, hint: nul.total_null_mean != null ? L(`打亂後平均 ${nul.total_null_mean} 條`, `shuffled average: ${nul.total_null_mean}`) : '' }))
  return (
    <ChartCard id="dx-chance" className="dx-c12 dx-anchor reveal" title="最後一關：和巧合比較"
      take={d.chance_excess ? '真實時間連出的軌跡明顯比巧合多，多出來的才值得追蹤。' : t`真實時間連出 ${nul.total_true} 條，打亂後平均 ${nul.total_null_mean} 條：差距在隨機起伏之內，所以這些軌跡都和巧合無法區分，沒有一條可以稱為候選。`}
      more={<p>擁擠的星場裡，三輪巡天各有幾百個疊加峰值，總會有幾組剛好排成「像視差」的形狀。我們把各輪的時間標籤互換再連一次——這樣在物理上不可能是真的天體——看巧合會連出多少條。</p>}>
      <div className="dx-split">
        <Bars bars={bars} height={280} label={L('真實時間和打亂時間各連出幾條軌跡', 'Tracks linked with true and with shuffled pass times')} yLabel={L('連出的軌跡（條）', 'Tracks linked')} />
        <ul className="dx-stats">
          <li><b className={live ? 'dx-good' : ''}>{live}</b><span>{L('條軌跡能和巧合區分開', 'tracks stand out from chance')}</span></li>
          {ms?.nl_sig && <li><b>{ms.nl_sig}σ</b><span>{L('真實和打亂的差距（論文的估計）', 'gap between true and shuffled times (as estimated in the paper)')}</span></li>}
          <li><b>{d.n_pass_checks}</b><span>{L('條通過了前七項檢查，卻過不了這一關', 'tracks pass the first seven checks but not this one')}</span></li>
        </ul>
      </div>
    </ChartCard>
  )
}

// ---- limits -------------------------------------------------------------------------------------------------------
function Limits({ lim, sg, ms, loading, narrow }) {
  if (loading) return <div className="dx-grid" aria-hidden="true"><div className="skel-card dx-c7" style={{ height: 520 }} /><div className="skel-card dx-c5" style={{ height: 520 }} /></div>
  if (!lim?.m50_ab) return <p className="dx-note">疊加深度的注入測試還在計算中。</p>
  const comp = lim.completeness.map((r) => ({ ...r, g: sg?.table?.find((x) => x.mag === r.mag) }))
  const mags = comp.map((r) => r.mag), lo = Math.min(...mags, ms ? +ms.effA : 99) - 0.35, hi = Math.max(...mags) + 0.35
  const pts = comp.map((r) => ({ x: r.mag, y: r.frac * 100, r: 10,
    tip: `AB ${r.mag.toFixed(1)}${L('：找回', ': recovered')} ${r.g ? `${r.g.recovered}/${r.g.n}` : `${Math.round(r.frac * 100)}%`}`,
    hint: r.g?.median_d_err_pct != null ? L(`找回的天體，距離誤差的中位數 ${r.g.median_d_err_pct}%`, `median distance error of those recovered: ${r.g.median_d_err_pct}%`) : L('疊加後一個也沒找回', 'none recovered after stacking') }))
  const p9 = lim.p9_fraction_brighter
  return (
    <div className="dx-grid">
      <ChartCard className="dx-c7 reveal" title={L('多暗的天體還找得到', 'How faint a body we can still find')}
        take={t`在這 ${lim.area_deg2} 平方度裡，沒有比 AB 17 更亮的遠方天體（單張影像的搜尋什麼都沒找到）；到 AB ${lim.m50_ab.toFixed(1)}（移位疊加的 50% 完整度），也沒有任何能和巧合區分開的天體。`}
        legend={[{ c: COL.good, label: L('注入的模擬天體被找回的比例', 'Share of injected bodies recovered') }, { c: COL.bad, hollow: true, label: L('一個也沒找回', 'None recovered') }, { c: COL.accent, line: true, label: L('50% 完整度', '50% completeness') },
          ...(ms ? [{ c: COL.warn, line: true, label: L('銀河面附近（擁擠天區）的 50% 極限，論文的估計', '50% limit near the Galactic plane (crowded fields), as estimated in the paper') }] : [])]}
        more={<>
          <p>{t`注入真實影像的模擬遠方天體（500 與 1500 AU，帶軌道運動），被疊加後找回的比例；這三片天空不擁擠，共出現 ${sg?.false_tracks_total ?? 0} 條假軌跡。靠近銀河面的搜尋天區更擁擠，實際的完整度會比較低。`}</p>
          {lim.note && <p>{L('AB 星等是 SPHEREx 單一波段的值；Planet Nine 的 V 波段亮度分布只當粗略的參考（它的近紅外顏色未知，甲烷會讓它更暗）。', lim.note)}</p>}
        </>}>
        <Plot height={narrow ? 280 : 320} points={pts} label="不同亮度的找回比例"
          x={{ domain: [lo, hi], ticks: narrow ? mags.filter((_, j) => j % 2 === 0) : mags, fmt: (v) => v.toFixed(1), label: L('注入天體的亮度（AB 星等，越右越暗）', 'Brightness of the injected body (AB mag, fainter to the right)') }}
          y={{ domain: [0, 108], ticks: [0, 25, 50, 75, 100], fmt: (v) => `${v}%`, label: L('找回的比例', 'Recovered'), gutter: 50 }}>
          {({ X, Y, hov }) => <>
            <path className="dx-area" d={`M${X(comp[0].mag)} ${Y(0)}${comp.map((r) => `L${X(r.mag)} ${Y(r.frac * 100)}`).join('')}L${X(comp.at(-1).mag)} ${Y(0)}Z`} />
            <polyline points={comp.map((r) => `${X(r.mag)},${Y(r.frac * 100)}`).join(' ')} fill="none" stroke={COL.good} strokeWidth="2.5" strokeLinejoin="round" />
            {ms && isFinite(+ms.effA) && <g>
              <line x1={X(+ms.effA)} x2={X(+ms.effA)} y1={Y(0)} y2={Y(108)} stroke={COL.warn} strokeWidth="2" strokeDasharray="6 5" />
              <text className="mark-label dx-warn" x={X(+ms.effA) + 8} y={Y(30)}>{L(`銀河面附近 ≈ AB ${ms.effA}`, `near the plane ≈ AB ${ms.effA}`)}</text>
            </g>}
            <line x1={X(lim.m50_ab)} x2={X(lim.m50_ab)} y1={Y(0)} y2={Y(108)} stroke={COL.accent} strokeWidth="2" strokeDasharray="6 5" />
            <text className="mark-label dx-accent" x={X(lim.m50_ab) + 8} y={Y(100)}>{`50% · AB ${lim.m50_ab.toFixed(1)}`}</text>
            {comp.map((r, j) => <g key={r.mag} opacity={hov == null || hov === j ? 1 : 0.6}>
              <circle cx={X(r.mag)} cy={Y(r.frac * 100)} r="6.5" style={{ fill: r.frac > 0 ? COL.good : BG }} stroke={r.frac > 0 ? COL.good : COL.bad} strokeWidth="2.5" />
              {r.g && <text className="mark-label" x={X(r.mag)} y={Y(r.frac * 100) - 14} textAnchor="middle">{`${r.g.recovered}/${r.g.n}`}</text>}
            </g>)}
          </>}
        </Plot>
      </ChartCard>
      <figure className="chart-card dx-c5 dx-depth reveal">
        <ul className="dx-stats">
          <li><b>AB {lim.m50_ab.toFixed(1)}</b><span>{L('移位疊加的 50% 完整度（不擁擠的天區）', '50% completeness of shift-and-stack (uncrowded fields)')}</span></li>
          <li><b>{sg?.false_tracks_total ?? 0}</b><span>{L(`條假軌跡，在 ${sg?.fields?.length ?? 0} 片不擁擠的測試天空裡`, `false tracks in ${sg?.fields?.length ?? 0} uncrowded test fields`)}</span></li>
        </ul>
        {p9 != null && <>
          <Meter value={p9} lo={0} hi={1} c={COL.distant} text={`≈ ${Math.round(p9 * 100)}%`} label={L('Planet Nine 比這個極限亮的機率（粗估）', 'Chance that Planet Nine is brighter than this limit (rough)')} />
          <p className="dx-take">{t` 以 Planet Nine 的預測亮度分布（V ≈ 22.0，Brown 等 2024）粗估，只有約 ${Math.round(p9 * 100)}% 的情況會比這個極限亮——所以這次搜尋找不到它是預期中的事。`.trim()}</p>
        </>}
      </figure>
    </div>
  )
}

// ---- how discoveries are reported ---------------------------------------------------------------------------------
function Steps() {
  const [k, setK] = useState(0)
  return (
    <div className="chart-card dx-steps reveal">
      <ol className="dx-stepper">
        {STEPS.map(([h], j) => (
          <li key={h} className={j === k ? 'on' : j < k ? 'done' : ''}>
            <button type="button" aria-pressed={j === k} aria-label={`${j + 1}. ${translate(h)}`} onClick={() => setK(j)}><i aria-hidden="true">{j + 1}</i><span>{h}</span></button>
          </li>
        ))}
      </ol>
      <div className="dx-step-text" aria-live="polite"><b>{STEPS[k][0]}</b><p>{STEPS[k][1]}</p></div>
    </div>
  )
}

export default function Discovery() {
  useLanguage(); useReveal()
  const ms = useManuscript()     // the paper's numbers, so this page and the paper agree
  const side = useMedia('(min-width: 1281px)'), narrow = useMedia('(max-width: 560px)')
  const [d, setD] = useState(null)
  const [votes, setVotes] = useState({})
  const [sel, setSel] = useState(null)
  const panel = useRef()
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + (L('發現搜尋', 'Discovery search')); api('/discovery/discovery.json').then(setD).catch(() => setD(false)) }, [])
  const vote = async (c, v) => {
    const k = d.candidates.indexOf(c)
    try { await api('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ field: 'discovery', cand: k, verdict: v }) }); setVotes((o) => ({ ...o, [k]: v })) } catch { /* offline */ }
  }
  const cands = d ? d.candidates || [] : []
  // one row per track, the ones that got farthest first; a track is numbered by its row
  const rows = useMemo(() => cands.map((c, i) => ({ c, i, s: stageOf(c) })).sort((a, b) => b.s - a.s || a.i - b.i), [d])
  const live = cands.filter((c) => c.survives)
  // a surviving candidate is the news: open it without being asked
  useEffect(() => { const k = rows.findIndex((r) => r.c.survives); if (k >= 0) setSel(k) }, [rows])
  const pickRow = (k) => {
    setSel(k)
    const r = k != null && panel.current?.getBoundingClientRect()     // the panel sits beside the matrix (above it on a phone): show its head
    if (r && (r.top < 64 || r.top > window.innerHeight - 200)) jump('dx-matrix')
  }
  const dw = d ? d.dwarfs?.map((x) => x.single?.blind || x.single?.fit_on_body).filter(Boolean) : null
  const best = dw?.length ? Math.max(...dw.map((x) => x.d_err_pct)) : null
  const stopList = ORDER.map((k, j) => [k, rows.filter((r) => r.s === j).length]).filter(([, n]) => n)
    .map(([k, n]) => L(`${n} 條停在「${translate(CHK[k].label)}」`, `${n} stop at “${translate(CHK[k].label)}”`)).join(L('、', ', ')) || L('全部通過', 'all pass')
  const facts = [
    { to: 'dx-dwarfs', n: ms ? `${Math.max(+ms.mm_err, +ms.hm_err)}%` : best != null ? `< ${Math.max(0.1, Math.ceil(best * 10) / 10)}%` : '—',
      label: L(ms ? `Makemake 與 Haumea（${ms.mm_d}、${ms.hm_d} au）的最大距離誤差，只靠 SPHEREx 的視差` : '真實矮行星的距離誤差（只靠 SPHEREx 的視差）', ms ? `largest distance error for Makemake and Haumea (${ms.mm_d} and ${ms.hm_d} au), from SPHEREx parallax only` : 'distance error on real dwarf planets (SPHEREx parallax only)') },
    { to: 'dx-map', n: d ? d.survey?.area_deg2 ?? '—' : '—', label: t`平方度：沿 Planet Nine 預測路徑搜尋的 ${d ? d.survey?.n_fields ?? 0 : '—'} 片天空` },
    { to: 'dx-limits', n: d && d.limits?.m50_ab ? `AB ${d.limits.m50_ab.toFixed(1)}` : '—', label: L(`移位疊加後的 50% 偵測極限（稀疏天區${ms ? `；銀河面附近約 AB ${ms.effA}` : ''}）`, `50% detection limit after shift-and-stack, uncrowded fields${ms ? `; ≈AB ${ms.effA} near the Galactic plane` : ''}`) },
    { to: 'dx-chance', n: d ? live.length : '—', label: t`能和巧合區分開的候選（疊加連出 ${d ? d.n_raw ?? 0 : '—'} 條軌跡）` },
  ]
  return (
    <div className="discovery">
      <header className="dx-head">
        <h1>我們真的{L('', ' ')}<Accent>去找了</Accent></h1>
        <p>模型做好之後，我們用它去搜尋 Planet Nine 可能在的天空。先用三顆真實的矮行星證明方法量得出距離，再做系統性的搜尋，最後把每個候選攤開來檢查。</p>
      </header>

      {d !== false && (
        <div className="dx-hero">
          <figure className="chart-card dx-funnel">
            <Funnel d={d} side={side} />
            <figcaption>{d && (live.length
              ? <p>{L(`${d.survey.n_fields} 片天空疊加後連出 ${d.n_raw} 條軌跡，${live.length} 條通過全部八項檢查：它們是需要其他望遠鏡後續觀測的候選，還不是發現。`, `Stacking linked ${d.n_raw} tracks in ${d.survey.n_fields} fields and ${live.length} pass all eight checks: candidates that need follow-up with other telescopes, not yet discoveries.`)}</p>
              : <p>{cands.length ? t`結論：沒有留下需要追蹤的遠方天體。單張影像的搜尋在 ${d.survey.n_fields} 片天空裡沒有任何遠距軌跡；疊加後連出的 ${cands.length} 條軌跡，${d.n_pass_checks} 條通過了前七項檢查，但它們的數量和打亂時間後的巧合一樣多。` : L('這次搜尋沒有找到任何遠方天體的候選。', 'This search found no candidate distant body.')}</p>)}</figcaption>
          </figure>
          <ul className="dx-facts">
            {facts.map((f) => <li key={f.to}><button type="button" className="dx-fact" onClick={() => jump(f.to)}><b>{f.n}</b><span>{f.label}</span></button></li>)}
          </ul>
        </div>
      )}
      {d === false && <p className="dx-note dx-missing">搜尋結果還沒產生。</p>}

      <section id="dx-dwarfs" className="dx-sec" aria-labelledby="h-dw">
        <h2 id="h-dw" className="reveal">第一步：量出真實矮行星的距離</h2>
        <DwarfCharts list={d ? d.dwarfs : null} loading={d === null} ms={ms} />
      </section>

      <section id="dx-map" className="dx-sec" aria-labelledby="h-map">
        <h2 id="h-map" className="reveal">第二步：沿 Planet Nine 的預測路徑搜尋</h2>
        <div className="dx-grid">
          <SkyMap sv={d ? d.survey : null} rows={rows} loading={d === null} narrow={narrow} sel={sel} onTrack={(k) => { setSel(k); jump('dx-matrix') }} />
        </div>
      </section>

      <section id="dx-checks" className="dx-sec" aria-labelledby="h-cand">
        <h2 id="h-cand" className="reveal">第三步：每條軌跡都要通過八項檢查</h2>
        <p className="dx-lead reveal">任何一項沒過就排除。通過全部檢查的，也只是「需要其他望遠鏡後續觀測的候選」，不是發現。你可以投票決定哪個最值得追蹤。</p>
        {d === null && <div className="dx-grid" aria-hidden="true"><div className="skel-card dx-c12" style={{ height: 760 }} /></div>}
        {d && rows.length > 0 && (
          <div className="dx-grid dx-anchor" id="dx-matrix">
            <TrackPanel rows={rows} sel={sel} onSel={setSel} vote={vote} voted={sel != null ? votes[rows[sel].i] : undefined} panel={panel} />
            <ChartCard className="dx-c7 dx-matrix-card reveal" title={L(`${rows.length} 條軌跡 × 八項檢查`, `${rows.length} tracks × eight checks`)}
              take={L(`一列是一條軌跡，由左到右過八項檢查：${stopList}。`, `One row is one track, checked left to right: ${stopList}.`)}
              legend={[{ c: COL.good, sq: true, label: L('通過', 'Passed') }, { c: COL.bad, sq: true, label: L('未通過（深色是它停下來的那一項）', 'Failed (solid where the track stops)') }, { c: 'rgb(var(--c-white) / .14)', sq: true, label: L('前面已排除，沒有檢查', 'Not checked: already rejected') }]}>
              <Matrix rows={rows} nul={d.null} sel={sel} onSel={pickRow} />
            </ChartCard>
          </div>
        )}
        {d && !rows.length && <p className="dx-note">{L('這次搜尋沒有找到任何遠方天體的候選。', 'This search found no candidate distant body.')}</p>}
        {d?.null && <div className="dx-grid"><Chance d={d} ms={ms} /></div>}
      </section>

      <section id="dx-limits" className="dx-sec" aria-labelledby="h-lim">
        <h2 id="h-lim" className="reveal">沒找到，也是結果</h2>
        <Limits lim={d ? d.limits : null} sg={d ? d.stack_grid : null} ms={ms} loading={d === null} narrow={narrow} />
      </section>

      <section id="dx-news" className="dx-sec" aria-labelledby="h-news">
        <h2 id="h-news" className="reveal">新聞裡的「發現行星，上報 NASA」是怎麼回事</h2>
        <p className="dx-lead reveal">{L('沒有「上報給 NASA」的表單：太陽系的小天體是回報給小行星中心（MPC），新聞說的「發現」很多只是候選或暫定編號。', 'There is no “report to NASA” form: small Solar System bodies go to the Minor Planet Center (MPC), and many “discoveries” in the news are candidates or provisional designations.')}</p>
        <details className="chart-more dx-more reveal"><summary>{L('詳細說明', 'Details')}</summary>
          <p>其實沒有「上報給 NASA」的表單。太陽系的小天體要回報給國際天文聯合會的小行星中心（MPC，經費來自 NASA）；繞其他恆星的系外行星走 NASA 的 ExoFOP 與論文。新聞說的「發現」，很多其實是候選或暫定編號。</p></details>
        <ol className="dx-time">
          {NEWS.map(([y, who, what, how]) => <li key={who} className="reveal"><span className="dx-yr">{y}</span><b>{who}</b><p>{what}</p><small>{how}</small></li>)}
        </ol>
        <h3 className="reveal">如果真的找到候選，我們會這樣上報</h3>
        <Steps />
        <p className="dx-note dx-src reveal">資料來源整理在專案的 DISCOVERY_NEWS.md（MPC 官方文件、Brown 等 2021／2024、Phan 等 2025）。</p>
      </section>
    </div>
  )
}
