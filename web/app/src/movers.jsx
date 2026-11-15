// Automatic proper-motion candidates: the list in each field lab / quick look, and #/movers, the public review queue
// (Backyard-Worlds style: blink the first and last survey pass, then say real / artefact / not sure).
import { useEffect, useMemo, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, PASS_C, PIX, api, dataBase, mjdToIso, reducedMotion } from './lib.js'
import { Blink } from './blink.jsx'
import { skyHash } from './sky.js'
import { MoverVectors } from './motion.jsx'
import { ChartCard, COL, Meter } from './charts.jsx'
import { RecoveryChart, useValidation } from './validation.jsx'
import { FakeMover } from './wiseview.jsx'
export const STATUS = {
  new: () => [L('新的：星表裡沒有', 'New: not in the catalogues'), 'distant'],
  mismatch: () => [L('移動和星表不符', 'Motion disagrees with the catalogue'), 'warn'],
  known: () => [L('已知的移動星', 'Known mover'), 'known'],
  static: () => [L('星表說它不動（可能是假訊號）', 'Catalogue says static (likely artefact)'), 'muted'],
}
export const bdText = (s) => (s == null ? L('光譜資料不足', 'not enough spectrum')
  : s >= 0.8 ? L(`光譜像冷棕矮星（${Math.round(s * 100)}%）`, `Spectrum looks like a cold brown dwarf (${Math.round(s * 100)}%)`)
  : s >= 0.5 ? L(`光譜有點像棕矮星（${Math.round(s * 100)}%）`, `Spectrum somewhat brown-dwarf-like (${Math.round(s * 100)}%)`)
  : L(`光譜像一般恆星（棕矮星 ${Math.round(s * 100)}%）`, `Spectrum looks like a normal star (brown dwarf ${Math.round(s * 100)}%)`))

/** One candidate's facts, drawn: the shift each detector measured (arrows), how fast it moves against the catalogue
 *  (two bars), how significant the shift is (a scale). The words are a caption, not the content. */
export function MoverFacts({ c, hideCat }) {
  let [st, cls] = (STATUS[c.status] || STATUS.new)()
  // across epochs every source is in CatWISE by construction; "new" there means Gaia does not have it
  if (c.method === 'xepoch' && c.status === 'new') st = L('Gaia 沒有這顆星（CatWISE 有）', 'Not in Gaia (CatWISE has it)')
  const cat = !hideCat && c.match?.pm_cat != null ? c.match.pm_cat : null
  const top = Math.max(c.pm_arcsec_yr, cat ?? 0, 1e-6)
  const yr = L('年', 'yr')
  return (
    <div className="mv-facts">
      <MoverVectors c={c} size={112} />
      <div className="mv-nums">
        {hideCat ? <span className="tag muted">{L('練習題：先判斷，再看答案', 'Practice: judge first, then see the answer')}</span> : <span className={`tag ${cls}`}>{st}</span>}
        <div className="pm-bars" role="img" aria-label={L(`SPHEREx 量到每年 ${c.pm_arcsec_yr.toFixed(2)} 角秒${cat != null ? `，${c.match.cat} 是 ${cat.toFixed(2)}` : ''}`, `SPHEREx measures ${c.pm_arcsec_yr.toFixed(2)} arcsec per year${cat != null ? `; ${c.match.cat} has ${cat.toFixed(2)}` : ''}`)}>
          <span>SPHEREx</span><i style={{ width: `${(c.pm_arcsec_yr / top) * 100}%`, '--c': COL.accent }} /><b>{c.pm_arcsec_yr.toFixed(2)}″/{yr}</b>
          {cat != null && <><span>{c.match.cat}</span><i style={{ width: `${Math.max(1, (cat / top) * 100)}%`, '--c': COL.known }} /><b>{cat.toFixed(2)}″/{yr}</b></>}
        </div>
        <Meter value={Math.min(c.sig, 30)} lo={0} hi={30} mark={5} c={c.sig >= 5 ? COL.good : COL.warn} label={L(`顯著度 · ${c.n_bands_agree}/${c.n_bands_fit} 個偵測器方向一致`, `Significance · ${c.n_bands_agree}/${c.n_bands_fit} detectors agree`)} text={`${c.sig}σ`} />
        <p className="mv-cap">{bdText(c.bd_score)}{c.method === 'xepoch' ? ` · ${L(`對 ${c.baseline_yr ? c.baseline_yr.toFixed(1) : '約 11'} 年前的 CatWISE 位置`, `against CatWISE ${c.baseline_yr ? c.baseline_yr.toFixed(1) : '~11'} yr earlier`)}` : ''}</p>
      </div>
      {/* no parallax on the card: the validation says SPHEREx's own parallax is too noisy to claim (static stars scatter 70–135 mas) */}
    </div>
  )
}

/** List under the field lab / quick look. onPick(c) centres the view on the candidate. */
export function MoverList({ data, onPick, fieldId }) {
  useLanguage()
  if (!data) return null
  const cs = data.candidates || []
  return (
    <section className="mv-list">
      <h2>{L('自動找到的移動恆星（幾年內移動）', 'Moving stars found automatically (they move over years)')}</h2>
      <p className="hint">{L('程式比較第一輪和最後一輪巡天的疊加影像，找出位置有移動、而且在至少兩個偵測器裡方向一致的星，之後才拿 Gaia／CatWISE 星表來標示是不是已知天體。', 'The search compares the first and last survey pass stacks, keeps stars whose shift is significant and agrees in at least two detectors, and only then asks Gaia / CatWISE whether each one is already known.')}
        {data.stats?.floor_px != null && ` ${L(`這片天空的位置雜訊底限 ${(data.stats.floor_px * PIX).toFixed(2)}″。`, `Positional noise floor here: ${(data.stats.floor_px * PIX).toFixed(2)}″.`)}`}</p>
      <p className="hint">{L('這和小行星是兩回事：小行星在幾小時內就移動，由差分影像和神經網路找；恆星在幾年內才移動一點點，由這裡的搜尋找。', 'This is a different thing from asteroids: an asteroid moves within hours and is found by the difference images and the neural network; a star moves a little over years and is found by this search.')}</p>
      {cs.length === 0 ? <p className="empty-line">{L('這片天空沒有找到移動夠明顯的星。', 'No star here moves enough to be detected.')}</p>
        : <ul>{cs.map((c) => (
          <li key={c.id}>
            <MoverFacts c={c} />
            <div className="mv-act">
              {onPick && <button className="btn small" onClick={() => onPick(c)}>{L('在影像上看', 'Show on the image')}</button>}
              <a className="btn small" href={`#/movers?f=${encodeURIComponent(fieldId)}&m=${c.id}`}>{L('幫忙判斷', 'Help review')}</a>
            </div>
          </li>))}</ul>}
    </section>
  )
}

/** Variable stars found automatically in an analysed field (var_candidates.json). onPick(c) measures it in the lab. */
export function VariableList({ data, onPick }) {
  useLanguage()
  if (!data) return null
  const cs = data.candidates || []
  const ST = {
    known_variable: [L('已知變星', 'Known variable'), 'known'],
    new: [L('新的：星表沒有標示會變', 'New: not flagged as variable in the catalogues'), 'distant'],
    catalogued_constant: [L('星表說它不變（可能是假訊號）', 'Catalogue says constant (likely artefact)'), 'muted'],
  }
  return (
    <section className="mv-list">
      <h2>{L('自動找到的變星', 'Variable stars found automatically')}</h2>
      <p className="hint">{L('SPHEREx 每張影像在同一個位置的波長都不同，直接比亮度會把光譜的形狀當成變化。所以程式先替每顆星、每個偵測器擬合「平滑光譜 × 每輪一個亮度係數」，再看各輪的亮度係數有沒有顯著不同、而且至少兩個偵測器方向一致。星表（Gaia、VSX）只用來標示，不參與搜尋。', 'Every SPHEREx exposure sees a given position at a different wavelength, so comparing raw fluxes would mistake the spectrum for variability. The search fits each star in each detector with "a smooth spectrum × one brightness factor per pass", then asks whether those factors differ significantly and agree in at least two detectors. Catalogues (Gaia, VSX) only label the result.')}
        {data.stats?.n_searched != null && ` ${L(`這片天空偵測到 ${data.stats.n_sources} 顆星，其中 ${data.stats.n_searched} 顆夠孤立、可以檢查（和鄰星混在一起的不列入，因為鄰星的光會在各輪之間進出孔徑，造成假的變化）。只有 3 到 4 輪巡天，所以量不出週期。`, `${data.stats.n_sources} stars detected here, ${data.stats.n_searched} isolated enough to check (blended ones are left out: a neighbour's light moves in and out of the aperture between passes and fakes a change). With only 3 or 4 passes, no period can be measured.`)}`}</p>
      {cs.length === 0 ? <p className="empty-line">{L('這片天空沒有找到亮度變化夠明顯的星。', 'No star here changes brightness enough to be detected.')}</p>
        : <ul>{cs.map((c) => {
          const [st, cls] = ST[c.status] || ST.new
          return (
            <li key={c.id}>
              <div className="var-facts">
                <PassDots L0={c.L} />
                <div className="mv-nums">
                  <span className={`tag ${cls}`}>{st}</span>
                  <span className="var-amp"><b>×{c.amp.toFixed(2)}</b> {L('最亮 ÷ 最暗', 'brightest ÷ faintest')}</span>
                  <Meter value={Math.min(c.sig, 30)} lo={0} hi={30} mark={5} c={COL.good} label={`${L('顯著度', 'Significance')}${c.n_dets_agree != null ? ` · ${L(`${c.n_dets_agree} 個偵測器一致`, `${c.n_dets_agree} detectors agree`)}` : ''}`} text={`${c.sig}σ`} />
                  {(c.match || c.saturated) && <p className="mv-cap">{c.match ? `${c.match.cat}${c.match.name ? ` ${c.match.name}` : ''}${c.match.type ? ` · ${c.match.type}` : ''}${c.match.period_d ? ` · ${L('週期', 'period')} ${(+c.match.period_d).toFixed(1)} ${L('天', 'd')}` : ''}` : ''}{c.saturated ? `${c.match ? ' · ' : ''}${L('核心飽和，用 PSF 外圍量測', 'saturated core, measured from the PSF wings')}` : ''}</p>}
                </div>
              </div>
              <div className="mv-act">{onPick && <button className="btn small" onClick={() => onPick(c)}>{L('量測它', 'Measure it')}</button>}</div>
            </li>)
        })}</ul>}
    </section>
  )
}

/** Relative brightness in each survey pass, as dots with error bars (pass colours). */
export function PassDots({ L0 }) {
  if (!L0?.length) return null
  const W = 150, H = 96, lo = Math.min(...L0.map((q) => q.rel - (q.err || 0)), 0.9), hi = Math.max(...L0.map((q) => q.rel + (q.err || 0)), 1.1)
  const X = (j) => 26 + (j * (W - 44)) / Math.max(1, L0.length - 1), Y = (v) => 12 + (1 - (v - lo) / (hi - lo)) * (H - 34)
  return (
    <svg className="var-dots" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={L(`各輪的相對亮度：${L0.map((q) => `×${q.rel.toFixed(2)}`).join('、')}`, `Relative brightness per pass: ${L0.map((q) => `×${q.rel.toFixed(2)}`).join(', ')}`)}>
      <line x1="10" x2={W - 6} y1={Y(1)} y2={Y(1)} stroke="rgb(255 255 255 / .2)" strokeDasharray="3 4" />
      <polyline points={L0.map((q, j) => `${X(j)},${Y(q.rel)}`).join(' ')} fill="none" stroke="rgb(255 255 255 / .35)" />
      {L0.map((q, j) => <g key={j}>
        {q.err > 0 && <line x1={X(j)} x2={X(j)} y1={Y(q.rel - q.err)} y2={Y(q.rel + q.err)} stroke={PASS_C[q.k % PASS_C.length]} strokeWidth="2" />}
        <circle cx={X(j)} cy={Y(q.rel)} r="5" fill={PASS_C[q.k % PASS_C.length]} />
        <text x={X(j)} y={H - 4} textAnchor="middle" fontSize="13" fill="#a3a8b2">{mjdToIso(q.mjd).slice(2, 7)}</text>
      </g>)}
    </svg>
  )
}

// ---- the review queue ---------------------------------------------------------------------------------------
function Card({ c, onVote }) {
  const [done, setDone] = useState(null), [v, setV] = useState(c.votes)
  const vote = (verdict) => api('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ field: c.field, mover: c.id, verdict }) })
    .then((r) => { setDone(verdict); setV(r[`m${c.id}`] || v); onVote?.() }).catch(() => setDone('error'))
  // a quick-look candidate reopens the preview it came from (same centre and field of view), not a new download
  const open = c.source === 'quick' ? (c.centre ? skyHash(`${c.centre.ra} ${c.centre.dec}`, c.centre.size) : skyHash(`${c.ra} ${c.dec}`)) : `#/lab/${encodeURIComponent(c.field)}`
  // catalogued movers double as practice: the answer is hidden until the visitor has judged
  const practice = ['known', 'static'].includes(c.status), voted = done && done !== 'error'
  const answer = c.status === 'known' ? ['real', L('正解：真的在動。星表裡有這顆星', 'Answer: it really moves. The catalogue has it')] : ['artifact', L('正解：假訊號。星表說它不動', 'Answer: an artefact. The catalogue says it does not move')]
  return (
    <article className="mv-card" id={`mv-${c.field}-${c.id}`}>
      <Blink c={c} />
      <div className="mv-body">
        <MoverFacts c={c} hideCat={practice && !voted} />
        <p className="hint">RA {c.ra?.toFixed(5)}°, Dec {c.dec?.toFixed(5)}° · {c.field}</p>
        <p className="mv-q">{L('它在各輪巡天之間真的移動了嗎？', 'Did it really move between the survey passes?')}</p>
        <div className="mv-act">
          <button className="btn small primary" disabled={!!voted} onClick={() => vote('real')}>{L('真的', 'Real')}</button>
          <button className="btn small" disabled={!!voted} onClick={() => vote('artifact')}>{L('假訊號', 'Artefact')}</button>
          <button className="btn small" disabled={!!voted} onClick={() => vote('unsure')}>{L('不確定', 'Not sure')}</button>
          <a className="btn small" href={open}>{c.source === 'quick' ? L('打開這個預覽', 'Open this preview') : L('打開這片天空', 'Open this sky')}</a>
        </div>
        {practice && voted && <p className={`note ${done === answer[0] ? 'ok' : ''}`}>{done === answer[0] ? L('答對了。', 'Correct. ') : done === 'unsure' ? '' : L('這次不一樣。', 'Not this time. ')}{answer[1]}{c.match?.pm_cat != null ? L(`（${c.match.cat} 自行 ${c.match.pm_cat.toFixed(2)}″/年，這裡量到 ${c.pm_arcsec_yr.toFixed(2)}″/年）。`, ` (${c.match.cat} proper motion ${c.match.pm_cat.toFixed(2)}″/yr; measured here ${c.pm_arcsec_yr.toFixed(2)}″/yr).`) : L('。', '.')}</p>}
        <p className="hint" role="status">{done === 'error' ? L('送出失敗，請再試一次。', 'Could not send; try again.') : voted ? L('謝謝！', 'Thank you!') : ''} {(!practice || voted) && L(`目前投票：真的 ${v.real} · 假訊號 ${v.artifact} · 不確定 ${v.unsure}`, `Votes so far: real ${v.real} · artefact ${v.artifact} · not sure ${v.unsure}`)}</p>
      </div>
    </article>
  )
}

// ---- positions people flagged in a lab or a quick look (/api/spots) --------------------------------------------
const KIND_TEXT = { moving: ['好像在移動', 'seems to move'], variable: ['亮度在變', 'brightness changes'], spectrum: ['光譜很特別', 'unusual spectrum'], other: ['其他', 'something else'] }
function SpotCard({ c }) {
  const [done, setDone] = useState(null), [v, setV] = useState(c.votes)
  const vote = (verdict) => api('/api/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ field: c.field, x: c.x, y: c.y, verdict }) })
    .then((r) => { setDone(r._duplicate ? 'dup' : verdict); setV(r[c.key] || v) }).catch(() => setDone('error'))
  const at = `x=${c.x}&y=${c.y}`
  const open = c.source === 'quick' ? (() => { const h = skyHash(`${c.centre.ra} ${c.centre.dec}`, c.centre.size); return `${h}${h.includes('?') ? '&' : '?'}${at}` })() : `#/lab/${encodeURIComponent(c.field)}?${at}`
  const kinds = Object.entries(c.kinds || {}).sort((a, b) => b[1] - a[1])
  const voted = done && done !== 'error'
  return (
    <article className="mv-card" id={`sp-${c.field}-${c.key}`}>
      <Blink c={{ ...c, id: c.key, base: dataBase(c.field), det_band: 0 }} label={L('這個位置在第一輪與最後一輪的疊加影像', 'This position in the first and last pass stacks')} />
      <div className="mv-body">
        <p className="mv-facts"><b>{kinds.length ? kinds.map(([k, n]) => `${L(...(KIND_TEXT[k] || [k, k]))}${n > 1 ? ` ×${n}` : ''}`).join(L('、', ', ')) : L('有人回報', 'Flagged')}</b></p>
        <p className="hint">RA {c.ra.toFixed(5)}°, Dec {c.dec.toFixed(5)}° · {c.source === 'quick' ? L('快速預覽', 'quick look') : c.name || c.field}</p>
        <p className="mv-q">{L('打開它、點這個位置看光譜和光變曲線。你覺得這裡有真的天體在變化嗎？', 'Open it and click the position for its spectrum and light curve. Is something real changing here?')}</p>
        <div className="mv-act">
          <button className="btn small primary" disabled={!!voted} onClick={() => vote('real')}>{L('真的', 'Real')}</button>
          <button className="btn small" disabled={!!voted} onClick={() => vote('artifact')}>{L('假訊號', 'Artefact')}</button>
          <button className="btn small" disabled={!!voted} onClick={() => vote('unsure')}>{L('不確定', 'Not sure')}</button>
          <a className="btn small" href={open}>{L('打開並量測', 'Open and measure')}</a>
        </div>
        <p className="hint" role="status">{done === 'error' ? L('送出失敗，請再試一次。', 'Could not send; try again.') : done === 'dup' ? L('你已經投過票了。', 'You already voted on this one. ') : voted ? L('謝謝！', 'Thank you! ') : ''}{L(`目前投票：真的 ${v.real} · 假訊號 ${v.artifact} · 不確定 ${v.unsure}`, `Votes so far: real ${v.real} · artefact ${v.artifact} · not sure ${v.unsure}`)}</p>
      </div>
    </article>
  )
}

function Spots() {
  const [all, setAll] = useState(null), [n, setN] = useState(6)
  useEffect(() => { api('/api/spots').then(setAll).catch(() => setAll([])) }, [])
  return (
    <section className="spots" aria-labelledby="spots-h">
      <h2 id="spots-h">{L('大家回報的位置', 'Positions people flagged')}</h2>
      <p className="hint">{L('在任何天空的工作台裡點一個位置，量完光譜和光變曲線後，可以按「回報」讓其他人一起看。電腦找不到的東西，常常是人先注意到的。', 'In any lab, click a position, measure its spectrum and light curve, then flag it so others can look too. People often notice what the computer misses.')}</p>
      {!all ? <div className="route-loading" role="status"><i aria-hidden="true" /></div>
        : !all.length ? <p className="hint">{L('還沒有人回報。打開任何一片天空的工作台（例如', 'Nothing flagged yet. Open any lab (for example ')}<a href="#/target/wise0855">WISE 0855</a>{L('），點一個位置就能回報。', '), click a position, and flag it.')}</p>
        : <>
          <div className="mv-grid">{all.slice(0, n).map((c) => <SpotCard key={`${c.field}-${c.key}`} c={c} />)}</div>
          {all.length > n && <p className="mv-more"><button className="btn" onClick={() => setN(n + 6)}>{L(`再顯示（還有 ${all.length - n} 個）`, `Show more (${all.length - n} left)`)}</button></p>}
        </>}
    </section>
  )
}

/** How well the search works, as the chart from the guide's validation (not six text cards): the queue is what this
 *  page is for, so the proof sits beside the introduction and links to the full validation. */
function Proof() {
  const v = useValidation()
  const ks = v?.known_stars
  const found = ks ? ks.strata.reduce((a, g) => a + g.found, 0) : null
  return (
    <ChartCard level={2} className="mv-proof" title={L('移動多快才找得到', 'How fast must it move to be found')}
      take={v ? <>{L(`${v.targets.filter((t) => t.found).length} 個測試目標全部自動找到`, `${v.targets.filter((t) => t.found).length} of ${v.targets.length} test targets found blind`)}
        {ks ? L(`；${ks.n_done} 顆已知移動星找回 ${found} 顆`, `; ${found} of ${ks.n_done} known movers recovered`) : ''}{L(`；假警報 ${v.false_movers_in_fields} 個。`, `; ${v.false_movers_in_fields} false alarms. `)}
        <a href="#/guide/trust">{L('完整驗證 →', 'Full validation →')}</a></> : v === false ? <a href="#/guide/trust">{L('方法驗證 →', 'How well it works →')}</a> : '\u00a0'}>
      {v ? <RecoveryChart data={v} height={190} /> : <div className="skel-card mv-proof-ph" />}
    </ChartCard>
  )
}

export default function Movers({ focus }) {
  useLanguage()
  const [all, setAll] = useState(null)
  const [show, setShow] = useState('all')
  const [limit, setLimit] = useState(12)              // a page of cards at a time (the full list was 17,000 px on a phone)
  useEffect(() => { setLimit(focus ? 1e9 : 12) }, [show, focus])
  useEffect(() => { api('/api/movers').then(setAll).catch(() => setAll([])) }, [])
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + L('移動星候選', 'Moving-star candidates') }, [])
  useEffect(() => {
    if (!all || !focus) return
    setTimeout(() => document.getElementById(`mv-${focus.f}-${focus.m}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 300)
  }, [all, focus])
  // what needs a human comes first; the catalogued movers (practice, answers known) after
  const list = useMemo(() => (all || []).filter((c) => show === 'all' || (show === 'review' ? ['new', 'mismatch'].includes(c.status) : ['known', 'static'].includes(c.status)))
    .map((c, i) => [c, i]).sort((a, b) => (['new', 'mismatch'].includes(b[0].status) - ['new', 'mismatch'].includes(a[0].status)) || a[1] - b[1]).map(([c]) => c), [all, show])
  const nNew = (all || []).filter((c) => ['new', 'mismatch'].includes(c.status)).length
  return (
    <div className="object target movers">
      <div className="mv-head">
      <header className="tg-listhead">
        <h1>{L('幫忙找移動的星', 'Help find moving stars')}</h1>
        <p className="lead">{L('每一片分析過的天空、每一次快速預覽，都會自動搜尋位置在兩輪巡天之間有移動的星。已知的移動星用來證明方法有效；星表裡沒有的就需要大家幫忙看：輪播各輪巡天，判斷它是真的在動，還是假訊號。', 'Every analysed field and every quick look is searched automatically for stars that shift between survey passes. Known movers show the method works; the ones no catalogue explains need your eyes: blink the survey passes and say whether it really moves.')}</p>
        <div className="seg" role="group">
          <button aria-pressed={show === 'all'} onClick={() => setShow('all')}>{L('全部', 'All')} {all ? all.length : ''}</button>
          <button aria-pressed={show === 'review'} onClick={() => setShow('review')}>{L('需要判斷', 'Needs review')} {all ? nNew : ''}</button>
          <button aria-pressed={show === 'known'} onClick={() => setShow('known')}>{L('練習題（已知答案）', 'Practice (answers known)')} {all ? all.length - nNew : ''}</button>
        </div>
        <button type="button" className="btn small mv-fakebtn" onClick={() => document.getElementById('fake-mover')?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })}>{L('練眼力：找出假的移動星 ↓', 'Practice: spot the fake mover ↓')}</button>
      </header>
      <Proof />
      </div>
      {!all ? <div className="route-loading" role="status"><i aria-hidden="true" /></div>
        : list.length === 0 ? <p className="hint">{show === 'review' ? L('目前沒有星表解釋不了的候選：找到的移動星都已經在星表裡。可以先用「練習題」練眼力；輸入新的座標做快速預覽，就會搜尋那片天空。', 'Nothing the catalogues cannot explain right now: every mover found so far is already catalogued. Practise on the catalogued ones, or start a quick look anywhere to search that sky.') : L('還沒有候選。', 'No candidates yet.')}</p>
        : <>
          <div className="mv-grid">{list.slice(0, limit).map((c) => <Card key={`${c.field}-${c.id}`} c={c} />)}</div>
          {list.length > limit && <p className="mv-more"><button className="btn" onClick={() => setLimit(limit + 12)}>{L(`再顯示 ${Math.min(12, list.length - limit)} 張（還有 ${list.length - limit} 張）`, `Show ${Math.min(12, list.length - limit)} more (${list.length - limit} left)`)}</button></p>}
        </>}
      <FakeMover />
      <Spots />
    </div>
  )
}
