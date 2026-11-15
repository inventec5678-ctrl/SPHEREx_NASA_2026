import { useEffect, useMemo, useRef, useState } from 'react'
import { L } from '../lib.js'

/*
 * Zoomed all the way in: one real SPHEREx field (0.3 deg) at the bottom of the cosmos zoom.
 * Pick a camera (SPHEREx has six detector arrays, each its own band of wavelengths, or all of them stacked), drag
 * time (half-year stacks, crossfaded, or every single exposure), switch to "what changed" (a stack minus the first
 * stack, or the pipeline's difference image), and zoom further in. The marks show how each verdict is reached: where
 * the star was measured in each half-year stack, where Gaia says it should be, the aperture a variable is measured
 * in, the detections an asteroid track is linked from.
 */
const CAMS = [
  { d: 0, um: L('全部', 'All') }, { d: 1, um: '0.75–1.09' }, { d: 2, um: '1.10–1.62' }, { d: 3, um: '1.63–2.41' },
  { d: 4, um: '2.42–3.82' }, { d: 5, um: '3.83–4.41' }, { d: 6, um: '4.42–5.00' },
]
const mjdDate = (m) => new Date((m - 40587) * 864e5).toISOString().slice(0, 10)
const pad4 = (i) => String(i).padStart(4, '0')
const clamp = (x, a, b) => Math.max(a, Math.min(b, x))

export default function FieldView({ summary, onExit, onNext, guide }) {
  const id = summary.id, base = `/data/fields/${id}`
  const [field, setField] = useState(null)
  const [pm, setPm] = useState([])
  const [cam, setCam] = useState(0)
  const [mode, setMode] = useState('stack')          // stack | single | change
  const [t, setT] = useState(0)                      // stack: 0 .. n-1 (fractional); single: index into the camera's exposures
  const [playing, setPlaying] = useState(false)
  const [zoom, setZoom] = useState(summary.target?.kind === 'pm' ? 3 : 1)   // a moving star: start close enough to see it move
  const [pan, setPan] = useState([0, 0])
  const [err, setErr] = useState(false)
  const stage = useRef(), diffCv = useRef()
  const [drag, setDrag] = useState(false)

  useEffect(() => {
    let dead = false
    fetch(`/api/field/${id}`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((f) => { if (!dead) setField(f) }).catch(() => !dead && setErr(true))
    fetch(`${base}/pm_candidates.json`).then((r) => (r.ok ? r.json() : null)).then((d) => { if (!dead && d) setPm(d.candidates || []) }).catch(() => {})
    return () => { dead = true }
  }, [id, base])

  const passes = field?.products?.passes || []
  const npass = passes.length
  useEffect(() => { if (field && !npass) setMode('single') }, [field, npass])
  const exps = useMemo(() => (field?.exposures || []).filter((e) => cam === 0 || e.detector === cam).sort((a, b) => a.mjd - b.mjd), [field, cam])
  const H = field?.shape?.[0] || 177, W = field?.shape?.[1] || 177
  const scale = field ? Math.abs(field.wcs.cdelt[0]) * 3600 : 6.15
  const tgt = field?.target

  // where to zoom: the target, else the fastest mover, else the middle
  const focus = useMemo(() => {
    if (tgt?.passes?.[0]) { const p = tgt.passes[0].fit || tgt.passes[0]; return [p.x, p.y] }
    const c = [...pm].sort((a, b) => (b.pm_arcsec_yr || 0) - (a.pm_arcsec_yr || 0))[0]
    if (c) return [c.x, c.y]
    const tr = field?.tracks?.[0]
    if (tr) { const m = field.candidates[tr.members[0]]; if (m) return [m.x, m.y] }
    return [W / 2 - 0.5, H / 2 - 0.5]
  }, [tgt, pm, field, W, H])

  // play: stacks glide through the year, single exposures step at 8 a second
  useEffect(() => {
    if (!playing) return
    let raf, last = performance.now()
    const n = mode === 'single' ? exps.length : npass
    const step = (now) => {
      const dt = (now - last) / 1000; last = now
      setT((v) => { const nv = v + dt * (mode === 'single' ? 8 : 0.5); return nv > n - 1 ? 0 : nv })
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [playing, mode, exps.length, npass])
  useEffect(() => { setT(mode === 'change' ? Math.max(0, npass - 1) : 0) }, [mode, cam]) // eslint-disable-line react-hooks/exhaustive-deps

  // "what changed" for stacks: this half-year minus the first, computed here (warm = brighter now, blue = fainter)
  const kNow = clamp(Math.round(t), 0, Math.max(0, npass - 1))
  useEffect(() => {
    if (mode !== 'change' || !npass || !diffCv.current) return
    let dead = false
    const load = (k) => new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = `${base}/pass/p${k}_d${cam}.webp` })
    Promise.all([load(0), load(kNow)]).then(([a, b]) => {
      if (dead) return
      const c = diffCv.current, g = c.getContext('2d', { willReadFrequently: true }); c.width = W; c.height = H
      g.drawImage(a, 0, 0); const A = g.getImageData(0, 0, W, H).data
      g.drawImage(b, 0, 0); const img = g.getImageData(0, 0, W, H), B = img.data
      for (let i = 0; i < B.length; i += 4) {
        const d = ((B[i] + B[i + 1] + B[i + 2]) - (A[i] + A[i + 1] + A[i + 2])) / 3, v = clamp(Math.abs(d) * 2.2, 0, 255)
        if (d > 0) { B[i] = 10 + v; B[i + 1] = 10 + v * 0.85; B[i + 2] = 10 + v * 0.55 } else { B[i] = 10 + v * 0.35; B[i + 1] = 10 + v * 0.65; B[i + 2] = 10 + v }
      }
      g.putImageData(img, 0, 0)
    }).catch(() => {})
    return () => { dead = true }
  }, [mode, kNow, cam, npass, base, W, H])

  // ---- zoom and pan: wheel or pinch; zooming out past the whole field returns to the sky -------------------------
  useEffect(() => {
    const el = stage.current
    if (!el) return
    const wheel = (e) => {
      e.preventDefault()
      const d = e.deltaMode === 1 ? e.deltaY * 30 : e.deltaY
      setZoom((z) => { const nz = z * Math.exp(d * 0.0016); if (nz < 0.9) { onExit(); return 1 } return clamp(nz, 1, 6) })   // same as the sky: down = in
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [onExit])
  const ptrs = useRef(new Map()), pinch = useRef(0)
  const onDown = (e) => { setDrag(true); ptrs.current.set(e.pointerId, [e.clientX, e.clientY]); e.currentTarget.setPointerCapture?.(e.pointerId); if (ptrs.current.size === 2) { const [a, b] = [...ptrs.current.values()]; pinch.current = Math.hypot(a[0] - b[0], a[1] - b[1]) } }
  const onMove = (e) => {
    const p = ptrs.current.get(e.pointerId)
    if (!p) return
    const dx = e.clientX - p[0], dy = e.clientY - p[1]; ptrs.current.set(e.pointerId, [e.clientX, e.clientY])
    if (ptrs.current.size === 2) {
      const [a, b] = [...ptrs.current.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1])
      if (pinch.current) setZoom((z) => { const nz = z * d / pinch.current; if (nz < 0.85) { onExit(); return 1 } return clamp(nz, 1, 6) })
      pinch.current = d; return
    }
    if (zoom > 1) setPan(([x, y]) => [x + dx, y + dy])
  }
  const onUp = (e) => { ptrs.current.delete(e.pointerId); if (ptrs.current.size < 2) pinch.current = 0; if (!ptrs.current.size) setDrag(false) }
  useEffect(() => { if (zoom <= 1.001) setPan([0, 0]) }, [zoom])

  // ---- what is shown at this moment ------------------------------------------------------------------------------
  const k0 = Math.floor(clamp(t, 0, Math.max(0, npass - 1))), k1 = Math.min(npass - 1, k0 + 1), frac = clamp(t - k0, 0, 1)
  const ex = exps[clamp(Math.round(t), 0, Math.max(0, exps.length - 1))]
  const when = mode === 'single'
    ? (ex ? `${ex.iso.slice(0, 10)} · ${ex.lam_um.toFixed(2)} µm · ${L('相機', 'camera')} ${ex.detector}` : '')
    : (passes[kNow] ? `${mjdDate(passes[kNow].mjd0)} → ${mjdDate(passes[kNow].mjd1)}` : '')
  const X = (x) => x + 0.5, Y = (y) => H - 0.5 - y
  const tPass = (k) => (passes[k].mjd0 + passes[k].mjd1) / 2
  const interp = (track) => {                              // a track's position at the current (fractional) pass
    const a = track.find((q) => q.k === k0), b = track.find((q) => q.k === k1) || a
    return a ? [a.x + (b.x - a.x) * frac, a.y + (b.y - a.y) * frac] : null
  }
  // Gaia's prediction from the catalogue proper motion, anchored on the first measured stack
  const gaia = useMemo(() => {
    if (!tgt || tgt.kind !== 'pm' || !tgt.passes?.length || !field) return null
    const p0 = tgt.passes[0].fit || tgt.passes[0], m0 = tPass(0)
    return tgt.passes.map((p, k) => {
      const dt = (tPass(k) - m0) / 365.25
      return { k, x: p0.x + (tgt.pmra / 1000 * dt / 3600) / field.wcs.cdelt[0], y: p0.y + (tgt.pmdec / 1000 * dt / 3600) / field.wcs.cdelt[1] }
    })
  }, [tgt, field]) // eslint-disable-line react-hooks/exhaustive-deps
  const measured = tgt?.passes?.map((p, k) => ({ k, x: (p.fit || p).x, y: (p.fit || p).y })) || []
  const tracks = useMemo(() => (field?.tracks || []).map((tr) => tr.members.map((m) => field.candidates[m]).filter(Boolean)), [field])

  const focusXY = [X(focus[0]) / W, Y(focus[1]) / H]
  const tf = `translate(${pan[0]}px, ${pan[1]}px) scale(${zoom})`
  const origin = `${focusXY[0] * 100}% ${focusXY[1] * 100}%`

  // ---- the words: how this verdict is reached --------------------------------------------------------------------
  const how = !tgt ? (tracks.length
    ? [L('同一晚連續拍很多張，每張都減掉這片天空的平均樣子。', 'Many exposures are taken over a night or two; each has the average look of this patch subtracted.'),
       L('剩下的亮點（圓圈）如果排成一直線、等速移動，就連成一條小行星軌跡。', 'What is left (circles) is linked into an asteroid track when the points fall on a straight line at a steady speed.'),
       L('切到「每一張曝光」，拖時間軸看它移動。', 'Switch to “Every exposure” and drag time to watch it move.')]
    : [L('每半年把這片天空的曝光疊成一張。', 'Every half year the exposures of this patch are stacked into one picture.'),
       L('比較每一張疊圖，找位置有移動的星（圓圈連線）。', 'The stacks are compared to find stars that changed position (linked circles).'),
       L('切到「變化」看相減的結果：會動的星變成一黑一亮的一對。', 'Switch to “What changed” to see the subtraction: a moving star becomes a dark-bright pair.')])
    : tgt.kind === 'pm'
      ? [L('每半年把這片天空的曝光疊成一張（時間軸上的每一格）。', 'Every half year the exposures are stacked into one picture (each step of the time dial).'),
         L('在每張疊圖上量出星的位置（實心圓）。', 'The star is measured in each stack (filled circles).'),
         L('和 Gaia 星表預測的位置（空心方框）比較。', 'Those positions are compared with where the Gaia catalogue says it should be (open squares).'),
         tgt.motion ? L(`結果：一年移動 ${tgt.motion.measured_arcsec}″ ± ${tgt.motion.err_arcsec}″，Gaia 預測 ${tgt.motion.predicted_arcsec}″。`, `Result: it moved ${tgt.motion.measured_arcsec}″ ± ${tgt.motion.err_arcsec}″ in a year; Gaia predicts ${tgt.motion.predicted_arcsec}″.`) : null].filter(Boolean)
      : [L('每半年用同一個圓圈（光圈）量這顆星的亮度。', 'Each half year its brightness is measured inside the same circle (the aperture).'),
         L('換相機看：不同波長的變化幅度不一樣。', 'Switch cameras: the change is different at different wavelengths.'),
         tgt.pass_ratio?.ring?.[`D${cam || 1}`] ? L(`相機 ${cam || 1}：最亮的半年是最暗的 ×${tgt.pass_ratio.ring[`D${cam || 1}`]}。`, `Camera ${cam || 1}: the brightest half year is ×${tgt.pass_ratio.ring[`D${cam || 1}`]} the faintest.`) : null].filter(Boolean)

  const n = mode === 'single' ? exps.length : npass
  const img = (k) => `${base}/pass/p${k}_d${cam}.webp`
  return (
    <div className="fv" role="region" aria-label={L('放大的 SPHEREx 天區', 'Zoomed-in SPHEREx field')}>
      <aside className="fv-side">
        <span className="cz-k">{L('拉近到一個天區', 'Zoomed in')} · 0.3°</span>
        <h2>{tgt?.name || summary.name}</h2>
        <span className="cz-m">RA {field ? field.ra.toFixed(3) : '…'}° · Dec {field ? field.dec.toFixed(3) : '…'}°</span>
        {(tgt?.about || summary.description) && <p className="fv-about">{tgt?.about || summary.description}</p>}
        <h3>{L('怎麼判斷的', 'How it is judged')}</h3>
        <ol className="fv-how">{how.map((s, i) => <li key={i}>{s}</li>)}</ol>
        {guide?.map((g, i) => <div key={i} className="fv-guide"><h3>{g.h}</h3><p>{g.p}</p></div>)}
        <div className="fv-legend" aria-hidden="true">
          {measured.length > 0 && <span><i className="lg-meas" />{L('SPHEREx 量到', 'SPHEREx measured')}</span>}
          {gaia && <span><i className="lg-gaia" />{L('Gaia 預測', 'Gaia predicts')}</span>}
          {!tgt && pm.length > 0 && <span><i className="lg-meas" />{L('移動的星', 'Moving star')}</span>}
          {tracks.length > 0 && <span><i className="lg-ast" />{L('小行星偵測', 'Asteroid detections')}</span>}
          {tgt?.kind === 'var' && <span><i className="lg-ap" />{L('量亮度的光圈', 'Brightness aperture')}</span>}
        </div>
        <div className="fv-acts">
          <button className="cz-btn is-go" onClick={onNext}>{L('隨機換一處 ↻', 'Another place ↻')}</button>
          <button className="cz-btn" onClick={onExit}>{L('回到星空', 'Back to the sky')}</button>
          <a className="cz-btn" href={tgt ? `#/target/${id}` : `#/lab/${id}`}>{L('完整分析 →', 'Full analysis →')}</a>
        </div>
      </aside>

      <div className="fv-main">
        <div className={`fv-stage${drag ? ' is-drag' : ''}`} ref={stage} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
          aria-label={L('滾輪或雙指縮放，拖曳平移；縮到最小回到星空', 'Scroll or pinch to zoom, drag to pan; zoom all the way out to return to the sky')}>
          {err && <p className="fv-err">{L('這個天區讀不到。', 'This field could not be loaded.')}</p>}
          {field && (
            <div className="fv-zoom" style={{ transform: tf, transformOrigin: origin }}>
              {mode === 'stack' && npass > 0 && <>
                <img src={img(k0)} alt="" draggable="false" />
                {k1 !== k0 && <img src={img(k1)} alt="" draggable="false" style={{ opacity: frac }} />}
              </>}
              {mode === 'change' && <canvas ref={diffCv} />}
              {mode === 'single' && ex && <img src={`${base}/sci/${pad4(ex.i)}.${field.frame_ext || 'webp'}`} alt="" draggable="false" />}
              <svg className="fv-marks" viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
                {/* proper-motion stars: measured per stack, the line between, and where it is now */}
                {(tgt?.kind === 'pm' ? [] : mode !== 'single' ? pm : []).map((c, i) => (
                  <g key={i} className="mk-meas">
                    <polyline points={c.track.map((q) => `${X(q.x)},${Y(q.y)}`).join(' ')} />
                    {c.track.map((q) => <circle key={q.k} cx={X(q.x)} cy={Y(q.y)} r={q.k === kNow ? 1.6 : 1} className={q.k === kNow ? 'on' : ''} />)}
                  </g>
                ))}
                {tgt?.kind === 'pm' && mode !== 'single' && <>
                  {gaia && <g className="mk-gaia">{gaia.map((q) => <rect key={q.k} x={X(q.x) - 0.55} y={Y(q.y) - 0.55} width="1.1" height="1.1" className={q.k === kNow ? 'on' : ''} />)}</g>}
                  <g className="mk-meas">
                    <polyline points={measured.map((q) => `${X(q.x)},${Y(q.y)}`).join(' ')} />
                    {measured.map((q) => <circle key={q.k} cx={X(q.x)} cy={Y(q.y)} r={q.k === kNow ? 0.4 : 0.25} className="fill" />)}
                    {(() => { const p = interp(measured); return p && <g className="mk-now"><circle cx={X(p[0])} cy={Y(p[1])} r="4.5" /><line x1={X(p[0]) - 7} x2={X(p[0]) - 5} y1={Y(p[1])} y2={Y(p[1])} /><line x1={X(p[0]) + 5} x2={X(p[0]) + 7} y1={Y(p[1])} y2={Y(p[1])} /></g> })()}
                  </g>
                </>}
                {tgt?.kind === 'var' && tgt.passes?.[kNow] && <circle className="mk-ap" cx={X(tgt.passes[kNow].x)} cy={Y(tgt.passes[kNow].y)} r={(tgt.aperture_px || 2) * 1.6} />}
                {/* asteroid tracks: every linked detection, the ones in this exposure lit */}
                {mode === 'single' && tracks.map((tr, j) => (
                  <g key={j} className="mk-ast">
                    <polyline points={tr.map((c) => `${X(c.x)},${Y(c.y)}`).join(' ')} />
                    {tr.filter((c) => ex && c.i === ex.i).map((c) => <circle key={c.id} cx={X(c.x)} cy={Y(c.y)} r="3.5" />)}
                  </g>
                ))}
              </svg>
            </div>
          )}
          <span className="fv-scale" aria-hidden="true">{L('視野', 'field')} {(W * scale / 60 / zoom).toFixed(1)}′ · {L('1 格 =', '1 px =')} {scale.toFixed(1)}″</span>
          {zoom < 5 && <span className="fv-zhint" aria-hidden="true">{L('再往裡捲動放大 · 往外捲回到星空', 'Scroll in to zoom closer · out to return to the sky')}</span>}
        </div>

        <div className="fv-bar">
          <div className="fv-row" role="group" aria-label={L('相機（偵測器）', 'Camera (detector)')}>
            <span className="fv-lab">{L('相機', 'Camera')}</span>
            {CAMS.map((c) => (
              <button key={c.d} className="cz-chip fv-cam" aria-pressed={cam === c.d} onClick={() => setCam(c.d)}>
                <b>{c.d === 0 ? L('全部疊加', 'All') : `D${c.d}`}</b><small>{c.d === 0 ? '0.75–5.0' : c.um} µm</small>
              </button>
            ))}
          </div>
          <div className="fv-row" role="group" aria-label={L('看什麼', 'What to show')}>
            <span className="fv-lab">{L('影像', 'Image')}</span>
            {npass > 0 && <button className="cz-btn" aria-pressed={mode === 'stack'} onClick={() => setMode('stack')}>{L('半年疊圖', 'Half-year stacks')}</button>}
            <button className="cz-btn" aria-pressed={mode === 'single'} onClick={() => setMode('single')}>{L('每一張曝光', 'Every exposure')}</button>
            {npass > 1 && <button className="cz-btn" aria-pressed={mode === 'change'} onClick={() => setMode('change')}>{L('變化（減去第一次）', 'What changed')}</button>}
          </div>
          <div className="cz-time fv-time">
            <button className="cz-btn" onClick={() => setPlaying(!playing)} aria-pressed={playing} aria-label={playing ? L('暫停', 'Pause') : L('播放', 'Play')}>{playing ? '❚❚' : '▶'}</button>
            <div className="cz-track">
              <input type="range" min={0} max={Math.max(0, n - 1)} step={mode === 'single' ? 1 : 0.01} value={Math.min(t, Math.max(0, n - 1))}
                onChange={(e) => { setPlaying(false); setT(+e.target.value) }} aria-label={L('時間', 'Time')} />
              <div className="cz-ticks" aria-hidden="true">
                {mode === 'single' ? <><span>{exps[0]?.iso.slice(0, 10)}</span><span>{L(`${exps.length} 張`, `${exps.length} exposures`)}</span><span>{exps[exps.length - 1]?.iso.slice(0, 10)}</span></>
                  : passes.map((p) => <span key={p.k}>{mjdDate(p.mjd0).slice(0, 7)}</span>)}
              </div>
            </div>
            <span className="cz-date fv-when">{when}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
