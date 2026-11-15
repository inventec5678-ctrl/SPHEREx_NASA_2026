// #/follow/<name>[?t0=YYYY-MM-DD&t1=YYYY-MM-DD]: follow one asteroid or comet through every SPHEREx image that caught it.
// IRSA's Moving Object Search Tool (MOST) lists the images and where the object was; the server (web/api_follow.py,
// sxlib/follow.py) cuts each image around that place, measures it, and the page shows: a movie that keeps the object
// in the middle while the stars stream past, its path on the sky, its spectrum (each image samples another wavelength),
// its brightness over time (the spin of an asteroid), how close the prediction was, and how our own pipeline did on
// known asteroids (web/data/validation/follow.json). Without a name: the search box and three ready-made examples.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { DET, L, api, loadImage } from './lib.js'
import { COL, ChartCard, Legend, Plot, extent } from './charts.jsx'
import { usePlayback } from './play.js'
import { PlayBar } from './playbar.jsx'
import { pixelFit, useBoxWidth } from './canvas.js'
import { hashParams } from './sky.js'
import { poll } from './jobs.js'
import './follow.css'

const PIXS = 6.15                      // arcsec per SPHEREx pixel
const pad4 = (n) => String(n).padStart(4, '0')
const fmt = (v, n = 1) => (v == null || !isFinite(v) ? '—' : Number(v).toFixed(n))
const med = (a) => { const s = a.filter(isFinite).sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : NaN }
/** Sunlight's shape in F_nu: a 5,778 K blackbody (sxlib/follow.py sun_fnu). */
const sun = (lam) => lam ** -3 / Math.expm1(14387.77 / (lam * 5778))
const followHash = (q, t0, t1) => {
  const u = new URLSearchParams()
  if (t0) u.set('t0', t0)
  if (t1) u.set('t1', t1)
  return `#/follow/${encodeURIComponent(q)}${u.toString() ? `?${u}` : ''}`
}
const kindText = (k) => (k === 'comet' ? L('彗星', 'comet') : L('小行星', 'asteroid'))

/** t0 / t1 of the address, kept current when only they change (the route's name stays the same). */
function useDates() {
  const read = () => { const u = hashParams(); return [u.get('t0') || null, u.get('t1') || null] }
  const [d, setD] = useState(read)
  useEffect(() => {
    const on = () => setD((p) => { const n = read(); return n[0] === p[0] && n[1] === p[1] ? p : n })
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return d
}

export default function Follow({ q }) {
  useLanguage()
  const [t0, t1] = useDates()
  useEffect(() => { document.title = `SPHEREx Sky Change · ${q || L('跟著一顆小行星', 'Follow an asteroid')}` }, [q])
  return (
    <div className="object fw">
      {q ? <FollowRun q={q} t0={t0} t1={t1} /> : <FollowHome />}
    </div>
  )
}

// ---- the search box -------------------------------------------------------------------------------------------
function FollowForm({ initial = '', compact = false }) {
  const [q, setQ] = useState(initial)
  const [t0, setT0] = useState('')
  const [t1, setT1] = useState('')
  const today = new Date().toISOString().slice(0, 10)
  return (
    <form className={`fw-form ${compact ? 'compact' : ''}`} role="search" aria-label={L('跟著一顆小行星或彗星', 'Follow an asteroid or comet')}
      onSubmit={(e) => { e.preventDefault(); if (q.trim()) location.hash = followHash(q.trim(), t0, t1) }}>
      <label className="sr-only" htmlFor="fw-q">{L('小行星或彗星的名稱', 'Name of an asteroid or comet')}</label>
      <input id="fw-q" type="search" enterKeyHint="go" autoComplete="off" spellCheck="false" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={L('名稱或編號，例如 Ceres、433 Eros、29P、C/2025 A6', 'Name or number, e.g. Ceres, 433 Eros, 29P, C/2025 A6')} />
      <button className="btn primary" type="submit">{L('跟著它', 'Follow it')}</button>
      {!compact && (
        <details className="fw-dates">
          <summary>{L('只看某段日期', 'Only some dates')}</summary>
          <label>{L('從', 'From')} <input type="date" min="2025-04-24" max={today} value={t0} onChange={(e) => setT0(e.target.value)} /></label>
          <label>{L('到', 'To')} <input type="date" min="2025-04-24" max={today} value={t1} onChange={(e) => setT1(e.target.value)} /></label>
        </details>
      )}
    </form>
  )
}

// ---- no name: examples ------------------------------------------------------------------------------------------
const NOTES = {
  cybele: ['這片天空我們做過完整分析，下面的驗證就是用它。', 'Our fully analysed field: the check below uses it.'],
  nea: ['會接近地球的小行星，2026 年 2 月離地球約 0.45 天文單位。', 'A near-Earth asteroid, about 0.45 AU from Earth in February 2026.'],
  comet: ['2025 年秋天的亮彗星。', 'The bright comet of autumn 2025.'],
}

function FollowCard({ c }) {
  const href = followHash(c.short || c.name, c.t0, c.t1)
  return (
    <a className="fw-card" href={href}>
      <span className="fw-card-img">
        {c.thumb && <img src={c.thumb} alt="" loading="lazy" width="196" height="196" />}
        {c.stack && <img className="fw-card-stack" src={c.stack} alt="" loading="lazy" width="196" height="196" />}
      </span>
      <span className="fw-card-body">
        <strong>{c.short || c.name}</strong>
        <span className="tag known">{kindText(c.kind)}</span>
        <span className="fw-card-meta num">{L(`${c.n} 張影像`, `${c.n} images`)} · {(c.first || '').slice(0, 10)} – {(c.last || '').slice(0, 10)}</span>
        {c.note && NOTES[c.note] && <span className="fw-card-note">{L(...NOTES[c.note])}</span>}
        {c.period_h && <span className="fw-card-note good">{L(`從亮度變化量出自轉週期 ${c.period_h} 小時`, `Spin of ${c.period_h} h found in its brightness`)}</span>}
      </span>
    </a>
  )
}

function FollowHome() {
  const [list, setList] = useState(null)
  useEffect(() => { api('/api/follow/list').then(setList).catch(() => setList({ showcase: [], recent: [], err: true })) }, [])
  return (
    <>
      <header className="fw-head">
        <h1>{L('跟著一顆小行星或彗星', 'Follow an asteroid or comet')}</h1>
        <p className="lead">{L('輸入名稱，就能看到 SPHEREx 每一張拍到它的影像：它留在畫面中間，背景的星星流過去。每張影像拍的波長都不同，合起來就是它的光譜。', 'Type a name to see every SPHEREx image that caught it: it stays in the middle while the stars stream past. Each image records a different wavelength, so together they make its spectrum.')}</p>
      </header>
      <FollowForm />
      <p className="hint">{L('NASA/IPAC IRSA 的移動天體搜尋工具（MOST）找出拍到它的影像，下載和量測約 1 到 3 分鐘，畫面會邊下載邊播放。', 'IRSA’s Moving Object Search Tool (MOST) finds the images; downloading and measuring take about 1 to 3 minutes, and frames play as they arrive.')}</p>
      <h2 className="fw-h2">{L('現成的例子', 'Ready-made examples')}</h2>
      {!list && <div className="route-loading" role="status"><i aria-hidden="true" /><span>{L('載入中…', 'Loading…')}</span></div>}
      {list && <div className="fw-cards">{list.showcase.map((c) => <FollowCard key={c.slug} c={c} />)}</div>}
      {list?.recent?.length > 0 && <>
        <h2 className="fw-h2">{L('其他人最近跟過的', 'Recently followed by others')}</h2>
        <div className="fw-cards small">{list.recent.map((c) => <FollowCard key={c.slug} c={c} />)}</div>
      </>}
      <FollowCheck />
      <Credits />
    </>
  )
}

// ---- one object -------------------------------------------------------------------------------------------------
function FollowRun({ q, t0, t1 }) {
  const [st, setSt] = useState({ s: 'start' })
  const [doc, setDoc] = useState(null)
  useEffect(() => {
    let live = true, stop = () => {}
    setSt({ s: 'start' }); setDoc(null)
    api('/api/follow', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q, t0, t1 }) })
      .then((r) => {
        if (!live) return
        if (r.status === 'ambiguous') { setSt({ s: 'ambiguous', choices: r.choices || [] }); return }
        setSt({ s: 'job', slug: r.slug })
        stop = poll(`/api/follow/job/${r.slug}`, {
          every: 2000,
          onUpdate: (d) => live && setDoc(d),
          done: (d) => d.status === 'done' || d.status === 'error',
          onMissing: () => live && setSt({ s: 'err' }),
        })
      })
      .catch((e) => {
        const m = String(e)
        if (live) setSt({ s: m.includes('404') ? 'unknown' : m.includes('429') ? 'busy' : m.includes('422') ? 'bad' : m.includes('507') ? 'disk' : 'err' })
      })
    return () => { live = false; stop() }
  }, [q, t0, t1])

  if (st.s === 'start' || (st.s === 'job' && !doc)) return <div className="route-loading" role="status"><i aria-hidden="true" /><span>{L(`查詢「${q}」…`, `Looking up “${q}”…`)}</span></div>
  if (st.s !== 'job') return <Problem q={q} st={st} />
  if (doc.status === 'error') return <Problem q={q} st={{ s: doc.error === 'ambiguous' ? 'ambiguous' : doc.error || 'err', choices: doc.choices }} />
  return <Result doc={doc} />
}

function Problem({ q, st }) {
  const msg = {
    ambiguous: [L(`「${q}」有好幾個天體`, `Several objects are called “${q}”`), L('選一個：', 'Pick one:')],
    unknown: [L(`JPL 不認得「${q}」`, `JPL does not know “${q}”`), L('JPL 小天體資料庫裡沒有這個名稱的小行星或彗星。檢查拼字，或改用編號（例如 433）或暫定編號（例如 2024 YR4）。', 'JPL’s Small-Body Database has no asteroid or comet of that name. Check the spelling, or use its number (e.g. 433) or designation (e.g. 2024 YR4).')],
    bad: [L('看不懂這個名稱', 'Could not read that name'), L('名稱只能有字母、數字、空格和 / ( ) - 等符號。', 'Use letters, digits, spaces and / ( ) - only.')],
    busy: [L('伺服器正在忙', 'The server is busy'), L('同時最多跑兩個，每人每天最多六個。請過幾分鐘再試。', 'At most two run at once, and six per person per day. Try again in a few minutes.')],
    disk: [L('伺服器空間不足', 'The server is short of disk space'), L('暫時無法開始新的。', 'New ones cannot start for now.')],
    no_images: [L(`SPHEREx 沒有拍到「${q}」`, `SPHEREx has no images of “${q}”`), L('MOST 在這段期間找不到拍到它的 SPHEREx 影像。試試別的日期，或不要限定日期。', 'MOST found no SPHEREx image of it in this period. Try other dates, or none.')],
    most_down: [L('IRSA 的 MOST 暫時連不上', 'IRSA’s MOST cannot be reached right now'), L('請稍後再試。', 'Please try again in a moment.')],
    stalled: [L('中斷了', 'It stopped'), L('重新整理頁面可以再試一次。', 'Reload the page to try again.')],
  }[st.s] || [L('出了點問題', 'Something went wrong'), L('請稍後再試。', 'Please try again in a moment.')]
  return (
    <>
      <header className="fw-head"><h1>{msg[0]}</h1><p className="lead">{msg[1]}</p></header>
      {st.s === 'ambiguous' && <div className="fw-choices">{(st.choices || []).map((c) => <a key={c} className="chip" href={followHash(c)}>{c}</a>)}</div>}
      <FollowForm initial={st.s === 'ambiguous' ? '' : q} compact />
      <p className="hint"><a href="#/follow">{L('← 看現成的例子', '← See the ready-made examples')}</a></p>
    </>
  )
}

function Facts({ doc }) {
  const fr = doc.frames || [], ph = doc.phys || {}
  const d = fr.map((f) => f.d_au).filter(isFinite), r = fr.map((f) => f.r_au).filter(isFinite)
  const items = [
    [L('拍到它的影像', 'Images of it'), `${doc.n_done ?? fr.length}`, doc.n_most > doc.n_total ? L(`MOST 共列出 ${doc.n_most} 張，平均抽 ${doc.n_total} 張`, `of ${doc.n_most} MOST lists, ${doc.n_total} sampled evenly`) : L(`MOST 列出 ${doc.n_most || '—'} 張`, `MOST lists ${doc.n_most || '—'}`)],
    [L('日期', 'Dates'), `${(doc.first || '').slice(0, 10)}`, `→ ${(doc.last || '').slice(0, 10)}`],
    d.length ? [L('離 SPHEREx', 'From SPHEREx'), `${fmt(Math.min(...d), 2)}–${fmt(Math.max(...d), 2)} AU`, r.length ? L(`離太陽 ${fmt(Math.min(...r), 2)}–${fmt(Math.max(...r), 2)} AU`, `${fmt(Math.min(...r), 2)}–${fmt(Math.max(...r), 2)} AU from the Sun`) : ''] : null,
    ph.diam_km ? [L('直徑（JPL）', 'Diameter (JPL)'), `${fmt(ph.diam_km, ph.diam_km < 10 ? 1 : 0)} km`, ph.albedo ? L(`反照率 ${Math.round(ph.albedo * 100)}%`, `albedo ${Math.round(ph.albedo * 100)}%`) : ''] : null,
    ph.rot_h ? [L('自轉（JPL）', 'Spin (JPL)'), L(`${ph.rot_h} 小時`, `${ph.rot_h} h`), ph.smass || ph.tholen ? L(`光譜類型 ${ph.smass || ph.tholen}`, `spectral type ${ph.smass || ph.tholen}`) : ''] : null,
  ].filter(Boolean)
  return <dl className="fw-facts">{items.map(([k, v, s]) => <div key={k}><dt>{k}</dt><dd className="num">{v}</dd>{s && <dd className="fw-sub">{s}</dd>}</div>)}</dl>
}

function Result({ doc }) {
  const frames = doc.frames || []
  const run = Math.floor(doc.started || 0)
  const url = (f) => `/data/follow/${doc.slug}/f/${pad4(f.f)}.webp?r=${run}`
  const [fps, setFps] = useState(6)
  const pb = usePlayback(frames.length, { hz: fps })
  const cur = frames[pb.k]
  const running = doc.status !== 'done'
  const prog = doc.n_total ? (doc.n_done + (doc.n_failed || 0)) / doc.n_total : 0
  return (
    <>
      <header className="fw-head">
        <p className="fw-kicker"><a href="#/follow">{L('跟著一顆小行星', 'Follow an asteroid')}</a> / <span className="tag known">{kindText(doc.kind)}</span></p>
        <h1>{doc.short || doc.name}</h1>
        <p className="lead">{L(`SPHEREx 每一張拍到 ${doc.short || doc.name} 的影像，都以 JPL 預測的位置為中心：它一直在十字中間，背景的星星流過去。`, `Every SPHEREx image of ${doc.short || doc.name}, centred where JPL predicts it: it stays inside the cross while the background stars stream past.`)}</p>
      </header>
      {running && (
        <div className="qp-progress fw-progress" role="status" aria-live="polite">
          <div className="qp-bar"><i style={{ width: `${Math.round(prog * 100)}%` }} /></div>
          <span>{doc.status === 'searching' ? L('向 IRSA 的 MOST 查詢哪些影像拍到它…', 'Asking IRSA’s MOST which images caught it…')
            : L(`已量好 ${doc.n_done} / ${doc.n_total} 張，邊下載邊播放`, `${doc.n_done} of ${doc.n_total} images measured; playing while the rest arrive`)}</span>
        </div>
      )}
      <Facts doc={doc} />
      <div className="fw-stage">
        <FollowPlayer frames={frames} url={url} pb={pb} npix={doc.npix || 49} fps={fps} setFps={setFps} />
        <div className="fw-side">
          <PathChart doc={doc} cur={cur} onPick={(j) => pb.seek(j)} />
          {doc.stack && <figure className="fw-stack">
            <img src={`/data/follow/${doc.slug}/stack.webp?r=${run}`} alt={L('所有影像以它為中心疊在一起', 'All images stacked on the object')} width="196" height="196" />
            <figcaption>{L(`${doc.stack} 張影像以它為中心疊起來：星星每張都在不同位置，疊加後就消失了，只剩下它。`, `${doc.stack} images stacked on the object: the stars sit somewhere else in every frame and vanish; only it remains.`)}</figcaption>
          </figure>}
        </div>
      </div>
      {frames.length >= 3 && <div className="fw-charts">
        <Spectrum doc={doc} cur={cur} onPick={(j) => pb.seek(j)} />
        {doc.kind === 'comet' ? <CometCurve doc={doc} cur={cur} onPick={(j) => pb.seek(j)} /> : <LightCurve doc={doc} cur={cur} onPick={(j) => pb.seek(j)} />}
        <PositionCheck doc={doc} cur={cur} onPick={(j) => pb.seek(j)} />
      </div>}
      <FollowCheck compact />
      <h2 className="fw-h2">{L('跟另一顆', 'Follow another')}</h2>
      <FollowForm compact />
      <Credits />
    </>
  )
}

// ---- the movie ----------------------------------------------------------------------------------------------------
function FollowPlayer({ frames, url, pb, npix, fps, setFps }) {
  const box = useRef(), cv = useRef()
  const bw = useBoxWidth(box)
  const fit = useMemo(() => pixelFit(Math.min(bw || 520, 620), npix), [bw, npix])
  const cur = frames[pb.k]
  useEffect(() => { for (let j = 1; j <= 8 && frames.length; j++) loadImage(url(frames[(pb.k + j) % frames.length])) }, [pb.k, frames]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const c = cv.current
    if (!c || !cur) return
    let live = true
    loadImage(url(cur), (im) => {
      if (!live || !im) return
      const { W, s, off, u } = fit
      if (c.width !== W || c.height !== W) { c.width = W; c.height = W }
      const g = c.getContext('2d')
      g.imageSmoothingEnabled = false
      g.fillStyle = '#000'; g.fillRect(0, 0, W, W)
      g.drawImage(im, 0, 0, im.width, im.height, off, off, npix * s, npix * s)
      // four ticks around the predicted place, leaving the object itself uncovered
      const m = off + (npix * s) / 2, a = Math.max(2.4 * s, 12 * u), b = a + 16 * u
      g.strokeStyle = 'rgba(242,230,201,.9)'; g.lineWidth = 2 * u
      g.beginPath()
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { g.moveTo(m + dx * a, m + dy * a); g.lineTo(m + dx * b, m + dy * b) }
      g.stroke()
    })
    return () => { live = false }
  }, [cur, fit]) // eslint-disable-line react-hooks/exhaustive-deps
  const bar = (60 / PIXS) * fit.s / fit.u
  return (
    <div className="fw-player" ref={box} tabIndex={0} onKeyDown={(e) => pb.onKey(e)} role="group"
      aria-label={L('影片：它留在中間，星星流過。空白鍵播放或暫停，左右鍵逐張。', 'Movie: the object stays in the middle while stars stream past. Space plays or pauses; arrows step.')}>
      <div className="fw-canvas" style={{ width: fit.css }}>
        <canvas ref={cv} style={{ width: fit.css, height: fit.css }} role="img" aria-label={L('以它為中心的 SPHEREx 影像', 'SPHEREx image centred on it')} />
        {!cur && <div className="route-loading lab-loading" role="status"><i aria-hidden="true" /><span>{L('等第一張影像…', 'Waiting for the first image…')}</span></div>}
        {cur && <span className="lab-badge num">{cur.iso} UTC · <b style={{ color: DET[cur.det]?.c }}>D{cur.det}</b> · {cur.lam.toFixed(2)} µm</span>}
        {cur && <span className="lab-scale" aria-hidden="true"><i style={{ width: bar }} />1′</span>}
        <span className="fw-compass" aria-hidden="true">{L('上北 · 左東', 'N up · E left')}</span>
      </div>
      <PlayBar pb={pb} n={frames.length} label={L('播放', 'Playback')} speeds={[3, 6, 12]} hz={fps} setHz={setFps} />
    </div>
  )
}

// ---- where it went ------------------------------------------------------------------------------------------------
function PathChart({ doc, cur, onPick }) {
  const frames = doc.frames || [], path = doc.path || []
  const ra0 = path[0]?.[1] ?? frames[0]?.ra ?? 0
  const un = (ra) => (ra - ra0 > 180 ? ra - 360 : ra - ra0 < -180 ? ra + 360 : ra)
  const pts = frames.map((f, j) => ({ x: un(f.ra), y: f.dec, r: 7, j, tip: `${f.iso} UTC`, hint: L('點一下：影片跳到這一張', 'Click: show it in the movie') }))
  const all = [...path.map((p) => [un(p[1]), p[2]]), ...pts.map((p) => [p.x, p.y])]
  if (all.length < 2) return null
  const xd = extent(all.map((p) => p[0]), 0.1), yd = extent(all.map((p) => p[1]), 0.1)
  const last = path.at(-1), prev = path.at(-2)
  const span = Math.hypot((xd[1] - xd[0]) * Math.cos((yd[0] + yd[1]) * Math.PI / 360), yd[1] - yd[0])
  return (
    <ChartCard level={3} title={L('它在天空走過的路', 'Its path across the sky')}
      take={L(`這段期間它在天空移動了約 ${fmt(span, span < 1 ? 2 : 0)}°；點是影片裡的影像。`, `It moved about ${fmt(span, span < 1 ? 2 : 0)}° across the sky; the dots are the images in the movie.`)}>
      <Plot height={250} equal points={pts} onPick={(p) => onPick(p.j)} label={L('天空路徑', 'Sky path')}
        x={{ domain: xd, reverse: true, fmt: (v) => `${((v + ra0 + 360) % 360).toFixed(xd[1] - xd[0] < 2 ? 1 : 0)}°`, label: L('赤經（東在左）', 'RA (east to the left)') }}
        y={{ domain: yd, fmt: (v) => `${v.toFixed(yd[1] - yd[0] < 2 ? 1 : 0)}°`, label: L('赤緯', 'Dec') }}>
        {({ X, Y }) => <>
          <polyline points={path.map((p) => `${X(un(p[1]))},${Y(p[2])}`).join(' ')} fill="none" stroke={COL.ink3} strokeOpacity=".55" strokeWidth="1.5" />
          {pts.map((p) => <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="3" fill={COL.accent} fillOpacity=".75" />)}
          {last && prev && <circle cx={X(un(last[1]))} cy={Y(last[2])} r="4" fill={COL.ink} />}
          {cur && <circle cx={X(un(cur.ra))} cy={Y(cur.dec)} r="8" fill="none" stroke={COL.ink} strokeWidth="2" />}
        </>}
      </Plot>
    </ChartCard>
  )
}

// ---- spectrum ------------------------------------------------------------------------------------------------------
function Spectrum({ doc, cur, onPick }) {
  const [mode, setMode] = useState('refl')
  const fr = (doc.frames || []).map((f, j) => ({ ...f, j })).filter((f) => f.flux > 0 && f.snr >= 5)
  const ref = fr.filter((f) => !f.sat && f.lam >= 0.85 && f.lam <= 1.3)
  const k = med((ref.length >= 3 ? ref : fr.filter((f) => !f.sat && f.lam < 1.7)).map((f) => f.flux / sun(f.lam)))
  if (fr.length < 3 || !isFinite(k)) return null
  const R = (f) => f.flux / (k * sun(f.lam))
  const refl = mode === 'refl'
  const val = (f) => (refl ? R(f) : f.flux / 1000)
  const yv = fr.map(val)
  // relative to sunlight: a linear scale, or a log one when its own heat makes it many times brighter at 4-5 µm
  const rmax = Math.max(1.6, ...fr.filter((f) => !f.sat).map(R)), rlog = refl && rmax > 4
  const yd = refl ? (rlog ? [Math.max(0.1, Math.min(...fr.map(R)) * 0.8), Math.min(100, rmax * 1.25)] : [0, rmax * 1.08]) : extent(yv, 0.15, true)
  const pts = fr.map((f) => ({ x: f.lam, y: refl ? Math.min(Math.max(val(f), yd[0]), yd[1]) : val(f), r: 7, j: f.j,
    tip: `${f.lam.toFixed(2)} µm · ${refl ? R(f).toFixed(2) : `${fmt(f.flux / 1000, 1)} mJy`}`, hint: `${f.iso} UTC · D${f.det}${f.sat ? L(' · 飽和', ' · saturated') : ''}` }))
  const hot = fr.filter((f) => f.lam >= 4.2 && !f.sat).map(R), warm = med(hot)
  const take = doc.kind === 'comet'
    ? L('彗星是一團氣體和塵埃，這裡量的是中心 12″ 內的亮度；4.26 µm 附近是二氧化碳的波段。', 'A comet is a cloud of gas and dust; this is the light within 12″ of its centre. Carbon dioxide glows near 4.26 µm.')
    : warm > 1.6 ? L(`4 µm 以上比反射的陽光亮 ${fmt(warm, 1)} 倍：它被太陽曬熱，自己在發熱光。`, `Above 4 µm it is ${fmt(warm, 1)} times brighter than reflected sunlight: the Sun has warmed it and it glows with its own heat.`)
      : L('各波長的亮度和反射的陽光差不多：顏色接近陽光，稍微偏紅或偏藍就是表面成分的線索。', 'Its brightness follows reflected sunlight: its colour is close to the Sun’s, and a slight tilt to red or blue is a clue to its surface.')
  const cj = cur ? fr.find((f) => f.mjd === cur.mjd && f.det === cur.det) : null
  return (
    <ChartCard level={3} title={L('它的光譜：每張影像一個波長', 'Its spectrum: one wavelength per image')} take={take}
      legend={[...[1, 2, 3, 4, 5, 6].filter((d) => fr.some((f) => f.det === d)).map((d) => ({ c: COL.det[d - 1], label: `D${d}` })),
        ...(fr.some((f) => f.sat) ? [{ c: COL.ink3, hollow: true, label: L('飽和，不可靠', 'saturated, unreliable') }] : []),
        { c: COL.ink3, line: true, label: L('反射的陽光', 'reflected sunlight') }]}
      more={<p>{L(`SPHEREx 沒有濾鏡輪：同一顆天體落在偵測器的不同位置，就拍到不同的波長。每一點是一張影像在它預測位置的強制測光（半徑 12″，不含孔徑修正）。「相對陽光」是除以 5,778 K 黑體的太陽光譜，並把 0.85–1.3 µm 的中位數設為 1。不同時間的點也受自轉影響，所以會上下散開。`, `SPHEREx has no filter wheel: where the object lands on the detector sets the wavelength it records. Each dot is forced photometry at the predicted position in one image (12″ radius, no aperture correction). "Relative to sunlight" divides by the Sun as a 5,778 K blackbody, with the median at 0.85–1.3 µm set to 1. Points from different times also differ by the spin, hence the scatter.`)}</p>}>
      <div className="seg fw-seg" role="group" aria-label={L('顯示', 'Show')}>
        <button aria-pressed={refl} onClick={() => setMode('refl')}>{L('相對陽光', 'Relative to sunlight')}</button>
        <button aria-pressed={!refl} onClick={() => setMode('flux')}>{L('亮度（mJy）', 'Brightness (mJy)')}</button>
      </div>
      <Plot height={280} points={pts} onPick={(p) => onPick(p.j)} label={L('光譜', 'Spectrum')}
        x={{ domain: [0.7, 5.15], ticks: [1, 2, 3, 4, 5], fmt: (v) => `${v}`, label: L('波長（µm）', 'Wavelength (µm)') }}
        y={refl ? { domain: yd, log: rlog, ticks: rlog ? [0.2, 0.5, 1, 2, 5, 10, 20, 50].filter((v) => v >= yd[0] && v <= yd[1]) : undefined, fmt: (v) => (!rlog ? v.toFixed(1) : v >= 2 ? v.toFixed(0) : `${v}`), label: L('相對陽光', 'Relative to sunlight'), gutter: 40 }
          : { domain: yd, log: true, fmt: (v) => (v >= 10 ? Math.round(v) : v.toFixed(1)), label: 'mJy', gutter: 46 }}>
        {({ X, Y }) => {
          const curve = []
          for (let l = 0.7; l <= 5.15; l += 0.05) curve.push(`${X(l)},${Y(refl ? 1 : (k * sun(l)) / 1000)}`)
          return <>
            <polyline points={curve.join(' ')} fill="none" stroke={COL.ink3} strokeDasharray="5 4" strokeWidth="1.5" />
            {pts.map((p, i) => { const f = fr[i]; return f.sat
              ? <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="4" fill="none" stroke={COL.ink3} strokeWidth="1.5" />
              : <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="4" fill={COL.det[f.det - 1]} fillOpacity=".85" /> })}
            {cj && <circle cx={X(cj.lam)} cy={Y(refl ? Math.min(Math.max(val(cj), yd[0]), yd[1]) : val(cj))} r="8" fill="none" stroke={COL.ink} strokeWidth="2" />}
          </>
        }}
      </Plot>
    </ChartCard>
  )
}

// ---- spin ------------------------------------------------------------------------------------------------------------
function LightCurve({ doc, cur, onPick }) {
  const lc = doc.lc || {}
  const P = lc.period_h
  const [fold, setFold] = useState(true)
  const fr = (doc.frames || []).map((f, j) => ({ ...f, j })).filter((f) => f.rel != null && !f.clip)
  if (fr.length < 8) {
    return doc.status === 'done' ? null : <ChartCard level={3} title={L('它的亮度變化', 'How its brightness changes')} take={L('影像都到了以後才算。', 'Worked out once every image is in.')} />
  }
  const t0 = Math.min(...fr.map((f) => f.mjd))
  const folded = P && fold
  const xOf = (f) => (folded ? (((f.mjd - t0) * 24) / P) % 1 : f.mjd - t0)
  const pct = (f) => 100 * (10 ** (-0.4 * f.rel) - 1)
  const yd = extent(fr.map(pct), 0.12)
  const pts = fr.map((f) => ({ x: xOf(f), y: pct(f), r: 7, j: f.j, tip: `${pct(f) >= 0 ? '+' : ''}${pct(f).toFixed(0)}%`, hint: `${f.iso} UTC · ${f.lam.toFixed(2)} µm` }))
  const ph = doc.phys || {}
  const take = P
    ? L(`每轉一圈亮暗兩次，量到一圈 ${P} 小時${ph.rot_h ? `；JPL 的資料是 ${ph.rot_h} 小時` : ''}。它不是圓球，轉到長邊對著我們時比較亮。`, `It brightens and fades twice per turn; we measure one turn as ${P} h${ph.rot_h ? ` (JPL lists ${ph.rot_h} h)` : ''}. It is not round: it looks brighter when its long side faces us.`)
    : L(`扣掉顏色和距離的影響後，亮度只變化約 ±${Math.round(100 * (lc.rms_mag || 0) / 1.0857)}%，這些影像看不出明確的自轉週期${ph.rot_h ? `（JPL 的資料是 ${ph.rot_h} 小時）` : ''}。`, `After removing its colour and the change in distance, its brightness varies by only about ±${Math.round(100 * (lc.rms_mag || 0) / 1.0857)}%; these images show no clear spin period${ph.rot_h ? ` (JPL lists ${ph.rot_h} h)` : ''}.`)
  const cj = cur ? fr.find((f) => f.mjd === cur.mjd && f.det === cur.det) : null
  const known = lc.known
  return (
    <ChartCard level={3} title={L('它的自轉：亮度隨時間變化', 'Its spin: brightness over time')} take={take}
      more={<p>{L(`每張影像的亮度先除以 (日距 × 地距)²，再除以同波長附近其他影像的中位數，剩下的就是自轉造成的變化。用 Lomb-Scargle 週期圖找 2 到 48 小時的重複；小行星每轉一圈通常亮暗兩次，所以自轉週期是最強重複的兩倍。只有誤報機率低於 1% 才算找到（這次最強的重複在 ${fmt(lc.peak_h, 2)} 小時，誤報機率 ${lc.fap != null ? (lc.fap < 1e-4 ? '< 0.01%' : `${fmt(100 * lc.fap, 1)}%`) : '—'}）。${known ? `在 JPL 的週期 ${known.rot_h} 小時的一半檢查，誤報機率 ${known.fap < 1e-4 ? '< 0.01%' : `${fmt(100 * known.fap, 1)}%`}。` : ''}`, `Each image’s brightness is divided by (Sun distance × SPHEREx distance)², then by the median of other images near the same wavelength; what is left is the change from the spin. A Lomb-Scargle periodogram looks for repeats between 2 and 48 hours; an asteroid usually brightens twice per turn, so the spin is twice the strongest repeat. Only a false-alarm chance below 1% counts as found (here the strongest repeat is at ${fmt(lc.peak_h, 2)} h, false-alarm chance ${lc.fap != null ? (lc.fap < 1e-4 ? '< 0.01%' : `${fmt(100 * lc.fap, 1)}%`) : '—'}).${known ? ` Tested at half of JPL’s ${known.rot_h} h: false-alarm chance ${known.fap < 1e-4 ? '< 0.01%' : `${fmt(100 * known.fap, 1)}%`}.` : ''}`)}</p>}>
      {P && <div className="seg fw-seg" role="group" aria-label={L('橫軸', 'Across')}>
        <button aria-pressed={fold} onClick={() => setFold(true)}>{L(`疊成一圈（${P} 小時）`, `Folded on one turn (${P} h)`)}</button>
        <button aria-pressed={!fold} onClick={() => setFold(false)}>{L('依時間', 'In time order')}</button>
      </div>}
      <Plot height={260} points={pts} onPick={(p) => onPick(p.j)} label={L('亮度變化', 'Brightness change')}
        x={folded ? { domain: [0, 1], ticks: [0, 0.25, 0.5, 0.75, 1], fmt: (v) => `${Math.round(v * P * 10) / 10}`, label: L('轉了多久（小時）', 'Time into the turn (hours)') }
          : { domain: extent(pts.map((p) => p.x), 0.03), label: L('第一張之後的天數', 'Days after the first image') }}
        y={{ domain: yd, fmt: (v) => `${v > 0 ? '+' : ''}${Math.round(v)}%`, label: L('比平均亮', 'Brighter than average'), gutter: 50 }}>
        {({ X, Y }) => <>
          <line className="grid" x1={X(folded ? 0 : pts[0].x)} x2={X(folded ? 1 : Math.max(...pts.map((p) => p.x)))} y1={Y(0)} y2={Y(0)} stroke={COL.ink3} />
          {pts.map((p, i) => <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="3.6" fill={COL.det[fr[i].det - 1]} fillOpacity=".85" />)}
          {cj && <circle cx={X(xOf(cj))} cy={Y(pct(cj))} r="8" fill="none" stroke={COL.ink} strokeWidth="2" />}
        </>}
      </Plot>
      {lc.pgram?.length > 10 && <Periodogram lc={lc} />}
    </ChartCard>
  )
}

function Periodogram({ lc }) {
  const pts = lc.pgram.map(([p, w]) => ({ x: p, y: w })).sort((a, b) => a.x - b.x)
  const top = Math.max(...pts.map((p) => p.y))
  return (
    <div className="fw-pgram">
      <p className="hint">{L('週期圖：越高代表越像在重複；標記是 JPL 自轉週期的一半。', 'Periodogram: higher means more like a repeat; the mark is half of JPL’s spin period.')}</p>
      <Plot height={130} label={L('週期圖', 'Periodogram')}
        x={{ domain: [2, 48], log: true, ticks: [2, 3, 5, 10, 20, 48], fmt: (v) => `${v} h` }}
        y={{ domain: [0, top * 1.1], ticks: [0, Math.round(top * 100) / 100], fmt: (v) => v.toFixed(2), gutter: 40 }}>
        {({ X, Y }) => <>
          <polyline points={pts.map((p) => `${X(p.x)},${Y(p.y)}`).join(' ')} fill="none" stroke={COL.known} strokeWidth="1.5" />
          {lc.known?.rot_h && <line x1={X(lc.known.rot_h / 2)} x2={X(lc.known.rot_h / 2)} y1={Y(0)} y2={Y(top * 1.05)} stroke={COL.good} strokeDasharray="4 3" strokeWidth="2" />}
        </>}
      </Plot>
    </div>
  )
}

function CometCurve({ doc, cur, onPick }) {
  const fr = (doc.frames || []).map((f, j) => ({ ...f, j })).filter((f) => f.flux > 0 && f.snr >= 5 && !f.sat && f.lam < 2.5)
  if (fr.length < 5) return null
  const t0 = Math.min(...fr.map((f) => f.mjd))
  const pts = fr.map((f) => ({ x: f.mjd - t0, y: f.flux / 1000, r: 7, j: f.j, tip: `${fmt(f.flux / 1000, 1)} mJy`, hint: `${f.iso} UTC · ${f.lam.toFixed(2)} µm · ${fmt(f.r_au, 2)} AU` }))
  const cj = cur ? fr.find((f) => f.mjd === cur.mjd && f.det === cur.det) : null
  return (
    <ChartCard level={3} title={L('它的亮度隨時間變化', 'Its brightness over time')}
      take={L(`這裡只畫 2.5 µm 以下（主要是反射的陽光）。離太陽從 ${fmt(Math.min(...fr.map((f) => f.r_au)), 1)} 到 ${fmt(Math.max(...fr.map((f) => f.r_au)), 1)} AU，彗星噴發的塵埃越少，就越暗。`, `Only below 2.5 µm (mostly reflected sunlight). From ${fmt(Math.min(...fr.map((f) => f.r_au)), 1)} to ${fmt(Math.max(...fr.map((f) => f.r_au)), 1)} AU from the Sun: the less dust it sheds, the fainter it gets.`)}>
      <Plot height={260} points={pts} onPick={(p) => onPick(p.j)} label={L('亮度隨時間', 'Brightness over time')}
        x={{ domain: extent(pts.map((p) => p.x), 0.03), label: L('第一張之後的天數', 'Days after the first image') }}
        y={{ domain: extent(pts.map((p) => p.y), 0.15, true), log: true, fmt: (v) => (v >= 10 ? Math.round(v) : v.toFixed(1)), label: 'mJy', gutter: 46 }}>
        {({ X, Y }) => <>
          {pts.map((p, i) => <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="3.6" fill={COL.det[fr[i].det - 1]} fillOpacity=".85" />)}
          {cj && <circle cx={X(cj.mjd - t0)} cy={Y(cj.flux / 1000)} r="8" fill="none" stroke={COL.ink} strokeWidth="2" />}
        </>}
      </Plot>
    </ChartCard>
  )
}

// ---- how close the prediction was ---------------------------------------------------------------------------------
function PositionCheck({ doc, cur, onPick }) {
  const fr = (doc.frames || []).map((f, j) => ({ ...f, j })).filter((f) => f.dra != null)
  if (fr.length < 3) return null
  const d = fr.map((f) => Math.hypot(f.dra, f.ddec)), m = med(d)
  const lim = Math.max(PIXS * 1.15, ...d.map((v) => Math.min(v, 15))) * 1.05
  const pts = fr.map((f) => ({ x: f.dra, y: f.ddec, r: 7, j: f.j, tip: `${fmt(Math.hypot(f.dra, f.ddec), 2)}″`, hint: `${f.iso} UTC · D${f.det}` }))
  const cj = cur ? fr.find((f) => f.mjd === cur.mjd && f.det === cur.det) : null
  return (
    <ChartCard level={3} title={L('預測準不準？', 'Was the prediction right?')}
      take={L(`在 ${fr.length} 張夠亮的影像裡，它的光心和 JPL 預測的位置中位數只差 ${fmt(m, 2)}″，不到一個 SPHEREx 像素（大圈，6.15″）的${m < 1.5 ? '四分之一' : '一半'}。`, `In ${fr.length} images where it is bright enough, its centre of light sits a median ${fmt(m, 2)}″ from JPL’s prediction: under a ${m < 1.5 ? 'quarter' : 'half'} of one SPHEREx pixel (big circle, 6.15″).`)}
      more={<p>{L('MOST 給的是 JPL Horizons 從 SPHEREx 看出去、在每張曝光「開始」時的位置；每張曝光約 2 分鐘，我們依它在相鄰曝光間的移動，把位置推到曝光中間再量。', 'MOST gives JPL Horizons’ position as seen from SPHEREx at the START of each exposure; exposures last about 2 minutes, so we move it to mid-exposure using its motion between neighbouring exposures, then measure.')}</p>}>
      <Plot height={250} equal points={pts} onPick={(p) => onPick(p.j)} label={L('量到的位置減去預測位置', 'Measured minus predicted position')}
        x={{ domain: [-lim, lim], reverse: true, fmt: (v) => `${Math.round(v)}″`, label: L('東 ← → 西', 'east ← → west') }}
        y={{ domain: [-lim, lim], fmt: (v) => `${Math.round(v)}″`, label: L('南 ↓ ↑ 北', 'south ↓ ↑ north'), gutter: 40 }}>
        {({ X, Y }) => <>
          <circle cx={X(0)} cy={Y(0)} r={Math.abs(X(PIXS) - X(0))} fill="rgba(110,195,255,.08)" stroke={COL.known} strokeOpacity=".5" />
          <line x1={X(-lim)} x2={X(lim)} y1={Y(0)} y2={Y(0)} stroke={COL.ink3} strokeOpacity=".4" />
          <line x1={X(0)} x2={X(0)} y1={Y(-lim)} y2={Y(lim)} stroke={COL.ink3} strokeOpacity=".4" />
          {pts.map((p) => <circle key={p.j} cx={X(p.x)} cy={Y(p.y)} r="3.2" fill={COL.accent} fillOpacity=".8" />)}
          {cj && <circle cx={X(cj.dra)} cy={Y(cj.ddec)} r="8" fill="none" stroke={COL.ink} strokeWidth="2" />}
        </>}
      </Plot>
    </ChartCard>
  )
}

// ---- validation: MOST vs our own pipeline in the 65 Cybele field --------------------------------------------------
let vPending = null
function FollowCheck({ compact = false }) {
  const [v, setV] = useState(null)
  useEffect(() => {
    (vPending ||= api('/data/validation/follow.json').catch((e) => { vPending = null; throw e })).then(setV).catch(() => setV(false))
  }, [])
  if (!v) return null
  const lab = (b) => (b.lo === 0 ? `< ${b.hi}` : b.hi >= 99 ? `> ${b.lo}` : `${b.lo}–${b.hi}`)
  const bars = v.by_v.map((b) => ({ x: lab(b), y: (100 * b.found) / b.n, b }))
  const tot = v.totals, cy = v.cybele || {}, tm = v.cybele_timing, mc = v.most_check
  const bright = v.by_v.filter((b) => b.hi <= 14), faint = v.by_v.filter((b) => b.lo >= 19)
  const sum = (a, k) => a.reduce((s, b) => s + b[k], 0)
  return (
    <section className={`fw-check ${compact ? 'compact' : ''}`} aria-labelledby="fw-check-h">
      <h2 id="fw-check-h" className="fw-h2">{L('驗證：我們的 AI 找得到已知的小行星嗎？', 'Check: does our AI find known asteroids?')}</h2>
      <p className="lead">{L(`在我們完整分析過的 65 Cybele 天區，MOST 預測 ${v.n_bodies_in_most} 顆已知小行星共出現在 ${tot.used.toLocaleString()} 張影像裡（離天區邊緣至少 1′）。在預測位置 ${v.radius_arcsec}″ 內找到我們的偵測，就算找到。`, `In our fully analysed 65 Cybele field, MOST predicts ${v.n_bodies_in_most} known asteroids in ${tot.used.toLocaleString()} images (at least 1′ inside the field). A detection of ours within ${v.radius_arcsec}″ of the prediction counts as found.`)}</p>
      <div className="fw-check-grid">
        <ChartCard level={3} title={L('依亮度分：找到幾成', 'Share found, by brightness')}
          take={L(`比 14 等亮的：${sum(bright, 'found')}/${sum(bright, 'n')}（Cybele ${cy.n_found}/${cy.n_used}）；比 19 等暗的幾乎都找不到（${sum(faint, 'found')}/${sum(faint, 'n').toLocaleString()}，隨機巧合預計約 ${fmt(sum(faint, 'chance'), 1)} 個），這是 SPHEREx 單張影像的極限。`, `Brighter than magnitude 14: ${sum(bright, 'found')} of ${sum(bright, 'n')} (Cybele ${cy.n_found} of ${cy.n_used}). Fainter than 19 almost none (${sum(faint, 'found')} of ${sum(faint, 'n').toLocaleString()}; about ${fmt(sum(faint, 'chance'), 1)} expected by chance): the limit of a single SPHEREx image.`)}
          more={<p>{L(`「找到」是天區的差分影像在預測位置 ${v.radius_arcsec}″ 內有偵測（訊噪比 ≥ 5）；其中 ${tot.nn} 個被神經網路接受，${tot.track} 個被串成軌跡。等級是 MOST 給的預測 V 星等，數字越大越暗。天區資料：${v.field_created}；MOST 查詢：${v.generated}。`, `"Found" means the field's difference images have a detection (S/N ≥ 5) within ${v.radius_arcsec}″ of the prediction; ${tot.nn} of these were accepted by the neural network and ${tot.track} linked into tracks. Brightness is MOST's predicted V magnitude: larger is fainter. Field data: ${v.field_created}; MOST queries: ${v.generated}.`)}</p>}>
          <Plot height={230} label={L('依預測亮度找到的比例', 'Share found by predicted brightness')} points={bars.map((b, j) => ({ x: j, y: b.y, r: 0, tip: L(`${b.b.found} / ${b.b.n} 張`, `${b.b.found} of ${b.b.n} images`), hint: `V ${b.x}` }))}
            x={{ domain: [-0.6, bars.length - 0.4], ticks: bars.map((_, j) => j), fmt: (j) => bars[j]?.x ?? '', label: L('預測亮度（V 星等，越大越暗）', 'Predicted brightness (V magnitude; larger is fainter)') }}
            y={{ domain: [0, 110], ticks: [0, 50, 100], fmt: (v2) => `${v2}%`, gutter: 46 }}>
            {({ X, Y }) => bars.map((b, j) => {
              const w = Math.max(10, Math.abs(X(1) - X(0)) * 0.62)
              return <g key={j}>
                <rect x={X(j) - w / 2} y={Y(b.y)} width={w} height={Math.max(1, Y(0) - Y(b.y))} rx="3" fill={b.y >= 50 ? COL.good : COL.known} />
                <text className="mark-label" x={X(j)} y={Y(b.y) - 7} textAnchor="middle">{Math.round(b.y)}%</text>
              </g>
            })}
          </Plot>
        </ChartCard>
        {tm && <ChartCard level={3} title={L('MOST 的位置是曝光開始的時候', 'MOST’s position is at the start of the exposure')}
          take={L(`Cybele 每小時移動 ${tm.rate_arcsec_h}″。我們量到的位置比 MOST 沿運動方向超前 ${tm.along_start_med}″；把 MOST 的位置推到曝光中間後，只差 ${tm.along_mid_med}″。${mc ? `MOST 和 JPL Horizons 從 SPHEREx 看、在曝光開始時的位置相差 ${mc.spherex_start.median}″。` : ''}`, `Cybele moves ${tm.rate_arcsec_h}″ an hour. Our measured positions lead MOST’s by ${tm.along_start_med}″ along its motion; moved to mid-exposure, by ${tm.along_mid_med}″.${mc ? ` MOST matches JPL Horizons seen from SPHEREx at exposure start to ${mc.spherex_start.median}″.` : ''}`)}>
          <Plot height={230} label={L('沿運動方向的位置差', 'Offset along the motion')}
            points={[{ x: 0, y: tm.along_start_med, r: 0, tip: `${tm.along_start_med}″` }, { x: 1, y: tm.along_mid_med, r: 0, tip: `${tm.along_mid_med}″` }]}
            x={{ domain: [-0.6, 1.6], ticks: [0, 1], fmt: (j) => (j === 0 ? L('MOST 原始位置', 'MOST as given') : L('推到曝光中間', 'moved to mid-exposure')) }}
            y={{ domain: [0, Math.max(0.8, tm.along_start_med * 1.3)], fmt: (v2) => `${v2.toFixed(1)}″`, gutter: 46, label: L('超前（角秒）', 'Lead (arcsec)') }}>
            {({ X, Y }) => [tm.along_start_med, tm.along_mid_med].map((y, j) => {
              const w = Math.abs(X(1) - X(0)) * 0.45
              return <g key={j}><rect x={X(j) - w / 2} y={Y(Math.max(0, y))} width={w} height={Math.max(1, Math.abs(Y(0) - Y(y)))} rx="3" fill={j ? COL.good : COL.warn} />
                <text className="mark-label" x={X(j)} y={Y(Math.max(0, y)) - 7} textAnchor="middle">{y}″</text></g>
            })}
          </Plot>
        </ChartCard>}
      </div>
      {!compact && v.bodies?.length > 0 && <BodyTable bodies={v.bodies.filter((b) => b.n_found > 0 || (b.V_most ?? 99) < 18.7).slice(0, 8)} />}
    </section>
  )
}

function BodyTable({ bodies }) {
  return (
    <div className="fw-table-wrap">
      <table className="fw-table">
        <caption className="sr-only">{L('各顆小行星的結果', 'Results per asteroid')}</caption>
        <thead><tr><th>{L('小行星', 'Asteroid')}</th><th>{L('預測亮度', 'Predicted V')}</th><th>{L('MOST 預測', 'MOST predicts')}</th><th>{L('找到', 'Found')}</th><th>{L('位置差（中位數）', 'Offset (median)')}</th></tr></thead>
        <tbody>{bodies.map((b) => <tr key={b.name}>
          <td><a href={followHash(b.name.replace(/\s*\([^)]*\)\s*$/, '') || b.name)}>{b.name}</a></td>
          <td className="num">{fmt(b.V_most, 1)}</td><td className="num">{b.n_used}</td>
          <td className="num"><Legend items={[{ c: b.n_found / b.n_used >= 0.5 ? COL.good : COL.ink3, sq: true, label: `${b.n_found}` }]} /></td>
          <td className="num">{b.med_off_arcsec != null ? `${b.med_off_arcsec}″` : '—'}</td>
        </tr>)}</tbody>
      </table>
    </div>
  )
}

function Credits() {
  return (
    <p className="hint fw-credits">{L('資料：NASA SPHEREx（IRSA 的 DR1 與 QR3）；影像清單與預測位置：IRSA 移動天體搜尋工具 MOST；名稱、大小與自轉：JPL 小天體資料庫；星曆：JPL Horizons。', 'Data: NASA SPHEREx (DR1 and QR3 at IRSA). Image list and predicted positions: IRSA’s Moving Object Search Tool (MOST). Names, sizes and spins: JPL Small-Body Database. Ephemerides: JPL Horizons.')}
      {' '}<a href="https://irsa.ipac.caltech.edu/applications/MOST/" target="_blank" rel="noreferrer">MOST ↗</a>{' · '}<a href="https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html" target="_blank" rel="noreferrer">SBDB ↗</a></p>
  )
}
