import { useEffect, useRef } from 'react'
import { L } from '@sx/i18n/core.js'
import { go } from './nav.js'

/*
 * The PARALLAX stage that opens the home page (the same scene as the static paper pages).
 * Pinned for 380svh; one rAF loop reads the scroll position and writes styles directly:
 *   0.00 – 0.18  a veil lifts off the lens
 *   0.08 – 0.24  PARALLAX resolves, and yields at 0.42 – 0.52
 *   0.20 – 0.86  one year passes: Earth goes round the Sun (inset) and a distant body traces its
 *                parallax loop plus a slow drift against the fixed stars; each pass leaves a detection
 *   0.86 – 1.00  everything falls away to black, where the page continues
 * The loop is exaggerated for legibility; the HUD says so.
 */
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const range = (v, a, b) => clamp((v - a) / (b - a))
const lerp = (a, b, t) => a + (b - a) * t
const ease = (t) => 1 - Math.pow(1 - t, 3)
const D_TRUE = 500
const PLX_AMP = 206265 / D_TRUE
const PASSES = [0.02, 0.52, 1.0]

const TEXT = {
  en: { kicker: 'SPHEREx · geometric distances in the outer Solar System', veil1: 'How it works', h1a: 'What moves in', h1b: 'the infrared sky', lead: 'We subtract SPHEREx images of the same sky taken days and months apart, let a network trained only on simulations pick out what really moves, and measure how far away it is by parallax.', cta1: 'Open the sky viewer', cta2: 'See how it works', veil2: 'Scroll to open the shutter',
    clock: 'Survey clock', plx: 'Parallax', from: 'From first pass', dist: 'Distance', passes: 'Passes', note: 'Schematic · loop exaggerated', scroll: 'Scroll' },
  zh: { kicker: 'SPHEREx · 外太陽系的幾何距離', veil1: '它怎麼運作', h1a: '紅外線天空裡，', h1b: '什麼在移動', lead: '把同一片天空相隔數天到數月的 SPHEREx 影像相減，讓只用模擬資料訓練的神經網路挑出真正在動的天體，再用視差量出它有多遠。', cta1: '打開天空檢視器', cta2: '看它怎麼運作', veil2: '往下捲動，打開快門',
    clock: '巡天時鐘', plx: '視差', from: '相對第一次巡天', dist: '距離', passes: '巡天', note: '示意 · 視差環已放大', scroll: '捲動' },
}

export default function Parallax({ lang, asPage = false }) {
  const H = asPage ? 'h1' : 'h2'
  const T = L(TEXT.zh, TEXT.en)
  const root = useRef(), cvRef = useRef(), titleRef = useRef(), veilRef = useRef(), hudRef = useRef()
  const clockRef = useRef(), plxRef = useRef(), distRef = useRef(), passRef = useRef()

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const cv = cvRef.current, ctx = cv.getContext('2d')
    let seed = 7
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
    const stars = Array.from({ length: 420 }, () => ({ x: rnd(), y: rnd(), r: Math.pow(rnd(), 3) * 1.8 + 0.25, a: 0.25 + rnd() * 0.7, tw: rnd() * 6.28 }))
    const motes = Array.from({ length: 120 }, () => ({ x: rnd(), y: rnd(), r: 0.4 + rnd() * 1.6, s: 0.3 + rnd(), a: 0.2 + rnd() * 0.5 }))
    const size = () => { const dpr = Math.min(devicePixelRatio || 1, 2); cv.width = Math.round(cv.clientWidth * dpr); cv.height = Math.round(cv.clientHeight * dpr) }
    size()
    const ro = new ResizeObserver(size); ro.observe(cv)
    const sky = (f, W, H) => {
      const s = Math.min(W, H), a = 2 * Math.PI * f
      return { x: W * 0.56 + s * (0.17 * Math.sin(a) + 0.09 * (f - 0.5)), y: H * 0.47 + s * (0.075 * Math.cos(a) - 0.04 * (f - 0.5)) }
    }
    let last = 0, raf = 0
    const frame = (time) => {
      raf = requestAnimationFrame(frame)
      const el = root.current
      if (!el) return
      const r = el.getBoundingClientRect()
      if (r.bottom < 0 || r.top > innerHeight) return
      // reduced motion: one still picture of the finished year (no pinned scroll; see .px-static)
      const p = reduced ? 0.62 : clamp(-r.top / Math.max(1, r.height - innerHeight))
      const dt = last ? Math.min(0.1, (time - last) / 1000) : 1 / 60; last = time
      const W = cv.clientWidth, H = cv.clientHeight, dpr = cv.width / Math.max(1, W)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H)
      const exit = range(p, 0.86, 1), settle = ease(range(p, 0, 0.4)), f = ease(range(p, 0.2, 0.86))

      ctx.save()
      ctx.translate(0, -exit * H * 0.35)
      const zoom = lerp(1.12, 1, settle)
      ctx.translate(W / 2, H / 2); ctx.scale(zoom, zoom); ctx.translate(-W / 2, -H / 2)
      for (const s of stars) {
        const tw = reduced ? 1 : 0.75 + 0.25 * Math.sin(time / 900 + s.tw)
        ctx.globalAlpha = s.a * tw * (1 - exit); ctx.fillStyle = s.r > 1.4 ? '#f2e6c9' : '#dfe6f2'
        ctx.beginPath(); ctx.arc(s.x * W, s.y * H, s.r, 0, 6.283); ctx.fill()
      }
      if (range(p, 0.2, 0.86) > 0) {
        ctx.globalAlpha = 0.55 * (1 - exit); ctx.strokeStyle = '#6fb6ff'; ctx.lineWidth = 1; ctx.setLineDash([3, 5])
        ctx.beginPath()
        for (let i = 0; i <= 160; i++) { const pt = sky((i / 160) * f, W, H); i ? ctx.lineTo(pt.x, pt.y) : ctx.moveTo(pt.x, pt.y) }
        ctx.stroke(); ctx.setLineDash([])
        PASSES.forEach((pf, k) => {
          if (f < pf - 0.001) return
          const pt = sky(pf, W, H)
          ctx.globalAlpha = 1 - exit; ctx.strokeStyle = '#f2e6c9'; ctx.strokeRect(pt.x - 9, pt.y - 9, 18, 18)
          ctx.fillStyle = '#f2e6c9'; ctx.font = "500 10px 'IBM Plex Mono', monospace"; ctx.fillText(`P${k + 1}`, pt.x + 13, pt.y - 10)
        })
      }
      const b = sky(f, W, H), show = range(p, 0.16, 0.26) * (1 - exit)
      if (show > 0) {
        ctx.globalAlpha = show
        const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, 14)
        g.addColorStop(0, 'rgba(111,182,255,0.9)'); g.addColorStop(1, 'rgba(111,182,255,0)')
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(b.x, b.y, 14, 0, 6.283); ctx.fill()
        ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(b.x, b.y, 2.2, 0, 6.283); ctx.fill()
        ctx.strokeStyle = 'rgba(111,182,255,0.9)'; ctx.lineWidth = 1
        const R = 22, L = 7
        for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
          ctx.beginPath(); ctx.moveTo(b.x + sx * R, b.y + sy * (R - L)); ctx.lineTo(b.x + sx * R, b.y + sy * R); ctx.lineTo(b.x + sx * (R - L), b.y + sy * R); ctx.stroke()
        }
      }
      ctx.restore()

      const ins = range(p, 0.22, 0.32) * (1 - range(p, 0.8, 0.9))
      if (ins > 0) {
        const s = Math.min(W, H), cx = W - s * 0.17 - 24, cy = H - s * 0.17 - 64, R = s * 0.1
        ctx.globalAlpha = ins; ctx.strokeStyle = 'rgba(201,204,211,0.35)'; ctx.lineWidth = 1
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.283); ctx.stroke()
        ctx.fillStyle = '#f2e6c9'; ctx.beginPath(); ctx.arc(cx, cy, 3.5, 0, 6.283); ctx.fill()
        const a = 2 * Math.PI * f - Math.PI / 2, ex = cx + R * Math.cos(a), ey = cy + R * Math.sin(a)
        ctx.strokeStyle = 'rgba(111,182,255,0.55)'; ctx.setLineDash([2, 4])
        ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(cx, cy - s * 0.32); ctx.stroke(); ctx.setLineDash([])
        ctx.fillStyle = '#6fb6ff'; ctx.beginPath(); ctx.arc(ex, ey, 3.5, 0, 6.283); ctx.fill()
        ctx.fillStyle = 'rgba(201,204,211,0.6)'; ctx.font = "500 10px 'IBM Plex Mono', monospace"
        ctx.fillText('SUN', cx + 7, cy + 4); ctx.fillText('EARTH · 1 AU', ex + 8, ey + 4)
      }
      ctx.globalAlpha = 1

      const v = 1 - range(p, 0, 0.18)
      if (v > 0.001) {
        ctx.fillStyle = '#dfe6f2'
        for (const m of motes) {
          if (!reduced) { m.x += 0.006 * m.s * dt; m.y -= 0.004 * m.s * dt; if (m.x > 1) m.x -= 1; if (m.y < 0) m.y += 1 }
          ctx.globalAlpha = m.a * v; ctx.beginPath(); ctx.arc(m.x * W, (m.y - p * 0.6) * H, m.r * (1 + p * 4), 0, 6.283); ctx.fill()
        }
        ctx.globalAlpha = 1
      }
      veilRef.current.style.opacity = String(v)
      veilRef.current.style.pointerEvents = v > 0.5 ? 'auto' : 'none'
      veilRef.current.style.visibility = v > 0.001 ? 'visible' : 'hidden'
      veilRef.current.style.transform = `translate3d(0, ${-range(p, 0, 0.18) * 24}vh, 0) scale(${1 + range(p, 0, 0.18) * 0.25})`
      const tIn = ease(range(p, 0.08, 0.24)), tOut = range(p, 0.42, 0.52), title = titleRef.current
      title.style.opacity = reduced ? '1' : String(tIn * (1 - tOut))
      title.firstChild.style.letterSpacing = `${lerp(0.6, 0.24, tIn)}em`
      title.style.transform = `translate3d(0, ${-p * 6}vh, 0)`
      title.style.filter = !reduced && tIn < 0.99 ? `blur(${(1 - tIn) * 10}px)` : ''
      hudRef.current.style.opacity = String(range(p, 0.02, 0.1) * (1 - range(p, 0.84, 0.92)))
      clockRef.current.textContent = `T+ ${String(Math.round(f * 365.25)).padStart(3, '0')} D`
      plxRef.current.textContent = `${(PLX_AMP * Math.abs(Math.sin(Math.PI * f)) * 2).toFixed(0)}″`
      const k = PASSES.filter((pf) => f >= pf - 0.001).length
      passRef.current.textContent = `${k} / 3`
      // two passes cannot separate distance from drift; the third fixes it
      distRef.current.textContent = k < 3 ? '— au' : `${D_TRUE} au`
    }
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [])

  return (
    <section ref={root} className={`px-stage ${typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'px-static' : ''}`} aria-label="Parallax">
      <div className="px-pin">
        <canvas ref={cvRef} aria-hidden="true" />
        <div ref={titleRef} className="px-title"><p className="px-word" aria-hidden="true">PARALLAX</p><p className="px-label">{T.kicker}</p></div>
        <div ref={veilRef} className="px-veil">
          <div className="px-hero">
            <p className="px-label">{T.veil1}</p>
            <H className="px-h1">{T.h1a}<br /><em>{T.h1b}</em></H>
            <p className="px-lead">{T.lead}</p>
            <div className="px-ctas">
              <button className="btn primary" onClick={() => go('cybele')}>{T.cta1} →</button>
              <button className="btn" onClick={() => document.getElementById('ch-method')?.scrollIntoView({ behavior: 'smooth' })}>{T.cta2}</button>
            </div>
            <p className="px-big">{T.veil2} <span className="px-bounce" aria-hidden="true">↓</span></p>
          </div>
        </div>
        <div ref={hudRef} className="px-hud px-brackets" aria-hidden="true">
          <div className="tl"><p ref={clockRef}>T+ 000 D</p><p className="dim">{T.clock}</p></div>
          <div className="tr"><p>{T.plx} <b ref={plxRef}>0″</b></p><p className="dim">{T.from}</p><p>{T.dist} <b ref={distRef}>— au</b></p><p className="dim">{T.passes} <span ref={passRef}>0 / 3</span></p></div>
          <div className="bl">{T.note}</div>
          <div className="br">{T.scroll} <span className="px-bounce">↓</span></div>
        </div>
      </div>
    </section>
  )
}
