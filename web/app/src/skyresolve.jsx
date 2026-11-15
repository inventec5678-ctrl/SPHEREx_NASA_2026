// #/sky/<query> (and /?ra=..&dec=.. or /?target=..): open whatever covers that position.
// The query is a challenge target name, decimal degrees "ra dec", sexagesimal "08h55m10.8s -07d14m42s" /
// "08:55:10.8 -07:14:42", or any object name SIMBAD knows (resolved by the server and moved to today's position).
import { useEffect, useRef, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api, forgetField } from './lib.js'
import { AladinView, HIPS, QuickLook } from './quick.jsx'
import { EmbedCode } from './embedcode.jsx'
import { QuickLab } from './lab.jsx'
import { Tour } from './tour.jsx'
import { SkySearch, FOVS } from './search.jsx'
import { COORD_CHARS, DEFAULT_FOV, parseSky, sep, setHashParams } from './sky.js'
import { jobError, jobFinished, poll, startAnalysis } from './jobs.js'
import { useMode } from './mode.js'
import { SectionNav } from './secnav.jsx'
import { ElsewhereLinks } from './elsewhere.jsx'
import { NeossatCoverage } from './neossat.jsx'

export { parseSky, sep }      // older imports

const FIELD_HIT = 0.45          // a position opens an analysed field when it lies within this fraction of the field's width
const JOB_POLL_MS = 3000
const fovOf = (fov) => (FOVS.includes(fov) ? fov : DEFAULT_FOV)
/** An analysed field's own page. */
const fieldHash = (f) => (f.target ? `#/target/${f.id}` : `#/field/${encodeURIComponent(f.id)}`)
const minutes = (z) => (z <= 0.15 ? L('約 5 分鐘', 'about 5 minutes') : z <= 0.3 ? L('約 5 到 10 分鐘', 'about 5 to 10 minutes') : L('30 分鐘以上', '30 minutes or more'))

export default function SkyResolve({ q, fov }) {
  useLanguage()
  const [state, setState] = useState({ s: 'look' })
  const [size, setSize] = useState(() => fovOf(fov))
  const [want, setWant] = useState(null)             // a field of view picked but not yet confirmed
  const [ql, setQl] = useState(null)                 // the quick look's own state, for the status line
  const stop = useRef(() => {})
  const mode = useMode()
  const [help, setHelp] = useState(null)              // the "?" notes: shown by default only in research mode
  const helpOn = help ?? mode === 'research'
  useEffect(() => () => stop.current(), [])
  useEffect(() => { setSize(fovOf(fov)); setWant(null) }, [fov, q])
  useEffect(() => {
    let live = true
    setState({ s: 'look' }); setQl(null)
    let fields = null                                  // the field list, once fetched (the name path asks for it first)
    const getFields = () => (fields ? Promise.resolve(fields) : api('/api/fields').then((fs) => (fields = fs)))
    const open = (v, name) => getFields().then((fs) => {
      if (!live) return
      const hit = fov != null ? null : fs.map((f) => ({ f, d: sep(v.ra, v.dec, f.ra, f.dec) })).filter((x) => x.d < x.f.size_deg * FIELD_HIT).sort((a, b) => a.d - b.d)[0]
      if (hit) location.replace(fieldHash(hit.f))
      else setState({ s: 'none', ...v, name })
    }).catch(() => live && setState({ s: 'err' }))
    const v = parseSky(q)
    if (v?.id) { location.replace(`#/target/${v.id}`); return }
    if (v) { open(v); return }
    // not a position: ask the name resolver, unless it is clearly a broken coordinate
    if (q.trim().length < 2 || COORD_CHARS.test(q)) { setState({ s: 'bad' }); return }
    // an analysed field by its id or name first (SIMBAD does not know asteroids such as 65 Cybele), then the resolver
    const w = q.trim().toLowerCase()
    getFields().catch(() => []).then((fs) => {
      if (!live) return
      const f = w.length >= 3 && fs.find((x) => x.id.toLowerCase() === w || (x.name || '').toLowerCase().includes(w))
      if (f) { location.replace(fieldHash(f)); return }
      api(`/api/resolve?q=${encodeURIComponent(q.trim())}`).then((r) => { if (live) open({ ra: r.ra, dec: r.dec }, r) })
        .catch((e) => { if (live) setState({ s: String(e).includes('404') || String(e).includes('422') ? 'unknown' : 'noresolve' }) })
    })
    return () => { live = false }
  }, [q, fov])
  useEffect(() => {
    if (state.s === 'none') document.title = `SPHEREx Sky Change · ${state.name?.name || `RA ${state.ra.toFixed(3)}° Dec ${state.dec.toFixed(3)}°`}`
    else if (state.s !== 'look') document.title = 'SPHEREx Sky Change · ' + L('找不到這個位置', 'Position not found')
  }, [state])

  async function submit() {
    try {
      const j = await startAnalysis(state.ra, state.dec, size)
      if (j.status === 'done') { location.replace(`#/field/${j.id}`); return }
      setState((s) => ({ ...s, job: j }))
      stop.current()
      stop.current = poll(`/api/jobs/${j.id}`, {
        every: JOB_POLL_MS,
        onUpdate: (r) => { if (r.status === 'done') { forgetField(j.id); location.replace(`#/field/${j.id}`) } else setState((s) => ({ ...s, job: r })) },
        done: jobFinished,
      })
    } catch (e) {
      setState((s) => ({ ...s, job: { status: 'error', error: jobError(e) } }))
    }
  }

  const j = state.job
  if (state.s === 'look') return <div className="route-loading" role="status"><i aria-hidden="true" /><span>{L('尋找這個位置…', 'Finding that position…')}</span></div>
  if (state.s !== 'none') {
    return (
      <div className="object target">
        <header className="tg-listhead">
          <h1>{state.s === 'bad' ? L('看不懂這個座標', 'Could not read that position')
            : state.s === 'unknown' ? L(`找不到「${q}」這個天體`, `No object called “${q}” was found`)
            : state.s === 'noresolve' ? L('名稱查詢服務暫時連不上', 'The name service cannot be reached right now')
            : L('暫時連不上伺服器', 'Cannot reach the server')}</h1>
          <p className="lead">{state.s === 'bad' ? L(`「${q}」不是完整的位置：需要赤經和赤緯兩個值。可以用十進位度數、時分秒，或天體名稱。`, `“${q}” is not a full position: it needs both an RA and a Dec. Use decimal degrees, sexagesimal, or an object name.`)
            : state.s === 'unknown' ? L('SIMBAD 不認得這個名稱。檢查拼字，或改用座標。', 'SIMBAD does not know that name. Check the spelling, or use coordinates instead.')
            : state.s === 'noresolve' ? L('SIMBAD 沒有回應，名稱暫時無法轉成座標。座標仍然可以用。', 'SIMBAD did not answer, so names cannot be turned into positions for now. Coordinates still work.')
            : L('請稍後再試。', 'Please try again in a moment.')}</p>
          <p className="hint">{L('例如：', 'For example: ')}<code>133.795 -7.245</code> · <code>08h55m10.8s -07d14m42s</code> · <code>Kapteyn's star</code> · <code>/?ra=133.795&amp;dec=-7.245</code></p>
        </header>
        <div style={{ maxWidth: 760, marginTop: 24 }}><SkySearch id="retry-q" autoFocus /></div>
      </div>
    )
  }
  const done = ql?.status === 'done', pending = want != null && want !== size
  return (
    <div className={`object target sky tool ${helpOn ? 'help-on' : ''}`}>
      {/* one header row (sticky on wide screens): where this is, the field of view, the section links, the notes switch */}
      <header className="sky-head tool-head">
        <div className="sky-title">
          <h1>{state.name?.name || L('快速預覽', 'Quick look')}</h1>
          <p className="sky-sub">RA {state.ra.toFixed(4)}°, Dec {state.dec.toFixed(4)}°{state.name?.pm_arcsec_yr ? L(` · 已依自行（${state.name.pm_arcsec_yr.toFixed(2)}″/年）推到今天的位置`, ` · moved to today's position by its proper motion (${state.name.pm_arcsec_yr.toFixed(2)}″/yr)`) : ''}</p>
        </div>
        <div className="sky-fov">
          <span className="lab-k">{L('視野', 'Field of view')}</span>
          <div className="seg" role="group" aria-label={L('視野', 'Field of view')}>
            {FOVS.map((z) => <button key={z} aria-pressed={(want ?? size) === z} onClick={() => setWant(z)}>{z}°</button>)}
          </div>
        </div>
        <SectionNav items={[
        { id: 'sec-play', label: L('影像', 'Images') },
        ...(done && ql.lab ? [{ id: 'ql-h', label: L('工作台', 'Lab') }, { id: 'sec-measure', label: L('量測', 'Measure') }] : []),
        { id: 'sec-aladin', label: L('其他望遠鏡', 'Other telescopes') },
        { id: 'sec-share', label: L('分享', 'Share') },
      ]} />
        <button type="button" className="btn small helpbtn" aria-pressed={helpOn} onClick={() => setHelp(!helpOn)} title={L('顯示或隱藏每個區塊的說明', 'Show or hide the notes under each part')}>？ {L('說明', 'Notes')}</button>
      </header>
      {pending && (
        <p className="note sky-confirm" role="status">
          {L(`換成 ${want}° 會重新向 IRSA 下載這片天空（${minutes(want)}），目前的預覽會被取代。`, `Switching to ${want}° downloads this patch again from IRSA (${minutes(want)}) and replaces the current preview.`)}
          <button className="btn small primary" onClick={() => { setSize(want); setWant(null); setHashParams({ fov: want === DEFAULT_FOV ? null : want, v: null, d: null, k: null }) }}>{L(`下載 ${want}°`, `Download ${want}°`)}</button>
          <button className="btn small" onClick={() => setWant(null)}>{L('取消', 'Cancel')}</button>
        </p>
      )}

      <div id="sec-play" className="sec-anchor"><QuickLook ra={state.ra} dec={state.dec} size={size} onState={setQl} /></div>
      <p className="lead sky-about">{done
        ? L(`這個位置的 ${ql.n_done} 張 SPHEREx 影像都已下載（${ql.first} – ${ql.last}），差分影像、各輪疊加、移動星的自動搜尋${ql.lab ? '和工作台' : ''}都完成了。`, `All ${ql.n_done} SPHEREx images of this position are in (${ql.first} – ${ql.last}); the difference frames, the pass stacks, the automatic search for moving stars${ql.lab ? ' and the lab' : ''} are done.`)
        : L('這個位置還沒有完整分析過，所以直接從 IRSA 下載這片天空的所有 SPHEREx 影像，邊下載邊播放。影像都到了以後，會自動加上差分影像、各輪疊加、移動星搜尋，最後做出工作台（相加相減、假彩色、即時光譜、星表疊圖、污染旗標）。', 'This position has not been fully analysed, so every SPHEREx image of it is being downloaded from IRSA and played as it arrives. When all are in, difference frames, pass stacks and a search for moving stars are added, and finally the lab (add and subtract, false colour, spectra on the fly, catalogue overlays, contamination flags).')}</p>
      {done && ql.lab && <QuickLab id={ql.id} />}
      <div className="two-col sec">
        <section className="sky-side">
          <h2 id="sec-aladin" className="sec-anchor">{L('SPHEREx 全天圖與其他望遠鏡', 'SPHEREx all-sky map and other telescopes')}</h2>
          <AladinView ra={state.ra} dec={state.dec} size={size} initial={`${HIPS}/SPHEREx/spherex_allsky_cube`} />
          <ElsewhereLinks ra={state.ra} dec={state.dec} size={size} />
          <NeossatCoverage ra={state.ra} dec={state.dec} />
        </section>
        <div className="sky-more">
          <details className="tool-more" open={!!j}>
          <summary>{L('完整分析：讓 AI 找小行星（20 到 40 分鐘）', 'Full analysis: let the AI look for asteroids (20 to 40 minutes)')}</summary>
          <p className="hint">{L('預覽跑完後，下面就會出現工作台（相加相減、假彩色、即時光譜、Gaia／WISE 疊圖、污染旗標）。完整分析另外用自己訓練的 AI 逐張找出移動快的天體（小行星、彗星），並比對已知的小天體，約 20 到 40 分鐘。', 'When the preview finishes, the lab appears below (add and subtract, false colour, spectra on the fly, Gaia/WISE overlays, contamination flags). The full analysis also runs the self-trained AI on every frame to find fast movers (asteroids, comets) and matches known small bodies; about 20 to 40 minutes.')}</p>
          <div className="ms-actions">
            <button className="btn" onClick={submit} disabled={j && ['queued', 'running'].includes(j.status)}>{L('開始完整分析', 'Start the full analysis')}</button>
          </div>
          {j && <div className="job" role="status" aria-live="polite">
            <strong>{j.status === 'error' ? j.error : j.status === 'queued' ? L(`排隊中（第 ${j.position || 1} 位）`, `Queued (position ${j.position || 1})`) : L('分析中…', 'Analysing…')}</strong>
            <pre>{(j.log || []).slice(-4).join('\n')}</pre>
          </div>}
          </details>
          <details id="sec-share" className="tool-more sec-anchor" open>
            <summary>{L('分享與嵌入', 'Share and embed')}</summary>
            <EmbedCode ra={state.ra} dec={state.dec} fov={size === DEFAULT_FOV ? null : size} />
          </details>
        </div>
      </div>
      <Tour kind="quick" />
    </div>
  )
}
