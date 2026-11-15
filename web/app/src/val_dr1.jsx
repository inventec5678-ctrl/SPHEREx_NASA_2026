// Validation: the switch from QR2 + QR3 to the first data release DR1 + QR3 (UPGRADE_PLAN.md §10, R1).
// IRSA retired QR2 when DR1 came out; every field was re-analysed on DR1 + QR3 with the new effective PSF, and the
// same measurements were repeated. Data: /data/validation/dr1.json (scripts/release_compare.py).
import { useEffect, useState } from 'react'
import { L } from './lib.js'
import { COL, ChartCard, Meter, Plot, extent, niceTicks } from './charts.jsx'

const BEFORE = COL.ink3, AFTER = COL.accent
const sum = (o) => Object.values(o || {}).reduce((a, b) => a + b, 0)
// short row labels (the full name is in the tooltip)
const SHORT = { barnard: 'Barnard', cybele: () => L('Cybele 天區', 'Cybele field'), epsindi: 'Eps Indi B', 'q043p280+16p853s15': 'Teegarden',
  'q183p200-01p400': 'RA 183°', rdra: 'R Dra', rwaur: 'RW Aur', taurus: () => L('金牛座', 'Taurus'), wise0855: 'WISE 0855' }
const short = (f) => { const v = SHORT[f.id]; return typeof v === 'function' ? v() : v || (f.name.length > 12 ? f.name.slice(0, 11) + '…' : f.name) }

/** One row per item, a hollow dot for before and a filled one for after, joined by a line. */
function Dumbbell({ rows, label, xLabel, fmt = (v) => v, ref1, domain }) {
  const vals = rows.flatMap((r) => [r.b, r.a]).filter((v) => v != null && Number.isFinite(v))
  if (!vals.length) return null
  const dom = domain || extent(vals.concat(ref1 != null ? [ref1] : []), 0.12)
  const pts = rows.flatMap((r, j) => [
    r.b != null && { x: r.b, y: j, tip: `${r.name}: ${fmt(r.b)}`, hint: L('換版本前', 'Before the switch') },
    r.a != null && { x: r.a, y: j, tip: `${r.name}: ${fmt(r.a)}`, hint: L('DR1 重算後', 'After re-analysis on DR1') },
  ].filter(Boolean))
  return (
    <Plot label={label} height={Math.max(150, 44 * rows.length + 60)} points={pts}
      x={{ domain: dom, label: xLabel, fmt, ticks: niceTicks(dom[0], dom[1], 5), grid: true }}
      y={{ domain: [rows.length - 0.4, -0.6], ticks: rows.map((_, j) => j), fmt: (j) => rows[j]?.short ?? '', grid: false, gutter: 104 }}>
      {({ X, Y, m, h }) => <>
        {ref1 != null && <line x1={X(ref1)} x2={X(ref1)} y1={m.t} y2={h - m.b} stroke={COL.good} strokeDasharray="4 4" />}
        {rows.map((r, j) => <g key={r.name}>
          {r.lo != null && r.hi != null && <line x1={X(r.lo)} x2={X(r.hi)} y1={Y(j) + 7} y2={Y(j) + 7} stroke={AFTER} strokeWidth="2" opacity=".6" />}
          {r.blo != null && r.bhi != null && <line x1={X(r.blo)} x2={X(r.bhi)} y1={Y(j) - 7} y2={Y(j) - 7} stroke={BEFORE} strokeWidth="2" opacity=".6" />}
          {r.b != null && r.a != null && <line x1={X(r.b)} x2={X(r.a)} y1={Y(j)} y2={Y(j)} stroke={COL.ink3} strokeWidth="2" />}
          {r.b != null && <circle cx={X(r.b)} cy={Y(j)} r="7" fill="none" stroke={BEFORE} strokeWidth="2.5" />}
          {r.a != null && <circle cx={X(r.a)} cy={Y(j)} r="7" fill={AFTER} />}
        </g>)}
      </>}
    </Plot>
  )
}

export default function ValDr1() {
  const [d, setD] = useState(null)
  useEffect(() => { fetch('/data/validation/dr1.json').then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => setD(null)) }, [])
  if (!d) return null
  const fields = d.fields.filter((f) => f.id !== 'planetx')
  const done = fields.filter((f) => f.rebuilt)
  const nb = fields.reduce((a, f) => a + f.before.n, 0), na = done.reduce((a, f) => a + f.after.n, 0)
  const nbDone = done.reduce((a, f) => a + f.before.n, 0)
  const rows = fields.map((f) => ({ name: f.name, short: short(f), b: f.before.n, a: f.after?.n ?? null }))
  const mov = d.targets.filter((t) => t.before.motion)
  const mrows = mov.map((t) => {
    const r = (m) => m && m.measured_arcsec / m.predicted_arcsec, e = (m) => m && m.err_arcsec / m.predicted_arcsec
    const b = t.before.motion, a = t.after?.motion
    return { name: t.name, short: short(t), b: r(b), a: r(a), blo: b && r(b) - e(b), bhi: b && r(b) + e(b), lo: a && r(a) - e(a), hi: a && r(a) + e(a) }
  })
  const pv = d.pm_validation || {}
  const rel = done.length ? done.reduce((o, f) => { for (const [k, v] of Object.entries(f.after.releases)) o[k] = (o[k] || 0) + v; return o }, {}) : null
  return (
    <>
      <ChartCard className="vd-dr1"
        title={L('換成正式版資料（DR1）', 'Switched to the first data release (DR1)')}
        take={done.length
          ? <>{L(`IRSA 在 DR1 推出後停止提供 QR2。${done.length} 片天空已用 DR1＋QR3 重算：同一批天空的影像從 ${nbDone} 張變成 `, `IRSA stopped serving QR2 when DR1 came out. ${done.length} fields have been re-analysed on DR1 + QR3: the same skies went from ${nbDone} images to `)}<b>{na}</b>{L(' 張。', '.')}</>
          : L(`IRSA 在 DR1 推出後停止提供 QR2。這些天空（共 ${nb} 張影像）正在用 DR1＋QR3 和新的 PSF 重算；完成後這裡會並排顯示前後結果。`, `IRSA stopped serving QR2 when DR1 came out. These fields (${nb} images) are being re-analysed on DR1 + QR3 with the new PSF; the results will appear here side by side.`)}
        legend={[{ c: BEFORE, hollow: true, label: `${d.before}` }, { c: AFTER, label: `${d.after}` }]}
        more={<>
          <p>{L('新版的差別：DR1 是 SPHEREx 第一次完整、一致處理的資料，旗標和校正都改進了；檔案裡附的是「有效 PSF」（ePSF，已含像素的響應，依偵測器位置分 21×21 區）。我們照 IRSA 的 PSF 教學，在像素中心取樣 ePSF，不再用 QR2 的舊 PSF。', 'What changed: DR1 is SPHEREx\'s first complete, uniformly processed release, with improved flags and calibration, and its files carry the effective PSF (ePSF: already includes the pixel response, in 21 × 21 zones per detector). Following IRSA\'s PSF tutorial we sample the ePSF at pixel centres instead of using the old QR2 PSF.')}</p>
          <p>{L('程式每天問 IRSA 有哪些資料版本，所以新的快速預覽在 DR1 公布當天就自動改用了；這裡是把已分析的天空也全部重算。模擬第九行星的測試天區是固定的測試案例，沒有重算。', 'The code asks IRSA once a day which releases exist, so new quick looks switched to DR1 on their own the day it appeared; this is the re-analysis of the fields analysed before. The simulated Planet X test field is a fixed test case and was not rebuilt.')}</p>
        </>}>
        <Dumbbell rows={rows} label={L('每片天空的影像數，換版本前後', 'Images per field, before and after the switch')} xLabel={L('影像張數', 'Images')} fmt={(v) => Math.round(v)} />
        {rel && <Meter value={(rel.DR1 || 0) / sum(rel)} c={AFTER} text={`${rel.DR1 || 0} / ${sum(rel)}`} label={L('重算後來自 DR1 的影像（其餘是 DR1 之後的 QR3）', 'Images from DR1 after the re-analysis (the rest are QR3, after DR1)')} />}
      </ChartCard>
      <ChartCard className="vd-dr1"
        title={L('換了資料，結果還一樣嗎', 'Same answers on the new data?')}
        take={mrows.some((r) => r.a != null)
          ? L('量到的移動距離除以星表預測，1 代表完全吻合（綠色虛線）。版本換了結果仍在誤差內，本身就是一項檢驗。', 'Measured motion over the catalogue prediction; 1 is a perfect match (green dashed line). Staying within the errors across a release change is a check in itself.')
          : L('三顆移動星在舊資料上量到的移動距離除以星表預測（1 代表完全吻合）。DR1 重算完成後，新的值會畫在旁邊。', 'Measured motion over the catalogue prediction for the three moving targets on the old data (1 is a perfect match). The DR1 values will be drawn next to them when the re-analysis finishes.')}
        legend={[{ c: BEFORE, hollow: true, label: d.before }, { c: AFTER, label: d.after }, { c: COL.good, line: true, label: L('完全吻合', 'Perfect match') }]}>
        <Dumbbell rows={mrows} ref1={1} label={L('量到的移動除以預測，換版本前後', 'Measured over predicted motion, before and after')} xLabel={L('量到 ÷ 預測', 'Measured ÷ predicted')} fmt={(v) => v.toFixed(3)} />
        {pv.before && <Meter value={pv.before.n_found / pv.before.n_tested} c={BEFORE} text={`${pv.before.n_found} / ${pv.before.n_tested}`}
          label={L(`45 顆已知移動星，自動找到（${d.before}）`, `45 known moving stars found blind (${d.before})`)} />}
        {pv.after && pv.after.n_tested >= 10 && <Meter value={pv.after.n_found / pv.after.n_tested} c={AFTER} text={`${pv.after.n_found} / ${pv.after.n_tested}${pv.after.n_tested < pv.after.n_stars ? L(`（已測 ${pv.after.n_tested} 顆）`, ` (${pv.after.n_tested} tested so far)`) : ''}`}
          label={L(`同一批星，自動找到（${d.after}）`, `The same stars found blind (${d.after})`)} />}
      </ChartCard>
    </>
  )
}
