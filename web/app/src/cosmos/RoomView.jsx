import { useEffect, useMemo, useRef, useState } from 'react'
import { L } from '../lib.js'
import FieldView from './FieldView.jsx'
import { askAbout, setPageContext } from '../ask/store.js'

/*
 * Inside the telescope (room.js): walk about, go to the window to choose what to observe, use the computer to see
 * how the verdict on it was reached (the same FieldView as the zoom on the home page).
 */
const thumb = (f) => `/data/fields/${f.id}/pass/p0_d0.webp`
const KIND = (f) => f.target?.kind === 'pm' ? L('移動的星', 'Moving star') : f.target?.kind === 'var' ? L('變星', 'Variable star') : f.n_tracks ? L('小行星', 'Asteroids') : L('天區', 'Field')

// SPHEREx's six detectors, each a stretch of the infrared (micrometres)
const BANDS = [[1, '0.75–1.09'], [2, '1.10–1.62'], [3, '1.63–2.41'], [4, '2.42–3.82'], [5, '3.83–4.41'], [6, '4.42–5.00']]
const imgCache = new Map()
const loadImg = (u) => {
  if (!imgCache.has(u)) imgCache.set(u, new Promise((res) => { const im = document.createElement('img'); im.onload = () => res(im); im.onerror = () => res(null); im.src = u }))
  return imgCache.get(u)
}
const ENH_SKY = 36, ENH_GAIN = 1.3                  // "enhanced": grey sky level taken off, contrast added
const bandColour = (j, n) => { if (n === 1) return [1, 1, 1]; const t = j / (n - 1); return [t, 1 - Math.abs(2 * t - 1), 1 - t] }   // short = blue, long = red
/* The picture out of the window for each visit: one band in grey, or several merged into colour (shortest wavelength
   blue, longest red). Raw is the survey's own preview stretch; enhanced takes off the grey sky level and adds contrast. */
async function compose(fid, nPass, bands, enh) {
  const out = []
  for (let k = 0; k < nPass; k++) {
    const ims = await Promise.all(bands.map((d) => loadImg(`/data/fields/${fid}/pass/p${k}_d${d}.webp`)))
    const first = ims.find(Boolean)
    if (!first) continue
    const W = first.naturalWidth, H = first.naturalHeight, cv = document.createElement('canvas'); cv.width = W; cv.height = H
    const g = cv.getContext('2d', { willReadFrequently: true })
    const px = ims.map((im) => { if (!im) return null; g.clearRect(0, 0, W, H); g.drawImage(im, 0, 0); return g.getImageData(0, 0, W, H).data })
    const cols = bands.map((_, j) => bandColour(j, bands.length)), norm = [0, 1, 2].map((c) => cols.reduce((a, q) => a + q[c], 0) || 1)
    const o = g.createImageData(W, H), od = o.data
    const lay = px.map((d, j) => d && { d, c: cols[j] }).filter(Boolean)       // only the bands that loaded
    const put = enh ? (v) => (v - ENH_SKY) * ENH_GAIN : (v) => v
    for (let i = 0, n = W * H * 4; i < n; i += 4) {
      let r = 0, gr = 0, b = 0
      for (const { d, c } of lay) { const v = d[i]; r += v * c[0]; gr += v * c[1]; b += v * c[2] }
      od[i] = put(r / norm[0]); od[i + 1] = put(gr / norm[1]); od[i + 2] = put(b / norm[2]); od[i + 3] = 255
    }
    g.putImageData(o, 0, 0); out.push(cv)
  }
  return out
}
const ROBOT = <svg viewBox="0 0 24 24" aria-hidden="true" className="rm-boticon"><rect x="5" y="8" width="14" height="10" rx="4" /><path d="M12 8V5" /><circle cx="12" cy="4" r="1.2" /><circle cx="9.5" cy="13" r="1.2" /><circle cx="14.5" cy="13" r="1.2" /></svg>
const mjdDate = (m) => new Date((m - 40587) * 864e5).toISOString().slice(0, 10)
const near = (arr, x, y, r) => arr.map((s) => ({ s, d: Math.hypot(s.x - x, s.y - y) })).filter((o) => o.d < r).sort((a, b) => a.d - b.d)[0]?.s || null

export default function RoomView({ fields, skyUrl, lite, onLeave, music, onMusic }) {
  const canvas = useRef(), inst = useRef(null)
  const [hot, setHot] = useState(null)
  const [panel, setPanel] = useState(null)          // 'window' (choose a field) | 'computer' | null
  const [target, setTarget] = useState(null)
  const [help, setHelp] = useState(true)
  const [safe, setSafe] = useState(false)          // the GPU gave up once: run the light version
  const [ready, setReady] = useState(false)        // the first frame is drawn
  const [broken, setBroken] = useState(false)      // even the light version drew black: no 3D, the panels still work
  const [passes, setPasses] = useState([])        // the chosen field's half-year visits
  const [tt, setTt] = useState(null)              // time on the window, set by the lever or the slider
  const [fd, setFd] = useState(null)              // the field in view: its stars, candidates and track
  const [pick, setPick] = useState(null)          // what was clicked out of the window: a star, or a bare patch of sky
  const choices = useMemo(() => fields.filter((f) => !f.simulated && isFinite(f.ra)), [fields])
  const pickRef = useRef(null)
  const [bands, setBands] = useState([0])          // 0 = all bands together (the survey's own grey stack); else detectors 1-6
  const [enh, setEnh] = useState(false)           // raw first; contrast only on request

  useEffect(() => {
    let dead = false
    ;(async () => {
      const { Room } = await import('./room.js')
      let drawn = false                                                       // the first frame only: no state update per frame
      if (dead || !canvas.current) return
      const hq = new URLSearchParams(location.search).has('hq') || undefined   // ?hq forces shadows and bloom (for checking on a machine without a GPU)
      inst.current = new Room(canvas.current, {
        lite: lite || safe, hq: safe ? false : hq, skyUrl, onHover: setHot, onAct: (w) => (w === 'robot' ? askRef.current() : setPanel(w)), onLever: setTt,
        reduced: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
        onPick: (p) => pickRef.current?.(p),
        onLost: () => { if (safe) setBroken(true); else { setReady(false); setSafe(true) } }, onFrame: () => { if (!drawn) { drawn = true; setReady(true) } },
      })
    })()
    return () => { dead = true; inst.current?.destroy(); inst.current = null }
  }, [lite, skyUrl, safe])

  const point = async (f) => {
    if (!f) return
    setTarget(f); setPanel(null); setTt(0); setPick(null); setFd(null)
    const base = `/data/fields/${f.id}`, get = (u) => fetch(u).then((r) => (r.ok ? r.json() : null)).catch(() => null)
    const [fj, ov, pc, vc] = await Promise.all([get(`/api/field/${f.id}`), get(`${base}/overlays.json`), get(`${base}/pm_candidates.json`), get(`${base}/var_candidates.json`)])
    const ps = fj?.products?.passes || []
    const pm = (pc?.candidates || []).filter((c) => c.track?.length > 1)
    // what moves here: the target's measured position at each visit, else the fastest mover the search found
    let track = fj?.target?.passes?.length ? fj.target.passes.map((p) => p.fit || p) : null
    if (!track) { const c = [...pm].sort((a, b) => (b.pm_arcsec_yr || 0) - (a.pm_arcsec_yr || 0))[0]; if (c && c.pm_arcsec_yr > 1) track = ps.map((_, k) => c.track.find((q) => q.k === k) || c.track[c.track.length - 1]) }
    const W = fj?.shape?.[1] || 177, H = fj?.shape?.[0] || 177
    const kind = f.target?.kind === 'var' ? 'var' : 'pm'
    setPasses(ps)
    // Gaia positions are for 2016; carry each star along its catalogue motion to the time of the SPHEREx visits
    // (Barnard's Star has moved 17 pixels since)
    const tObs = ps.length ? ps.reduce((a, p) => a + (p.mjd0 + p.mjd1) / 2, 0) / ps.length : null
    const gaia = (ov?.gaia || []).map((g) => (tObs && g.mjd0 ? { ...g, x: g.x + g.pmx * (tObs - g.mjd0) / 365.25, y: g.y + g.pmy * (tObs - g.mjd0) / 365.25 } : g))
    setFd({ id: f.id, W, H, fj, gaia: gaia.filter((g) => g.x > 1 && g.y > 1 && g.x < W - 2 && g.y < H - 2), pm, vr: vc?.candidates || [], track, kind })
    const frames = await compose(f.id, Math.max(1, ps.length || 3), bands, enh)
    inst.current?.setTarget(f, frames, { W, H, track, kind })
  }

  // a click out of the window: the point-source model on the server says whether there is a star there
  const seq = useRef(0)
  const onPick = async (p) => {
    if (p.kind !== 'star' || !fd) return
    const n = ++seq.current
    setPick({ kind: 'star', x: p.x, y: p.y, loading: true }); inst.current?.selectStar(p.x, p.y); inst.current?.showTrack(null)
    let r = null
    try { const res = await fetch(`/api/field/${fd.id}/starcheck?x=${p.x.toFixed(2)}&y=${p.y.toFixed(2)}`); r = res.ok ? await res.json() : null } catch { /* shown as failed */ }
    if (n !== seq.current) return
    const x = r?.x ?? p.x, y = r?.y ?? p.y
    setPick({ kind: 'star', x, y, r, failed: !r })
    const seen = r && r.verdict !== 'none'
    inst.current?.selectStar(seen ? x : null, y)
    // a moving star chosen: show where each visit measured it
    const t = fd.track?.[0], c = near(fd.pm, x, y, 2.5)
    if (seen && t && Math.hypot(t.x - x, t.y - y) < 2.5) inst.current?.showTrack(fd.track, fd.kind)
    else if (seen && c) inst.current?.showTrack(passes.map((_, k) => c.track.find((q) => q.k === k) || c.track[c.track.length - 1]), 'pm')
  }
  pickRef.current = onPick
  const pickAt = (x, y) => onPick({ kind: 'star', x, y })

  // another band, a merge, raw or enhanced: re-make the pictures, the telescope stays put
  const fdId = fd?.id
  useEffect(() => {
    if (!fdId) return
    let live = true
    compose(fdId, Math.max(1, passes.length || 3), bands, enh).then((fr) => { if (live && fr.length) inst.current?.setFrames(fr) })
    return () => { live = false }
  }, [bands, enh]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggleBand = (d) => setBands((b) => {
    if (d === 0) return [0]
    const cur = b.includes(0) ? [] : b
    const nx = cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort((a, c) => a - c)
    return nx.length ? nx : [0]
  })
  const bandNote = bands[0] === 0
    ? L('全部 6 個波段疊在一起（0.75–5 µm，灰階）', 'All 6 bands stacked together (0.75–5 µm, grey)')
    : bands.length === 1
    ? L(`只看 D${bands[0]}（${BANDS[bands[0] - 1][1]} µm，灰階）`, `D${bands[0]} only (${BANDS[bands[0] - 1][1]} µm, grey)`)
    : L(`彩色合併：${bands.map((d) => `D${d}`).join('＋')}，短波長藍、長波長紅`, `Colour merge: ${bands.map((d) => `D${d}`).join(' + ')}, short wavelengths blue, long red`)

  // the robot (and its button): ask about the field out of the window, with the bands and the pass on show
  const roomCtx = () => ({
    kind: 'room', id: target?.id, name: target ? target.target?.name || target.name : L('控制室', 'Control room'), ra: target?.ra, dec: target?.dec,
    facts: { bands: bands[0] === 0 ? 'all 6 detectors stacked (0.75-5 um, grey)' : bands.map((d) => `D${d} (${BANDS[d - 1][1]} um)`).join(' + '), display: enh ? 'enhanced contrast' : 'raw',
      pass: kNow != null && passes.length ? `${kNow + 1} of ${passes.length}` : null, pass_date: kNow != null && passes[kNow] ? mjdDate(passes[kNow].mjd0) : null },
  })
  const askRef = useRef(() => {})
  askRef.current = () => askAbout(roomCtx())
  const slide = (v) => { setTt(v); inst.current?.setTime(v) }
  const kNow = tt == null ? null : Math.round(tt)
  const openComputer = () => { if (!target) point(choices.find((x) => x.id === 'barnard') || choices[0]); setPanel('computer') }
  useEffect(() => { if (panel === 'computer' && !target) openComputer() }, [panel]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(() => setHelp(false), 9000); return () => clearTimeout(t) }, [])
  // while inside, the Ask button's default is the room as it is now
  useEffect(() => { setPageContext(roomCtx()) }, [target, bands, enh, kNow, passes]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => setPageContext(null), [])
  // out of the window there is a field from the start: Barnard's Star, the fastest-moving star in the sky
  useEffect(() => { if (ready && !target) point(choices.find((x) => x.id === 'barnard') || choices[0]) }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps

  // a few stars worth a look in the field in view
  const reps = []
  if (fd) {
    const add = (r) => { if (!reps.some((q) => Math.hypot(q.x - r.x, q.y - r.y) < 2)) reps.push(r) }
    if (fd.track && target?.target) add({ label: target.target.name, x: fd.track[0].x, y: fd.track[0].y })
    for (const c of fd.vr.slice(0, 2)) add({ label: c.match?.name || L('變光候選', 'Brightness change'), x: c.x, y: c.y })
    for (const c of [...fd.pm].sort((a, b) => b.pm_arcsec_yr - a.pm_arcsec_yr).slice(0, 2)) add({ label: L(`移動候選 ${c.pm_arcsec_yr.toFixed(1)}″/年`, `Mover ${c.pm_arcsec_yr.toFixed(1)}″/yr`), x: c.x, y: c.y })
    const b = [...fd.gaia].sort((a, c) => a.m - c.m)[0]
    if (b) add({ label: L('最亮的星', 'Brightest star'), x: b.x, y: b.y })
  }
  const randomStar = () => { const g = fd?.gaia; if (g?.length) { const s = g[Math.floor(Math.random() * g.length)]; pickAt(s.x, s.y) } }

  return (
    <div className={`rm${pick ? ' has-pick' : ''}`}>
      <canvas key={safe ? 'safe' : 'full'} ref={canvas} className="rm-canvas" tabIndex={0} aria-label={L('望遠鏡內部：WASD 或方向鍵走動、拖曳轉頭、點地板走過去、點窗外的星', 'Inside the telescope: WASD or arrow keys to walk, drag to look, click the floor to walk there, click a star out of the window')} />
      <div className="rm-vig" aria-hidden="true" />
      {!ready && !broken && <p className="rm-loading" role="status">{L('正在進入望遠鏡…', 'Entering the telescope…')}</p>}
      <div className="rm-top">
        <div>
          <span className="cz-k">{L('在 SPHEREx 裡面', 'Inside SPHEREx')} <span className="rm-tag">{L('示意', 'stylised')}</span></span>
        </div>
        <div className="rm-acts">
          <button className="cz-btn" aria-pressed={music} onClick={onMusic} title={L('音樂：團隊原創', 'Music: original, by the team')}>{music ? L('♪ 音樂 開', '♪ Music on') : L('♪ 音樂 關', '♪ Music off')}</button>
          <button className="cz-btn" onClick={onLeave}>{L('離開望遠鏡', 'Leave the telescope')}</button>
        </div>
      </div>
      {broken
        ? !panel && <p className="rm-hot">{L('這個瀏覽器畫不出 3D 控制室。下面的按鈕一樣能用：換天區、拉時間、看電腦。', 'This browser cannot draw the 3D room. The buttons below still work: change field, pull the time lever, use the computer.')}</p>
        : safe && <p className="rm-hot">{L('顯示卡畫不出完整畫質，已改用輕量畫質重新載入。', 'The graphics card could not draw the full quality; reloaded in the lighter quality.')}</p>}
      {help && <p className="rm-help">{window.matchMedia('(pointer: coarse)').matches
        ? L('拖曳轉頭 · 點地板走 · 點星星', 'Drag to look · tap the floor · tap a star')
        : L('WASD 走動 · 拖曳轉頭 · 點星星', 'WASD to walk · drag to look · click a star')}</p>}
      {hot && !panel && !pick && <p className="rm-hot">{hot === 'field' ? L('點這裡：看這顆星的狀態', 'Click: see this star') : hot === 'sky' ? L('點這裡：這個方向的天空', 'Click: this part of the sky') : hot === 'window' ? L('窗戶：走過去看外面', 'Window: walk over and look out') : hot === 'robot' ? L('助理機器人：問它窗外的天區', 'Assistant robot: ask it about the field outside') : hot === 'lever' ? L('時間拉桿：上下拖動，讓窗外的天空在各次觀測之間切換', 'Time lever: drag up or down to step the sky outside between visits') : L('電腦：看它是怎麼判斷出來的', 'Computer: see how it was judged')}</p>}
      <div className="rm-go">
        <button className="cz-btn is-go" onClick={() => (broken ? setPanel('window') : inst.current?.walkTo('window'))}>{L('走到窗前', 'Go to the window')}</button>
        <button className="cz-btn" onClick={() => (broken ? openComputer() : inst.current?.walkTo('computer', true))}>{L('走到電腦', 'Go to the computer')}</button>
        <button className="cz-btn rm-ask" onClick={() => askRef.current()}>{ROBOT}{L('問機器人', 'Ask the robot')}</button>
        {target && <span className="rm-tgt">{L('窗外：', 'Outside: ')}<b>{target.target?.name || target.name}</b></span>}
      </div>

      {target && !panel && (
        <div className="rm-time" role="group" aria-label={L('窗外的天區', 'The field outside')}>
          <div className="rm-reps">
            <span className="cz-k" aria-hidden="true">★</span>
            {reps.map((r) => <button key={`${r.x},${r.y}`} className="rm-chip" onClick={() => pickAt(r.x, r.y)}>{r.label}</button>)}
            {fd?.gaia?.length > 0 && <button className="rm-chip" onClick={randomStar}>{L('↻ 隨機一顆星', '↻ A random star')}</button>}
            <button className="rm-chip is-alt" onClick={() => setPanel('window')}>{L('換天區…', 'Another field…')}</button>
          </div>
          <div className="rm-bands" role="group" aria-label={L('波段', 'Bands')}>
            <span className="cz-k" aria-hidden="true">λ</span>
            <button className="rm-chip" aria-pressed={bands[0] === 0} onClick={() => toggleBand(0)}>{L('全部', 'All')}</button>
            {BANDS.map(([d, um]) => {
              const j = bands.indexOf(d), c = j >= 0 && bands.length > 1 ? bandColour(j, bands.length).map((v) => Math.round(60 + v * 195)) : null
              return <button key={d} className="rm-chip" aria-pressed={j >= 0} onClick={() => toggleBand(d)} title={`${um} µm`} style={c ? { borderColor: `rgb(${c})`, boxShadow: `inset 0 -3px 0 rgb(${c})` } : undefined}>D{d}<small>{um}</small></button>
            })}
            <button className="rm-chip is-alt" aria-pressed={enh} onClick={() => setEnh((v) => !v)}>{enh ? L('◐ 加強', '◐ Enhanced') : L('◑ 原始', '◑ Raw')}</button>
          </div>
          {passes.length > 1 && <>
            <input type="range" min={0} max={passes.length - 1} step={0.01} value={tt ?? 0} onChange={(e) => slide(+e.target.value)} aria-label={L('觀測時間', 'Observation time')} />
            <span className="rm-when">{kNow == null
              ? mjdDate(passes[0].mjd0)
              : `${mjdDate(passes[kNow].mjd0)} · ${kNow + 1}/${passes.length}`}</span>
          </>}
        </div>
      )}

      {pick && !panel && <StarCard pick={pick} fd={fd} target={target} passes={passes}
        onClose={() => { seq.current++; setPick(null); inst.current?.selectStar(null); inst.current?.showTrack(null) }} onComputer={() => setPanel('computer')} />}

      {panel === 'window' && (
        <div className="rm-panel" role="dialog" aria-label={L('選擇要觀察的天區', 'Choose a field to observe')}>
          <div className="rm-ph">
            <strong>{L('把望遠鏡轉向…', 'Point the telescope at…')}</strong>
            <button className="cz-x" onClick={() => setPanel(null)} aria-label={L('關閉', 'Close')}>×</button>
          </div>
          <div className="rm-grid">
            {choices.map((f) => (
              <button key={f.id} className={`rm-card${target?.id === f.id ? ' is-on' : ''}`} onClick={() => point(f)}>
                <img src={thumb(f)} alt="" loading="lazy" width="177" height="177" />
                <span className="cz-k">{KIND(f)}</span>
                <b>{f.target?.name || f.name}</b>
              </button>
            ))}
            <button className="rm-card rm-rand" onClick={() => point(choices[Math.floor(Math.random() * choices.length)])}>
              <span className="rm-dice" aria-hidden="true">↻</span><b>{L('隨機', 'Random')}</b>
            </button>
          </div>
        </div>
      )}

      {panel === 'computer' && target && (
        <div className="rm-pc">
          <FieldView key={target.id} summary={target} guide={GUIDE()} onExit={() => setPanel(null)} onNext={() => point(choices[Math.floor(Math.random() * choices.length)])} />
          <button className="cz-btn rm-pcx" onClick={() => setPanel(null)}>{L('離開電腦', 'Step away')}</button>
        </div>
      )}
    </div>
  )
}

/* What the window and the star check show, in words: kept on the computer, so the window itself stays plain. */
const GUIDE = () => [
  { h: L('窗外', 'Out of the window'), p: L('望遠鏡此刻對準的 0.3° 天區，SPHEREx 每半年一輪巡天的疊加影像（紅外線，放大顯示），背後沒有其他底圖。拉桿或滑桿切換各輪。這是示意的控制室：真正的 SPHEREx 是無人太空望遠鏡。', 'The 0.3° field the telescope points at: the stacked SPHEREx picture of each half-year survey pass (infrared, magnified), with nothing behind it. The lever or the slider steps through the passes. The control room is stylised: the real SPHEREx is an uncrewed telescope.') },
  { h: L('波段 λ', 'Bands λ'), p: L('D1–D6 是六個偵測器，各看一段紅外線（0.75–5 µm）。選一個是灰階；選幾個就合併成彩色，短波長藍、長波長紅（按鈕底線就是它的顏色）。「原始」是巡天預覽的原樣；「加強」去掉背景灰、加對比，只改顯示。亮星中心的黑點或色斑是飽和、被標為不可用的像素。', 'D1–D6 are the six detectors, each seeing a stretch of the infrared (0.75–5 µm). One is grey; several merge into colour, short wavelengths blue and long red (the underline on each button is its colour). Raw is the survey preview as it is; enhanced removes the grey sky and adds contrast, display only. A black or coloured centre on a bright star is saturated pixels flagged unusable.') },
  { h: L('點星星：形狀', 'Clicking a star: shape'), p: L('點是光，曲線是點光源模型（這片天區的星平均有多寬）。點落在曲線上就是一顆星；太寬可能是星系或擠在一起的星，太尖比較像壞像素。用的是全部影像的中位數，偵測器的瑕疵和宇宙射線在中位數裡會消失。', 'The dots are the light, the curve is the point-source model (how wide the stars in this field are). Dots on the curve: a star. Wider: a galaxy or a blend; sharper: more like a bad pixel. It uses the median of all exposures, where detector flaws and cosmic rays drop out.') },
  { h: L('點星星：每張都在', 'Clicking a star: every exposure'), p: L('每一格是一張曝光，依時間排列。亮的格子是這張裡它有被偵測到，暗的是沒有，灰的是那張不能用。一顆星每張都在；只偶爾出現的比較像雜訊。', 'Each square is one exposure, in time order. Lit: detected there; dark: not; grey: that exposure is unusable there. A star is in every one; something seen only now and then is more like noise.') },
  { h: L('點星星：光譜', 'Clicking a star: spectrum'), p: L('每張曝光看一個波長，合起來就是它的光譜（點）。曲線是最符合的黑體，給出表面溫度；圓點的顏色就是那個溫度的顏色。若光譜比較像冪律，就是星系的樣子。距離是假設為主序星的粗估。', 'Each exposure sees one wavelength; together they make its spectrum (dots). The curve is the best-fitting blackbody, giving the surface temperature; the swatch is that temperature\'s colour. A power-law shape looks like a galaxy. The distance is a rough estimate assuming a main-sequence star.') },
  { h: L('點星星：AI', 'Clicking a star: AI'), p: L('真假判別 CNN 只看「相減之後留下的東西」：會動或會變的才會留下。每個點是一次偵測的分數，直線是門檻。一顆不動不變的星什麼都不留，所以是空的。', 'The real/bogus CNN only looks at what subtraction leaves behind: only things that move or change leave anything. Each dot is one detection\'s score; the line is the threshold. A star that neither moves nor changes leaves nothing, so it is empty.') },
  { h: L('點星星：標記', 'Clicking a star: marks'), p: L('白圈是選到的星。會動的星另有橘圈（此刻位置）、藍點（每輪量到的位置）和黃箭頭（移動方向，長度放大 10 倍）。', 'The white ring is the chosen star. A moving star also gets an orange ring (where it is now), blue dots (where each pass measured it) and a yellow arrow (its direction, drawn 10 times longer).') },
]

const VERDICT = {
  star: ['yes', () => L('星', 'Star')],
  saturated: ['yes', () => L('亮星', 'Bright star')],
  none: ['no', () => L('沒有光源', 'Nothing')],
  extended: ['no', () => L('不是單星', 'Not one star')],
  sharp: ['no', () => L('壞像素？', 'Bad pixel?')],
  transient: ['no', () => L('雜訊', 'Noise')],
  unfit: ['maybe', () => L('？', '?')],
}
// the colour of a blackbody of temperature T (an approximation good enough for a swatch)
function bbColour(T) {
  const t = T / 100
  const r = t <= 66 ? 255 : 329.7 * Math.pow(t - 60, -0.1332)
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.1 : 288.1 * Math.pow(t - 60, -0.0755)
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5 * Math.log(t - 10) - 305
  const c = (v) => Math.round(Math.max(0, Math.min(255, v)))
  return `rgb(${c(r)},${c(g)},${c(b)})`
}
const bnu = (lam, T) => { const nu = 2.998e8 / (lam * 1e-6), x = Math.min(700, 6.626e-34 * nu / (1.381e-23 * T)); return nu ** 3 / Math.expm1(x) }

function Profile({ pts, fwhm }) {
  const W = 150, H = 80, sx = (r) => 6 + r / 5 * (W - 12), sy = (v) => H - 6 - Math.max(-0.1, Math.min(1.15, v)) / 1.15 * (H - 12)
  const sg = fwhm / 2.3548, curve = Array.from({ length: 41 }, (_, i) => { const r = i / 8; return `${i ? 'L' : 'M'}${sx(r).toFixed(1)},${sy(Math.exp(-r * r / (2 * sg * sg))).toFixed(1)}` }).join('')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="rm-viz" aria-hidden="true">
      <line x1="6" x2={W - 6} y1={sy(0)} y2={sy(0)} className="rm-ax" />
      <path d={curve} className="rm-model rm-draw" pathLength="1" />
      {pts.map(([r, v], i) => <circle key={i} cx={sx(r)} cy={sy(v)} r="1.8" className="rm-pt" style={{ animationDelay: `${0.3 + r * 0.12}s` }} />)}
    </svg>
  )
}
function Spectrum({ bins, T }) {
  if (!bins?.length) return null
  const W = 150, H = 80, lx = (l) => 6 + (Math.log(l) - Math.log(0.75)) / (Math.log(5) - Math.log(0.75)) * (W - 12)
  let num = 0, den = 0
  for (const [l, f, e] of bins) { const m = bnu(l, T), w = 1 / Math.max(e, 0.03 * Math.abs(f) + 1e-9) ** 2; num += w * m * f; den += w * m * m }
  const s = den ? num / den : 0, fmax = Math.max(...bins.map((b) => b[1]), ...bins.map((b) => s * bnu(b[0], T))) || 1
  const sy = (f) => H - 6 - Math.max(0, f) / fmax * (H - 14)
  const curve = Array.from({ length: 60 }, (_, i) => { const l = 0.75 * Math.pow(5 / 0.75, i / 59); return `${i ? 'L' : 'M'}${lx(l).toFixed(1)},${sy(s * bnu(l, T)).toFixed(1)}` }).join('')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="rm-viz" aria-hidden="true">
      <line x1="6" x2={W - 6} y1={H - 6} y2={H - 6} className="rm-ax" />
      {bins.map(([l, f], i) => <circle key={i} cx={lx(l)} cy={sy(f)} r="1.8" className="rm-pt" style={{ animationDelay: `${0.2 + i * 0.015}s`, fill: `hsl(${240 - i * 4},80%,70%)` }} />)}
      <path d={curve} className="rm-model rm-draw" pathLength="1" style={{ stroke: bbColour(T), animationDelay: '1.1s' }} />
    </svg>
  )
}
function Presence({ seq }) {
  return <div className="rm-seq" aria-hidden="true">{[...seq].map((c, i) => <i key={i} className={c === '1' ? 'on' : c === '0' ? 'off' : 'na'} style={{ animationDelay: `${i * 0.003}s` }} />)}</div>
}
function AiBar({ ai }) {
  return (
    <div className={`rm-ai${ai.n ? '' : ' is-empty'}`} aria-hidden="true">
      <span className="rm-ai-thr" style={{ left: `${ai.p_link * 100}%` }} />
      {ai.p.map((p, i) => <i key={i} className={p >= ai.p_link ? 'real' : ''} style={{ left: `${p * 100}%`, animationDelay: `${0.2 + i * 0.08}s` }} />)}
    </div>
  )
}
function Flip({ fd, x, y, passes }) {
  const [k, setK] = useState(0)
  useEffect(() => { const t = setInterval(() => setK((v) => (v + 1) % Math.max(1, passes.length)), 700); return () => clearInterval(t) }, [passes.length])
  const Z = 7, S = 12
  return (
    <div className="rm-flip" aria-hidden="true">
      <div style={{ width: S * Z, height: S * Z, backgroundImage: `url(/data/fields/${fd.id}/pass/p${k}_d0.webp)`, backgroundSize: `${fd.W * Z}px ${fd.H * Z}px`, backgroundPosition: `${-(x + 0.5 - S / 2) * Z}px ${-(fd.H - 0.5 - y - S / 2) * Z}px` }} />
      <span className="rm-dots">{passes.map((_, i) => <b key={i} className={i === k ? 'on' : ''} />)}</span>
    </div>
  )
}

function StarCard({ pick, fd, target, passes, onClose, onComputer }) {
  if (!fd) return null
  const { x, y, r } = pick
  const T = r?.tests || {}
  const v = r ? VERDICT[r.verdict] || VERDICT.unfit : null
  const pm = near(fd.pm, x, y, 2.5), vr = near(fd.vr, x, y, 2.5)
  const t = fd.track?.[0], isT = t && Math.hypot(t.x - x, t.y - y) < 2.5 && target?.target
  const seen = r && r.verdict !== 'none'
  const sp = T.spectrum
  return (
    <div className="rm-star" role="dialog" aria-label={L('星星檢查', 'Star check')}>
      <div className="rm-ph">
        <strong>{isT ? target.target.name : vr?.match?.name || (v ? <span className={`rm-verdict is-${v[0]}`}>{v[0] === 'yes' ? '✓ ' : v[0] === 'no' ? '✗ ' : ''}{v[1]()}</span> : '…')}</strong>
        <button className="cz-x" onClick={onClose} aria-label={L('關閉', 'Close')}>×</button>
      </div>
      {(isT || vr?.match) && v && <span className={`rm-verdict is-${v[0]}`}>{v[0] === 'yes' ? '✓ ' : v[0] === 'no' ? '✗ ' : ''}{v[1]()}</span>}
      {pick.loading && <div className="rm-spin" aria-label={L('檢查中', 'Checking')} />}
      {pick.failed && <button className="rm-chip" onClick={onClose}>{L('沒有成功，再點一次', 'Failed, click again')}</button>}
      {r && (
        <div className="rm-tiles">
          {seen && <figure className="rm-tile"><Flip fd={fd} x={x} y={y} passes={passes} /><figcaption>{pm ? `${pm.pm_arcsec_yr.toFixed(1)}″/${L('年', 'yr')} →` : vr ? `×${vr.amp.toFixed(1)} ◐` : L('三輪', '3 passes')}</figcaption></figure>}
          {T.profile && T.fwhm_ref && <figure className="rm-tile"><Profile pts={T.profile} fwhm={T.fwhm_ref} /><figcaption>{L('形狀', 'Shape')} {T.width_ratio != null ? `×${T.width_ratio}` : ''}</figcaption></figure>}
          {T.seq && <figure className="rm-tile is-wide"><Presence seq={T.seq} /><figcaption>{L('每張都在', 'Every exposure')} {T.present}/{T.usable}</figcaption></figure>}
          {sp?.bins && <figure className="rm-tile"><Spectrum bins={sp.bins} T={sp.T} /><figcaption><i className="rm-sw" style={{ background: sp.kind === 'galaxy' ? 'transparent' : bbColour(sp.T) }} />{sp.kind === 'galaxy' ? L('像星系', 'Galaxy-like') : `${sp.T.toLocaleString()} K`}{sp.distance_pc ? ` · ~${Math.round(sp.distance_pc)} pc` : ''}{sp.bd >= 0.5 ? ` · ${L('棕矮星', 'brown dwarf')} ${Math.round(sp.bd * 100)}%` : ''}</figcaption></figure>}
          {T.ai && <figure className="rm-tile"><AiBar ai={T.ai} /><figcaption>AI {T.ai.n ? `${T.ai.n_real}/${T.ai.n}` : '—'}{T.ai.track?.known ? ` · ${T.ai.track.known}` : ''}</figcaption></figure>}
          {T.snr != null && <figure className="rm-tile"><div className="rm-snr" aria-hidden="true"><i style={{ width: `${Math.min(100, T.snr / 50 * 100)}%` }} /><span style={{ left: '10%' }} /></div><figcaption>S/N {T.snr}</figcaption></figure>}
          <figure className="rm-tile"><div className="rm-cats">
            <b className={T.gaia ? 'on' : ''}>Gaia{T.gaia ? ` ${T.gaia.m}` : ''}</b>
            <b className={T.catwise ? 'on' : ''}>WISE{T.catwise ? ` ${T.catwise.m}` : ''}</b>
          </div><figcaption>{L('星表', 'Catalogues')}</figcaption></figure>
        </div>
      )}
      {r && <button className="rm-chip" onClick={() => askAbout({ kind: 'star', id: `${fd.id}@${x.toFixed(1)},${y.toFixed(1)}`,
        name: isT ? target.target.name : vr?.match?.name || L('窗外的一顆星', 'A star out of the window'),
        facts: { field: target?.target?.name || target?.name, check: r.verdict, temperature_K: sp && sp.kind !== 'galaxy' ? sp.T : null, spectrum_shape: sp?.kind || null,
          distance_pc_rough: sp?.distance_pc ? Math.round(sp.distance_pc) : null, brown_dwarf_prob: sp?.bd ?? null, gaia_G: T.gaia?.m ?? null, wise_mag: T.catwise?.m ?? null,
          snr: T.snr ?? null, proper_motion_arcsec_yr: pm ? +pm.pm_arcsec_yr.toFixed(2) : null, brightness_change_x: vr ? +vr.amp.toFixed(2) : null } })}>{L('問問這顆星 →', 'Ask about this star →')}</button>}
      <button className="rm-chip is-alt" onClick={onComputer}>{L('電腦：看說明與完整分析 →', 'Computer: explanations and full analysis →')}</button>
    </div>
  )
}
