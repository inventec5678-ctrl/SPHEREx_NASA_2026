// Validation page: our automatic variable-star search against Gaia DR3's variable stars (scripts/gaia_build.py
// variables -> /data/validation/gaia.json). Two cards: how Gaia's variables in our fields fall through the search
// (and what Gaia says about our own candidates), and how much they change in Gaia against what SPHEREx saw.
import { useEffect, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L } from './lib.js'
import { ChartCard, COL, Plot } from './charts.jsx'
import { varClass } from './starcard.jsx'
import './starcard.css'

const GROUP = { SOLAR_LIKE: COL.det[3], ECL: COL.known, 'DSCT|GDOR|SXPHE': COL.det[1], RR: COL.det[1], CEP: COL.det[1], LPV: COL.bad, RS: COL.distant, CV: COL.distant, YSO: COL.distant, S: COL.distant }
const colourOf = (c) => GROUP[c] || COL.ink3
const pct = (ratio) => Math.max(0.3, (ratio - 1) * 100)           // a change as a percentage, floored for the log axis
const gaiaRatio = (mag) => 10 ** (0.4 * mag)
const NAMES = () => ({ rdra: L('天龍座 R', 'R Draconis'), rwaur: L('御夫座 RW', 'RW Aurigae') })

export default function ValGaia() {
  useLanguage()
  const [d, setD] = useState(null)
  useEffect(() => { fetch('/data/validation/gaia.json').then((r) => (r.ok ? r.json() : false)).then(setD).catch(() => setD(false)) }, [])
  if (!d) return null
  const f = d.funnel, nf = d.fields.length
  const stages = [
    [f.footprint, L('在我們天區裡的 Gaia 變星', 'Gaia variables inside our fields'), COL.ink3],
    [f.in_range, L('亮到我們量得到', 'bright enough for our source finder'), COL.known],
    [f.measured, L('就是我們量到的那顆星', 'the very star we measured'), COL.known],
    [f.searched, L('有檢查（沒有和鄰星混在一起）', 'searched (not blended with a neighbour)'), COL.known],
    [f.flagged, L('被我們的搜尋標為變星', 'flagged by our search'), COL.good],
  ]
  const named = NAMES()
  const fieldOf = (c) => named[c.field] || c.field
  const cs = d.cand_summary
  const pts = d.variables.filter((v) => v.measured && v.gaia_range != null && v.our_amp != null).map((v) => ({
    x: pct(gaiaRatio(v.gaia_range)), y: pct(v.our_amp), v, r: v.flagged ? 11 : 8,
    tip: `${varClass(v.cls)}`,
    hint: L(`Gaia ${Math.round((gaiaRatio(v.gaia_range) - 1) * 100)}%，SPHEREx ${((v.our_amp - 1) * 100).toFixed(1)}% · G ${v.g} · ${fieldOf(v)}${v.flagged ? ' · 已標出' : v.searched ? '' : ' · 和鄰星混在一起，沒有檢查'}`,
      `Gaia ${Math.round((gaiaRatio(v.gaia_range) - 1) * 100)}%, SPHEREx ${((v.our_amp - 1) * 100).toFixed(1)}% · G ${v.g} · ${fieldOf(v)}${v.flagged ? ' · flagged' : v.searched ? '' : ' · blended, not searched'}`),
  }))
  const thrs = d.fields.map((x) => x.threshold_unsat).sort((a, b) => a - b)
  const tlo = thrs[0], thi = thrs[nf - 1]
  const classes = d.by_class.filter((b) => b.in_range > 0)
  // searched stars whose change in Gaia exceeds their own field's threshold (the ring threshold for a saturated star)
  const fOf = Object.fromEntries(d.fields.map((x) => [x.field, x]))
  const big = d.variables.filter((v) => v.searched && v.gaia_range != null && gaiaRatio(v.gaia_range) >= fOf[v.field][v.saturated ? 'threshold_sat' : 'threshold_unsat'])
  return <>
    <ChartCard
      title={L('對照 Gaia DR3 的變星表', 'Checked against Gaia DR3’s variable stars')}
      take={<>{L(`${nf} 片天空裡，Gaia 列出 `, `In our ${nf} fields Gaia lists `)}<b>{f.in_range}</b>{L(' 顆亮到 SPHEREx 量得到的變星；我們的搜尋標出 ', ' variable stars bright enough for SPHEREx; our search flagged ')}<b>{f.flagged}</b>{L(' 顆。我們的 ', '. Of our ')}<b>{cs.n}</b>{L(' 個候選，Gaia 也列為變星的有 ', ' candidates, Gaia also lists ')}<b>{cs.gaia_variable}</b>{L(' 個。', ' as variable.')}</>}
      more={<>
        <p>{L('「亮到量得到」：比這片天空的極限亮（我們的找星程式在這個亮度至少找到一半的 Gaia 星；各天區 G 介於 ', '“Bright enough”: brighter than the field’s limit, where our source finder still picks up at least half of Gaia’s stars (G ')}{Math.min(...d.fields.map((x) => x.g_limit))}–{Math.max(...d.fields.map((x) => x.g_limit))}{L('）。「就是我們量到的那顆星」：它是我們量測位置 1 像素內最亮的 Gaia 星；否則量到的是旁邊更亮的星。', '). “The very star we measured”: it is the brightest Gaia star within 1 pixel of a position we measured; otherwise the light we measured is a brighter neighbour’s.')}</p>
        <p>{L('變星分類來自 Gaia DR3 的 vari_classifier_result。資料由 ESA 的 Gaia 資料庫提供，連不上時改用 MAST；程式只用 Gaia 對照結果，不用它挑選。', 'Classes come from Gaia DR3’s vari_classifier_result. Data from ESA’s Gaia archive, with MAST as the fallback; Gaia only checks the result, it never selects.')} {L(`更新：${d.updated.slice(0, 10)}。`, `Updated ${d.updated.slice(0, 10)}.`)}</p>
      </>}>
      <ol className="gv-funnel" aria-label={L('Gaia 變星一步步經過我們的搜尋', 'Gaia’s variables, step by step through our search')}>
        {stages.map(([n, t, c]) => <li key={t}><span>{t}</span><i style={{ width: `${(n / Math.max(1, f.footprint)) * 100}%`, '--c': c }} /><b>{n}</b></li>)}
      </ol>
      <p className="vd-sub">{L('亮到量得到的 Gaia 變星，依 Gaia 的分類', 'The bright-enough Gaia variables, by Gaia’s class')}</p>
      <ul className="gv-classes" aria-label={L('各類 Gaia 變星：亮到量得到的數目，和我們標出的數目', 'Gaia classes: how many are bright enough, and how many we flagged')}>
        {classes.slice(0, 5).map((b) => <li key={b.cls}><i style={{ '--c': colourOf(b.cls) }} /><span>{varClass(b.cls)}</span><b>{b.in_range}{b.flagged ? L(` · 標出 ${b.flagged}`, ` · ${b.flagged} flagged`) : ''}</b></li>)}
        {classes.length > 5 && <li><i style={{ '--c': COL.distant }} /><span title={classes.slice(5).map((b) => `${varClass(b.cls)} ${b.in_range}`).join(' · ')}>{L(`其他 ${classes.length - 5} 類（${classes.slice(5).map((b) => varClass(b.cls).split(/[（(]/)[0].trim()).join('、')}）`, `${classes.length - 5} other classes (${classes.slice(5).map((b) => varClass(b.cls).split(/[（(]/)[0].trim()).join(', ')})`)}</span><b>{classes.slice(5).reduce((a, b) => a + b.in_range, 0)}{classes.slice(5).some((b) => b.flagged) ? L(` · 標出 ${classes.slice(5).reduce((a, b) => a + b.flagged, 0)}`, ` · ${classes.slice(5).reduce((a, b) => a + b.flagged, 0)} flagged`) : ''}</b></li>}
      </ul>
      <p className="vd-sub">{L('我們的候選，Gaia 怎麼說', 'Our candidates, as Gaia sees them')}</p>
      <div className="gv-cands">
        {d.candidates.map((c) => <div key={`${c.field}${c.id}`} className="gv-cand" style={{ '--c': c.gaia_variable ? COL.good : COL.warn }}>
          <strong>{fieldOf(c)} · {L(`各輪相差 ×${c.amp.toFixed(2)}`, `changed ×${c.amp.toFixed(2)} between passes`)}</strong>
          <span>{c.gaia_variable ? L(`Gaia：變星，${varClass(c.cls)}`, `Gaia: variable, ${varClass(c.cls)}`)
            : c.gaia_id ? <>{L('Gaia：沒有列為變星', 'Gaia: not listed as variable')}{c.match?.cat === 'VSX' && (/TTS/.test(c.match.type || '') ? L('；AAVSO 的變星表（VSX）列為年輕的金牛座 T 型星', '; AAVSO’s variable star index (VSX) lists it as a young T Tauri star') : L(`；AAVSO 的變星表（VSX）列為變星（${c.match.type}）`, `; AAVSO’s variable star index (VSX) lists it as variable (${c.match.type})`))}</>
              : L('Gaia：這個位置沒有星', 'Gaia: no star at this position')}</span>
        </div>)}
      </div>
    </ChartCard>
    <ChartCard
      title={L('為什麼大多數沒被標出：變化太小', 'Why most were not flagged: too small a change')}
      take={L(`Gaia 看到的變化大多不到 5%。有檢查、而且 Gaia 的變化比我們的門檻（${Math.round((tlo - 1) * 100)}–${Math.round((thi - 1) * 100)}%，依天區）大的只有 ${big.length} 顆，我們標出其中 ${big.filter((v) => v.flagged).length} 顆。`, `Most change by under 5% in Gaia. Only ${big.length} of the stars we searched change in Gaia by more than our threshold (${Math.round((tlo - 1) * 100)}–${Math.round((thi - 1) * 100)}%, by field); we flagged ${big.filter((v) => v.flagged).length} of them.`)}
      legend={[
        { c: COL.det[3], label: L('有黑子的類太陽星', 'Sun-like, spotted') }, { c: COL.known, label: L('食雙星', 'Eclipsing') }, { c: COL.det[1], label: L('脈動星', 'Pulsating') },
        { c: COL.bad, label: L('長週期變星', 'Long-period') }, { c: COL.distant, label: L('其他', 'Other') }, { c: COL.ink3, hollow: true, label: L('空心：和鄰星混在一起，沒有檢查', 'Hollow: blended, not searched') },
      ]}
      more={<>
        <p>{L('橫軸：Gaia 在可見光、約三年間看到的亮度變化（去掉極端值的範圍）。縱軸：SPHEREx 在紅外線、3 到 4 次巡天之間量到的最大變化。虛線：同樣的變化。灰色帶：我們的門檻，各天區不同（由那片天空不變的亮星量出）；要被標出，還需要至少兩個偵測器同時看到 5σ 以上的變化。', 'Across: the change Gaia saw in visible light over about three years (range without the extremes). Up: the largest change SPHEREx measured in the infrared between its 3 or 4 visits. Dashed diagonal: the same change. Grey band: our threshold, which differs by field (set by that field’s steady bright stars); a flag also needs at least two detectors to see a change above 5σ.')}</p>
        <p>{L('紅外線裡，黑子和脈動造成的變化通常比可見光小；只有 3–4 次造訪，也可能剛好錯過食雙星的變暗或激變變星的爆發。', 'In the infrared, spots and pulsations usually change a star less than in visible light; and 3–4 visits can simply miss an eclipse or a dwarf-nova outburst.')}</p>
      </>}>
      <Plot height={380} points={pts} label={L('Gaia 看到的變化對 SPHEREx 量到的變化', 'Change seen by Gaia against change measured by SPHEREx')}
        x={{ domain: [0.5, 2500], log: true, ticks: [1, 3, 10, 30, 100, 300, 1000], fmt: (v) => `${v}%`, label: L('Gaia 看到的變化（可見光）', 'Change seen by Gaia (visible)') }}
        y={{ domain: [0.25, 150], log: true, ticks: [1, 3, 10, 30, 100], fmt: (v) => `${v}%`, label: L('SPHEREx（紅外線）', 'SPHEREx (infrared)'), gutter: 44 }}>
        {({ X, Y, m, w }) => <>
          <line className="vd-ref" x1={X(0.5)} y1={Y(0.5)} x2={X(150)} y2={Y(150)} />
          <rect className="gv-band" x={m.l} width={w - m.r - m.l} y={Y((thi - 1) * 100)} height={Y((tlo - 1) * 100) - Y((thi - 1) * 100)} />
          <text className="mark-label" x={w - m.r - 4} y={Y((thi - 1) * 100) - 8} textAnchor="end">{L('我們的門檻（依天區）', 'our threshold (by field)')}</text>
          {pts.map((p, j) => <circle key={j} cx={X(p.x)} cy={Y(p.y)} r={p.v.flagged ? 9 : 6} fill={p.v.searched ? colourOf(p.v.cls) : 'none'} stroke={p.v.searched ? COL.ink : colourOf(p.v.cls)} strokeWidth={p.v.flagged ? 3 : p.v.searched ? 1 : 2} />)}
          {pts.filter((p) => p.v.flagged).map((p) => <text key={p.v.id} className="mark-label" x={X(p.x) - 14} y={Y(p.y) + 5} textAnchor="end">{fieldOf(p.v)}</text>)}
        </>}
      </Plot>
    </ChartCard>
  </>
}
