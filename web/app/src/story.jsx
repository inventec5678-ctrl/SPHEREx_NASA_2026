// The home page as a scroll-told story: one sticky stage, six short steps. Real data throughout:
// 65 Cybele's own images (sky, then difference, then with its trail), the 3D space-time cube of the
// whole field (noise fading out), and the simulated distant planet's parallax zig-zag.
import { useEffect, useMemo, useRef, useState } from 'react'
import { t } from '@sx/i18n/core.js'
import { blitFrame, frameImg, getField, ready, reducedMotion as reduced } from './lib.js'
import { go } from './nav.js'
import { usePlayback } from './play.js'
import { PlayButton } from './playbar.jsx'
import { gpuOK } from './canvas.js'

const STEPS = ['sky', 'diff', 'trail', 'cube', 'px']

function useTrack(fid, pick) {
  const [d, setD] = useState(null)
  useEffect(() => { getField(fid).then((f) => { const tr = pick(f); if (tr) setD({ f, tr }) }).catch(() => {}) }, [fid]) // eslint-disable-line react-hooks/exhaustive-deps
  return d
}

/** 2D: a fixed window around Cybele's path, cycling its images. */
function Blink({ data, kind, trail, active }) {
  const ref = useRef()
  const mem = useMemo(() => {
    if (!data) return []
    const { f, tr } = data, ex = f.exposures
    const all = tr.members.map((m) => f.cand.get(m)).sort((a, b) => ex[a.i].mjd - ex[b.i].mjd)
    const cnt = {}; for (const c of all) cnt[ex[c.i].detector] = (cnt[ex[c.i].detector] || 0) + 1
    const det = +Object.entries(cnt).sort((a, b) => b[1] - a[1])[0][0]
    return all.filter((c) => ex[c.i].detector === det)      // one band: the blink shows motion, not colour
  }, [data])
  const { k, playing: run, toggle } = usePlayback(mem.length, { hz: 1 / 0.48, active })
  useEffect(() => {
    const cv = ref.current; if (!cv || !mem.length) return
    const { f } = data, H = f.shape[0], W = f.shape[1], c = mem[k]
    const xs = mem.map((q) => q.x), ys = mem.map((q) => q.y)
    const half = Math.round(Math.min(Math.min(W, H) / 2 - 1, Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 2 + 26))
    const n = 2 * half + 1, cx = Math.round((Math.min(...xs) + Math.max(...xs)) / 2), cy = Math.round((Math.min(...ys) + Math.max(...ys)) / 2)
    const sx = Math.min(Math.max(cx - half, 0), W - n), sy = Math.min(Math.max(H - 1 - cy - half, 0), H - n), S = cv.width / n
    const im = frameImg(f, kind, c.i)
    const draw = () => {
      const g = cv.getContext('2d'); g.imageSmoothingEnabled = false; g.fillStyle = '#000'; g.fillRect(0, 0, cv.width, cv.height)
      blitFrame(g, im, kind, sx, sy, n, n, cv.width, cv.height)
      if (kind === 'sci') {        // a faint hint for first-time viewers: where to look
        const P = (q) => [(q.x - sx + 0.5) * S, (H - 1 - q.y - sy + 0.5) * S], [x, y] = P(c)
        g.strokeStyle = '#ffb547'; g.globalAlpha = 0.55; g.lineWidth = 2; g.setLineDash([6, 6])
        g.beginPath(); g.arc(x, y, Math.max(26, 7 * S), 0, 7); g.stroke(); g.setLineDash([]); g.globalAlpha = 1
      }
      if (trail) {
        const P = (q) => [(q.x - sx + 0.5) * S, (H - 1 - q.y - sy + 0.5) * S]
        g.strokeStyle = '#6ec3ff'; g.lineWidth = 3; g.globalAlpha = 0.6; g.beginPath()
        mem.slice(0, k + 1).forEach((q, j) => { const [x, y] = P(q); j ? g.lineTo(x, y) : g.moveTo(x, y) }); g.stroke()
        for (let j = 0; j <= k; j++) { const [x, y] = P(mem[j]); g.globalAlpha = 0.3 + 0.7 * (j / Math.max(k, 1)); g.fillStyle = '#6ec3ff'; g.beginPath(); g.arc(x, y, 5, 0, 7); g.fill() }
        g.globalAlpha = 1; const [x, y] = P(c); g.lineWidth = 3; g.beginPath(); g.arc(x, y, Math.max(18, 5 * S), 0, 7); g.stroke()
      }
    }
    if (ready(im)) draw(); else frameImg(f, kind, c.i, (ok) => ok && draw())
    for (let j = 1; j <= 4; j++) frameImg(f, kind, mem[(k + j) % mem.length].i)
  }, [k, kind, trail, mem, data])
  const e = data && mem[k] ? data.f.exposures[mem[k].i] : null
  return (
    <div className="blink">
      <canvas ref={ref} width={720} height={720} role="img" aria-label={kind === 'diff' ? '65 Cybele 天區的差分影像依時間播放' : '65 Cybele 天區的 SPHEREx 影像依時間播放'} />
      {e && <p className="blink-meta num"><PlayButton playing={run} onClick={toggle} /> · {e.iso} UTC · {e.lam_um.toFixed(2)} µm · {k + 1}/{mem.length}</p>}
    </div>
  )
}

/** 3D: one SpaceTime instance, re-pointed at the cube (step 3) or the simulated planet (step 4). */
function Cube({ cy, px, step }) {
  const cv = useRef(), labels = useRef(), inst = useRef(null)
  const [ok, setOk] = useState(() => gpuOK())            // no GPU acceleration: a still picture and a button
  const [asked, setAsked] = useState(false)
  const [loading, setLoading] = useState(null)
  const want = step === 'cube' ? 'cube' : step === 'px' || step === 'you' ? 'px' : null
  useEffect(() => () => inst.current?.destroy(), [])
  useEffect(() => {
    if (!want) return
    let dead = false
    ;(async () => {
      if (!inst.current) {
        const { SpaceTime } = await import('./spacetime.js')
        if (dead) return
        try { inst.current = new SpaceTime(cv.current, labels.current, { reduced: reduced(), onProgress: (n, m) => setLoading(n < m ? [n, m] : null) }) } catch { setOk(false); return }
      }
      const st = inst.current
      if (want === 'cube' && cy) {
        st.showNoise(true)
        await st.setData({ field: cy.f, frames: cy.f.exposures.filter((e) => e.coverage > 0.2).map((e) => e.i), track: null, maxFrames: 80 })
        if (!dead) setTimeout(() => !dead && st.showNoise(false), reduced() ? 0 : 1600)
      } else if (want === 'px' && px) {
        st.showNoise(false)
        await st.setData({ field: px.f, frames: [...new Set(px.tr.members.map((m) => px.f.cand.get(m).i))], track: px.tr, color: '#ff4fd8' })
      }
      if (!dead) st.setCurrent?.(null)
    })()
    return () => { dead = true }
  }, [want, cy, px])
  if (!ok) return (
    <div className="story-nogl">
      <img src="/media/hero_blink.webp" alt="" />
      <p>{asked ? '這個瀏覽器不支援 WebGL，無法顯示 3D。' : '這台裝置沒有 GPU 加速，3D 時空立方體會讓頁面卡住好幾秒，先顯示平面影像。'}</p>
      {!asked && <button className="btn small" onClick={() => { setAsked(true); setOk(true) }}>仍要開啟 3D</button>}
    </div>
  )
  return (
    <div className="cube">
      <canvas ref={cv} aria-label="差分影像依時間疊成的 3D 時空立方體" />
      <div ref={labels} className="st-labels" aria-hidden="true" />
      {loading && <p className="st-load">{t`正在疊合差分影像 ${loading[0]} / ${loading[1]}`}</p>}
    </div>
  )
}

export default function Story() {
  const [step, setStep] = useState('sky')
  const cy = useTrack('cybele', (f) => f.tracks.find((x) => (x.known || '').startsWith('65 ')))
  const px = useTrack('planetx', (f) => f.tracks.find((x) => x.kind === 'distant'))
  const refs = useRef({})
  // while the reader looks at the first steps, quietly fetch what the 3D steps need
  useEffect(() => {
    if (!cy || step === 'sky') return
    const id = setTimeout(() => {
      import('./spacetime.js')
      const ex = cy.f.exposures.filter((e) => e.coverage > 0.2).map((e) => e.i)
      const st = ex.length / 80
      for (let k = 0; k < Math.min(80, ex.length); k++) frameImg(cy.f, 'diff', ex[Math.floor(k * st)])
      if (px) for (const i of new Set(px.tr.members.map((m) => px.f.cand.get(m).i))) frameImg(px.f, 'diff', i)
    }, 800)
    return () => clearTimeout(id)
  }, [cy, px, step === 'sky']) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) setStep(e.target.dataset.step) }), { rootMargin: window.matchMedia('(max-width: 900px)').matches ? '-74% 0px -18% 0px' : '-45% 0px -45% 0px' })
    Object.values(refs.current).forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [])
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    let raf = 0
    const on = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const stage = document.querySelector('.story-stage'); if (!stage) return
        const edge = mq.matches ? stage.getBoundingClientRect().bottom + 6 : -1e9
        for (const el of document.querySelectorAll('.story .step > *')) el.classList.toggle('under', el.getBoundingClientRect().top < edge)
      })
    }
    on(); window.addEventListener('scroll', on, { passive: true }); window.addEventListener('resize', on)
    return () => { window.removeEventListener('scroll', on); window.removeEventListener('resize', on); cancelAnimationFrame(raf) }
  }, [])
  const two = ['sky', 'diff', 'trail'].includes(step)
  const tr = cy?.tr
  const moved = tr ? Math.round(tr.rate_arcsec_h * tr.span_h) : null
  const art = (k, body) => <article key={k} data-step={k} ref={(el) => { refs.current[k] = el }} className={`step ${step === k ? 'on' : ''}`}>{body}</article>
  return (
    <section className="story" aria-label="SPHEREx 怎麼找到會動的東西">
      <div className="story-stage" aria-live="off">
        <div className={`layer ${two ? 'on' : ''}`}>
          <Blink data={cy} kind={step === 'sky' ? 'sci' : 'diff'} trail={step === 'trail'} active={two} />
        </div>
        <div className={`layer ${two ? '' : 'on'}`}>
          <Cube cy={cy} px={px} step={step} />
        </div>
        <ol className="story-dots" aria-hidden="true">{STEPS.map((k) => <li key={k} className={k === step ? 'on' : ''} />)}</ol>
      </div>
      <div className="story-steps">
        {art('sky', <>
          <h2>同一片天空，不同時間</h2>
          <p className="lead">這是 NASA SPHEREx 太空望遠鏡在兩天內，對同一片天空拍的 12 張紅外線影像。仔細看：有一個光點在星星之間移動。</p>
          <div className="story-cta">
            <button className="link" onClick={() => go('cybele')}>直接打開這片天空 →</button>
          </div>
          <p className="src">室女座 · SPHEREx 真實資料</p>
        </>)}
        {art('diff', <>
          <h2>相減，只留下變化</h2>
          <p className="lead">每一張影像都減去同一片天空的參考影像。不會動的恆星互相抵消、消失了；變亮的地方是琥珀色，變暗的是藍色。</p>
        </>)}
        {art('trail', <>
          <h2>AI 確認它是真的，再把它串起來</h2>
          <p className="lead">{t`神經網路檢查每一個亮點是不是真的點光源，再把同一個天體的偵測連成軌跡。這顆是主帶小行星 65 Cybele：${tr ? tr.span_h : '45.7'} 小時內移動了 ${moved ?? 1138}″，和 JPL 的預測位置只差 ${tr?.jpl?.median_arcsec ?? 0.6}″。`}</p>
        </>)}
        {art('cube', <>
          <h2>把所有影像依時間疊起來</h2>
          <p className="lead">深度是時間。一開始淡色的點是差分影像裡所有的雜訊；AI 把它們篩掉之後，每一顆移動的小行星都變成一條斜線穿過時空。</p>
        </>)}
        {art('px', <>
          <h2>開場的視差環，在真實影像裡</h2>
          <p className="lead"><span className="tag sim">模擬資料</span>{t`距離幾百 au 的天體只隨地球繞太陽來回擺動，再加上自己緩慢的軌道運動；在疊起來的時空裡，就是這條之字形。只有兩次巡天時，任何位移都能用軌道漂移解釋；第三次巡天才把距離和漂移分開。這顆是注入真實影像的模擬行星，管線量出它在 ${px ? px.tr.d_au : 420} au 外。`}</p>
        </>)}
      </div>
    </section>
  )
}
