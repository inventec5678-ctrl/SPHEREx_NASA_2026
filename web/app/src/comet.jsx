// #/comet: the interstellar comet 3I/ATLAS as SPHEREx (NASA) saw it in August and December 2025, next to the
// NEOSSat (Canadian Space Agency) view of 2025-12-02 (UPGRADE_PLAN.md section 10, R4). Every product is precomputed
// by scripts/comet_build.py into /data/comet/ (comet.json, movie sprite sheets, stacks, CO2 maps); the NEOSSat stack
// (neossat.json / neossat.webp / neossat_stars.webp) is made separately and shown when it exists.
// #/comet/<section> scrolls to a section: path, movie, spectrum, co2, neossat, notes.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api, loadImage, reducedMotion } from './lib.js'
import { usePlayback } from './play.js'
import { PlayBar } from './playbar.jsx'
import { dpr, useBoxWidth } from './canvas.js'
import { ChartCard, COL, Plot, niceTicks } from './charts.jsx'
import './comet.css'

const D = '/data/comet'
const PIX = 6.15                                     // arcsec per pixel of every comet-centred picture
const EPC = { aug: COL.pass[0], dec: COL.pass[1] }  // the two SPHEREx visits
const CO2C = '#ffb547', CONTC = COL.ink3
const EPN = { aug: () => L('2025 年 8 月', 'August 2025'), dec: () => L('2025 年 12 月', 'December 2025') }
const SECS = [
  ['path', () => L('它從哪裡來', 'Where it came from')],
  ['movie', () => L('SPHEREx 的影片', 'SPHEREx movies')],
  ['co2', () => L('二氧化碳', 'Carbon dioxide')],
  ['neossat', () => L('兩個太空總署', 'Two space agencies')],
  ['notes', () => L('注意事項', 'Caveats')],
]
// gas bands the SPHEREx team papers discuss, at the wavelengths where they sit
const BANDS = [[2.7, () => L('水', 'water'), 'end'], [4.26, () => L('二氧化碳', 'CO₂'), 'end'], [4.67, () => L('一氧化碳', 'CO'), 'start']]
const fmt = (v, d = 0) => (v == null || !isFinite(v) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }))
const AU_KM = 149597870.7
const kmPerArcmin = (delta) => delta * AU_KM * (Math.PI / 180 / 60)
const jump = (id) => document.getElementById(id)?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })

export default function Comet({ sec }) {
  useLanguage()
  const [d, setD] = useState(null)
  const [neo, setNeo] = useState(undefined)            // undefined: loading; null: not made yet
  useEffect(() => {
    document.title = 'SPHEREx Sky Change · ' + L('星際彗星 3I/ATLAS', 'Interstellar comet 3I/ATLAS')
    api(`${D}/comet.json`).then(setD).catch(() => setD(false))
    api('/api/comet/neossat').then((n) => setNeo(n.available ? n : null)).catch(() => setNeo(null))
  }, [])
  // #/comet/<section>: scroll there once the page has its content
  useEffect(() => {
    if (!sec || !d) return
    const id = setTimeout(() => jump(`cm-${sec}`), 200)
    return () => clearTimeout(id)
  }, [sec, d])
  const go = (s) => { history.replaceState(history.state, '', `#/comet/${s}`); jump(`cm-${s}`) }
  return (
    <div className="comet">
      <Hero d={d} />
      <nav className="cm-nav" aria-label={L('本頁段落', 'Sections of this page')}>
        {SECS.map(([k, t]) => <button key={k} type="button" className="chip" onClick={() => go(k)}>{t()}</button>)}
      </nav>
      {d === false && <p className="cm-note cm-missing">{L('彗星的資料還沒產生（scripts/comet_build.py）。', 'The comet products have not been made yet (scripts/comet_build.py).')}</p>}
      {d && <>
        <PathSection d={d} />
        <MovieSection d={d} />
        <Co2Section d={d} />
        <AgencySection d={d} neo={neo} />
        <Notes d={d} />
        <Credits />
      </>}
    </div>
  )
}

// ---- head -----------------------------------------------------------------------------------------------------
function Hero({ d }) {
  const f = d?.facts
  const facts = [
    { n: L('第 3 個', '3rd'), t: L('已知從太陽系外飛來的天體（前兩個是 2017 年的 ʻOumuamua 和 2019 年的 Borisov）', 'object known to come from outside the Solar System (after ʻOumuamua in 2017 and Borisov in 2019)') },
    { n: f ? `${fmt(f.v_inf_kms)} km/s` : '—', t: L('離太陽很遠時的速度：太快，太陽留不住它，它不會再回來', 'its speed far from the Sun: too fast for the Sun to hold, so it will never come back') },
    { n: d ? fmt(d.n_frames) : '—', t: L(`張 SPHEREx 影像，用在這一頁（IRSA 列出 ${d?.n_table ?? 259} 張）`, `SPHEREx images used on this page (IRSA lists ${d?.n_table ?? 259})`) },
    { n: f ? `${fmt(f.perihelion.r_au, 2)} au` : '—', t: L(`離太陽最近的距離（${f ? isoDay(f.perihelion.date) : ''}；1 au 是地球到太陽的距離）`, `closest to the Sun (${f ? isoDay(f.perihelion.date) : ''}; 1 au is the Earth–Sun distance)`) },
  ]
  const dec = d?.facts?.epochs?.dec
  return (
    <header className="cm-hero">
      <div className="cm-hero-text">
        <p className="cm-kicker">{L('星際彗星', 'Interstellar comet')}</p>
        <h1>3I/ATLAS</h1>
        <p className="cm-lead">{L('2025 年 7 月發現的彗星，來自另一顆恆星附近，只是路過太陽系。SPHEREx 在 8 月和 12 月拍了它兩百多次，用一百多種顏色的紅外線。', 'A comet found in July 2025 that formed around another star and is only passing through. SPHEREx photographed it over two hundred times, in more than a hundred infrared colours, in August and December 2025.')}</p>
        <ul className="cm-facts">
          {facts.map((x, j) => <li key={j}><b>{x.n}</b><span>{x.t}</span></li>)}
        </ul>
      </div>
      <figure className="cm-hero-img">
        {d ? <SkyPic src={`${D}/deep_dec_short.webp`} delta={dec?.delta_au} alt={L('SPHEREx 拍到的 3I/ATLAS：12 月的影像以彗星為中心疊加', '3I/ATLAS seen by SPHEREx: December images stacked on the comet')} />
          : <div className="cm-pic cm-pic-empty" />}
        {d && <figcaption>{L(`SPHEREx，${dec?.first}～${dec?.last}：${d.epochs.dec?.deep?.short?.n ?? ''} 張近紅外影像（0.75–2.4 µm）以彗星為中心疊加。中間亮的是彗核周圍的塵埃雲（彗髮），星星因為彗星在移動而被抹掉。`, `SPHEREx, ${dec?.first} to ${dec?.last}: ${d.epochs.dec?.deep?.short?.n ?? ''} near-infrared images (0.75–2.4 µm) stacked on the comet. The glow is the dust cloud (coma) around the nucleus; the stars are smeared out because the comet moves.`)}</figcaption>}
      </figure>
    </header>
  )
}
const MON = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06', Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' }
/** '2025-Oct-29' -> '2025-10-29' */
const isoDay = (s) => (s ? s.replace(/^(\d{4})-(\w{3})-(\d{2}).*/, (_, y, m, dd) => `${y}-${MON[m] || m}-${dd}`) : '')

/** A comet-centred picture (north up, east left) with a compass and a 1-arcminute scale bar. */
function SkyPic({ src, alt, delta, px = 101, label, className = '' }) {
  const bar = (60 / PIX / px) * 100
  return (
    <div className={`cm-pic ${className}`}>
      <img src={src} alt={alt} width={px} height={px} loading="lazy" />
      {label && <span className="cm-pic-label">{label}</span>}
      <span className="cm-compass" aria-hidden="true"><i>N</i><b>E</b></span>
      <span className="cm-scale" style={{ width: `${bar}%` }} aria-hidden="true">
        <span>1′{delta ? ` ≈ ${fmt(kmPerArcmin(delta) / 1000)} ${L('千公里', 'thousand km')}` : ''}</span>
      </span>
    </div>
  )
}

function Section({ id, title, lead, children }) {
  return (
    <section id={`cm-${id}`} className="cm-sec" aria-labelledby={`cm-h-${id}`}>
      <h2 id={`cm-h-${id}`}>{title}</h2>
      {lead && <p className="cm-lead2">{lead}</p>}
      {children}
    </section>
  )
}

// ---- where it came from ----------------------------------------------------------------------------------------
function PathSection({ d }) {
  const f = d.facts
  return (
    <Section id="path" title={L('它從哪裡來，往哪裡去', 'Where it came from, where it goes')}
      lead={L('一般的彗星繞著太陽轉；3I/ATLAS 的路線是一條打開的曲線，只轉一個彎就離開。', 'Ordinary comets go round the Sun. 3I/ATLAS follows an open curve: one turn, then it leaves.')}>
      <div className="cm-grid">
        <ChartCard className="cm-c6" title={L('從太陽系上方往下看', 'The Solar System seen from above')}
          take={L(`它在 ${isoDay(f.perihelion.date)} 離太陽最近（${fmt(f.perihelion.r_au, 2)} au，在火星軌道內側）。SPHEREx 在地球附近，8 月和 12 月兩次看向它。`, `It passed closest to the Sun on ${isoDay(f.perihelion.date)} (${fmt(f.perihelion.r_au, 2)} au, inside the orbit of Mars). SPHEREx, near the Earth, looked at it in August and in December.`)}
          legend={[{ c: COL.accent, line: true, label: L('3I/ATLAS 的路線', 'path of 3I/ATLAS') }, { c: EPC.aug, label: EPN.aug() }, { c: EPC.dec, label: EPN.dec() }]}>
          <OrbitChart d={d} />
        </ChartCard>
        <ChartCard className="cm-c6" title={L('在天空中的路線', 'Its path across the sky')}
          take={L('8 月時它在銀河中心的方向，背景擠滿星星；12 月時背景乾淨多了。', 'In August it lay towards the centre of the Milky Way, among crowds of stars; in December the background was much emptier.')}
          legend={[{ c: COL.ink3, line: true, label: L('每天的位置（JPL Horizons）', 'daily position (JPL Horizons)') }, { c: EPC.aug, label: L('SPHEREx 8 月', 'SPHEREx, August') }, { c: EPC.dec, label: L('SPHEREx 12 月', 'SPHEREx, December') }, { c: COL.good, hollow: true, label: L('NEOSSat 12/2', 'NEOSSat, 2 Dec') }]}>
          <SkyPathChart d={d} />
        </ChartCard>
      </div>
    </Section>
  )
}

function OrbitChart({ d }) {
  const o = d.orbit, mk = o.marks || {}
  const marks = ['aug', 'dec'].filter((k) => mk[k]).map((k) => [k, mk[k], EPC[k], EPN[k]()])
  const peri = mk.peri?.comet || o.comet[0]
  const pts = [
    ...marks.map(([k, m, c, t]) => ({ x: m.comet[0], y: m.comet[1], tip: L(`SPHEREx 觀測：${t}`, `SPHEREx visit: ${t}`), hint: L(`彗星離太陽 ${fmt(d.facts.epochs[k]?.r_au, 2)} au，離地球 ${fmt(d.facts.epochs[k]?.delta_au, 2)} au`, `comet ${fmt(d.facts.epochs[k]?.r_au, 2)} au from the Sun, ${fmt(d.facts.epochs[k]?.delta_au, 2)} au from Earth`), c })),
    ...marks.map(([k, m, , t]) => ({ x: m.earth[0], y: m.earth[1], tip: L(`地球（SPHEREx）：${t}`, `Earth (SPHEREx): ${t}`), r: 6 })),
    { x: peri[0], y: peri[1], tip: L('離太陽最近', 'Closest to the Sun'), hint: `${isoDay(d.facts.perihelion.date)} · ${fmt(d.facts.perihelion.r_au, 2)} au` },
    { x: 0, y: 0, tip: L('太陽', 'Sun'), r: 8 },
  ]
  const R = 4.2
  return (
    <Plot label={L('太陽系俯視圖：3I/ATLAS 的路線、地球、火星和木星', 'Top view of the Solar System: the path of 3I/ATLAS, Earth, Mars and Jupiter')}
      x={{ domain: [-R, R], label: 'au', grid: false, ticks: [-4, -2, 0, 2, 4] }} y={{ domain: [-R, R], grid: false, ticks: [-4, -2, 0, 2, 4] }} square equal points={pts}>
      {({ X, Y, w, h, m }) => {
        const r = (a) => Math.abs(X(a) - X(0))
        const line = (arr) => arr.map((p, j) => `${j ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')
        return <g clipPath="url(#cm-orbit-clip)">
          <clipPath id="cm-orbit-clip"><rect x={m.l} y={m.t} width={w - m.l - m.r} height={h - m.t - m.b} /></clipPath>
          {[[1, L('地球軌道', "Earth's orbit"), -1], [1.52, L('火星軌道', "Mars's orbit"), 1], [5.2, L('木星軌道', "Jupiter's orbit"), 1]].map(([a, t, sg]) => (
            <g key={a}><circle cx={X(0)} cy={Y(0)} r={r(a)} className="cm-orb" />
              {a < 5 ? <text className="mark-note" x={X(0) + r(a) * 0.72 + 4} y={Y(0) - sg * r(a) * 0.72 + (sg < 0 ? 14 : -4)}>{t}</text>
                : <text className="mark-note" x={X(0) + r(a) * 0.6} y={Y(0) - r(a) * 0.8}>{t}</text>}</g>
          ))}
          <circle cx={X(0)} cy={Y(0)} r="7" fill={COL.warn} />
          <path d={line(o.comet)} className="cm-path" />
          {marks.map(([k, m, c]) => {
            const p = m.comet, e = m.earth
            return <g key={k}>
              <line x1={X(e[0])} y1={Y(e[1])} x2={X(p[0])} y2={Y(p[1])} stroke={c} strokeDasharray="4 4" strokeWidth="1.5" />
              <circle cx={X(e[0])} cy={Y(e[1])} r="4.5" fill={COL.known} />
              <circle cx={X(p[0])} cy={Y(p[1])} r="7" fill={c} />
            </g>
          })}
          <circle cx={X(peri[0])} cy={Y(peri[1])} r="5" fill="none" stroke={COL.accent} strokeWidth="2" />
          <ArrowOnPath o={o.comet} X={X} Y={Y} R={R} />
        </g>
      }}
    </Plot>
  )
}
/** An arrowhead on the comet's path, near the end, pointing the way it moves. */
function ArrowOnPath({ o, X, Y, R }) {
  // the last point of the path still inside the frame
  let k = o.length - 1
  while (k > 1 && (Math.abs(o[k][0]) > R * 0.92 || Math.abs(o[k][1]) > R * 0.92)) k--
  const a = o[k - 1], b = o[k]
  const x = X(b[0]), y = Y(b[1]), ang = Math.atan2(Y(b[1]) - Y(a[1]), X(b[0]) - X(a[0])), h = 11
  return <path d={`M${x},${y}L${x - h * Math.cos(ang - 0.45)},${y - h * Math.sin(ang - 0.45)}L${x - h * Math.cos(ang + 0.45)},${y - h * Math.sin(ang + 0.45)}Z`} fill={COL.accent} />
}

function SkyPathChart({ d }) {
  const path = d.path
  const ras = path.map((p) => p.ra), decs = path.map((p) => p.dec)
  const GC = [266.42, -29.01]                     // the centre of the Milky Way (Sgr A*)
  const xd = [Math.min(...ras) - 4, Math.max(Math.max(...ras), GC[0]) + 4], yd = [Math.min(Math.min(...decs), GC[1]) - 5, Math.max(...decs) + 6]
  const ne = d.facts.neossat_day
  const month1 = path.filter((p) => p.d.endsWith('-01'))
  const pts = [
    ...month1.map((p) => ({ x: p.ra, y: p.dec, tip: isoDay(p.d), hint: L(`離地球 ${fmt(p.delta, 2)} au`, `${fmt(p.delta, 2)} au from Earth`), r: 5 })),
    ...['aug', 'dec'].map((k) => { const o = d.obs.filter((x) => x.ep === k), m = o[Math.floor(o.length / 2)]; return m && { x: m.ra, y: m.dec, tip: L(`SPHEREx：${o.length} 張`, `SPHEREx: ${o.length} images`), hint: EPN[k](), r: 9 } }).filter(Boolean),
    ...(ne ? [{ x: ne.ra, y: ne.dec, tip: 'NEOSSat', hint: isoDay('2025-Dec-02'), r: 7 }] : []),
    { x: GC[0], y: GC[1], tip: L('銀河中心', 'Centre of the Milky Way'), hint: L('人馬座方向', 'towards Sagittarius'), r: 8 },
  ]
  return (
    <Plot label={L('3I/ATLAS 在天空中的路線（赤經、赤緯）', 'Path of 3I/ATLAS on the sky (right ascension, declination)')} height={340}
      x={{ domain: xd, reverse: true, label: L('赤經（度，東在左）', 'right ascension (deg, east to the left)'), fmt: (v) => `${v}°` }}
      y={{ domain: yd, label: L('赤緯（度）', 'declination (deg)'), fmt: (v) => `${v}°` }} points={pts}>
      {({ X, Y, narrow }) => {
        const gal = d.galactic_plane.filter((p) => p[0] >= xd[0] && p[0] <= xd[1] && p[1] >= yd[0] && p[1] <= yd[1])
        const runs = []
        gal.forEach((p, j) => { if (!j || Math.abs(p[0] - gal[j - 1][0]) > 2) runs.push([]); runs.at(-1).push(p) })
        const gl = runs.find((r) => r.length > 4)
        return <>
          {runs.map((r, j) => <path key={j} d={r.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')} className="cm-gal" />)}
          {gl && !narrow && <text className="mark-note cm-gal-label" x={X(gl[Math.floor(gl.length * 0.3)][0]) + 6} y={Y(gl[Math.floor(gl.length * 0.3)][1]) - 8}>{L('銀河盤面', 'Milky Way plane')}</text>}
          <path d={path.map((p, j) => `${j ? 'L' : 'M'}${X(p.ra).toFixed(1)},${Y(p.dec).toFixed(1)}`).join('')} className="cm-skypath" />
          {month1.map((p) => <g key={p.d}><circle cx={X(p.ra)} cy={Y(p.dec)} r="3" fill={COL.ink3} /><text className="mark-note" x={X(p.ra)} y={Y(p.dec) + 18} textAnchor="middle">{isoDay(p.d).slice(5, 7)}{L('月', '')}</text></g>)}
          {d.obs.map((o, j) => <circle key={j} cx={X(o.ra)} cy={Y(o.dec)} r="4" fill={EPC[o.ep]} opacity=".85" />)}
          {ne && <circle cx={X(ne.ra)} cy={Y(ne.dec)} r="7" fill="none" stroke={COL.good} strokeWidth="2.5" />}
          <circle cx={X(GC[0])} cy={Y(GC[1])} r="16" className="cm-gc" />
          <circle cx={X(GC[0])} cy={Y(GC[1])} r="4" fill={COL.distant} />
          <text className="mark-note cm-gal-label" x={X(GC[0]) + 22} y={Y(GC[1]) + 4}>{L('銀河中心', 'Galactic centre')}</text>
        </>
      }}
    </Plot>
  )
}

// ---- movies and the spectrum -----------------------------------------------------------------------------------
function EpochSwitch({ ep, setEp, d }) {
  return (
    <div className="seg" role="group" aria-label={L('哪一次觀測', 'Which visit')}>
      {['dec', 'aug'].filter((k) => d.epochs[k]).map((k) => <button key={k} type="button" aria-pressed={ep === k} onClick={() => setEp(k)}>{EPN[k]()}</button>)}
    </div>
  )
}

function MovieSection({ d }) {
  const [ep, setEp] = useState('dec')
  const e = d.epochs[ep]
  const [order, setOrder] = useState('time')
  const list = useMemo(() => {
    const idx = e.frames.map((_, j) => j)
    if (order === 'lam') idx.sort((a, b) => e.frames[a].lam - e.frames[b].lam)
    return idx
  }, [e, order])
  const [hz, setHz] = useState(4)
  const pb = usePlayback(list.length, { hz })
  const j = list[pb.k] ?? 0
  useEffect(() => { pb.seek(0); pb.setPlaying(!reducedMotion()) }, [ep, order]) // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (i) => { const k = list.indexOf(i); if (k >= 0) pb.seek(k) }
  const f = e.frames[j]
  const fe = d.facts.epochs[ep]
  return (
    <Section id="movie" title={L('跟著彗星看', 'Riding along with the comet')}
      lead={L('每一張都以彗星為中心，所以彗星不動，背景的星星往後流。SPHEREx 每張影像在每個位置只量一種顏色（波長），所以每一張的顏色都不一樣。', 'Every frame is centred on the comet, so the comet stays put and the stars stream past. Each SPHEREx image sees one colour (wavelength) at each spot, so every frame shows a different colour.')}>
      <div className="cm-toolbar">
        <EpochSwitch ep={ep} setEp={setEp} d={d} />
        <div className="seg" role="group" aria-label={L('播放順序', 'Order of the frames')}>
          <button type="button" aria-pressed={order === 'time'} onClick={() => setOrder('time')}>{L('照時間', 'By time')}</button>
          <button type="button" aria-pressed={order === 'lam'} onClick={() => setOrder('lam')}>{L('照波長', 'By wavelength')}</button>
        </div>
      </div>
      <div className="cm-grid">
        <figure className="chart-card cm-c5 cm-movie">
          <MovieCanvas e={e} j={j} delta={fe?.delta_au} />
          <FrameInfo f={f} />
          <PlayBar pb={pb} n={list.length} speeds={[2, 4, 8]} hz={hz} setHz={setHz} label={L('播放彗星影片', 'Play the comet movie')} />
          <figcaption className="cm-note">{ep === 'aug'
            ? L(`8 月的彗星很暗（離太陽 ${fmt(fe?.r_au, 1)} au），背景又是銀河中心方向擁擠的星空：多數單張只看得到星星。把它們疊起來，它才浮現（下方）。`, `In August the comet was faint (${fmt(fe?.r_au, 1)} au from the Sun) against the crowded stars towards the centre of the Milky Way: most single frames show only stars. Stack them and it appears (below).`)
            : L(`12 月它剛繞過太陽、比較活躍，離地球 ${fmt(fe?.delta_au, 2)} au：每一張都看得到它的彗髮。`, `In December, just after passing the Sun and more active, ${fmt(fe?.delta_au, 2)} au from Earth: its coma shows in every frame.`)}
            {' '}{L('灰階依每張影像自己的雜訊拉伸，所以不同張之間的亮度不能直接比。', 'Each frame is stretched by its own noise, so brightness cannot be compared between frames.')}</figcaption>
        </figure>
        <ChartCard className="cm-c7" id="cm-spectrum" title={L('每張影像量到的亮度（粗略的光譜）', 'Brightness in each image (a rough spectrum)')}
          take={L('每個點是一張影像，在彗星周圍 25″ 的圓裡量的亮度。點一個點，左邊就跳到那一張。', 'Each dot is one image: the brightness within 25″ of the comet. Click a dot to show that image on the left.')}
          legend={[1, 2, 3, 4, 5, 6].map((k) => ({ c: COL.det[k - 1], label: `D${k}` }))}
          more={L('只能當參考：彗星是延展的天體，IRSA 建議不要用點光源的光譜測光工具量它；很多波長的訊號很弱；每張影像拍的時間不同（8 月的影像分散在兩週內），彗星本身也在變。背景圈在 2–3 角分外，彗髮延伸得更遠，所以總亮度會略為低估。8 月有些點偏高，是星星剛好落在圈內。', 'Indicative only: the comet is extended, and IRSA advises against measuring it with the point-source spectrophotometry tool; many wavelengths have weak signal; the images were taken at different times (August spans two weeks) while the comet itself changed. The background ring is 2–3 arcminutes out and the coma reaches farther, so totals are slightly low. Some high August points are stars that happened to fall in the circle.')}>
          <SedChart e={e} cur={j} onPick={(p) => pick(p.i)} />
        </ChartCard>
      </div>
      <div className="cm-grid cm-deep">
        {['short', 'long'].filter((k) => e.deep[k]).map((k) => (
          <figure key={k} className="chart-card cm-c6">
            <SkyPic src={`${D}/deep_${ep}_${k}.webp`} delta={fe?.delta_au} alt={L(`${EPN[ep]()} 疊加影像`, `${EPN[ep]()} stack`)}
              label={`${fmt(e.deep[k].lam[0], 2)}–${fmt(e.deep[k].lam[1], 2)} µm`} />
            <figcaption className="cm-note">{L(`${e.deep[k].n} 張${k === 'short' ? '較短波長（D1–D3）' : '較長波長（D4–D6）'}的影像以彗星為中心疊加（中位數）。`, `${e.deep[k].n} ${k === 'short' ? 'shorter-wavelength (D1–D3)' : 'longer-wavelength (D4–D6)'} images stacked on the comet (median).`)}</figcaption>
          </figure>
        ))}
      </div>
    </Section>
  )
}

/** One comet-centred frame from the epoch's sprite sheet, at a whole-number zoom, with a reticle that leaves the
 *  comet itself uncovered. */
function MovieCanvas({ e, j, delta }) {
  const box = useRef(), cv = useRef()
  const w = useBoxWidth(box)
  const [sheet, setSheet] = useState(null)
  useEffect(() => {
    let live = true
    setSheet(null)
    loadImage(e.movie.url, (im) => { if (live) setSheet(im) })
    return () => { live = false }
  }, [e.movie.url])
  const n = e.movie.tile
  useEffect(() => {
    const c = cv.current
    if (!c || !w) return
    const u = dpr(), s = Math.max(1, Math.floor((Math.min(w, 560) * u) / n)), W = s * n
    if (c.width !== W || c.height !== W) { c.width = W; c.height = W }
    c.style.width = `${W / u}px`
    const g = c.getContext('2d')
    g.imageSmoothingEnabled = false
    g.fillStyle = '#000'; g.fillRect(0, 0, W, W)
    if (!sheet) return
    const col = j % e.movie.cols, row = Math.floor(j / e.movie.cols)
    g.drawImage(sheet, col * n, row * n, n, n, 0, 0, W, W)
    g.strokeStyle = 'rgba(242,230,201,.75)'; g.lineWidth = 2 * u
    const m = W / 2, r = 26 * u, t = 14 * u
    g.beginPath(); g.moveTo(m - r - t, m); g.lineTo(m - r, m); g.moveTo(m + r, m); g.lineTo(m + r + t, m)
    g.moveTo(m, m - r - t); g.lineTo(m, m - r); g.moveTo(m, m + r); g.lineTo(m, m + r + t); g.stroke()
  }, [sheet, j, w, n, e.movie.cols])
  const bar = (60 / PIX / n) * 100
  return (
    <div ref={box} className="cm-moviebox">
      <div className="cm-pic cm-pic-canvas">
        <canvas ref={cv} role="img" aria-label={L('以彗星為中心的 SPHEREx 影像', 'SPHEREx image centred on the comet')} />
        {!sheet && <span className="cm-loading">{L('載入影像…', 'Loading images…')}</span>}
        <span className="cm-compass" aria-hidden="true"><i>N</i><b>E</b></span>
        <span className="cm-scale" style={{ width: `${bar}%` }} aria-hidden="true"><span>1′{delta ? ` ≈ ${fmt(kmPerArcmin(delta) / 1000)} ${L('千公里', 'thousand km')}` : ''}</span></span>
      </div>
    </div>
  )
}

/** Time, wavelength and detector of the frame on screen, with the frame's place on the 0.75-5 µm ruler. */
function FrameInfo({ f }) {
  if (!f) return null
  const pos = ((f.lam - 0.75) / (5.0 - 0.75)) * 100
  return (
    <div className="cm-frameinfo">
      <div className="cm-frameinfo-row">
        <span className="num">{f.iso} UT</span>
        <b className="num" style={{ color: COL.det[f.det - 1] }}>{fmt(f.lam, 2)} µm</b>
        <span>{L(`偵測器 D${f.det}`, `detector D${f.det}`)}{f.band === 'co2' ? <em className="cm-co2tag">{L('二氧化碳波段', 'CO₂ band')}</em> : null}</span>
      </div>
      <div className="cm-ruler" aria-hidden="true">
        <i className="cm-ruler-co2" style={{ left: `${((4.2 - 0.75) / 4.25) * 100}%`, width: `${(0.12 / 4.25) * 100}%` }} />
        <b style={{ left: `${pos}%`, '--c': COL.det[f.det - 1] }} />
      </div>
      <div className="cm-ruler-ticks" aria-hidden="true"><span>0.75 µm</span><span>{L('紅外線', 'infrared')}</span><span>5 µm</span></div>
    </div>
  )
}

function SedChart({ e, cur, onPick }) {
  const sed = e.sed
  const pos = sed.filter((p) => p.mjy > 0).map((p) => p.mjy)
  const hi = Math.max(...pos) * 1.6
  const lo = Math.max(0.2, Math.min(...pos.filter((v) => v > 0.05)) / 1.5)
  const pts = sed.map((p) => ({ ...p, x: p.lam, y: Math.max(lo, p.mjy), low: p.mjy < lo, r: 6,
    tip: `${fmt(p.lam, 3)} µm · ${p.mjy < lo ? `< ${fmt(lo, 1)}` : fmt(p.mjy, 1)} mJy`, hint: `${e.frames[p.i]?.iso} UT · D${p.det}` }))
  const curP = pts.find((p) => p.i === cur)
  // a running median (±0.06 µm) so the shape reads through the scatter
  const run = useMemo(() => {
    const s = [...sed].sort((a, b) => a.lam - b.lam), out = []
    for (const p of s) {
      const w = s.filter((q) => Math.abs(q.lam - p.lam) <= 0.06).map((q) => q.mjy).sort((a, b) => a - b)
      out.push([p.lam, Math.max(lo, w[Math.floor(w.length / 2)])])
    }
    return out
  }, [sed, lo])
  return (
    <Plot label={L('3I/ATLAS 在每張影像的亮度和波長', 'Brightness of 3I/ATLAS against wavelength, one dot per image')} height={420}
      x={{ domain: [0.7, 5.05], label: L('波長（µm）', 'wavelength (µm)'), ticks: [1, 2, 3, 4, 5] }}
      y={{ domain: [lo, hi], log: true, label: L('亮度（mJy）', 'brightness (mJy)'), fmt: (v) => (v >= 1 ? fmt(v) : fmt(v, 1)) }}
      points={pts} onPick={onPick}>
      {({ X, Y, m }) => <>
        {BANDS.map(([l, t, a]) => <g key={l}><line x1={X(l)} x2={X(l)} y1={m.t} y2={Y(lo)} className="cm-bandline" /><text className="mark-note" x={X(l) + (a === 'end' ? -5 : 5)} y={m.t + 12} textAnchor={a}>{t()}</text></g>)}
        <path d={run.map((p, j) => `${j ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('')} className="cm-run" />
        {pts.map((p, j) => p.low
          ? <path key={j} d={`M${X(p.x) - 4},${Y(p.y) - 3}L${X(p.x) + 4},${Y(p.y) - 3}L${X(p.x)},${Y(p.y) + 4}Z`} fill="none" stroke={COL.det[p.det - 1]} strokeWidth="1.2" opacity=".7" />
          : <circle key={j} cx={X(p.x)} cy={Y(p.y)} r="3.6" fill={COL.det[p.det - 1]} opacity=".85" />)}
        {curP && <circle cx={X(curP.x)} cy={Y(curP.y)} r="10" fill="none" stroke={COL.ink} strokeWidth="2.5" />}
      </>}
    </Plot>
  )
}

// ---- carbon dioxide --------------------------------------------------------------------------------------------
function Co2Section({ d }) {
  const [ep, setEp] = useState('dec')
  const e = d.epochs[ep], c = e.co2, fe = d.facts.epochs[ep]
  const ok = c?.measured
  const pics = ok ? [
    ['blue', `${fmt(c.lam.blue, 2)} µm`, L('旁邊的顏色', 'next colour down'), c.n.blue],
    ['co2', `${fmt(c.lam.co2, 2)} µm`, L('二氧化碳的顏色', 'the colour of CO₂'), c.n.co2],
    ['red', `${fmt(c.lam.red, 2)} µm`, L('旁邊的顏色', 'next colour up'), c.n.red],
    ['excess', L('相減', 'difference'), L('只剩二氧化碳', 'CO₂ only'), null],
  ] : []
  const stats = ok ? [
    { n: c.ratio ? `${fmt(c.ratio)}×` : c.ratio_min ? `> ${fmt(c.ratio_min)}×` : '—',
      t: c.ratio ? L('在 4.26 µm，彗星比只有塵埃時亮的倍數', 'how much brighter the comet is at 4.26 µm than its dust alone')
        : L('在 4.26 µm 比塵埃亮的倍數下限：這時塵埃本身暗到量不到', 'at least this much brighter at 4.26 µm than the dust, which is too faint to measure'), c: CO2C },
    { n: c.line?.snr ? `${fmt(c.line.snr)}` : '—', t: L('訊號是雜訊的幾倍（二氧化碳波段的總亮度）', 'times above the noise (total brightness of the CO₂ band)') },
    { n: `${c.n.co2} + ${c.n.blue + c.n.red}`, t: L('張影像：落在二氧化碳波段的，加上兩邊連續光的', 'images: inside the CO₂ band, plus the continuum on either side') },
  ] : []
  return (
    <Section id="co2" title={L('它被一大團二氧化碳包著', 'Wrapped in a huge cloud of carbon dioxide')}
      lead={L('二氧化碳氣體被陽光照到，會在 4.26 µm 這個紅外線顏色發光。SPHEREx 的團隊（Lisse 等人）發現 3I/ATLAS 有一大團二氧化碳。我們用公開的影像自己重做一次。', 'Carbon dioxide gas lit by the Sun glows at one infrared colour, 4.26 µm. The SPHEREx team (Lisse et al.) found a large CO₂ cloud around 3I/ATLAS. We redo it ourselves from the public images.')}>
      <div className="cm-toolbar"><EpochSwitch ep={ep} setEp={setEp} d={d} /></div>
      {!ok && <p className="cm-note">{L('這次觀測沒有足夠的影像落在二氧化碳波段和兩邊。', 'This visit has too few images in the CO₂ band and on either side.')}</p>}
      {ok && <>
        <div className="cm-co2row">
          {pics.map(([k, a, b, n]) => (
            <figure key={k} className={`cm-co2pic ${k === 'co2' ? 'on' : ''} ${k === 'excess' ? 'diff' : ''}`}>
              <SkyPic src={`${D}/co2_${ep}_${k}.webp`} alt={`${a} ${b}`} delta={k === 'excess' ? fe?.delta_au : null} />
              <figcaption><b>{a}</b><span>{b}{n ? L(`，${n} 張`, `, ${n} images`) : ''}</span></figcaption>
            </figure>
          ))}
        </div>
        <p className="cm-take">{L('前三張用同一個亮度尺度。只有中間那個顏色亮，表示亮光來自二氧化碳氣體，不是塵埃。第四張是二氧化碳那張減掉兩邊推算的連續光。', 'The first three share one brightness scale. Only the middle colour is bright, so the light comes from carbon dioxide gas, not dust. The fourth is the CO₂ image minus the continuum estimated from either side.')}</p>
        <ul className="cm-facts cm-facts3">
          {stats.map((x, j) => <li key={j}><b style={x.c ? { color: x.c } : undefined}>{x.n}</b><span>{x.t}</span></li>)}
        </ul>
        <div className="cm-grid">
          <ChartCard className="cm-c6" title={L('二氧化碳波段附近的亮度', 'Brightness around the CO₂ band')}
            take={L('每個點是一張影像。橘色點落在二氧化碳波段，比兩邊（灰色）亮得多。', 'One dot per image. The orange dots, inside the CO₂ band, stand far above those on either side (grey).')}
            legend={[{ c: CO2C, label: L('二氧化碳波段 4.20–4.32 µm', 'CO₂ band 4.20–4.32 µm') }, { c: CONTC, label: L('連續光', 'continuum') }, { c: COL.ink3, line: true, label: L('擬合的連續光', 'fitted continuum') }]}
            more={<Co2Detail c={c} ep={ep} />}>
            <ZoomChart e={e} c={c} />
          </ChartCard>
          <ChartCard className="cm-c6" title={L('二氧化碳的光暈比塵埃大', 'The CO₂ glow reaches farther than the dust')}
            take={L(`離中心越遠越暗，但二氧化碳暗得慢得多。${fe ? `在這個距離，1 角分約 ${fmt(kmPerArcmin(fe.delta_au) / 1000)} 千公里。` : ''}`, `Both fade away from the centre, but the CO₂ fades far more slowly.${fe ? ` At this distance one arcminute is about ${fmt(kmPerArcmin(fe.delta_au) / 1000)} thousand km.` : ''}`)}
            legend={[{ c: CO2C, label: L('二氧化碳（相減後）', 'CO₂ (difference)') }, { c: COL.ink2, label: L('塵埃（0.75–2.4 µm 疊加）', 'dust (0.75–2.4 µm stack)') }]}>
            <ProfileChart e={e} c={c} />
          </ChartCard>
        </div>
      </>}
    </Section>
  )
}

function Co2Detail({ c, ep }) {
  return (
    <div className="cm-detail">
      <p>{L(`怎麼做：SPHEREx 的濾鏡顏色在影像上逐列改變，所以每張影像取「彗星所在像素」的波長。波長落在 4.20–4.32 µm 的 ${c.n.co2} 張疊成二氧化碳影像，3.90–4.10 µm 的 ${c.n.blue} 張和 4.45–4.60 µm 的 ${c.n.red} 張疊成兩邊的連續光（每張先轉到以彗星為中心、北上東左的格子，單位 MJy/sr）。連續光依波長線性內插到 ${fmt(c.lam.co2, 2)} µm 後相減。`, `How: SPHEREx's filter colour changes row by row across each image, so each image is assigned the wavelength at the comet's pixel. The ${c.n.co2} images at 4.20–4.32 µm are stacked into the CO₂ image, the ${c.n.blue} at 3.90–4.10 µm and the ${c.n.red} at 4.45–4.60 µm into the continuum on either side (each first resampled onto a comet-centred, north-up grid, in MJy/sr). The continuum is interpolated linearly in wavelength to ${fmt(c.lam.co2, 2)} µm and subtracted.`)}</p>
      <p>{L(`量測（半徑 ${c.aperture_arcsec}″ 的圓，背景取 ${c.annulus_arcsec[0]}–${c.annulus_arcsec[1]}″ 的環）：相減後 ${fmt(c.excess_mjy, 1)} mJy。雜訊（同樣大小的圓放在 32 個空的位置）±${fmt(c.err_noise_mjy, 1)} mJy；但這個數字很依賴哪幾張影像剛好落在波段的哪裡，隨機重抽影像時變動 ±${fmt(c.err_exposures_mjy)} mJy。`, `Measurement (a ${c.aperture_arcsec}″ radius circle, background from the ${c.annulus_arcsec[0]}–${c.annulus_arcsec[1]}″ ring): ${fmt(c.excess_mjy, 1)} mJy after subtraction. Noise (the same circle at 32 empty places): ±${fmt(c.err_noise_mjy, 1)} mJy. But the number depends strongly on where in the band the few images fall: redrawing the images at random moves it by ±${fmt(c.err_exposures_mjy)} mJy.`)}</p>
      {c.line?.flux_w_m2 && <p>{L(`所以我們也把波段內每張影像高出連續光的部分沿波長積分，得到整個波段的亮度 ${c.line.flux_w_m2.toExponential(2)} W/m²（雜訊 ±${c.line.err_w_m2.toExponential(1)}，${c.line.n_band} 張；不含校正誤差和波長取樣的誤差${ep === 'aug' ? '；8 月的影像分散在兩週內，彗星在這段時間變亮' : ''}）。`, `So we also integrate, over wavelength, how far each in-band image stands above the continuum: the whole band gives ${c.line.flux_w_m2.toExponential(2)} W/m² (noise ±${c.line.err_w_m2.toExponential(1)}, ${c.line.n_band} images; calibration and wavelength-sampling errors not included${ep === 'aug' ? '; the August images span two weeks, while the comet brightened' : ''}).`)}</p>}
    </div>
  )
}

function ZoomChart({ e, c }) {
  const sed = e.sed.filter((p) => p.lam >= 3.85 && p.lam <= 4.65)
  const role = (l) => (l >= 4.2 && l <= 4.32 ? 'co2' : (l >= 3.9 && l <= 4.1) || (l >= 4.45 && l <= 4.6) ? 'cont' : 'other')
  const ys = sed.map((p) => p.mjy)
  const top = Math.max(...ys) * 1.12, bot = Math.min(0, Math.min(...ys) * 1.2)
  const pts = sed.map((p) => ({ ...p, x: p.lam, y: p.mjy, r: 7, tip: `${fmt(p.lam, 3)} µm · ${fmt(p.mjy, 1)} mJy`, hint: `${e.frames[p.i]?.iso} UT · D${p.det}` }))
  const cf = c.line?.cont_coef
  return (
    <Plot label={L('二氧化碳波段附近每張影像的亮度', 'Brightness of each image around the CO₂ band')} height={320}
      x={{ domain: [3.85, 4.65], label: L('波長（µm）', 'wavelength (µm)'), ticks: [3.9, 4.0, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6] }}
      y={{ domain: [bot, top], label: 'mJy', ticks: niceTicks(bot, top, 4), fmt: (v) => fmt(v) }} points={pts}>
      {({ X, Y, m, h }) => <>
        <rect x={X(4.2)} width={X(4.32) - X(4.2)} y={m.t} height={h - m.b - m.t} className="cm-band" />
        {[[3.9, 4.1], [4.45, 4.6]].map(([a, b]) => <rect key={a} x={X(a)} width={X(b) - X(a)} y={m.t} height={h - m.b - m.t} className="cm-contband" />)}
        <line x1={X(3.85)} x2={X(4.65)} y1={Y(0)} y2={Y(0)} className="axis" />
        {cf && <line x1={X(3.9)} x2={X(4.6)} y1={Y(cf[0] * 3.9 + cf[1])} y2={Y(cf[0] * 4.6 + cf[1])} stroke={COL.ink3} strokeDasharray="5 4" strokeWidth="1.5" />}
        {pts.map((p, j) => {
          const r = role(p.x)
          return <g key={j}>
            {p.err > 0 && <line x1={X(p.x)} x2={X(p.x)} y1={Y(p.y - p.err)} y2={Y(p.y + p.err)} stroke={COL.ink3} strokeWidth="1.2" />}
            <circle cx={X(p.x)} cy={Y(p.y)} r={r === 'co2' ? 5.5 : 4} fill={r === 'co2' ? CO2C : r === 'cont' ? CONTC : 'none'} stroke={r === 'other' ? COL.ink3 : 'none'} strokeWidth="1.2" />
          </g>
        })}
      </>}
    </Plot>
  )
}

function ProfileChart({ e, c }) {
  const prof = c.profile
  const dust = e.deep.short?.profile
  const x0 = prof[0].excess
  const rows = prof.map((p, j) => ({ r: p.r_arcsec, gas: p.excess / x0, dust: dust ? dust[j] : null })).filter((p) => p.r <= 200)
  const lo = 0.003
  const line = (k, X, Y) => rows.filter((p) => p[k] != null).map((p, j) => `${j ? 'L' : 'M'}${X(p.r).toFixed(1)},${Y(Math.max(lo, p[k])).toFixed(1)}`).join('')
  const pts = rows.flatMap((p) => [
    { x: p.r, y: Math.max(lo, p.gas), tip: L(`二氧化碳：中心的 ${fmt(p.gas * 100, 1)}%`, `CO₂: ${fmt(p.gas * 100, 1)}% of the centre`), hint: `${fmt(p.r)}″` },
    ...(p.dust != null ? [{ x: p.r, y: Math.max(lo, p.dust), tip: L(`塵埃：中心的 ${fmt(p.dust * 100, 1)}%`, `dust: ${fmt(p.dust * 100, 1)}% of the centre`), hint: `${fmt(p.r)}″` }] : []),
  ])
  return (
    <Plot label={L('二氧化碳和塵埃的亮度隨離中心距離的變化', 'Brightness of CO₂ and of dust against distance from the centre')} height={320}
      x={{ domain: [0, 200], label: L('離彗核的距離（角秒）', 'distance from the nucleus (arcsec)'), ticks: [0, 50, 100, 150, 200] }}
      y={{ domain: [lo, 1.2], log: true, label: L('相對於中心', 'relative to the centre'), fmt: (v) => (v >= 0.1 ? `${fmt(v * 100)}%` : `${fmt(v * 100, 1)}%`) }} points={pts}>
      {({ X, Y }) => <>
        {dust && <path d={line('dust', X, Y)} fill="none" stroke={COL.ink2} strokeWidth="2.5" />}
        <path d={line('gas', X, Y)} fill="none" stroke={CO2C} strokeWidth="3" />
      </>}
    </Plot>
  )
}

// ---- two agencies -----------------------------------------------------------------------------------------------
function AgencySection({ d, neo }) {
  const dec = d.facts.epochs.dec, nd = d.facts.neossat_day
  const [neoView, setNeoView] = useState('comet')
  const sx = [
    [L('望遠鏡', 'Telescope'), L('20 公分，在地球軌道上', '20 cm, in Earth orbit')],
    [L('看的光', 'Light'), L('紅外線 0.75–5 µm，102 種顏色', 'infrared 0.75–5 µm, 102 colours')],
    [L('像素', 'Pixel'), '6.2″'],
    [L('日期', 'Dates'), `${dec?.first} – ${dec?.last}`],
  ]
  const nx = neo ? [
    [L('望遠鏡', 'Telescope'), L('15 公分，在地球軌道上', '15 cm, in Earth orbit')],
    [L('看的光', 'Light'), L('可見光', 'visible light')],
    [L('像素', 'Pixel'), `${fmt(neo.pixscale_arcsec, 1)}″`],
    [L('日期', 'Date'), neo.date],
    [L('影像', 'Images'), L(`${neo.n_frames} 張 × ${fmt(neo.exp_s)} 秒`, `${neo.n_frames} × ${fmt(neo.exp_s)} s`)],
  ] : null
  return (
    <Section id="neossat" title={L('同一顆彗星，兩個太空總署', 'One comet, two space agencies')}
      lead={L('加拿大太空總署的 NEOSSat 是第一顆專門找小行星和彗星的太空望遠鏡。它在 12 月 2 日拍了 3I/ATLAS，比 SPHEREx 早一週。', "The Canadian Space Agency's NEOSSat was the first space telescope built to hunt asteroids and comets. It photographed 3I/ATLAS on 2 December, a week before SPHEREx.")}>
      <div className="cm-grid">
        <figure className="chart-card cm-c6 cm-agency">
          <h3>SPHEREx <small>NASA</small></h3>
          <SkyPic src={`${D}/deep_dec_short.webp`} delta={dec?.delta_au} alt={L('SPHEREx 12 月疊加影像', 'SPHEREx December stack')} label="0.75–2.4 µm" />
          <dl className="cm-specs">{sx.map(([a, b]) => <div key={a}><dt>{a}</dt><dd>{b}</dd></div>)}</dl>
        </figure>
        <figure className="chart-card cm-c6 cm-agency">
          <h3>NEOSSat <small>{L('加拿大太空總署', 'Canadian Space Agency')}</small></h3>
          {neo === undefined && <div className="cm-pic cm-pic-empty" />}
          {neo === null && (
            <div className="cm-pic cm-pic-empty cm-placeholder">
              <p>{L('NEOSSat 的疊加影像還在處理中。', 'The NEOSSat stack is still being made.')}</p>
              <p className="cm-note">{nd ? L(`那天彗星在赤經 ${fmt(nd.ra, 2)}°、赤緯 ${fmt(nd.dec, 2)}°，離地球 ${fmt(nd.delta_au, 2)} au；單張 15 秒的影像上看不太出來，要沿著它的路線疊加。`, `That day the comet was at RA ${fmt(nd.ra, 2)}°, Dec ${fmt(nd.dec, 2)}°, ${fmt(nd.delta_au, 2)} au from Earth; it barely shows in a single 15 s image, so the frames must be stacked along its path.`) : null}</p>
            </div>
          )}
          {neo && <>
            <div className="seg cm-neoseg" role="group" aria-label={L('疊加方式', 'How the images are stacked')}>
              <button type="button" aria-pressed={neoView === 'comet'} onClick={() => setNeoView('comet')}>{L('跟著彗星', 'On the comet')}</button>
              <button type="button" aria-pressed={neoView === 'stars'} onClick={() => setNeoView('stars')}>{L('跟著星星', 'On the stars')}</button>
            </div>
            <div className="cm-pic cm-pic-free">
              <img src={`${D}/${neoView === 'comet' ? 'neossat.webp' : 'neossat_stars.webp'}`} alt={neoView === 'comet' ? L('NEOSSat 以彗星為中心疊加', 'NEOSSat stacked on the comet') : L('NEOSSat 以星星對齊疊加', 'NEOSSat stacked on the stars')} />
              {neo.width_arcsec ? <span className="cm-scale" style={{ width: `${Math.min(100, (60 / neo.width_arcsec) * 100)}%` }} aria-hidden="true"><span>1′</span></span> : null}
            </div>
            <dl className="cm-specs">{nx.map(([a, b]) => <div key={a}><dt>{a}</dt><dd>{b}</dd></div>)}</dl>
            <p className="cm-note">{neo.detected ? L(`偵測到彗星（訊噪比約 ${fmt(neo.snr)}）。`, `Comet detected (signal-to-noise about ${fmt(neo.snr)}).`) : L('這次疊加沒有清楚偵測到彗星。', 'This stack does not clearly detect the comet.')} {L(neo.note_zh || '', neo.note_en || '')}</p>
          </>}
        </figure>
      </div>
      <p className="cm-take">{L('兩者互補：NEOSSat 用可見光看塵埃反射的陽光，SPHEREx 用一百多種紅外線顏色，分得出塵埃、冰和不同的氣體。', 'They complement each other: NEOSSat sees sunlight reflected by dust in visible light; SPHEREx, with over a hundred infrared colours, can tell dust, ice and different gases apart.')}</p>
    </Section>
  )
}

// ---- caveats and credits ----------------------------------------------------------------------------------------
function Notes({ d }) {
  const items = [
    L('彗星是延展的天體。IRSA 提醒：不適合用為點光源設計的光譜測光工具量它。這一頁的亮度都是用 25″ 的圓量的，背景取 2–3 角分外的環；彗髮延伸得更遠，所以總亮度略為低估。', 'The comet is extended. IRSA warns that its spectrophotometry tool, made for point sources, is not suitable for it. Brightness on this page is measured in a 25″ circle with the background from a ring 2–3 arcminutes out; the coma reaches farther, so totals are slightly low.'),
    L('很多波長的訊號很弱，尤其 8 月：彗星暗，背景是銀河中心方向擁擠的星空，有些點受到星星污染。', 'Many wavelengths have weak signal, especially in August: the comet was faint against the crowded stars towards the centre of the Milky Way, and some points are contaminated by stars.'),
    L('每張影像只量一個波長，光譜是不同時間的影像拼起來的；彗星在這段時間裡也在變。', 'Each image measures one wavelength, so the spectrum is pieced together from images taken at different times, while the comet itself changed.'),
    L(`彗星位置用 IRSA 表格的預測值。疊加影像中彗星的中心和預測位置差不到 2″（SPHEREx 一個像素是 6.2″）。`, `Comet positions are the predictions in IRSA's table. In the stacks the comet's centre is within 2″ of them (one SPHEREx pixel is 6.2″).`),
    L(`IRSA 的表格指向已停用的 QR2 版本。我們在現行的 DR1 版本找回同樣的曝光：${d.n_table ?? 259} 筆中找到 ${d.n_matched} 筆；${d.n_frames} 張可用（其他的彗星太靠近影像邊緣）。`, `IRSA's table points at the retired QR2 release. We found the same exposures in the current DR1 release: ${d.n_matched} of ${d.n_table ?? 259}; ${d.n_frames} are usable (in the others the comet is too close to the image edge).`),
    L('這不是 SPHEREx 團隊的分析。科學結果請看下面 Lisse 等人的論文。', "This is not the SPHEREx team's analysis. For the science results, see the papers by Lisse et al. below."),
  ]
  return (
    <Section id="notes" title={L('注意事項', 'Caveats')}>
      <ol className="cm-notes">{items.map((t, j) => <li key={j}>{t}</li>)}</ol>
    </Section>
  )
}

function Credits() {
  return (
    <section className="cm-credits" aria-labelledby="cm-h-credits">
      <h2 id="cm-h-credits">{L('資料來源與致謝', 'Data and credits')}</h2>
      <ul>
        <li>{L('SPHEREx 影像：NASA；由加州理工學院 IPAC 的紅外線科學檔案庫（IRSA）提供，DR1 版本。SPHEREx 是噴射推進實驗室與加州理工學院的合作計畫，由 NASA 出資。', 'SPHEREx images: NASA, served by the NASA/IPAC Infrared Science Archive (IRSA, Caltech), DR1 release. SPHEREx is a joint project of the Jet Propulsion Laboratory and Caltech, funded by NASA.')}{' '}
          <a href="https://irsa.ipac.caltech.edu/Missions/spherex.html" target="_blank" rel="noreferrer">IRSA SPHEREx</a> ·{' '}
          <a href="https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/obscore_3I_Atlas.vot" target="_blank" rel="noreferrer">{L('3I/ATLAS 觀測表', '3I/ATLAS observation table')}</a></li>
        <li>{L('SPHEREx 團隊的 3I/ATLAS 論文：', 'SPHEREx team papers on 3I/ATLAS: ')}
          <a href="https://ui.adsabs.harvard.edu/abs/2025RNAAS...9..242L/abstract" target="_blank" rel="noreferrer">Lisse et al., RNAAS 9, 242</a>{L('（8 月，水冰與二氧化碳彗髮）', ' (August: water ice and a CO₂ coma)')} ·{' '}
          <a href="https://ui.adsabs.harvard.edu/abs/2025arXiv251207318L/abstract" target="_blank" rel="noreferrer">Lisse et al. 2025, arXiv:2512.07318</a>{L('（近日點前的 H₂O、CO₂、CO）', ' (pre-perihelion H₂O, CO₂, CO)')} ·{' '}
          <a href="https://ui.adsabs.harvard.edu/abs/2026arXiv260106759L/abstract" target="_blank" rel="noreferrer">Lisse et al. 2026, arXiv:2601.06759</a>{L('（12 月）', ' (December)')}</li>
        <li>{L('位置、距離與軌道：JPL Horizons。', 'Positions, distances and orbit: JPL Horizons.')} <a href="https://ssd.jpl.nasa.gov/horizons/" target="_blank" rel="noreferrer">JPL Horizons</a></li>
        <li>{L('NEOSSat 影像：加拿大太空總署，經加拿大天文資料中心（CADC）取得，依加拿大開放政府授權使用。', 'NEOSSat images: Canadian Space Agency, obtained through the Canadian Astronomy Data Centre (CADC), used under the Open Government Licence – Canada.')}{' '}
          <a href="https://open.canada.ca/en/open-government-licence-canada" target="_blank" rel="noreferrer">{L('授權條款', 'Licence')}</a></li>
        <li>{L('產生方式：', 'Made with ')}<code>scripts/comet_build.py</code>{L('（從 IRSA 下載裁切影像，所有圖都可以重現）。', ' (downloads the cutouts from IRSA; every picture can be remade).')}</li>
      </ul>
    </section>
  )
}
