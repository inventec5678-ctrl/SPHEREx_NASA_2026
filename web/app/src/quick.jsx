// Quick look and the embeddable player.
//   QuickLook: any RA/Dec plays within about a minute. The server streams aligned frames in while the rest download
//              (cutouts are requested round robin over survey passes and detectors, so the first frames already span
//              the whole time range); when all are in it adds wavelength-matched difference frames and per-pass stacks.
//   Player:    frames sorted by time, filtered by detector, as images / differences / per-pass stacks, with each
//              frame's SPHEREx contamination flags (overlay and per-flag shares). Used for quick looks and, in the
//              embed page, for analysed fields too.
//   AladinView: Aladin Lite (CDS) with other telescopes' surveys under the SPHEREx field, plus our markers.
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { DET, L, PIX, blitFrame, loadImage, pix2world } from './lib.js'
import { usePlayback } from './play.js'
import { dpr, useBoxWidth } from './canvas.js'
import { TimeWave } from './timewave.jsx'
import { ChartCard } from './charts.jsx'
import { PlayBar } from './playbar.jsx'
import { poll, postJson } from './jobs.js'
import { hashParams, setHashParams } from './sky.js'

// movers.jsx pulls in the validation and WiseView pages (~150 kB): load it only when its lists are shown
const MoverList = lazy(() => import('./movers.jsx').then((m) => ({ default: m.MoverList })))

// SPHEREx L2 FLAGS names (MP_* keywords of the FLAGS header) in plain words
const FLAG_TEXT = {
  SOURCE: ['已知天體', 'known source'], TRANSIENT: ['讀出時的暫態', 'transient during readout'], OVERFLOW: ['飽和', 'saturated'],
  SUR_ERROR: ['機上處理錯誤', 'onboard processing error'], PHANTOM: ['幻影像素', 'phantom pixel'], REFERENCE: ['參考像素', 'reference pixel'],
  NONFUNC: ['永久失效', 'permanently unusable'], DICHROIC: ['分光片效率低', 'low dichroic efficiency'], MISSING_DATA: ['資料遺失', 'data lost onboard'],
  HOT: ['熱像素', 'hot pixel'], COLD: ['冷像素', 'cold pixel'], PHANMISS: ['未做幻影校正', 'no phantom correction'],
  NONLINEAR: ['非線性無法校正', 'nonlinearity not correctable'], PERSIST: ['殘影', 'persistence'], OUTLIER: ['離群（如宇宙射線）', 'outlier (e.g. cosmic ray)'],
  GHOST: ['鬼影', 'ghost'], UNUSABLE: ['不可用', 'unusable'],
}
// colours of the flag overlay (sxlib/products.flag_rgba)
const FLAG_KEY = [['#ff4646', ['飽和', 'saturated']], ['#aa78ff', ['殘影', 'persistence']], ['#ff4fd8', ['鬼影', 'ghost']], ['#ffa03c', ['離群', 'outlier']], ['#969696', ['不可用', 'unusable']]]
const FLAG_COL = ['#ff4646', '#ffa03c', '#aa78ff', '#ff4fd8', '#6ec3ff', '#9be37a']
const DETS = [1, 2, 3, 4, 5, 6]
/** Index of the frame nearest in time to `m` (MJD), and how far it is (days). */
function nearest(list, m) {
  let best = 0
  list.forEach((f, j) => { if (Math.abs(f.mjd - m) < Math.abs(list[best].mjd - m)) best = j })
  return [best, Math.abs(list[best].mjd - m)]
}
const pct = (v) => (v >= 0.1 ? `${Math.round(v * 100)}%` : v >= 0.001 ? `${(v * 100).toFixed(1)}%` : '<0.1%')

/** frames: [{sci, diff?, flag?, fl?, mjd, iso, det, lam}] ; stacks: [{url, pass, det, iso, n}] ; geo: {wcs, shape} */
export function Player({ frames, stacks, geo, loading, compact, title, marks, note, side }) {
  useLanguage()
  // the view (what is shown, which detector, which frame when paused) lives in the URL, so a shared link shows the same thing
  const init = useMemo(() => { const u = hashParams(); return { v: u.get('v'), d: u.get('d'), k: u.get('k'), pf: u.get('pf') === '1' } }, [])
  const [showFlags, setShowFlags] = useState(init.pf)
  const { hasFlags, hasDiff, hasFl, dets } = useMemo(() => ({
    hasFlags: frames.some((f) => f.flag), hasDiff: frames.some((f) => f.diff), hasFl: frames.some((f) => f.fl),
    dets: DETS.filter((d) => frames.some((f) => f.det === d)),
  }), [frames])
  const [det, setDet] = useState(init.d != null ? +init.d : -1)          // -1: not chosen yet (all detectors until enough frames are in)
  const [mode, setModeRaw] = useState(['diff', 'stack'].includes(init.v) ? init.v : 'sci')
  const [fps, setFps] = useState(6)
  const [hover, setHover] = useState(null)
  const cv = useRef(), stage = useRef(), seekTo = useRef(null)
  const stageW = useBoxWidth(stage)
  // one detector by default: neighbouring frames then have similar wavelengths, so the picture is steady and what
  // changes is position, not brightness. The fullest detector is picked once a few frames are in.
  useEffect(() => {
    if (det !== -1 || frames.length < 6) return
    const cnt = {}; for (const f of frames) cnt[f.det] = (cnt[f.det] || 0) + 1
    setDet([3, 2, 4, 1, 5, 6].filter((d) => cnt[d]).sort((a, b) => cnt[b] - cnt[a])[0] || 0)
  }, [det, frames])
  const wantMode = useRef(init.v)
  // a link that asks for differences or stacks waits for them, then switches
  useEffect(() => {
    if (wantMode.current === 'diff' && !hasDiff) setModeRaw('sci')
    else if (wantMode.current === 'stack' && !stacks?.length) setModeRaw('sci')
    else if (wantMode.current) { setModeRaw(wantMode.current); wantMode.current = null }
  }, [hasDiff, stacks?.length])
  const passes = useMemo(() => [...new Set((stacks || []).map((s) => s.pass))].sort((a, b) => a - b), [stacks])
  const list = useMemo(() => {
    if (mode === 'stack') {
      const d = det > 0 ? det : 6
      return passes.map((p) => (stacks.find((s) => s.pass === p && s.det === d))).filter(Boolean)
        .map((s) => ({ sci: s.url, iso: s.iso, det: s.det, pass: s.pass, n: s.n, partial: s.partial }))
    }
    return frames.filter((f) => (det <= 0 || f.det === det) && (mode === 'sci' || f.diff)).sort((a, b) => a.mjd - b.mjd)
  }, [frames, det, mode, stacks, passes])
  // a link that carries a paused frame (?k=) opens paused on it
  const pb = usePlayback(list.length, { hz: mode === 'stack' ? 1 / 0.9 : fps, autoplay: init.k == null, start: init.k != null ? +init.k : 0 })
  const { k, setK, playing: play, setPlaying: setPlay } = pb
  const setMode = (m) => { setModeRaw(m); setK(0) }
  useEffect(() => { setHashParams({ v: mode === 'sci' ? null : mode, d: det > 0 ? det : det === 0 ? 0 : null, k: play ? null : k, pf: showFlags ? 1 : null }) }, [mode, det, play, k, showFlags])
  const cur = list[k]
  // preload a few frames ahead so playback does not stutter while streaming
  useEffect(() => { for (let j = 1; j <= 8 && list.length; j++) { const f = list[(k + j) % list.length]; loadImage(mode === 'diff' ? f.diff : f.sci); if (showFlags && f.flag && mode !== 'stack') loadImage(f.flag) } }, [k, list, mode, showFlags])
  const n = geo.shape[0]
  // a whole number of device pixels per SPHEREx pixel, and a box exactly that size; the charts take the rest
  const wide = !compact && stageW >= 900
  const avail = stageW ? (wide ? Math.min(760, Math.max(320, stageW * 0.56)) : stageW) : (compact ? 480 : 600)
  const fit = useMemo(() => { const u = dpr(), sp = Math.max(1, Math.floor((avail * u) / n)), W = sp * n; return { W, s: sp, off: 0, u, css: W / u } }, [avail, n])
  useEffect(() => {
    const c = cv.current
    if (!c || !cur) return
    const url = mode === 'diff' ? cur.diff : cur.sci
    let live = true
    loadImage(url, (im) => {
      if (!live || !im) return
      // whole-number zoom at the screen's pixel density (an 89-pixel image is not stretched by 6.74)
      const { W, s, off: m0, u } = fit
      if (c.width !== W || c.height !== W) { c.width = W; c.height = W }
      const D = n * s
      const g = c.getContext('2d')
      g.imageSmoothingEnabled = false
      g.fillStyle = '#000'; g.fillRect(0, 0, W, W)
      g.save(); g.translate(m0, m0)
      blitFrame(g, im, mode === 'diff' ? 'diff' : 'sci', 0, 0, im.width, im.height, D, D)
      g.restore()
      const rest = () => {
        // centre reticle (the requested position)
        g.strokeStyle = 'rgba(255,255,255,.55)'; g.lineWidth = 1.5 * u
        const m = W / 2, r = 14 * u, t = 10 * u
        g.beginPath(); g.moveTo(m - r - t, m); g.lineTo(m - r, m); g.moveTo(m + r, m); g.lineTo(m + r + t, m)
        g.moveTo(m, m - r - t); g.lineTo(m, m - r); g.moveTo(m, m + r); g.lineTo(m, m + r + t); g.stroke()
        for (const mk of marks || []) {
          if (cur.pass != null ? mk.k !== cur.pass : mk.mjd0 && !(cur.mjd >= mk.mjd0 - 5 && cur.mjd <= mk.mjd1 + 5)) continue
          g.strokeStyle = mk.c || '#ffb547'; g.lineWidth = 2 * u
          g.beginPath(); g.arc(m0 + (mk.x + 0.5) * s, m0 + (n - 0.5 - mk.y) * s, Math.max(10 * u, 2.2 * s), 0, 7); g.stroke()
        }
      }
      // the frame's contamination flags over the image
      if (showFlags && cur.flag && mode !== 'stack') loadImage(cur.flag, (fm) => { if (!live) return; if (fm) g.drawImage(fm, 0, 0, fm.width, fm.height, m0, m0, D, D); rest() })
      else rest()
    })
    return () => { live = false }
  }, [cur, mode, n, compact, marks, showFlags, fit])
  // keyboard: Space plays or pauses, the arrow keys step (from the player itself, or from the page when nothing is focused)
  const onKey = (e) => {
    if (e.target !== document.body && e.target !== e.currentTarget && e.target.tagName !== 'CANVAS') return
    pb.onKey(e)
  }
  // a point clicked in a light curve or spectrum on this page: show that exposure here
  const listRef = useRef(list); listRef.current = list
  useEffect(() => {
    const on = (e) => {
      const L0 = listRef.current, m = e.detail?.mjd
      if (!L0.length || !m || mode === 'stack') return
      const [best, d] = nearest(L0, m)
      if (d > 0.01) return
      pb.seek(best)
      cv.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
    window.addEventListener('sx:seek', on)
    return () => window.removeEventListener('sx:seek', on)
  }, [mode]) // eslint-disable-line react-hooks/exhaustive-deps
  const keyRef = useRef(onKey); keyRef.current = onKey
  useEffect(() => {
    const on = (e) => { if (e.target === document.body) keyRef.current(e) }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])
  const toPix = (e) => { const r = e.target.getBoundingClientRect(), k = fit.W / r.width; return { x: ((e.clientX - r.left) * k - fit.off) / fit.s - 0.5, y: n - 0.5 - ((e.clientY - r.top) * k - fit.off) / fit.s } }
  const arc = n * PIX > 1500 ? 300 : 120, barCss = (arc / PIX) * fit.s / fit.u
  const world = hover ? pix2world(geo, hover.x, hover.y) : null
  // a click on the time × wavelength chart: show that exposure (now, or once the detector filter has changed)
  const trySeek = () => {
    const m = seekTo.current
    if (m == null || !list.length || mode === 'stack') return
    const [best, d] = nearest(list, m)
    if (d < 0.01) { seekTo.current = null; pb.seek(best) }
  }
  useEffect(trySeek)
  // every exposure in time and wavelength (all detectors), with the one on screen ringed; a click shows it
  const tw = useMemo(() => frames.map((f) => ({ mjd: f.mjd, lam: f.lam, det: f.det, iso: f.iso })), [frames])
  const twCur = cur && mode !== 'stack' ? frames.findIndex((f) => f.mjd === cur.mjd && f.det === cur.det) : null
  const flagItems = cur?.fl && mode !== 'stack' ? Object.entries(cur.fl).filter(([, v]) => v > 0).sort((x, y) => y[1] - x[1]) : []
  return (
    <div ref={stage} className={`qp tool-stage ${compact ? 'compact' : ''}`} tabIndex={0} onKeyDown={onKey} role="group" style={wide ? { gridTemplateColumns: `${fit.css}px minmax(0, 1fr)` } : undefined}
      aria-label={L('影像播放器。空白鍵播放或暫停，左右鍵逐張。', 'Image player. Space plays or pauses; left and right arrows step.')}>
      <div className="stage-main">
        <div className="toolbar" role="toolbar" aria-label={L('播放控制', 'Player controls')}>
          <div className="seg" role="group" aria-label={L('顯示', 'Show')}>
            <button aria-pressed={mode === 'sci'} onClick={() => setMode('sci')}>{L('影像', 'Images')}</button>
            <button aria-pressed={mode === 'diff'} disabled={!hasDiff} onClick={() => setMode('diff')}>{L('差分', 'Difference')}</button>
            <button aria-pressed={mode === 'stack'} disabled={!stacks?.length} onClick={() => { setMode('stack'); if (det <= 0) setDet(6) }}>{L('各輪疊加', 'Pass stacks')}</button>
          </div>
          <label className="tb-select"><span>{L('偵測器', 'Detector')}</span>
            <select className="tb-det" aria-label={L('偵測器', 'Detector')} value={String(Math.max(0, det))} onChange={(e) => { setDet(+e.target.value); setK(0) }}>
              {mode !== 'stack' && <option value="0">{L('全部（依時間交錯）', 'All (in time order)')}</option>}
              {dets.map((d) => <option key={d} value={d}>D{d} · {DET[d].r}</option>)}
            </select>
          </label>
          {hasFlags && <button type="button" className="btn small" aria-pressed={showFlags} disabled={mode === 'stack'} onClick={() => setShowFlags(!showFlags)}>{L('疊上污染旗標', 'Overlay flags')}</button>}
        </div>
      <div className="lab-canvas qp-canvas" style={{ width: fit.css }}>
          <canvas ref={cv} onMouseMove={(e) => setHover(toPix(e))} onMouseLeave={() => setHover(null)}
            aria-label={L('SPHEREx 影像序列', 'SPHEREx image sequence')} />
          {!cur && <div className="route-loading lab-loading" role="status"><i aria-hidden="true" /><span>{loading || L('等待第一張影像…', 'Waiting for the first frame…')}</span></div>}
          {cur && <span className="lab-badge">{mode === 'stack' ? L(`第 ${cur.pass + 1} 輪 · D${cur.det} · ${cur.n} 張疊加${cur.partial ? '（還在增加）' : ''}`, `Pass ${cur.pass + 1} · D${cur.det} · ${cur.n} stacked${cur.partial ? ' (growing)' : ''}`) : `${cur.iso} UTC · D${cur.det} · ${cur.lam.toFixed(2)} µm${cur.rel ? ` · ${cur.rel}` : ''}`}</span>}
          {cur && <span className="lab-scale" aria-hidden="true"><i style={{ width: barCss }} />{arc >= 60 ? `${arc / 60}′` : `${arc}″`}</span>}
          {world && <span className="lab-coord">RA {world[0].toFixed(4)}° Dec {world[1].toFixed(4)}°</span>}
          {title && <span className="qp-title">{title}</span>}
        </div>
        <PlayBar pb={pb} n={list.length} label={L('影像播放', 'Image playback')} speeds={mode !== 'stack' ? [3, 6, 12] : null} hz={fps} setHz={setFps} />
        {/* the frame's SPHEREx flags as a bar of fixed height: the shares change while playing, the layout does not */}
        {hasFl && mode !== 'stack' && (
          <div className="qp-meta flagbar" tabIndex={0} role="img" style={{ maxWidth: fit.css }}
            aria-label={`${L('這張影像的 SPHEREx 旗標', 'SPHEREx flags in this frame')}: ${flagItems.length ? flagItems.map(([nm, v]) => `${L(...(FLAG_TEXT[nm] || [nm, nm]))} ${pct(v)}`).join(', ') : L('沒有', 'none')}`}>
            <b>{L('這張影像的 SPHEREx 旗標', 'SPHEREx flags in this frame')}</b>
            <div className="flagbar-bar">{flagItems.slice(0, 6).map(([nm, v], j) => <i key={nm} style={{ flexGrow: Math.max(v, 0.004), background: FLAG_COL[j % FLAG_COL.length] }} title={`${L(...(FLAG_TEXT[nm] || [nm, nm]))} ${pct(v)}`} />)}<i className="clean" style={{ flexGrow: Math.max(0.01, 1 - flagItems.reduce((t, [, v]) => t + v, 0)) }} /></div>
            <ul className="legend">{flagItems.length ? flagItems.slice(0, 3).map(([nm, v], j) => <li key={nm}><i className="sq" style={{ '--c': FLAG_COL[j % FLAG_COL.length] }} />{L(...(FLAG_TEXT[nm] || [nm, nm]))} {pct(v)}</li>) : <li>{cur?.fl ? L('沒有', 'none') : '—'}</li>}</ul>
          </div>)}
        {showFlags && hasFlags && mode !== 'stack' && <ul className="qp-flagkey">{FLAG_KEY.map(([c, t]) => <li key={c}><i style={{ background: c }} />{L(...t)}</li>)}</ul>}
        {!compact && <p className="stage-note hint" style={{ maxWidth: fit.css }}>{mode === 'diff' ? L('差分：每張減去同一偵測器、同波長、其他時間的中位數。橘色是變亮或新出現，藍色是變暗或離開；移動的天體會留下一對橘藍點。', 'Difference: each frame minus the median of the same detector at the same wavelength at other times. Orange = brighter or new, blue = fainter or gone; a mover leaves an orange-blue pair.')
          : mode === 'stack' ? L('各輪疊加：同一輪巡天、同一偵測器的影像平均，雜訊較低；輪流播放時，移動的星會跳動。', 'Pass stacks: every exposure of one survey pass and one detector averaged, for lower noise; blinking them makes moving stars jump.')
          : L('中間的十字是你輸入的座標。只閃一下的單一亮點或暗點是壞像素或宇宙射線；真的天體會連續出現在好幾張裡。', 'The cross marks the position you asked for. A single dot that flashes once is a bad pixel or a cosmic ray; a real object appears in several frames in a row.')}
          {!hasDiff && frames.length > 0 && mode === 'sci' ? L(' 差分影像在下載到約三分之一時就會先出現。', ' Difference frames first appear when about a third of the images are in.') : ''}
          {note ? ` ${note}` : ''}</p>}
      </div>
      {!compact && <aside className="stage-side">
        <ChartCard level={3} title={L('什麼時候、用哪個波長拍這裡', 'When, and at what wavelength, SPHEREx looked here')}
          take={L(`已經有 ${frames.length} 張影像。白圈是現在播放的這一張；每張的波長都不同，所以亮度會隨波長跳動。`, `${frames.length} exposures so far. The ring is the one on screen; each has its own wavelength, which is why brightness jumps from frame to frame.`)}>
          <TimeWave height={300} frames={tw} current={twCur != null && twCur >= 0 ? twCur : null} pass={mode === 'stack' ? cur?.pass ?? null : null} hint={L('點一下：播放這一張', 'Click: show this exposure')}
            onPick={(f) => { if (mode === 'stack') setMode('sci'); if (det > 0 && f.det !== det) setDet(f.det); seekTo.current = f.mjd; trySeek() }} />
        </ChartCard>
        {side}
      </aside>}
    </div>
  )
}

// ---- quick look -----------------------------------------------------------------------------------------------
export function QuickLook({ ra, dec, size = 0.3, compact, onState }) {
  useLanguage()
  const [st, setSt] = useState(null), [err, setErr] = useState(null)
  useEffect(() => {
    let live = true, stop = () => {}
    setSt(null); setErr(null)
    postJson('/api/quick', { ra, dec, size })
      .then((j) => {
        if (!live) return
        stop = poll(`/api/quick/${j.id}`, {
          onUpdate: (p) => { setSt(p); onState?.(p); if (p.status === 'error') setErr(p.error) },
          done: (p) => p.status === 'done' || p.status === 'error',
        })
      })
      .catch((e) => {
        const m = String(e)
        if (live) setErr(m.includes('429') ? 'busy' : m.includes('507') ? 'disk' : 'server')
      })
    return () => { live = false; stop() }
  }, [ra, dec, size])
  const base = st ? `/data/quick/${st.id}` : ''
  const run = st?.started ? Math.round(st.started) : 0          // frame names restart if the same look is run again
  const frames = useMemo(() => (st?.frames || []).map((f) => {
    const nm = String(f.f).padStart(4, '0')
    // a difference frame is recomputed when all images are in: its version (dv) keeps the cached early one from sticking
    return { ...f, sci: `${base}/sci/${nm}.webp?r=${run}`, diff: f.diff ? `${base}/diff/${nm}.webp?r=${run}${f.dv ? `&v=${f.dv}` : ''}` : null,
      flag: f.fl ? `${base}/flag/${nm}.webp?r=${run}` : null }
  }), [st, base, run])
  // stacks are rewritten as frames arrive: the frame count in the URL makes the browser fetch the new version
  const marks = useMemo(() => (st?.movers?.candidates || []).flatMap((c) => c.track.map((t) => (
    { x: t.x, y: t.y, k: t.k, mjd0: t.mjd - 40, mjd1: t.mjd + 40, c: c.status === 'known' ? '#5fd39a' : '#ff4fd8' }))), [st])
  const stacks = useMemo(() => (st?.stacks || []).map((s) => ({ ...s, url: `${base}/stack/p${s.pass}_d${s.det}.webp?n=${s.n}` })), [st, base])
  const msg = () => ({
    busy: L('伺服器正在處理其他預覽，請過一分鐘再試。', 'The server is busy with other previews; try again in a minute.'),
    disk: L('伺服器空間不足，暫時無法預覽。', 'The server is short of disk space; previews are paused.'),
    server: L('暫時連不上伺服器。', 'Cannot reach the server.'),
    no_data: L('SPHEREx 目前還沒有拍到這個位置。', 'SPHEREx has no images of this position yet.'),
    too_few: L('這裡可用的影像太少。', 'Too few usable images here.'),
    stalled: L('預覽中斷了，重新整理頁面可以再試一次。', 'The preview stopped; reload the page to try again.'),
  })
  if (err && !st?.frames?.length) return <p className="note lab-warn">{msg()[err] || err}</p>
  const geo = st?.wcs ? { wcs: st.wcs, shape: st.shape } : { wcs: { crpix: [1, 1], cdelt: [1, 1], crval: [ra, dec] }, shape: [1, 1] }
  const prog = st && st.n_total ? st.n_done / st.n_total : 0
  return (
    <div className="quick">
      {st && st.status !== 'done' && (
        <div className="qp-progress" role="status" aria-live="polite">
          <div className="qp-bar"><i style={{ width: `${Math.round((st.phase === 'difference' ? (st.n_diff || 0) / Math.max(1, st.n_done) : prog) * 100)}%` }} /></div>
          <span>{st.phase === 'search' || st.status === 'searching' ? L('向 IRSA 查詢這個位置的影像…', 'Asking IRSA for images of this position…')
            : st.phase === 'movers' ? L('正在自動搜尋移動的星（比較各輪疊加，並查 Gaia／CatWISE）…', 'Searching for moving stars (comparing pass stacks, then Gaia / CatWISE)…')
            : st.phase === 'lab' ? L('正在做工作台：資料立方體（即時光譜用）、各輪與各偵測器疊加、旗標圖，並搜尋變星…', 'Building the lab: the data cube for spectra on the fly, pass and detector stacks, flag maps, and a variable-star search…')
            : st.phase === 'difference' ? L(`影像都到了，正在做差分與各輪疊加（${st.n_diff || 0} / ${st.n_done}）`, `All frames in; building differences and pass stacks (${st.n_diff || 0} / ${st.n_done})`)
            : L(`已收到 ${st.n_done} / ${st.n_total} 張影像（${st.first} – ${st.last}），邊下載邊播放`, `${st.n_done} of ${st.n_total} images in (${st.first} – ${st.last}); playing while the rest arrive`)}</span>
        </div>
      )}
      {st?.wcs && <Player frames={frames} stacks={stacks} geo={geo} compact={compact} marks={marks}
        title={compact ? `RA ${(+ra).toFixed(4)}° Dec ${(+dec).toFixed(4)}°` : null}
        note={st.diff_partial ? L('現在的差分是用已經到的影像先算的，全部到齊後會重算一次。', 'These differences use the images received so far; they are recomputed once every image is in.') : null}
        loading={st.status === 'searching' ? L('查詢影像中…', 'Finding images…') : null}
        side={st?.movers && !compact ? <Suspense fallback={null}><MoverList data={st.movers} fieldId={st.id} /></Suspense> : null} />}
      {st?.phase === 'movers' && <p className="hint">{L('正在自動搜尋移動的星…', 'Searching for moving stars…')}</p>}
      {!st && <div className="route-loading" role="status"><i aria-hidden="true" /><span>{L('準備預覽…', 'Starting the preview…')}</span></div>}
    </div>
  )
}

// ---- Aladin Lite ----------------------------------------------------------------------------------------------
let aladinP = null
const ALADIN_URL = 'https://cdn.jsdelivr.net/npm/aladin-lite@3.6.5/dist/aladin.js'     // pinned ES module build
function loadAladin() {
  if (!aladinP) {
    aladinP = import(/* @vite-ignore */ ALADIN_URL).then(async (m) => { const A = m.default; await A.init; return A })
      .catch((e) => { aladinP = null; throw e })
  }
  return aladinP
}
// HiPS served by IRSA (CDS's own servers are not reachable from every network); the SPHEREx DR1 all-sky cube is IRSA's.
export const HIPS = 'https://irsa.ipac.caltech.edu/data/hips'
const WISE_HIPS = `${HIPS}/CDS/AllWISE/RGB-W4-W2-W1`
const surveys = () => [
  [WISE_HIPS, 'WISE (3.4–22 µm)'],
  [`${HIPS}/SPHEREx/spherex_allsky_cube`, L('SPHEREx DR1 全天', 'SPHEREx DR1 all-sky')],
  [`${HIPS}/CDS/2MASS/Color`, '2MASS (1.2–2.2 µm)'],
  [`${HIPS}/CDS/DSS2/color`, L('DSS2（可見光）', 'DSS2 (visible)')],
]

/** markers: [{ra, dec, label, c}] ; catalogs: [{name, c, shape, src: [{ra, dec, label}]}] */
export function AladinView({ ra, dec, size, markers, catalogs, initial }) {
  useLanguage()
  const div = useRef(), al = useRef(null)
  const [survey, setSurvey] = useState(initial || WISE_HIPS)
  const [state, setState] = useState('idle')
  useEffect(() => {
    let live = true
    const timers = []
    setState('loading')
    loadAladin().then((A) => {
      if (!live || !div.current) return
      div.current.innerHTML = ''
      const a = A.aladin(div.current, { survey, fov: size * 1.6, target: `${ra} ${dec}`, cooFrame: 'ICRSd', showReticle: false,
        showFullscreenControl: true, showLayersControl: true, showGotoControl: false, showFrame: false, showCooGrid: false,
        log: false })      // no usage ping to CDS's logger (unreachable from some networks; its failure showed as a page error)
      al.current = a
      const h = size / 2, cd = Math.cos((dec * Math.PI) / 180)
      const box = A.graphicOverlay({ color: '#ffffff', lineWidth: 2, name: L('SPHEREx 視野', 'SPHEREx field') })
      a.addOverlay(box)
      box.add(A.polygon([[ra - h / cd, dec - h], [ra + h / cd, dec - h], [ra + h / cd, dec + h], [ra - h / cd, dec + h]]))
      for (const c of catalogs || []) {
        if (!c.src.length) continue
        const cat = A.catalog({ name: c.name, color: c.c, sourceSize: 12, shape: c.shape || 'circle' })
        a.addCatalog(cat)
        cat.addSources(c.src.map((s) => A.source(s.ra, s.dec, { name: s.label || '' })))
        if (c.hidden) cat.hide()
      }
      if (markers?.length) {
        const cat = A.catalog({ name: L('目標', 'Target'), color: '#ffb547', sourceSize: 18, shape: 'cross' })
        a.addCatalog(cat)
        cat.addSources(markers.map((m) => A.marker(m.ra, m.dec, { popupTitle: m.label, popupDesc: '' })))
      }
      setState('ready')
      // Aladin's icon buttons and icons carry no accessible name; name the ones we know, mark icons as decorative
      const NAMES = [['zoom-in', L('放大', 'Zoom in')], ['zoom-out', L('縮小', 'Zoom out')], ['location-copy', L('複製座標', 'Copy coordinates')], ['fullscreen', L('全螢幕', 'Full screen')],
        ['stack', L('圖層', 'Layers')], ['layer', L('圖層', 'Layers')], ['projection', L('投影', 'Projection')], ['grid', L('座標格線', 'Coordinate grid')], ['share', L('分享', 'Share')], ['settings', L('設定', 'Settings')]]
      const name = () => {
        if (!div.current) return
        for (const im of div.current.querySelectorAll('img:not([alt])')) im.alt = ''
        for (const b of div.current.querySelectorAll('button, [role="button"], .aladin-btn')) {
          if (b.getAttribute('aria-label') || b.textContent.trim()) continue
          const cls = typeof b.className === 'string' ? b.className : ''
          b.setAttribute('aria-label', (NAMES.find(([k]) => cls.includes(k)) || [0, b.title || L('Aladin 控制項', 'Aladin control')])[1])
        }
      }
      name(); timers.push(setTimeout(name, 1500), setTimeout(name, 4000))
    }).catch(() => live && setState('error'))
    return () => { live = false; timers.forEach(clearTimeout) }
  }, [ra, dec, size, markers, catalogs])
  useEffect(() => {
    const a = al.current
    if (!a) return
    try { (a.setBaseImageLayer || a.setImageSurvey).call(a, survey) } catch { /* older API */ }
  }, [survey, state])
  return (
    <div className="sx-aladin">
      <div className="lab-row">
        <span className="lab-k">{L('底圖', 'Survey')}</span>
        <div className="seg" role="group">{surveys().map(([id, nm]) => <button key={id} aria-pressed={survey === id} onClick={() => setSurvey(id)}>{nm}</button>)}</div>
      </div>
      {/* Aladin adds its own classes to this element: React must never rewrite its className */}
      <div className="sx-aladin-wrap">
        <div className="sx-aladin-map" ref={div} />
        {state === 'loading' && <div className="sx-aladin-skel skel-card" aria-hidden="true" />}
      </div>
      {state === 'loading' && <p className="hint">{L('載入 Aladin Lite…', 'Loading Aladin Lite…')}</p>}
      {state === 'error' && <p className="hint">{L('Aladin Lite 載入失敗（需要連到 CDS）。', 'Aladin Lite could not be loaded (it needs CDS).')}</p>}
      <p className="hint">{L('Aladin Lite 由法國斯特拉斯堡天文資料中心（CDS）提供，底圖由 NASA/IPAC IRSA 提供。白框是 SPHEREx 的視野；可以縮放、切換底圖，右上角能開關圖層。「SPHEREx DR1 全天」是 IRSA 2026 年 11 月發布的全天資料立方體，Aladin Lite 只顯示其中一個波段。', 'Aladin Lite is by the Strasbourg astronomical Data Centre (CDS); the surveys are served by NASA/IPAC IRSA. The white box is the SPHEREx field; zoom, switch the survey, or toggle layers at top right. "SPHEREx DR1 all-sky" is the all-sky data cube IRSA released in November 2026; Aladin Lite shows one of its bands.')}</p>
    </div>
  )
}
