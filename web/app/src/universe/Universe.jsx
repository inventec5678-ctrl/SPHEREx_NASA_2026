import { useEffect, useMemo, useRef, useState } from 'react'
import { L, t } from '@sx/i18n/core.js'
import { gpuOK } from '../canvas.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { api } from '../lib.js'
import { fieldName } from '../fields_text.js'
import { go, goUniverse } from '../nav.js'
import { LIBRARY, PARAMS, bbColor, predicted } from './presets.js'
import { Preview, UniverseScene } from './scene.js'
import { askAbout } from '../ask/store.js'
import './universe.css'

export const TYPE_LABEL = { star: '恆星', galaxy: '星系', rocky: '小行星', comet: '彗星', ice_giant: '遠距行星' }
const clamp = (v, a, b) => Math.min(b, Math.max(a, v))
const reducedMotionMs = () => (window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 900 : 3600)
const MAX_SPHERES = 120

/** universe.json + field.json -> list of buildable bodies with depth. */
export function toBodies(uni, field) {
  const out = []
  // only the brightest sources become spheres; the rest stay in the backdrop image
  const top = [...uni.sources].sort((a, b) => b.snr - a.snr).slice(0, MAX_SPHERES)
  for (const s of top) {
    const pr = predicted({ ...s, group: 'source' })
    const z = s.kind === 'galaxy' ? -780 : s.distance_pc ? clamp(-40 - 210 * Math.log10(s.distance_pc / 20), -760, -30) : -380
    out.push({ key: `s${s.id}`, group: 'source', src: s, x: s.x, y: s.y, z, seed: s.id + 3, type: pr.type, params: pr.p, predicted: pr })
  }
  uni.movers.forEach((m, k) => {
    const pr = predicted({ ...m, group: 'mover' })
    const tr = field?.tracks?.[m.track]
    const z = pr.type === 'ice_giant' ? 15 : 20 + 9 * (k % 5)
    out.push({ key: `m${m.track}`, group: 'mover', src: m, track: tr, x: m.path[0][1], y: m.path[0][2], z, seed: 101 + k,
      path: [...m.path].sort((a, b) => a[0] - b[0]).map((p) => [p[1], p[2]]), pathT: [...m.path].sort((a, b) => a[0] - b[0]).map((p) => p[0]), type: pr.type, params: pr.p, predicted: pr })
  })
  return out
}

export function bodyTitle(b) {
  if (b.group === 'mover') {
    if (b.src.simulated) return t`模擬遠距行星（${b.src.preset?.d_au ?? '?'} AU）`
    return b.src.known || t`未辨識移動天體 #${b.src.track}`
  }
  return b.src.kind === 'galaxy' ? t`星系候選 #${b.src.id}` : t`恆星 #${b.src.id}`
}

// Same Planck shape as the backend fit (nu^3 / (e^x - 1)), to draw the model curve.
function bnu(lam, T) { const nu = 2.99792458e8 / (lam * 1e-6), x = Math.min(6.62607015e-34 * nu / (1.380649e-23 * T), 700); return nu ** 3 / Math.expm1(x) }

export function Spectrum({ b }) {
  const W = 340, H = 170, P = 34
  const pts = b.group === 'source' ? b.src.spectrum.map(([l, f]) => [l, f]) : b.src.photometry
  const good = pts.filter(([, f]) => f > 0)
  if (good.length < 2) return <p className="muted small">光度資料不足，無法畫出光譜。</p>
  const ys = good.map(([, f]) => Math.log10(f)), y0 = Math.min(...ys) - 0.2, y1 = Math.max(...ys) + 0.2
  const X = (l) => P + (Math.log10(l / 0.75) / Math.log10(5 / 0.75)) * (W - P - 8), Y = (v) => H - 22 - ((v - y0) / (y1 - y0)) * (H - 34)
  const curve = []
  if (b.group === 'source' && b.src.fit) for (let l = 0.75; l <= 5; l *= 1.04) { const v = b.src.fit.model_scale * bnu(l, b.src.fit.T); if (v > 0) curve.push(`${X(l).toFixed(1)},${Y(Math.log10(v)).toFixed(1)}`) }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="spec" role="img" aria-label="實測光譜與模型">
      <rect x={P} y={8} width={W - P - 8} height={H - 30} fill="none" stroke="#ffffff22" />
      {[0.75, 1, 2, 3, 5].map((l) => <text key={l} x={X(l)} y={H - 6} textAnchor="middle">{l}</text>)}
      <text x={W - 8} y={H - 6} textAnchor="end">µm</text>
      <text x={4} y={14}>log F</text>
      {curve.length > 1 && <polyline points={curve.join(' ')} fill="none" stroke="#ffb547" strokeWidth="1.6" />}
      {good.map(([l, f], k) => <circle key={k} cx={X(l)} cy={Y(Math.log10(f))} r="2.2" fill="#6ec3ff" />)}
    </svg>
  )
}

function Editor({ body, onApply }) {
  const [type, setType] = useState(body.type)
  const [p, setP] = useState(body.params)
  const pv = useRef(), prev = useRef()
  useEffect(() => { setType(body.type); setP(body.params) }, [body.key])
  useEffect(() => { prev.current = new Preview(pv.current); return () => prev.current.destroy() }, [])
  useEffect(() => { prev.current?.show(type, p, body.seed) }, [type, p, body.seed])
  const lib = LIBRARY.filter((l) => (body.group === 'source' ? ['star', 'galaxy'] : ['rocky', 'comet', 'ice_giant']).includes(l.type))
  return (
    <div className="editor">
      <canvas ref={pv} className="preview" aria-label="建構預覽" />
      <label className="field">預設
        <select value="" onChange={(e) => {
          if (e.target.value === 'model') { setType(body.predicted.type); setP(body.predicted.p); return }
          const l = LIBRARY.find((x) => x.id === e.target.value); if (l) { setType(l.type); setP({ ...l.p }) }
        }}>
          <option value="" disabled>選擇預設…</option>
          <option value="model">模型預測（由光譜擬合）</option>
          {lib.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
      </label>
      <div className="sliders">
        {PARAMS[type].map((d) => (
          <label key={d.key} className="slider">
            <span>{d.label}<b className="num">{d.key === 'temperature' ? Math.round(p[d.key]) : Number(p[d.key] ?? 0).toFixed(d.step < 1 ? 2 : 0)}</b></span>
            {d.key === 'temperature' && <i className="swatch" style={{ background: `rgb(${bbColor(p.temperature).map((v) => Math.round(v * 255)).join(',')})` }} />}
            <input type="range" min={d.log ? Math.log(d.min) : d.min} max={d.log ? Math.log(d.max) : d.max} step={d.log ? 0.01 : d.step}
              value={d.log ? Math.log(p[d.key] ?? d.min) : (p[d.key] ?? d.min)}
              onChange={(e) => setP({ ...p, [d.key]: d.log ? Math.exp(+e.target.value) : +e.target.value })} />
          </label>
        ))}
      </div>
      <div className="row">
        <button className="btn primary small" onClick={() => onApply({ ...body, type, params: p })}>重建這顆球</button>
        <button className="btn small" onClick={() => { setType(body.predicted.type); setP(body.predicted.p); onApply({ ...body, type: body.predicted.type, params: body.predicted.p }) }}>還原模型預測</button>
      </div>
    </div>
  )
}

/** The assistant's context for a reconstructed body: what the spectrum fit or JPL says about it. */
function bodyCtx(b, field) {
  const s = b.src, num = (v, d = 2) => (v == null || !isFinite(v) ? null : +(+v).toFixed(d))
  if (b.group === 'source') {
    return { kind: s.kind === 'galaxy' ? 'body' : 'star', id: `${field?.id}/s${s.id}`, name: bodyTitle(b), ra: num(s.ra, 5), dec: num(s.dec, 5),
      facts: { field: field ? fieldName(field) : null, model: s.kind === 'galaxy' ? 'power law (galaxy-like)' : 'blackbody', temperature_K: s.kind === 'galaxy' ? null : num(s.fit?.T, 0),
        power_law_beta: s.kind === 'galaxy' ? num(s.fit?.beta) : null, chi2r_blackbody: num(s.fit?.chi2r_bb, 1), chi2r_power_law: num(s.fit?.chi2r_pl, 1),
        distance_pc_if_main_sequence: num(s.distance_pc, 0), snr: s.snr } }
  }
  return { kind: 'object', id: `${field?.id}/${b.track?.id ?? s.track}`, name: bodyTitle(b), facts: { field: field ? fieldName(field) : null, simulated: s.simulated ? true : null,
    known_as: s.known || null, diameter_km: s.sbdb?.diameter ?? null, albedo: s.sbdb?.albedo ?? null, rotation_h: s.sbdb?.rot_per ?? null, spectral_class: s.sbdb?.spec_B || s.sbdb?.spec_T || null,
    orbit_class: s.sbdb?.orbit_class ?? null, reflectance_slope_per_um: num(s.reflectance_slope, 3), parallax_distance_au: s.preset?.d_au ?? null, detections: s.path?.length } }
}

function Details({ b, field, onApply, onClose }) {
  const s = b.src
  return (
    <aside className="u-panel" aria-label="天體資料">
      <button className="close" onClick={onClose} aria-label="關閉">×</button>
      <p className="u-kind">{TYPE_LABEL[b.predicted.type] || b.predicted.type}{s.simulated ? <span className="tag sim" style={{ marginLeft: 8 }}>模擬</span> : null}</p>
      <h2>{bodyTitle(b)}</h2>
      <button className="btn small" onClick={() => askAbout(bodyCtx(b, field))}>{L('問問這個天體 →', 'Ask about this →')}</button>
      {b.group === 'source' ? (
        <dl className="kv">
          <dt>模型</dt><dd>{s.kind === 'galaxy' ? t`冪律比黑體更符合（β = ${s.fit.beta.toFixed(2)}）` : t`黑體 T = ${Math.round(s.fit.T)} K`}</dd>
          <dt>擬合品質</dt><dd className="num">χ²ᵣ {s.fit.chi2r_bb.toFixed(1)} (BB) · {s.fit.chi2r_pl.toFixed(1)} (PL)</dd>
          {s.distance_pc && <><dt>推估距離</dt><dd>{t`約 ${s.distance_pc >= 1000 ? (s.distance_pc / 1000).toFixed(1) + ' kpc' : Math.round(s.distance_pc) + ' pc'}（假設主序星）`}</dd></>}
          <dt>座標</dt><dd className="num">RA {s.ra.toFixed(4)}° · Dec {s.dec.toFixed(4)}°</dd>
          <dt>訊噪比</dt><dd className="num">{s.snr}</dd>
        </dl>
      ) : (
        <dl className="kv">
          {s.known && <><dt>已知名稱</dt><dd>{s.known}</dd></>}
          {s.sbdb?.diameter && <><dt>直徑（JPL）</dt><dd>{s.sbdb.diameter} km</dd></>}
          {s.sbdb?.albedo && <><dt>反照率（JPL）</dt><dd>{s.sbdb.albedo}</dd></>}
          {s.sbdb?.rot_per && <><dt>自轉週期（JPL）</dt><dd>{s.sbdb.rot_per} h</dd></>}
          {(s.sbdb?.spec_B || s.sbdb?.spec_T) && <><dt>光譜分類（JPL）</dt><dd>{s.sbdb.spec_B || s.sbdb.spec_T}</dd></>}
          {s.sbdb?.orbit_class && <><dt>軌道類型</dt><dd>{s.sbdb.orbit_class}</dd></>}
          {s.reflectance_slope != null && <><dt>反射光譜斜率</dt><dd className="num">{s.reflectance_slope.toFixed(3)} / µm</dd></>}
          {s.preset?.d_au && <><dt>視差擬合距離</dt><dd>{s.preset.d_au} AU</dd></>}
          <dt>偵測次數</dt><dd>{s.path.length}</dd>
        </dl>
      )}
      <h3>實測光譜</h3>
      <Spectrum b={b} />
      <p className="muted small">{b.group === 'source' ? '藍點：每個 SPHEREx 波段的實測流量；橘線：模型。' : '藍點：每次偵測在差分影像中的流量（不同時間、不同波長）。'}</p>
      <h3>外觀參數</h3>
      <p className="muted small">每顆球都是依照這組參數即時「建構」的。選一個預設或拖動滑桿，再按「重建這顆球」。</p>
      <Editor body={b} onApply={onApply} />
      {b.group === 'mover' && b.track && <button className="btn small" style={{ marginTop: 12 }} onClick={() => go(field.id, b.track.id)}>查看科學證據 →</button>}
    </aside>
  )
}

export default function Universe({ fields, section, page, initialField, pick }) {
  const lang = useLanguage()
  const canvas = useRef(), sceneRef = useRef()
  const [fid, setFid] = useState(initialField || 'cybele')
  useEffect(() => { if (initialField) setFid(initialField) }, [initialField])
  const [bodies, setBodies] = useState([])
  const [expanded, setExpanded] = useState(false)
  const [sel, setSel] = useState(null)
  const [hover, setHover] = useState(null)
  const [state, setState] = useState('loading')
  const [touched, setTouched] = useState(false)
  const [force, setForce] = useState(false)          // open 3D even without GPU acceleration
  const field = useMemo(() => fields.find((f) => f.id === fid), [fields, fid])
  const choices = useMemo(() => fields.filter((f) => f.has_universe), [fields])

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!force && !gpuOK()) { setState('slowgl'); return undefined }
    try {
      const probe = document.createElement('canvas')
      if (!(probe.getContext('webgl2') || probe.getContext('webgl'))) throw new Error('no WebGL')
      sceneRef.current = new UniverseScene(canvas.current, {
        reducedMotion: reduced, noShift: !!page,
        onPick: (d) => setSel(d),
        onHover: (h) => setHover(h),
      })
    } catch { setState('nogl') }
    // render only while the scene is on screen and the tab is visible
    const el = canvas.current.parentElement
    let onScreen = true
    const sync = () => sceneRef.current?.setActive(onScreen && !document.hidden)
    const io = new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; sync() })
    io.observe(el); document.addEventListener('visibilitychange', sync)
    return () => { io.disconnect(); document.removeEventListener('visibilitychange', sync); sceneRef.current?.destroy(); sceneRef.current = null }
  }, [force])

  useEffect(() => {
    if (!sceneRef.current) { setState((v) => (v === 'slowgl' ? v : 'nogl')); return }
    let dead = false
    setState('loading'); setSel(null); setExpanded(false)
    Promise.all([api(`/data/fields/${fid}/universe.json`), api(`/api/field/${fid}`)]).then(([uni, fd]) => {
      if (dead) return
      const bs = toBodies(uni, fd)
      setBodies(bs)
      sceneRef.current.load({ W: uni.shape[1], H: uni.shape[0], imageUrl: `/data/fields/${fid}/deep_rgb.webp`, bodies: bs })
      setState('ready')
      setTimeout(() => { if (!dead) { sceneRef.current.expand(true); setExpanded(true) } }, 700)
      // deep link: open one body (e.g. from the point check or an object page) once the universe has unfolded
      if (pick) setTimeout(() => { const b = bs.find((x) => x.key === pick); if (!dead && b) { setSel(b); sceneRef.current.focus(b.key) } }, reducedMotionMs())
    }).catch((e) => { console.error('universe load failed', e); setState('error') })
    return () => { dead = true }
  }, [fid, pick, force])

  // test hook (used by the automated screenshot checks): select a body by key
  useEffect(() => { window.__sxScene = sceneRef.current; window.__sxKeys = bodies.map((b) => b.key); window.__sxPick = (key) => { const b = bodies.find((x) => x.key === key); if (b) { setSel(b); sceneRef.current.focus(key) } } }, [bodies])

  const counts = useMemo(() => {
    const c = { star: 0, known: 0, cand: 0, sim: 0, distant: 0 }, names = new Set()
    for (const b of bodies) {
      if (b.group === 'source') { if (b.type === 'star') c.star++; continue }
      if (b.src.simulated) c.sim++
      else if (b.type === 'ice_giant') c.distant++
      else if (b.src.known) names.add(b.src.known)
      else c.cand++
    }
    c.known = names.size
    return c
  }, [bodies])

  useEffect(() => { sceneRef.current?.setPanel(!!sel) }, [sel])

  function apply(nb) {
    sceneRef.current.rebuild(nb)
    setBodies((bs) => bs.map((b) => (b.key === nb.key ? nb : b)))
    setSel(nb)
  }

  return (
    <div className={`universe ${section ? 'as-section' : ''} ${page ? 'as-page' : ''}`}>
      <canvas ref={canvas} className="u-canvas" onPointerDown={() => setTouched(true)} onWheel={() => setTouched(true)} aria-label="SPHEREx 天區的 3D 宇宙：拖曳旋轉、滾輪縮放、點選天體" />
      {(state === 'nogl' || state === 'slowgl') && <img className="u-fallback" src={`/data/fields/${fid}/deep_rgb.webp`} alt={L('這片天空的 SPHEREx 深度合成影像', 'Deep SPHEREx composite of this field')} />}
      {state === 'slowgl' && <div className="u-status u-slow">{L('這台裝置沒有 GPU 加速，3D 會讓頁面卡住好幾秒，先顯示平面影像。', 'This device has no GPU acceleration; 3D would freeze the page for seconds, so the flat image is shown.')} <button className="btn small" onClick={() => setForce(true)}>{L('仍要開啟 3D', 'Open 3D anyway')}</button></div>}
      <div className={`u-head ${sel ? 'dim' : ''}`}>
        <div className="u-actions">
          <button className="btn primary" onClick={() => { sceneRef.current.expand(!expanded); setExpanded(!expanded) }}>{expanded ? '收回成影像' : '展開成宇宙'}</button>
          <button className="link" onClick={() => go(fid)}>打開這片天空 →</button>
        </div>
      </div>
      {state === 'loading' && <div className="u-status">正在把影像轉成宇宙…</div>}
      {state === 'error' && <div className="u-status">這個天區還沒有 3D 資料。</div>}
      {hover && !sel && <div className="u-tip" style={{ left: hover.x + 14, top: hover.y + 14 }}><b>{bodyTitle(hover.data)}</b><span>{TYPE_LABEL[hover.data.type]}</span></div>}
      <div className={`u-bar ${sel ? 'with-panel' : ''}`}>
        <div className="u-fields" role="group" aria-label="切換天區">
          {choices.map((f) => <button key={f.id} className={f.id === fid ? 'on' : ''} aria-pressed={f.id === fid} onClick={() => (page ? goUniverse(f.id) : setFid(f.id))}>{fieldName(f)}</button>)}
        </div>
        <p className={`u-legend ${touched ? 'quiet' : ''}`}>
          <span><i style={{ background: '#fff4e0' }} />{t`${counts.star} 顆恆星`}</span>
          {counts.known ? <span><i style={{ background: '#6ec3ff' }} />{t`${counts.known} 顆已知小行星`}</span> : null}
          {counts.cand ? <span><i style={{ background: '#ffb547' }} />{t`${counts.cand} 個未確認的移動候選`}</span> : null}
          {counts.sim ? <span><i style={{ background: '#ff4fd8' }} />{t`${counts.sim} 顆模擬行星`}</span> : null}
          {counts.distant ? <span><i style={{ background: '#c08bff' }} />{t`${counts.distant} 個遠距候選`}</span> : null}
          <span className="hint">拖曳旋轉、滾輪縮放；深度為模型推估</span>
        </p>
      </div>
      {sel && <Details b={bodies.find((b) => b.key === sel.key) || sel} field={field} onApply={apply} onClose={() => { setSel(null); sceneRef.current.select(null) }} />}
    </div>
  )
}
