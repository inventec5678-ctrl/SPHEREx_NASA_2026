import { useEffect, useMemo, useRef, useState } from 'react'
import { L, api } from '../lib.js'
import { gpuOK } from '../canvas.js'
import { openSky } from '../search.jsx'
import FieldView from './FieldView.jsx'
import RoomView from './RoomView.jsx'
import { askAbout, setPageContext } from '../ask/store.js'
import './cosmos.css'

/*
 * The home page's 3D cosmos: a zoom journey from the Milky Way to the Solar System, the Earth with SPHEREx on its
 * orbit, and the SPHEREx sky seen from the Earth (scene.js). Scroll or pinch flies in, the stage rail on the right
 * jumps, drag turns, a tap picks (a target, a planet, SPHEREx, any spot on the sky), and the time dial at the bottom
 * moves the planets, the SPHEREx orbit plane and the scan circle through the year.
 * Without WebGL a still picture of the same sky is shown.
 */
const SKY = (lite) => (!lite && window.innerWidth > 1100 ? '/cosmos/sky_4k.webp' : '/cosmos/sky_2k.webp')
const webgl = () => { try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')) } catch { return false } }
const fmtRa = (ra) => { const h = ra / 15; return `${String(Math.floor(h)).padStart(2, '0')}h${String(Math.floor((h % 1) * 60)).padStart(2, '0')}m` }
const fmtDec = (d) => `${d < 0 ? '−' : '+'}${Math.abs(d).toFixed(1)}°`
const fmtDay = (off) => new Date(Date.now() + off * 864e5).toISOString().slice(0, 10)
const PLANET = { Sun: () => L('太陽', 'Sun'), Mercury: () => L('水星', 'Mercury'), Venus: () => L('金星', 'Venus'), Earth: () => L('地球', 'Earth'), Mars: () => L('火星', 'Mars'),
  Jupiter: () => L('木星', 'Jupiter'), Saturn: () => L('土星', 'Saturn'), Uranus: () => L('天王星', 'Uranus'), Neptune: () => L('海王星', 'Neptune') }
const name = (n) => (PLANET[n] ? PLANET[n]() : n)
const scanNote = (d) => d < 3
  ? L('這天 SPHEREx 正掃過這裡（藍色大圓）。', 'On this date SPHEREx is sweeping over this spot (the blue circle).')
  : L(`離這天的掃描圈 ${d.toFixed(0)}°；拖曳時間軸，看藍色大圓何時掃過它。`, `${d.toFixed(0)}° from this date's scan circle; drag the time dial to see when the blue circle sweeps over it.`)
const labelText = (l) => l.kind === 'sat' ? L('SPHEREx · 點我進去', 'SPHEREx · click to go inside') : l.kind === 'here' ? L('太陽在這裡', 'The Sun is here') : l.kind === 'planet' || l.kind === 'earth' || l.kind === 'sun' ? name(l.label) : l.label
/** What the assistant is asked about for a picked thing on the home page. */
const SPHEREX_CTX = () => ({ kind: 'body', id: 'spherex', name: 'SPHEREx', facts: { type: 'space telescope (NASA)', launched: '2025-03', orbit: 'polar, about 98 min, above the day-night line', survey: 'whole sky every six months in 102 infrared colours (0.75-5 um)' } })
function askCtx(sel) {
  const at = { ra: +sel.ra?.toFixed(4), dec: +sel.dec?.toFixed(4) }
  const scan = sel.scan != null ? { deg_from_todays_scan_circle: Math.round(sel.scan) } : {}
  switch (sel.kind) {
    case 'target': return { kind: 'target', id: sel.id, name: sel.label, ...at, facts: scan }
    case 'field': return { kind: 'field', id: sel.id, name: sel.label, ...at, facts: scan }
    case 'point': return { kind: 'field', name: `RA ${fmtRa(sel.ra)} Dec ${fmtDec(sel.dec)}`, ...at, facts: { what: 'a spot picked on the SPHEREx all-sky map', ...scan } }
    case 'here': case 'sun': return { kind: 'star', id: 'sun', name: name('Sun'), facts: { type: 'G2V star' } }
    case 'earth': return { kind: 'body', id: 'earth', name: name('Earth'), facts: { note: 'SPHEREx orbits about 700 km above it' } }
    case 'planet': return { kind: 'body', id: String(sel.label).toLowerCase(), name: name(sel.label), facts: { distance_from_sun_au: sel.a } }
    case 'sat': return SPHEREX_CTX()
    default: return { kind: 'page', name: 'landing' }
  }
}
const DAYS_PER_SECOND = 30                    // the time dial's play speed
const lightTime = (a) => { const s = a * 499; return s < 3600 ? L(`${Math.round(s / 60)} 分鐘`, `${Math.round(s / 60)} min`) : L(`${(s / 3600).toFixed(1)} 小時`, `${(s / 3600).toFixed(1)} h`) }
const STAGE = () => [
  { name: L('銀河系', 'The Milky Way'), line: L('一千億顆恆星。SPHEREx 用 102 種顏色量它們的光。', 'A hundred billion stars. SPHEREx measures their light in 102 colours.') },
  { name: L('太陽系', 'The Solar System'), line: L('拖曳下方時間軸，行星沿軌道移動。', 'Drag the time dial below and the planets move along their orbits.') },
  { name: L('地球與 SPHEREx', 'Earth and SPHEREx'), line: L('SPHEREx 在晨昏線上方繞極飛行，一次掃過一整圈天空。點它，走進望遠鏡裡。（NASA 沒有公開 SPHEREx 3D 模型，圖中是外型相近的紅外線巡天衛星 WIRE 的 NASA 模型。）', 'SPHEREx flies pole to pole above the day-night line, sweeping one full circle of sky at a time. Click it to step inside. (NASA has not released a SPHEREx 3D model; shown is NASA\'s model of WIRE, a similar infrared survey satellite.)') },
  { name: L('SPHEREx 的天空', 'The SPHEREx sky'), line: L('捲動或雙指一直放大，會降落在 SPHEREx 量過的一個隨機天區。往外縮，看望遠鏡在哪裡。', 'Keep scrolling or pinching in and you land on a random patch SPHEREx has measured. Zoom out to see where the telescope is.') },
]

export default function Cosmos({ onDeep }) {
  const canvas = useRef(), inst = useRef(null), veil = useRef()
  const [ok] = useState(() => webgl())
  const [lite] = useState(() => !gpuOK())
  const [force, setForce] = useState(false)
  const [view, setView] = useState('sky')
  const [si, setSi] = useState(2)                  // which stage (0 galaxy .. 3 sky); changes rarely
  const [deepS, setDeepS] = useState(false)
  const [dive, setDive] = useState(null)           // the field we zoomed into, or null
  const [room, setRoom] = useState(false)          // inside the telescope
  const [entering, setEntering] = useState(false)
  const roomRef = useRef(false)
  const diveRef = useRef(null), diving = useRef(false), fieldsRef = useRef([])
  const [labels, setLabels] = useState([])
  const teleRef = useRef(), labelEls = useRef({}), labelSig = useRef(''), siRef = useRef(2), deepSRef = useRef(false), teleText = useRef('')
  const [fields, setFields] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [sel, setSel] = useState(null)
  const [hot, setHot] = useState(null)
  const [touched, setTouched] = useState(false)
  const [day, setDay] = useState(0)
  const [playing, setPlaying] = useState(false)
  const live = ok || force
  const pick = useRef(() => {}), deep = useRef(false)

  useEffect(() => { api('/api/fields').then((d) => { const a = Array.isArray(d) ? d : []; fieldsRef.current = a; setFields(a) }).catch(() => {}) }, [])
  useEffect(() => { diveRef.current = dive; inst.current?.dirty() }, [dive])
  // zoomed into a field: the assistant's default is that field
  useEffect(() => {
    if (!dive) return undefined
    setPageContext({ kind: dive.target ? 'target' : 'field', id: dive.id, name: dive.target?.name || dive.name, ra: dive.ra, dec: dive.dec })
    return () => setPageContext(null)
  }, [dive])

  /** Zoom into a field: the one given, or a random measured one (never the one just shown). */
  function diveTo(f) {
    const s = inst.current
    if (!s || diving.current) return
    const pool = fieldsRef.current.filter((x) => !x.simulated && isFinite(x.ra) && x.id !== diveRef.current?.id)
    f = f || pool[Math.floor(Math.random() * pool.length)]
    if (!f) return
    diving.current = true; setSel(null); s.setPin(null); setDive(null)
    s.goSky(f.ra, f.dec, 1.2, () => { diving.current = false; setDive(f) })
  }
  const exitDive = () => {
    const s = inst.current, f = diveRef.current
    setDive(null)
    if (s && f) { s.look = { ...s.look, fov: 1.2 }; s.goSky(f.ra, f.dec, 24) }
  }

  useEffect(() => {
    if (!live || room) return                     // inside the telescope the cosmos is torn down: one WebGL context at a time
    let dead = false
    ;(async () => {
      const { Cosmos: Scene } = await import('./scene.js')
      if (dead || !canvas.current) return
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      const s = new Scene(canvas.current, { skyUrl: SKY(lite), reduced, lite, onView: (v) => setView(v) })
      s.onFrame = () => {
        // per frame: move the labels and the readout directly; React re-renders only when something appears or goes
        const ls = s.labels(), sig = ls.map((l) => l.key).join('|')
        if (sig !== labelSig.current) { labelSig.current = sig; setLabels(ls) }
        else for (const l of ls) { const el = labelEls.current[l.key]; if (el) el.style.transform = `translate(${l.x}px, ${l.y}px)` }
        const c = s.centre()
        const tele = c ? `RA ${fmtRa(c.ra)}   Dec ${fmtDec(c.dec)}   ${L('視野', 'FOV')} ${c.fov.toFixed(c.fov < 10 ? 1 : 0)}°` : ''
        if (teleRef.current && tele !== teleText.current) { teleText.current = tele; teleRef.current.textContent = tele }
        const st = s.stage(); if (st !== siRef.current) { siRef.current = st; setSi(st) }
        if (veil.current) veil.current.style.opacity = s.fade
        const zoomed = s.p < 2.3 || (s.p > 2.9 && (s.p < 3.45 || s.look.fov < 45))
        if (zoomed !== deepSRef.current) { deepSRef.current = zoomed; setDeepS(zoomed) }
        const d = !!diveRef.current || roomRef.current || zoomed
        s.shiftOn = !d
        if (d !== deep.current) { deep.current = d; onDeep?.(d) }
      }
      s.onPick = (h) => pick.current(h)
      s.onHover = (k) => setHot(k)
      s.onInteract = () => setTouched(true)
      s.onDiveRequest = () => diveTo(null)
      inst.current = s; setLoaded(true); window.__sxCosmos = s      // for the acceptance and timing scripts
    })()
    return () => { dead = true; inst.current?.destroy(); inst.current = null; setLoaded(false); labelSig.current = ''; teleText.current = ''; setLabels([]) }
  }, [live, room]) // eslint-disable-line react-hooks/exhaustive-deps

  const markers = useMemo(() => fields.filter((f) => !f.simulated && isFinite(f.ra)).map((f) => ({
    id: f.id, ra: f.ra, dec: f.dec, kind: f.target ? 'target' : 'field',
    label: f.target ? f.target.name : f.user ? `${fmtRa(f.ra)} ${fmtDec(f.dec)}` : f.name,
  })), [fields])
  const targets = useMemo(() => fields.filter((f) => f.target), [fields])
  useEffect(() => { inst.current?.setMarkers(markers) }, [markers, loaded])

  useEffect(() => { inst.current?.setDayOffset(day) }, [day, loaded])
  useEffect(() => {
    if (!playing) return
    let raf
    const t0 = performance.now(), d0 = day
    const step = (now) => {
      const d = d0 + (now - t0) / 1000 * DAYS_PER_SECOND
      if (d >= 365) { setDay(365); setPlaying(false); return }
      setDay(Math.round(d)); raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps

  pick.current = (h) => {
    const s = inst.current
    if (!s) return
    if (!h) { setSel(null); s.setPin(null); return }
    if (h.kind === 'target' || h.kind === 'field') { s.setPin(null); setSel({ kind: h.kind, id: h.id, label: h.label, ra: h.ra, dec: h.dec, scan: s.scanDistance(h.ra, h.dec) }) }
    else if (h.kind === 'point') { s.setPin(h.ra, h.dec, `${fmtRa(h.ra)} ${fmtDec(h.dec)}`); setSel({ kind: 'point', ra: h.ra, dec: h.dec, scan: s.scanDistance(h.ra, h.dec) }) }
    else if (h.kind === 'sat') enter()
    else setSel({ kind: h.kind, label: h.label, a: h.a })
  }
  // ---- music: two original tracks by the team, one outside and one inside the telescope; off until asked for ----
  const audio = useRef(null)
  const [music, setMusic] = useState(() => { try { return localStorage.getItem('sx-music') === '1' } catch { return false } })
  const toggleMusic = () => { const on = !music; setMusic(on); try { localStorage.setItem('sx-music', on ? '1' : '0') } catch { /* private mode */ } }
  useEffect(() => {
    let a = audio.current
    if (!a) { a = audio.current = document.createElement('audio'); a.loop = true; a.preload = 'none'; a.volume = 0 }
    const want = room ? '/audio/inside.m4a' : '/audio/cosmos.m4a'
    let raf, dead = false
    const fade = (to, then) => {
      const from = a.volume, t0 = performance.now()
      const step = (n) => { if (dead) return; const k = Math.min(1, (n - t0) / 900); a.volume = Math.max(0, Math.min(1, from + (to - from) * k)); if (k < 1) raf = requestAnimationFrame(step); else then?.() }
      raf = requestAnimationFrame(step)
    }
    const start = () => { a.play().then(() => fade(0.55)).catch(() => {}) }
    if (!music) fade(0, () => a.pause())
    else if (!a.src.endsWith(want)) { if (!a.paused && a.volume > 0.01) fade(0, () => { a.src = want; start() }); else { a.src = want; start() } }
    else start()
    return () => { dead = true; cancelAnimationFrame(raf) }
  }, [music, room])
  useEffect(() => () => { audio.current?.pause() }, [])

  /** Click SPHEREx: the screen flares and you are inside the telescope. */
  const enter = () => {
    setSel(null); setEntering(true)
    try { if (localStorage.getItem('sx-music') !== '0') setMusic(true) } catch { setMusic(true) }   // the music starts inside unless it was turned off
    setTimeout(() => { roomRef.current = true; setRoom(true); onDeep?.(true); setEntering(false) }, 650)
  }
  const leave = () => { roomRef.current = false; setRoom(false) }         // the cosmos is rebuilt and opens at the Earth again
  const go = (i) => { setSel(null); inst.current?.setPin(null); inst.current?.goStage(i) }
  const flyOut = (ra, dec, fov, then) => {
    const s = inst.current
    if (!s) return then()
    setLeaving(false); setSel(null)
    s.goSky(ra, dec, fov, () => { setLeaving(true); setTimeout(then, 520) })
  }
  const open = (id) => {
    const f = fields.find((x) => x.id === id)
    const then = () => { location.hash = f?.target ? `#/target/${id}` : `#/lab/${id}` }
    if (!f) return then()
    flyOut(f.ra, f.dec, 20, then)
  }
  const playPoint = (ra, dec) => flyOut(ra, dec, 10, () => openSky(`${ra.toFixed(4)} ${dec.toFixed(4)}`, 0.3))

  if (!live) {
    return (
      <div className="cz cz-still" aria-hidden="false">
        <div className="cz-still-img" style={{ backgroundImage: `url(/cosmos/sky_2k.webp)` }} role="img" aria-label={L('SPHEREx DR1 全天影像', 'The SPHEREx DR1 all-sky picture')} />
        <div className="cz-ctl">
          <span className="cz-note">{L('這個瀏覽器不支援 WebGL，先顯示平面全天圖。', 'This browser has no WebGL, so the flat all-sky picture is shown.')}</span>
          <button className="cz-btn" onClick={() => setForce(true)}>{L('試著開啟 3D', 'Try 3D')}</button>
        </div>
      </div>
    )
  }
  const stages = STAGE()
  return (
    <div className={`cz cz-${view} cz-s${si}${leaving ? ' cz-leaving' : ''}${entering ? ' cz-entering' : ''}`}>
      {!room && <canvas ref={canvas} className="cz-canvas" aria-label={L('3D 宇宙：捲動或雙指縮放飛入、拖曳旋轉、點一下選取', '3D cosmos: scroll or pinch to fly in, drag to turn, tap to pick')} />}
      <div className="cz-veil" ref={veil} aria-hidden="true" />
      <div className="cz-labels" aria-hidden="true">
        {labels.map((l) => (
          <span key={l.key} ref={(el) => { if (el) labelEls.current[l.key] = el; else delete labelEls.current[l.key] }} className={`cz-l cz-${l.kind}${hot === l.key || (sel && (sel.id === l.key || sel.label === l.key)) ? ' is-hot' : ''}`} style={{ transform: `translate(${l.x}px, ${l.y}px)` }}>
            {l.kind === 'target' || l.kind === 'field' || l.kind === 'pin' || l.kind === 'here' ? <i /> : null}<b>{labelText(l)}</b>
          </span>
        ))}
      </div>

      {!dive && (deepS || window.innerWidth <= 900) && (
        <div className="cz-stagetext" key={si} aria-live="polite">
          <span className="cz-k">{L('現在', 'Now')}</span>
          <strong>{stages[si].name}</strong>
          <p>{stages[si].line}</p>
        </div>
      )}

      {!dive && !room && (
        <nav className="cz-rail" aria-label={L('縮放', 'Zoom')}>
          {[
            { name: L('走進望遠鏡', 'Step inside SPHEREx'), on: false, act: () => enter() },
            { name: L('拉近：隨機天區', 'Zoom in: a random patch'), on: false, act: () => diveTo(null) },
            { name: stages[3].name, on: si === 3, act: () => go(3) },
            { name: stages[2].name, on: si === 2, act: () => go(2) },
            { name: stages[1].name, on: si === 1, act: () => go(1) },
            { name: stages[0].name, on: si === 0, act: () => go(0) },
          ].map((st, i) => (
            <button key={i} className={`cz-stop${i === 0 ? ' is-in' : ''}`} aria-current={st.on ? 'step' : undefined} onClick={st.act}>
              <i /><span>{st.name}</span>
            </button>
          ))}
          <button className="cz-stop cz-music" aria-pressed={music} onClick={toggleMusic} title={L('音樂：團隊原創', 'Music: original, by the team')}>
            <i /><span>{music ? L('♪ 音樂 開', '♪ Music on') : L('♪ 音樂 關', '♪ Music off')}</span>
          </button>
        </nav>
      )}

      {!touched && loaded && !dive && si === 3 && (
        <p className="cz-hint">{L('捲動或雙指一直放大', 'Scroll or pinch to zoom in')}<span aria-hidden="true">＋</span></p>
      )}

      {dive && <FieldView key={dive.id} summary={dive} onExit={exitDive} onNext={() => diveTo(null)} />}
      {room && <RoomView fields={fields} skyUrl={SKY(lite)} lite={lite} onLeave={leave} music={music} onMusic={toggleMusic} />}
      {!touched && loaded && !dive && !room && si === 2 && (
        <p className="cz-hint">{L('點擊 SPHEREx，走進望遠鏡', 'Click SPHEREx to step inside')}<span aria-hidden="true">↗</span></p>
      )}

      <div className="cz-hud">
        {sel && (
          <div className="cz-card" role="dialog" aria-label={L('選取的天體', 'Selection')}>
            <button className="cz-x" onClick={() => pick.current(null)} aria-label={L('關閉', 'Close')}>×</button>
            {(sel.kind === 'target' || sel.kind === 'field') && <>
              <span className="cz-k">{sel.kind === 'target' ? L('測試目標', 'Test target') : L('已分析的天區', 'Analysed field')}</span>
              <strong>{sel.label}</strong>
              <span className="cz-m">RA {fmtRa(sel.ra)} · Dec {fmtDec(sel.dec)}</span>
              <p>{scanNote(sel.scan)}</p>
              <div className="cz-acts">
                <button className="cz-btn is-go" onClick={() => diveTo(fields.find((x) => x.id === sel.id))}>{L('拉近看它怎麼變 ＋', 'Zoom in and watch it change ＋')}</button>
                <button className="cz-btn" onClick={() => open(sel.id)}>{L('完整分析 →', 'Full analysis →')}</button>
              </div>
            </>}
            {sel.kind === 'point' && <>
              <span className="cz-k">{L('你選的位置', 'Your pick')}</span>
              <strong className="is-coord">RA {fmtRa(sel.ra)} · Dec {fmtDec(sel.dec)}</strong>
              <p>{scanNote(sel.scan)}</p>
              <div className="cz-acts"><button className="cz-btn is-go" onClick={() => playPoint(sel.ra, sel.dec)}>{L('播放這裡的 SPHEREx 影像 ▶', 'Play SPHEREx images here ▶')}</button></div>
            </>}
            {sel.kind === 'here' && <>
              <span className="cz-k">{L('恆星', 'Star')}</span><strong>{name('Sun')}</strong>
              <p>{L('離銀河中心約 2.6 萬光年，在獵戶臂的內緣。', 'About 26,000 light years from the centre of the Galaxy, on the inner edge of the Orion Arm.')}</p>
              <div className="cz-acts"><button className="cz-btn is-go" onClick={() => go(1)}>{L('飛進太陽系', 'Fly into the Solar System')}</button></div>
            </>}
            {sel.kind === 'earth' && <>
              <span className="cz-k">{L('行星', 'Planet')}</span><strong>{name('Earth')}</strong>
              <p>{L('SPHEREx 就在地球上空約 700 公里繞行。', 'SPHEREx circles about 700 km above it.')}</p>
              <div className="cz-acts"><button className="cz-btn is-go" onClick={() => go(2)}>{L('飛到地球', 'Fly to the Earth')}</button></div>
            </>}
            {sel.kind === 'planet' && <>
              <span className="cz-k">{L('行星', 'Planet')}</span><strong>{name(sel.label)}</strong>
              <p>{L(`離太陽 ${sel.a} au，光要走 ${lightTime(sel.a)}。`, `${sel.a} au from the Sun; light takes ${lightTime(sel.a)} to get there.`)}</p>
            </>}
            {sel.kind === 'sun' && <>
              <span className="cz-k">{L('恆星', 'Star')}</span><strong>{name('Sun')}</strong>
              <p>{L('SPHEREx 永遠讓太陽在側面，只看與太陽成 90° 的那一圈天空。', 'SPHEREx always keeps the Sun at its side and looks only at the ring of sky 90° from it.')}</p>
            </>}
            {sel.kind === 'sat' && <>
              <span className="cz-k">{L('太空望遠鏡', 'Space telescope')}</span><strong>SPHEREx</strong>
              <p>{L('2025 年 3 月發射。約 98 分鐘繞地球一圈，半年掃完全天，每個位置拍 102 種顏色。（圖中軌道高度放大）', 'Launched March 2025. About 98 minutes per orbit, the whole sky every six months, every spot in 102 colours. (Orbit height exaggerated here.)')}</p>
              <div className="cz-acts"><button className="cz-btn is-go" onClick={() => go(3)}>{L('用 SPHEREx 的眼睛看', 'Look out with SPHEREx')}</button></div>
            </>}
            <div className="cz-acts"><button className="cz-btn cz-ask" onClick={() => askAbout(askCtx(sel))}>{L('問問這個 →', 'Ask about this →')}</button></div>
          </div>
        )}
        {!sel && si === 2 && !room && !dive && <button className="cz-btn cz-ask" onClick={() => askAbout(SPHEREX_CTX())}>{L('問問 SPHEREx →', 'Ask about SPHEREx →')}</button>}
        {si === 3 && (
          <div className="cz-targets" role="group" aria-label={L('飛到一個測試目標', 'Fly to a test target')}>
            {targets.map((f) => <button key={f.id} className="cz-chip" disabled={view === 'flying'} onClick={() => diveTo(f)}>{f.target.name}</button>)}
          </div>
        )}
        <div className="cz-tele" ref={teleRef} hidden={si !== 3} />
      </div>

      <div className="cz-time" role="group" aria-label={L('時間軸', 'Time dial')}>
        <button className="cz-btn" onClick={() => { if (!playing && day >= 365) setDay(0); setPlaying(!playing) }} aria-pressed={playing}
          aria-label={playing ? L('暫停時間', 'Pause time') : L('讓時間走一年', 'Run time for a year')}>{playing ? '❚❚' : '▶'}</button>
        <div className="cz-track">
          <input type="range" min={-365} max={365} step={1} value={day} onChange={(e) => { setPlaying(false); setDay(+e.target.value) }}
            aria-label={L('時間（距今天數）', 'Time (days from today)')} />
          <div className="cz-ticks" aria-hidden="true"><span>{L('一年前', '−1 yr')}</span><span>{L('今天', 'today')}</span><span>{L('一年後', '+1 yr')}</span></div>
        </div>
        <span className="cz-date">{fmtDay(day)}</span>
        {day !== 0 && <button className="cz-btn cz-today" onClick={() => { setPlaying(false); setDay(0) }}>{L('回到今天', 'Today')}</button>}
      </div>
    </div>
  )
}
