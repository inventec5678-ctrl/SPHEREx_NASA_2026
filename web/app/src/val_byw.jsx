// Validation: brown dwarfs that Backyard Worlds: Planet 9 volunteers discovered by blinking WISE images, looked for
// again in SPHEREx (UPGRADE_PLAN.md §10, R9). Data: /data/validation/byw.json and the pictures under /data/byw/<id>/
// (scripts/byw_validate.py). Three cards: how many SPHEREx sees by brightness, the faintness limit (click a dot for
// its picture), and the motion measured over ~11 years against the catalogue's.
import { useEffect, useRef, useState } from 'react'
import { L, loadImage } from './lib.js'
import { COL, ChartCard, Meter, Plot, niceTicks } from './charts.jsx'
import { Blink, devicePx } from './blink.jsx'
import './val_byw.css'

const SEEN = COL.known, FOUND = COL.good, MISSED = COL.ink3
const f2 = (v, n = 2) => (v == null || !isFinite(v) ? '—' : Number(v).toFixed(n))
const perYr = () => L('″/年', '″/yr')
const kind = (o) => (o.found ? 'found' : o.detected ? 'seen' : 'missed')
const colour = (o) => ({ found: FOUND, seen: SEEN, missed: MISSED })[kind(o)]
const shortName = (o) => o.name.replace(/^(CWISE|WISEA|WISEU) J(\d{4})\S*([+-]\d{4})\S*$/, 'J$2$3')
const what = (o) => ({
  found: L('自動搜尋找到', 'Found by the automatic search'),
  seen: L('在預測位置看到', 'Seen at the predicted position'),
  missed: L('沒看到', 'Not seen'),
})[kind(o)]

/** The deepest picture (every D5 + D6 exposure) with where WISE saw the object (the catalogue position at its epoch,
 *  hollow circle) and where SPHEREx sees it now (ticks), joined by an arrow: ~11 years of motion. */
function Then({ o, px = 220, size = 19 }) {
  const cv = useRef()
  const [im, setIm] = useState(null)
  useEffect(() => { let on = true; setIm(null); loadImage(`${o.img.base}/deep_d56.webp`, (x) => on && setIm(x)); return () => { on = false } }, [o.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = cv.current, g = el?.getContext('2d')
    if (!g || !im) return
    const W = devicePx(px)
    if (el.width !== W || el.height !== W) { el.width = W; el.height = W }
    const z = Math.max(1, Math.round(W / size)), n = Math.ceil(W / z) + 1
    const c = o.img.pred || o.img.track[0]
    const cx = Math.round(c[0] ?? c.x), cy = im.height - 1 - Math.round(c[1] ?? c.y)
    const sx = cx - Math.floor(n / 2), sy = cy - Math.floor(n / 2), off = Math.round((W - n * z) / 2)
    g.imageSmoothingEnabled = false
    g.fillStyle = '#000'; g.fillRect(0, 0, W, W)
    g.drawImage(im, sx, sy, n, n, off, off, n * z, n * z)
    const P = ([x, y]) => [off + (x - sx + 0.5) * z, off + (im.height - 1 - y - sy + 0.5) * z]
    const s = W / px, lw = 2 * s
    const then = o.img.cat && P(o.img.cat), now = o.img.fit && P(o.img.fit)
    if (then && now) {
      const a = Math.atan2(now[1] - then[1], now[0] - then[0]), h = 8 * s
      g.strokeStyle = 'rgba(255,255,255,.85)'; g.fillStyle = 'rgba(255,255,255,.85)'; g.lineWidth = lw
      g.beginPath(); g.moveTo(...then); g.lineTo(...now); g.stroke()
      g.beginPath(); g.moveTo(...now); g.lineTo(now[0] - h * Math.cos(a - 0.5), now[1] - h * Math.sin(a - 0.5)); g.lineTo(now[0] - h * Math.cos(a + 0.5), now[1] - h * Math.sin(a + 0.5)); g.closePath(); g.fill()
    }
    if (then) { g.strokeStyle = COL.known; g.lineWidth = lw; g.beginPath(); g.arc(then[0], then[1], Math.max(9 * s, 0.9 * z), 0, 7); g.stroke() }
    const at = now || (o.img.pred && P(o.img.pred))
    if (at) {
      const r0 = Math.max(10 * s, 1.2 * z), r1 = r0 + 14 * s
      g.strokeStyle = now ? FOUND : COL.ink3; g.lineWidth = lw; g.beginPath()
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { g.moveTo(at[0] + dx * r0, at[1] + dy * r0); g.lineTo(at[0] + dx * r1, at[1] + dy * r1) }
      g.stroke()
    }
  }, [im, px, size, o])
  return <canvas ref={cv} className="mv-blink byw-then" style={{ width: px }} role="img"
    aria-label={L(`${shortName(o)}：藍圈是 WISE 當年看到的位置，綠色記號是 SPHEREx 現在看到的位置`, `${shortName(o)}: the blue circle is where WISE saw it, the green ticks where SPHEREx sees it now`)} />
}

/** Recovery by brightness: per W2 bin, the share seen at the predicted position and the share found blind. */
function ByBrightness({ d }) {
  const bins = d.summary.bins.filter((b) => b.n > 0)
  const pts = bins.flatMap((b, j) => [
    { x: j - 0.17, y: (100 * b.detected) / b.n, tip: `W2 ${b.w2_lo}–${b.w2_hi}: ${b.detected} / ${b.n}`, hint: L('在預測位置看到', 'seen at the predicted position') },
    { x: j + 0.17, y: (100 * b.found) / b.n, tip: `W2 ${b.w2_lo}–${b.w2_hi}: ${b.found} / ${b.n}`, hint: L('自動搜尋找到', 'found by the automatic search') },
  ])
  return (
    <Plot label={L('依亮度分組：看到和自動找到的比例', 'Share seen and share found, by brightness')} height={250} points={pts}
      x={{ domain: [-0.6, bins.length - 0.4], ticks: bins.map((_, j) => j), fmt: (j, narrow) => (bins[j] ? (narrow ? `${bins[j].w2_lo}` : `${bins[j].w2_lo}–${bins[j].w2_hi}`) : ''), label: L('W2 星等（越大越暗）', 'W2 magnitude (larger = fainter)') }}
      y={{ domain: [0, 112], ticks: [0, 25, 50, 75, 100], fmt: (v) => `${v}%`, gutter: 48 }}>
      {({ X, Y, hov, narrow }) => {
        const bw = Math.max(8, Math.abs(X(1) - X(0)) * 0.3)
        return pts.map((p, j) => {
          const b = bins[Math.round(p.x)], n = j % 2 ? b.found : b.detected
          return (
            <g key={j} opacity={hov == null || hov === j ? 1 : 0.55}>
              <rect x={X(p.x) - bw / 2} y={Y(p.y)} width={bw} height={Math.max(2, Y(0) - Y(p.y))} rx="3" fill={j % 2 ? FOUND : SEEN} />
              <text className={narrow ? 'mark-note' : 'mark-label'} x={X(p.x)} y={Y(p.y) - 7} textAnchor="middle">{n}/{b.n}</text>
            </g>
          )
        })
      }}
    </Plot>
  )
}

/** Detection S/N against brightness, with the S/N = 5 line and the fitted limit. */
function Limit({ d, sel, onPick }) {
  const obs = d.objects.filter((o) => o.covered && !o.skip && o.snr_best != null)
  const ys = obs.map((o) => o.snr_best)
  const top = Math.max(12, Math.ceil(Math.max(...ys) / 5) * 5 + 2), bot = Math.min(-2, Math.floor(Math.min(...ys)) - 1)
  const lim = d.limit_w2_snr5
  const pts = obs.map((o) => ({ x: o.w2, y: o.snr_best, o, tip: <><b>{shortName(o)}</b> W2 {f2(o.w2)}</>, hint: `S/N ${f2(o.snr_best, 1)} · ${what(o)}` }))
  return (
    <Plot label={L('每顆棕矮星在預測位置的訊噪比，對亮度', 'Signal-to-noise at the predicted position against brightness, one dot per brown dwarf')} height={280} points={pts}
      onPick={(p) => onPick(p.o)}
      x={{ domain: [13.85, 15.1], ticks: [14, 14.25, 14.5, 14.75, 15], fmt: (v) => v.toFixed(2).replace(/0$/, ''), label: L('W2 星等（越大越暗）', 'W2 magnitude (larger = fainter)'), grid: true }}
      y={{ domain: [bot, top], ticks: niceTicks(bot, top, 5), label: L('訊噪比', 'Signal-to-noise'), gutter: 36 }}>
      {({ X, Y, m, w, h }) => <>
        <rect className="byw-zone" x={m.l} y={Y(top)} width={w - m.l - m.r} height={Y(5) - Y(top)} />
        <line className="byw-thr" x1={m.l} x2={w - m.r} y1={Y(5)} y2={Y(5)} />
        <text className="mark-note" x={w - m.r - 4} y={Y(5) - 6} textAnchor="end">{L('5 = 看得到', '5 = seen')}</text>
        {lim != null && lim > 13.85 && lim < 15.1 && <>
          <line className="byw-lim" x1={X(lim)} x2={X(lim)} y1={m.t} y2={h - m.b} />
          <text className="mark-label" x={X(lim) + 6} y={m.t + 14}>{L(`極限 ≈ ${f2(lim, 1)}`, `limit ≈ ${f2(lim, 1)}`)}</text>
        </>}
        {pts.map((p, j) => {
          const k = kind(p.o)
          return <circle key={j} cx={X(p.x)} cy={Y(Math.max(bot, p.y))} r={sel?.id === p.o.id ? 9 : 7}
            className={k === 'missed' ? 'byw-miss' : ''} fill={k === 'missed' ? 'none' : colour(p.o)} stroke={k === 'missed' ? MISSED : sel?.id === p.o.id ? COL.ink : 'none'} strokeWidth="2" />
        })}
      </>}
    </Plot>
  )
}

/** Measured motion (SPHEREx now against the catalogue's epoch, ~7-11 years) against the catalogue's motion. */
function Motion({ d, onPick }) {
  const rows = d.objects.filter((o) => o.seeded)
  if (!rows.length) return <p className="hint">{L('還沒有看得到的棕矮星可以量移動。', 'No brown dwarf seen yet whose motion could be measured.')}</p>
  const hi = Math.ceil(Math.max(...rows.flatMap((o) => [o.pm_cat, o.seeded.pm + o.seeded.pm_err])) * 5 + 0.5) / 5
  const pts = rows.map((o) => ({ x: o.pm_cat, y: o.seeded.pm, o, tip: <><b>{shortName(o)}</b></>,
    hint: `${L('星表', 'catalogue')} ${f2(o.pm_cat)}${perYr()} · ${L('量到', 'measured')} ${f2(o.seeded.pm)} ± ${f2(o.seeded.pm_err)}${perYr()}` }))
  return (
    <Plot label={L('量到的移動速度對星表', 'Measured motion against the catalogue')} square points={pts} onPick={(p) => onPick(p.o)}
      x={{ domain: [0, hi], ticks: niceTicks(0, hi, 4), fmt: (v) => `${v}″`, label: L('星表：每年移動', 'Catalogue: motion per year'), grid: true }}
      y={{ domain: [0, hi], ticks: niceTicks(0, hi, 4), fmt: (v) => `${v}″`, label: L('SPHEREx 量到', 'Measured by SPHEREx'), gutter: 44 }}>
      {({ X, Y }) => <>
        <line className="byw-thr" x1={X(0)} y1={Y(0)} x2={X(hi)} y2={Y(hi)} />
        {pts.map((p, j) => <g key={j}>
          <line className="byw-err" x1={X(p.x)} x2={X(p.x)} y1={Y(Math.max(0, p.y - p.o.seeded.pm_err))} y2={Y(Math.min(hi, p.y + p.o.seeded.pm_err))} />
          <circle cx={X(p.x)} cy={Y(p.y)} r="7" fill={colour(p.o)} />
        </g>)}
      </>}
    </Plot>
  )
}

/** One brown dwarf: its picture (then and now), a blink of the survey passes, and its numbers. */
function Card({ o }) {
  return (
    <div className="byw-pick">
      <div className="byw-pics">
        {o.img && <figure><Then o={o} px={200} /><figcaption>{L(`${Math.floor(o.epoch)} → 現在`, `${Math.floor(o.epoch)} → now`)}</figcaption></figure>}
        {o.img && <figure><Blink c={{ id: o.id, field: `byw-${o.id}`, base: o.img.base, det_band: '56', track: o.img.track }} size={19} px={200}
          label={L('各輪巡天的 D5＋D6 疊加影像，輪流顯示', 'D5 + D6 stack of each survey pass, shown in turn')} /></figure>}
      </div>
      <dl className="byw-facts">
        <div><dt>{L('名稱', 'Name')}</dt><dd>{o.name}{o.sptype ? ` · ${o.sptype}` : ''}</dd></div>
        <div><dt>W2</dt><dd>{f2(o.w2)}</dd></div>
        <div><dt>{L('訊噪比', 'S/N')}</dt><dd style={{ color: colour(o) }}>{f2(o.snr_best, 1)} · {what(o)}</dd></div>
        <div><dt>{L('星表移動', 'Catalogue motion')}</dt><dd>{f2(o.pm_cat)}{perYr()}</dd></div>
        {o.seeded && <div><dt>{L(`SPHEREx 量到（${Math.round(o.seeded.baseline_yr)} 年）`, `SPHEREx measured (${Math.round(o.seeded.baseline_yr)} yr)`)}</dt><dd>{f2(o.seeded.pm)} ± {f2(o.seeded.pm_err)}{perYr()}</dd></div>}
        {o.found && <div><dt>{L('自動搜尋量到', 'Automatic search')}</dt><dd>{f2(o.pm_meas)}{perYr()}</dd></div>}
        {o.bd_score != null && <div><dt>{L('光譜 AI：棕矮星的機率', 'Spectrum AI: brown-dwarf score')}</dt><dd>{f2(o.bd_score)}</dd></div>}
      </dl>
    </div>
  )
}

export default function ValByw() {
  const [d, setD] = useState(null)
  const [sel, setSel] = useState(null)
  useEffect(() => { fetch('/data/validation/byw.json').then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => setD(null)) }, [])
  if (!d || !d.objects?.length) return null
  const s = d.summary, n = s.n_covered
  const seenRows = d.objects.filter((o) => o.detected && o.img).sort((a, b) => b.snr_best - a.snr_best)
  const pick = sel || seenRows[0] || d.objects.find((o) => o.img)
  const motion = d.objects.filter((o) => o.seeded)
  const ratio = motion.map((o) => o.seeded.pm / o.pm_cat).sort((a, b) => a - b)
  const med = ratio.length ? ratio[Math.floor(ratio.length / 2)] : null
  const depth = d.config?.pick_per_pass
  return (
    <>
      <ChartCard className="vd-byw"
        title={L('志工發現的棕矮星，SPHEREx 也看得到嗎？', 'Brown dwarfs that volunteers found: does SPHEREx see them?')}
        take={<>{L('這些棕矮星是 Backyard Worlds 的志工在 WISE 影像裡用閃爍比對找到的。', 'Backyard Worlds volunteers found these brown dwarfs by blinking WISE images. ')}
          {L(`${n} 顆裡，SPHEREx 在星表預測的位置看到 `, `Of ${n}, SPHEREx sees `)}<b>{s.n_detected}</b>{L(' 顆；自動搜尋不看星表，自己找到 ', ' at the predicted position; the automatic search, which never looks at the catalogue, finds ')}<b>{s.n_found}</b>{L(' 顆。', '.')}</>}
        legend={[{ c: SEEN, sq: true, label: L('在預測位置看到', 'Seen where predicted') }, { c: FOUND, sq: true, label: L('自動搜尋找到', 'Found by the search') }]}
        more={<>
          <p>{L('名單：Kirkpatrick 等 2021（20 秒差距普查，表 1 標出每顆的發現者）裡由志工發現的，和 Meisner 等 2020（ApJ 899, 123，志工發現的冷棕矮星）。條件在看資料前就定好：W2 不暗於 15.0 等、每年移動至少 0.3 角秒。', 'The list: objects found by volunteers in Kirkpatrick et al. 2021 (the 20-parsec census, whose table 1 credits each discoverer) and Meisner et al. 2020 (ApJ 899, 123, cold brown dwarfs found by volunteers). The cuts were fixed before looking at any data: W2 no fainter than 15.0 and moving at least 0.3″ a year.')}</p>
          <p>{L(`「看到」：在星表預測的位置（自行＋視差）做強制測光，雜訊用旁邊 48 條平行軌跡實際量，訊噪比 5 以上。「自動找到」：和網站上一樣的移動星搜尋（各輪比對，加上和 CatWISE 2015 年位置的跨時期比對），完全不看星表，只在事後比對。`, `"Seen": forced photometry where the catalogue predicts it (proper motion + parallax), with the noise measured on 48 parallel tracks beside it; S/N 5 or more. "Found": the site's own moving-star search (pass to pass, plus the cross-epoch check against CatWISE's 2015 positions), blind to the catalogue, which only labels the result afterwards.`)}</p>
          {depth && <p>{L(`每個 IRSA 裁切影像都附 4 MB 的 PSF 表，所以每顆只下載每輪 D5、D6 各 ${depth[5]} 張、D4 ${depth[4]} 張（可用的大約三分之一），比網站上的天區淺。`, `Every IRSA cutout carries a 4 MB PSF table, so each object used ${depth[5]} D5 and ${depth[6]} D6 exposures per pass plus ${depth[4]} D4 (about a third of what exists): shallower than the site's fields.`)}</p>}
        </>}>
        <div className="byw-meters">
          <Meter value={s.n_detected / Math.max(1, n)} c={SEEN} text={`${s.n_detected} / ${n}`} label={L('在預測位置看到', 'Seen at the predicted position')} />
          <Meter value={s.n_found / Math.max(1, n)} c={FOUND} text={`${s.n_found} / ${n}`} label={L('自動搜尋自己找到', 'Found by the automatic search')} />
        </div>
        <ByBrightness d={d} />
      </ChartCard>
      <ChartCard className="vd-byw"
        title={L('多暗還看得到', 'How faint is too faint')}
        take={d.limit_w2_snr5 != null
          ? <>{L('每個點是一顆棕矮星。照這些點的趨勢，訊噪比在 W2 ≈ ', 'One dot per brown dwarf. Following the trend, the signal-to-noise falls below 5 at W2 ≈ ')}<b>{f2(d.limit_w2_snr5, 1)}</b>{L(' 等降到 5 以下。點一下看那顆的影像。', '. Click a dot to see its picture.')}</>
          : L('每個點是一顆棕矮星。點一下看那顆的影像。', 'One dot per brown dwarf. Click a dot to see its picture.')}
        legend={[{ c: FOUND, label: L('自動找到', 'Found') }, { c: SEEN, label: L('看到', 'Seen') }, { c: MISSED, hollow: true, label: L('沒看到', 'Not seen') }]}
        more={<p>{L('W2 是 WISE 4.6 微米的星等，每大 1 等暗 2.5 倍。挑戰目標 WISE 0855 是 14.0 等，在網站上用全部影像的天區裡被自動找到。', 'W2 is the WISE 4.6 µm magnitude; each step of 1 is 2.5 times fainter. The challenge target WISE 0855 is W2 = 14.0 and is found blind in the site\'s full-depth field.')}</p>}>
        <Limit d={d} sel={pick} onPick={setSel} />
        {pick && <Card o={pick} />}
      </ChartCard>
      <ChartCard className="vd-byw"
        title={L('移動得和星表一樣快嗎', 'Moving as fast as the catalogue says?')}
        take={med != null
          ? <>{L(`把 SPHEREx 現在看到的位置，和 WISE 當年的位置相比（大約 ${Math.round(motion[0].seeded.baseline_yr)} 年）。${motion.length} 顆看得到的棕矮星，量到的速度中位數是星表的 `, `SPHEREx's position now against WISE's then (about ${Math.round(motion[0].seeded.baseline_yr)} years apart). For the ${motion.length} brown dwarfs seen, the measured speed is, at the median, `)}<b>{Math.round(100 * med)}%</b>{L('。', ' of the catalogue\'s.')}</>
          : L('還沒有看得到的棕矮星可以量移動。', 'No brown dwarf seen yet whose motion could be measured.')}
        legend={[{ c: COL.ink2, line: true, label: L('完全吻合', 'Perfect match') }]}
        more={<p>{L('這不是盲搜：從星表預測的位置開始擬合，用 Gaia 星對齊影像，再和星表在它自己年代（CatWISE 2015.4 或 Meisner 2018–19）的位置比。誤差至少是 PSF 寬度除以訊噪比。', 'This is not blind: the fit starts where the catalogue predicts, the picture is aligned on Gaia stars, and the position is compared with the catalogue\'s at its own epoch (CatWISE 2015.4, or Meisner 2018–19). The error is at least the PSF width over the S/N.')}</p>}>
        <Motion d={d} onPick={setSel} />
      </ChartCard>
    </>
  )
}
