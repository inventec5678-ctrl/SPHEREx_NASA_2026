// The challenge's named test targets (Barnard's Star, Epsilon Indi B, WISE 0855, RW Aurigae, R Draconis):
// the list page; each target's own page is the field lab with the target marked.
import { Suspense, lazy, useEffect, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api } from './lib.js'
import Lab from './lab.jsx'
import { TARGET_IDS, TargetCards, targetName } from './targets_meta.jsx'
import { ChartCard, COL } from './charts.jsx'
import { CmdCard } from './starcard.jsx'

// movers.jsx pulls in the validation and WiseView pages (~150 kB): load it only when its lists are shown
const PassDots = lazy(() => import('./movers.jsx').then((m) => ({ default: m.PassDots })))
const VAR_PH = <div className="skel-card tg-var-ph" />

export function TargetPage({ id }) {
  return <Lab id={id} />
}

/** A field's strongest variable-star candidate (false: none), fetched once per visit (a failed fetch is asked again). */
const varBest = new Map()
function loadVarBest(id) {
  if (!varBest.has(id)) {
    varBest.set(id, fetch(`/data/fields/${id}/var_candidates.json`).then((r) => (r.ok ? r.json() : null))
      .then((d) => (d?.candidates || []).sort((a, b) => b.sig - a.sig)[0] || false)
      .catch(() => { varBest.delete(id); return false }))
  }
  return varBest.get(id)
}

/** What SPHEREx measured for each target, drawn: for the movers the measured shift beside the catalogue's prediction,
 *  for the variables the brightness in each survey pass (field summaries from /api/fields; the variable search's own
 *  per-pass numbers from var_candidates.json). */
function VarCard({ t }) {
  const [c, setC] = useState(null)
  useEffect(() => { loadVarBest(t.id).then(setC) }, [t.id])
  const amp = Object.entries(t.pass_ratio?.ring || {}).sort((a, b) => b[1] - a[1])[0]
  return (
    <ChartCard level={3} title={<a href={`#/target/${t.id}`}>{targetName(t)}</a>}
      take={c ? L(`各輪亮度相差 ×${c.amp.toFixed(2)}（${c.sig}σ），程式沒有被告知位置就自己找到。`, `Brightness differs by ×${c.amp.toFixed(2)} between passes (${c.sig}σ); the search found it without being told where it is.`)
        : amp ? L(`各輪亮度最多相差 ×${amp[1].toFixed(2)}（${amp[0]}）。`, `Brightness differs by up to ×${amp[1].toFixed(2)} between passes (${amp[0]}).`) : null}>
      <div className="tg-var">
        {c ? <Suspense fallback={VAR_PH}><PassDots L0={c.L} /></Suspense> : VAR_PH}
        <dl className="kv">
          <dt>{L('類型（VSX）', 'Type (VSX)')}</dt><dd>{t.vsx?.type || '—'}</dd>
          <dt>{L('週期', 'Period')}</dt><dd>{t.vsx?.period_d ? `${(+t.vsx.period_d).toFixed(1)} ${L('天', 'd')}` : '—'}</dd>
        </dl>
      </div>
    </ChartCard>
  )
}
function Results({ fields }) {
  const by = new Map(fields.map((f) => [f.id, f.target]).filter(([, t]) => t))
  const ts = TARGET_IDS.map((id) => by.get(id))
  const movers = ts.filter((t) => t?.motion)
  const vars = ts.filter((t) => t?.kind === 'var')
  if (!movers.length && !vars.length) return null
  const top = Math.max(...movers.map((t) => Math.max(t.motion.measured_arcsec + t.motion.err_arcsec, t.motion.predicted_arcsec)), 1)
  return (
    <section className="tg-results sec" aria-labelledby="tg-res-h">
      <h2 id="tg-res-h">{L('量到的結果', 'What SPHEREx measured')}</h2>
      <div className="chart-grid">
        {movers.map((t) => { const m = t.motion, d = m.measured_arcsec - m.predicted_arcsec; return (
          <ChartCard key={t.id} level={3} title={<a href={`#/target/${t.id}`}>{targetName(t)}</a>}
            take={L(`${Math.round(m.days)} 天移動 ${m.measured_arcsec.toFixed(2)}″，和星表預測差 ${Math.abs(d).toFixed(2)}″（誤差 ±${m.err_arcsec.toFixed(2)}″）。`, `Moved ${m.measured_arcsec.toFixed(2)}″ in ${Math.round(m.days)} days, ${Math.abs(d).toFixed(2)}″ from the catalogue prediction (error ±${m.err_arcsec.toFixed(2)}″).`)}>
            <div className="pm-bars big" role="img" aria-label={L(`SPHEREx 量到 ${m.measured_arcsec.toFixed(2)} 角秒，星表預測 ${m.predicted_arcsec.toFixed(2)} 角秒`, `SPHEREx measured ${m.measured_arcsec.toFixed(2)} arcsec; the catalogue predicts ${m.predicted_arcsec.toFixed(2)} arcsec`)}>
              <span>SPHEREx</span><i style={{ width: `${(m.measured_arcsec / top) * 100}%`, '--c': COL.accent }}><u style={{ width: `${Math.min(100, (2 * m.err_arcsec / m.measured_arcsec) * 100)}%` }} /></i><b>{m.measured_arcsec.toFixed(2)}″</b>
              <span>{L('星表預測', 'Catalogue')}</span><i style={{ width: `${(m.predicted_arcsec / top) * 100}%`, '--c': COL.known }} /><b>{m.predicted_arcsec.toFixed(2)}″</b>
            </div>
          </ChartCard>) })}
        {vars.map((t) => <VarCard key={t.id} t={t} />)}
      </div>
      <p className="hint">{L('移動的位移在第一輪與最後一輪的疊加影像上用高斯擬合量出（飽和的核心不用）；誤差是擬合誤差，不含系統誤差。每個目標頁有完整的移動圖、光譜和光變曲線。', 'Shifts are fitted with a Gaussian on the first and last pass stacks (a saturated core is left out); the error is the fit error only, without systematics. Each target page has the full motion plot, spectrum and light curves.')} <a href="#/guide/trust">{L('驗證與限制 →', 'Validation and limits →')}</a></p>
    </section>
  )
}

export function TargetList({ missing }) {
  useLanguage()
  const [fields, setFields] = useState(null)
  useEffect(() => { api('/api/fields').then(setFields).catch(() => setFields([])) }, [])
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + L('挑戰測試目標', 'Challenge test targets') }, [])
  return (
    <div className="object target">
      <header className="tg-listhead">
        <h1>{L('挑戰指定的五個測試目標', 'The five test targets named by the challenge')}</h1>
        <p className="lead">{L('三顆近距離、移動很快的恆星與棕矮星，和兩顆變星。每個都有各輪巡天的疊加影像、逐張播放、光變曲線與即時光譜。也可以直接在網址帶座標：', 'Three nearby fast-moving stars and brown dwarfs, and two variable stars. Each has per-pass stacks, frame-by-frame playback, a light curve and an on-the-fly spectrum. Any position can also be opened from the URL: ')}<code>/?ra=269.446&amp;dec=4.768</code></p>
        {missing && <p className="hint">{L('這個目標還在分析中，完成後會出現在這裡。', 'That target is still being analysed; it will appear here when done.')}</p>}
      </header>
      {fields ? <TargetCards fields={fields} level={2} /> : <div className="route-loading" role="status"><i aria-hidden="true" /></div>}
      {fields && <Results fields={fields} />}
      {fields && <CmdCard />}
    </div>
  )
}
