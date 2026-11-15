// Gaia DR3 beside SPHEREx: the field lab's star card (click a star, see what ESA's Gaia measured for it) and the
// colour–magnitude diagram (CMD) the card and the target list share.
// Data: /api/gaia/star and /api/gaia/marks (web/api_gaia.py; sxlib/gaia.py asks ESA's Gaia archive first and MAST
// when ESA does not answer) and /data/gaia/cmd.json (scripts/gaia_build.py: every Gaia star within 100 pc, binned).
import { useEffect, useMemo, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api } from './lib.js'
import { ChartCard, COL, Plot } from './charts.jsx'
import './starcard.css'

let cmdP = null
/** The 100-pc background, fetched once per page load. null while loading, false when it failed. */
export function useCmd() {
  const [d, setD] = useState(null)
  useEffect(() => {
    let live = true
    cmdP = cmdP || fetch('/data/gaia/cmd.json').then((r) => (r.ok ? r.json() : false)).catch(() => false)
    cmdP.then((v) => { if (live) setD(v) })
    return () => { live = false }
  }, [])
  return d
}

/** The density as an image: one pixel per bin, brighter where more stars are (log scale). */
function densityUrl(cmd) {
  const c = document.createElement('canvas')
  c.width = cmd.nx; c.height = cmd.ny
  const g = c.getContext('2d'), im = g.createImageData(cmd.nx, cmd.ny)
  let mx = 0
  for (const n of cmd.counts) if (n > mx) mx = n                     // no spread: the grid can be large
  const top = Math.log1p(mx)
  cmd.counts.forEach((n, j) => {
    if (!n) return
    const a = 0.22 + 0.78 * Math.log1p(n) / top
    im.data[j * 4] = 201; im.data[j * 4 + 1] = 204; im.data[j * 4 + 2] = 211; im.data[j * 4 + 3] = Math.round(255 * a)    // COL.ink2
  })
  g.putImageData(im, 0, 0)
  return c.toDataURL()
}

const SUN = { bp_rp: 0.82, abs_g: 4.67 }
/** BP−RP as the colour a star looks (blue-white to red). */
export function starColour(c) {
  const stops = [[-0.4, [155, 176, 255]], [0.3, [202, 216, 255]], [0.82, [255, 244, 232]], [1.5, [255, 210, 161]], [2.5, [255, 178, 110]], [4, [255, 130, 80]]]
  if (c == null) return null
  const k = stops.findIndex((s) => s[0] >= c)
  if (k <= 0) return `rgb(${stops[k === 0 ? 0 : stops.length - 1][1].join(' ')})`
  const [a, ca] = stops[k - 1], [b, cb] = stops[k], f = (c - a) / (b - a)
  return `rgb(${ca.map((v, i) => Math.round(v + f * (cb[i] - v))).join(' ')})`
}
const colourWord = (c) => (c < 0.3 ? L('藍白色', 'blue-white') : c < 0.7 ? L('白色', 'white') : c < 1.0 ? L('黃色（像太陽）', 'yellow, like the Sun') : c < 1.6 ? L('橙色', 'orange') : L('紅色', 'red'))

/** Gaia's variability classes in plain words. */
export const varClass = (c) => ({
  SOLAR_LIKE: L('有黑子的類太陽星（隨自轉變亮變暗）', 'Sun-like star with spots (rotation)'),
  ECL: L('食雙星（兩顆星互相遮擋）', 'Eclipsing binary (two stars block each other)'),
  'DSCT|GDOR|SXPHE': L('快速脈動的星（盾牌座 δ 型等）', 'Fast pulsating star (δ Scuti type)'),
  LPV: L('長週期變星（像米拉的脈動紅巨星）', 'Long-period variable (pulsating red giant, like Mira)'),
  RR: L('天琴座 RR 型脈動星', 'RR Lyrae pulsating star'),
  RS: L('活躍的雙星（獵犬座 RS 型）', 'Active binary (RS CVn type)'),
  CV: L('激變變星（會爆發的白矮星雙星）', 'Cataclysmic variable (outbursting white-dwarf binary)'),
  YSO: L('年輕恆星（還在形成）', 'Young star, still forming'),
  S: L('短時間的閃變', 'Short-timescale flicker'),
  AGN: L('活躍星系核（遠方的星系，不是恆星）', 'Active galactic nucleus (a distant galaxy, not a star)'),
  CEP: L('造父變星', 'Cepheid'),
  unclassified: L('Gaia 沒有分類', 'Not classified by Gaia'),
}[c] || c)

/**
 * The colour–magnitude diagram: the Sun's neighbourhood as the background, region names, and markers.
 * marks: [{ bp_rp, abs_g, c, r, shape ('star' | 'dot' | 'ring' | 'diamond'), label, tip, hint }]
 */
export function Cmd({ marks = [], height = 420, small = false, label }) {
  const cmd = useCmd()
  const url = useMemo(() => (cmd ? densityUrl(cmd) : null), [cmd])
  const pts = marks.filter((m) => m.bp_rp != null && m.abs_g != null).map((m) => ({ ...m, x: m.bp_rp, y: m.abs_g, r: (m.r || 7) + 3 }))
  const all = [...pts, { x: SUN.bp_rp, y: SUN.abs_g, r: 9, tip: L('太陽（放在這張圖上的位置）', 'The Sun (where it would sit)'), hint: 'BP−RP 0.82 · G 4.67' }]
  const regions = small ? [
    [1.45, 3.6, L('主序星', 'Main sequence')], [-0.55, 17.2, L('白矮星', 'White dwarfs')], [1.8, -1.6, L('巨星', 'Giants')],
  ] : [
    [1.45, 3.4, L('主序星（像太陽這樣的星）', 'Main sequence (stars like the Sun)')], [3.0, 9.6, L('紅矮星', 'Red dwarfs')],
    [-0.55, 17.2, L('白矮星', 'White dwarfs')], [1.8, -1.6, L('巨星', 'Giants')],
  ]
  const shape = (m, X, Y) => {
    const x = X(m.x), y = Y(m.y), r = m.r - 3, c = m.c || COL.accent
    if (m.shape === 'ring') return <circle cx={x} cy={y} r={r + 3} fill="none" stroke={c} strokeWidth="3" />
    if (m.shape === 'diamond') return <path d={`M${x} ${y - r - 1}l${r + 1} ${r + 1}l${-r - 1} ${r + 1}l${-r - 1} ${-r - 1}z`} fill={c} stroke={COL.ink} strokeWidth="1" />
    if (m.shape === 'star') {
      const d = Array.from({ length: 10 }, (_, k) => { const a = -Math.PI / 2 + k * Math.PI / 5, q = k % 2 ? r * 0.45 : r * 1.25; return `${k ? 'L' : 'M'}${(x + q * Math.cos(a)).toFixed(1)} ${(y + q * Math.sin(a)).toFixed(1)}` }).join(' ') + 'Z'
      return <path d={d} fill={c} stroke={COL.ink} strokeWidth="1" />
    }
    return <circle cx={x} cy={y} r={r} fill={c} stroke={COL.ink} strokeWidth="1" />
  }
  return (
    <Plot height={height} points={all} label={label || L('顏色－星等圖', 'Colour–magnitude diagram')}
      x={{ domain: [-0.7, 5.6], label: L('顏色 BP−RP（左藍、右紅）', 'Colour BP−RP (blue ← → red)'), ticks: small ? [0, 2, 4] : [0, 1, 2, 3, 4, 5] }}
      y={{ domain: [21, -4], label: small ? L('真實亮度', 'True brightness') : L('真實亮度（絕對星等，上亮下暗）', 'True brightness (absolute G; bright at top)'), ticks: small ? [0, 5, 10, 15, 20] : [-4, 0, 4, 8, 12, 16, 20], gutter: 34 }}>
      {({ X, Y, w, m: mg }) => <>
        {url && <image href={url} x={X(cmd.x0)} y={Y(cmd.y0)} width={X(cmd.x0 + cmd.nx * cmd.dx) - X(cmd.x0)} height={Y(cmd.y0 + cmd.ny * cmd.dy) - Y(cmd.y0)} preserveAspectRatio="none" />}
        {regions.map(([x, y, t]) => <text key={t} className="mark-label sc-region" x={X(x)} y={Y(y)}>{t}</text>)}
        {!small && <g className="sc-bd">
          <text className="mark-label sc-region" x={X(5.5)} y={Y(18.6)} textAnchor="end">{L('棕矮星：大多太暗，Gaia 看不到', 'Brown dwarfs: mostly too faint for Gaia')}</text>
          <path d={`M${X(5.0)} ${Y(19.3)}l${X(5.45) - X(5.0)} ${Y(20.6) - Y(19.3)}`} className="sc-arrow" />
        </g>}
        <circle cx={X(SUN.bp_rp)} cy={Y(SUN.abs_g)} r="7" fill="none" stroke={COL.accent} strokeWidth="2" /><circle cx={X(SUN.bp_rp)} cy={Y(SUN.abs_g)} r="2" fill={COL.accent} />
        {!small && <text className="mark-label" x={X(SUN.bp_rp) - 12} y={Y(SUN.abs_g) + 5} textAnchor="end">{L('太陽', 'Sun')}</text>}
        {pts.map((m, j) => { const left = X(m.x) > w - mg.r - 110; return <g key={j}>{shape(m, X, Y)}{m.label && <text className="mark-label sc-mlabel" x={X(m.x) + (left ? -m.r - 2 : m.r + 2)} y={Y(m.y) + (left ? -10 : 5)} textAnchor={left ? 'end' : 'start'}>{m.label}</text>}</g> })}
      </>}
    </Plot>
  )
}

const fmt = (v, d = 2) => (v == null ? '—' : v.toFixed(d))
const lyText = (pc) => { const v = pc * 3.2616; return v < 100 ? v.toFixed(1) : Math.round(v).toLocaleString('en-US') }
/** A change in magnitudes as words: a factor when large, a percentage when small. */
export const magChange = (m) => { const r = 10 ** (0.4 * m); return r >= 2 ? `×${r < 10 ? r.toFixed(1) : Math.round(r)}` : `${Math.round((r - 1) * 100)}%` }

/** Links: MAST's portal opened on its Gaia DR3 catalogue at the star (a 0.2° cone, nearest first; the star's 2016
 *  position), the star's full record in ESA's Gaia archive, and SIMBAD. */
function links(s) {
  const esa = `https://gea.esac.esa.int/tap-server/tap/sync?REQUEST=doQuery&LANG=ADQL&FORMAT=json&QUERY=${encodeURIComponent(`SELECT * FROM gaiadr3.gaia_source WHERE source_id = ${s.source_id}`)}`
  const pos = `${s.ra.toFixed(6)} ${s.dec.toFixed(6)}`
  const mast = { service: 'GAIADR3', inputText: pos, paramsService: 'Mast.Catalogs.GaiaDR3.Cone', title: `Gaia DR3: ${pos}`, columns: '*' }
  return [
    { href: `https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html?searchQuery=${encodeURIComponent(JSON.stringify(mast))}`, t: L('MAST 的 Gaia DR3（最近的排第一）', 'Gaia DR3 at MAST (nearest first)') },
    { href: esa, t: L('ESA Gaia 資料庫的完整紀錄', 'Full record in ESA’s Gaia archive') },
    { href: `https://simbad.cds.unistra.fr/simbad/sim-id?Ident=${encodeURIComponent(`Gaia DR3 ${s.source_id}`)}`, t: 'SIMBAD' },
  ]
}

/** What Gaia DR3 says about the star at a clicked position. ra/dec in degrees; mjd: when the image was taken (Gaia
 *  positions are moved there with their proper motions). */
export function StarCard({ ra, dec, mjd }) {
  useLanguage()
  const [d, setD] = useState(null)
  const [tgt, setTgt] = useState([])
  useEffect(() => {
    let live = true
    setD('loading')
    const q = `/api/gaia/star?ra=${ra.toFixed(5)}&dec=${dec.toFixed(5)}${mjd ? `&mjd=${mjd.toFixed(1)}` : ''}`
    api(q).then((r) => live && setD(r)).catch(() => live && setD('error'))
    return () => { live = false }
  }, [ra, dec, mjd])
  useEffect(() => { fetch('/data/gaia/targets.json').then((r) => (r.ok ? r.json() : null)).then((v) => setTgt(v?.targets || [])).catch(() => {}) }, [])
  if (d === 'loading' || d == null) return <div className="sc sc-wait" role="status"><i aria-hidden="true" />{L('查詢 Gaia DR3 星表…', 'Asking the Gaia DR3 catalogue…')}</div>
  if (d === 'error') return <p className="sc sc-msg" role="alert">{L('現在連不上 Gaia DR3（ESA 和 MAST 都沒有回應），請稍後再點一次。', 'Gaia DR3 cannot be reached right now (neither ESA nor MAST answered); click again later.')}</p>
  const s = d.star
  const bright = d.neighbours.filter((n) => n.g != null).sort((a, b) => a.g - b.g)[0]
  if (!s) {
    return (
      <section className="sc" aria-label={L('Gaia DR3 資料卡', 'Gaia DR3 star card')}>
        <h3 className="sc-title">{L('Gaia DR3：這裡沒有星', 'Gaia DR3: no star here')}</h3>
        <p className="sc-msg">{L(`你點的位置 ${fmt(d.r_match, 0)}″ 內（1.5 個 SPHEREx 像素）沒有 Gaia 天體。Gaia 用可見光，最暗只到 G ≈ 21：很冷的棕矮星（例如 WISE 0855）在可見光幾乎不發光，所以只出現在紅外線的 SPHEREx 影像上。`, `No Gaia source within ${fmt(d.r_match, 0)}″ (1.5 SPHEREx pixels) of your click. Gaia works in visible light down to G ≈ 21: a very cold brown dwarf (WISE 0855, for one) gives almost no visible light, so it shows up only in infrared images like SPHEREx's.`)}</p>
        {d.n_near > 0 && <p className="hint">{L(`30″ 內有 ${d.n_near} 個 Gaia 天體${bright ? `，最亮 G = ${fmt(bright.g)}，離 ${fmt(bright.sep, 1)}″` : ''}。`, `${d.n_near} Gaia source${d.n_near > 1 ? 's' : ''} within 30″${bright ? `; the brightest is G = ${fmt(bright.g)}, ${fmt(bright.sep, 1)}″ away` : ''}.`)}</p>}
      </section>
    )
  }
  const v = s.vari
  const close = d.neighbours.filter((n) => n.sep <= d.r_match && n.g != null && s.g != null && n.g < s.g + 2.5)
  const notStar = Math.max(s.p_galaxy || 0, s.p_quasar || 0) > 0.5
  const marks = [
    ...tgt.filter((t) => t.in_gaia).map((t) => ({ bp_rp: t.bp_rp, abs_g: t.abs_g, c: COL.ink3, shape: 'diamond', r: 5, tip: t.name, hint: L('挑戰測試目標', 'challenge test target') })),
    ...(s.abs_g != null ? [{ bp_rp: s.bp_rp, abs_g: s.abs_g, c: COL.warn, shape: 'star', r: 9, tip: L('你點的星', 'The star you clicked'), hint: `G ${fmt(s.g)} · BP−RP ${fmt(s.bp_rp)}` }] : []),
  ]
  return (
    <section className="sc" aria-label={L('Gaia DR3 資料卡', 'Gaia DR3 star card')}>
      <div className="sc-head">
        <h3 className="sc-title">{L('歐洲 Gaia 衛星量到的這顆星', 'This star as ESA’s Gaia satellite measured it')}</h3>
        <p className="hint">Gaia DR3 {s.source_id} · {L(`離你點的位置 ${fmt(s.sep, 1)}″`, `${fmt(s.sep, 1)}″ from your click`)}{d.service === 'mast' || d.service === 'mast-catalog' ? L('（資料來自 MAST）', ' (served by MAST)') : ''}</p>
      </div>
      <div className="sc-body">
        <dl className="sc-facts">
          <div><dt>{L('亮度 G', 'Brightness G')}</dt><dd>{fmt(s.g)}</dd><small>{L('可見光星等，數字越小越亮', 'visible-light magnitude; smaller is brighter')}</small></div>
          <div><dt>{L('顏色 BP−RP', 'Colour BP−RP')}</dt><dd>{s.bp_rp != null && <i className="sc-swatch" style={{ background: starColour(s.bp_rp) }} aria-hidden="true" />}{fmt(s.bp_rp)}</dd><small>{s.bp_rp != null ? colourWord(s.bp_rp) : L('Gaia 沒有量到顏色', 'no colour measured')}</small></div>
          <div><dt>{L('距離', 'Distance')}</dt><dd>{s.dist_pc != null ? `${s.dist_pc < 100 ? fmt(s.dist_pc, s.dist_pc < 10 ? 2 : 1) : Math.round(s.dist_pc)} pc` : '—'}</dd>
            <small>{s.dist_pc != null ? L(`約 ${lyText(s.dist_pc)} 光年；由視差 ${fmt(s.plx, 2)} mas 算出`, `about ${lyText(s.dist_pc)} light-years, from a parallax of ${fmt(s.plx, 2)} mas`) : L('視差太不準，算不出距離', 'parallax too uncertain for a distance')}</small></div>
          <div><dt>{L('自行', 'Proper motion')}</dt><dd>{s.pm != null ? `${(s.pm / 1000).toFixed(s.pm >= 1000 ? 2 : 3)}″/${L('年', 'yr')}` : '—'}</dd><small>{L('每年在天上移動的角度', 'how far it crosses the sky each year')}</small></div>
          <div><dt>RUWE</dt><dd>{fmt(s.ruwe)}</dd><small>{s.ruwe == null ? '—' : s.ruwe <= 1.4 ? L('單星模型擬合得很好', 'a single star fits it well') : L('大於 1.4：可能是雙星或有看不見的伴星', 'above 1.4: perhaps a double star or an unseen companion')}</small></div>
          <div className={v ? 'sc-var' : ''}><dt>{L('變星', 'Variable?')}</dt><dd>{s.variable === 'VARIABLE' ? L('是', 'Yes') : L('沒有標記', 'Not flagged')}</dd>
            <small>{s.variable !== 'VARIABLE' ? L('Gaia 沒有把它列為變星', 'Gaia does not list it as variable')
              : v ? `${varClass(v.cls || 'unclassified')}${v.trimmed_range_mag != null ? L(`；Gaia 看到亮度變化約 ${magChange(v.trimmed_range_mag)}`, `; Gaia saw its brightness change by about ${magChange(v.trimmed_range_mag)}`) : ''}` : L('Gaia 標為變星', 'flagged variable by Gaia')}</small></div>
        </dl>
        <figure className="sc-cmd">
          <Cmd small height={260} marks={marks} label={L('顏色－星等圖：你點的星在哪裡', 'Colour–magnitude diagram: where the clicked star sits')} />
          <figcaption className="hint">{s.abs_g != null ? L('★ 你點的星；◇ 挑戰測試目標；○ 太陽。背景是 100 秒差距內 22 萬顆 Gaia 星。', '★ the star you clicked; ◇ challenge targets; ○ the Sun. Background: 222,000 Gaia stars within 100 pc.') : L('沒有可靠的距離，無法放進這張圖。', 'Without a reliable distance it cannot be placed on this diagram.')}</figcaption>
        </figure>
      </div>
      {notStar && <p className="note lab-warn">{L('Gaia 的分類認為這比較像星系或類星體，不是恆星。', 'Gaia’s classifier thinks this is more likely a galaxy or quasar than a star.')}</p>}
      {close.length > 0 && <p className="note lab-warn">{L(`旁邊 ${fmt(close[0].sep, 1)}″ 還有一顆 G = ${fmt(close[0].g)} 的星；在 SPHEREx 6″ 的像素裡兩顆會混在一起。`, `Another star (G = ${fmt(close[0].g)}) sits ${fmt(close[0].sep, 1)}″ away; in SPHEREx's 6″ pixels the two blend into one.`)}</p>}
      <p className="sc-links">{links(s).map((k) => <a key={k.href} className="btn small" href={k.href} target="_blank" rel="noreferrer">{k.t} ↗</a>)}</p>
      {d.n_near > 1 && <p className="hint">{L(`30″ 內還有 ${d.n_near - 1} 個 Gaia 天體。`, `${d.n_near - 1} more Gaia source${d.n_near > 2 ? 's' : ''} within 30″.`)}</p>}
    </section>
  )
}

/** The target list's card: the challenge's targets and every moving star the search found, on the CMD. */
export function CmdCard() {
  useLanguage()
  const [m, setM] = useState(null)
  useEffect(() => {
    api('/api/gaia/marks').then(setM).catch(() => fetch('/data/gaia/targets.json').then((r) => r.json()).then((t) => setM({ targets: t.targets, movers: [] })).catch(() => setM(false)))
  }, [])
  const tg = m?.targets || [], mv = (m?.movers || []).filter((x) => x.in_gaia && !tg.some((t) => t.source_id === x.source_id))
  const missing = tg.filter((t) => !t.in_gaia)
  // moving objects with no Gaia star, other than a target already named as missing (WISE 0855 moves ~8″ a year)
  const mvOut = (m?.movers || []).filter((x) => x.in_gaia === false && !missing.some((t) => Math.hypot((x.ra - t.ra) * Math.cos(t.dec * Math.PI / 180), x.dec - t.dec) < 0.1))
  const name = (t) => ({ barnard: L('巴納德星', 'Barnard’s Star'), epsindi: L('印第安座 ε B', 'Eps Indi B'), rwaur: L('御夫座 RW', 'RW Aur'), rdra: L('天龍座 R', 'R Dra'), wise0855: 'WISE 0855' }[t.id] || t.name)
  const marks = [
    ...mv.map((x) => ({ bp_rp: x.bp_rp, abs_g: x.abs_g, c: COL.known, shape: 'dot', r: 6,
      tip: L(`SPHEREx 找到的移動星：${x.pm_arcsec_yr?.toFixed(2)}″/年`, `Moving star found by SPHEREx: ${x.pm_arcsec_yr?.toFixed(2)}″/yr`),
      hint: `Gaia DR3 ${x.source_id} · G ${x.g?.toFixed(1)}${x.dist_pc ? ` · ${x.dist_pc < 100 ? x.dist_pc.toFixed(1) : Math.round(x.dist_pc)} pc` : ''}` })),
    ...tg.filter((t) => t.in_gaia).map((t) => ({ bp_rp: t.bp_rp, abs_g: t.abs_g, c: t.kind === 'pm' ? COL.distant : COL.good, shape: 'star', r: 9, label: name(t),
      tip: name(t), hint: `G ${t.g.toFixed(2)} · BP−RP ${t.bp_rp?.toFixed(2)} · ${t.dist_pc < 100 ? t.dist_pc.toFixed(2) : Math.round(t.dist_pc)} pc` })),
  ]
  return (
    <section className="tg-cmd sec" aria-labelledby="tg-cmd-h">
      <ChartCard level={2} title={<span id="tg-cmd-h">{L('它們是什麼樣的星？', 'What kind of stars are they?')}</span>}
        take={L('橫軸是顏色，縱軸是真實亮度（已扣掉距離）。太陽附近 22 萬顆星排成幾條帶：大部分是主序星，左下是白矮星。巴納德星是暗紅的紅矮星；天龍座 R 是很亮的紅巨星。', 'Across: colour. Up: true brightness (distance taken out). The 222,000 stars near the Sun fall into bands: most on the main sequence, white dwarfs at lower left. Barnard’s Star is a dim red dwarf; R Draconis a luminous red giant.')}
        legend={[{ c: COL.distant, label: L('移動很快的測試目標', 'Fast-moving test targets') }, { c: COL.good, label: L('變星測試目標', 'Variable test targets') }, { c: COL.known, label: L(`SPHEREx 自動找到的移動星（${mv.length}）`, `Moving stars the search found (${mv.length})`) }, { c: COL.accent, hollow: true, label: L('太陽', 'The Sun') }]}
        more={<>
          <p>{L('背景：Gaia DR3 裡距離 100 秒差距（326 光年）以內、視差誤差小於 10%、顏色量得準的 222,000 顆星，分格計數（深淺代表星數，對數）。', 'Background: the 222,000 Gaia DR3 stars within 100 pc (326 light-years) with parallax errors under 10% and clean colours, counted in bins (shade = number of stars, logarithmic).')}</p>
          <p>{L('真實亮度（絕對星等）= 視星等 G + 5 log₁₀(視差／100 mas)：把每顆星都搬到同樣距離再比亮度。資料由 ESA 的 Gaia 資料庫提供；連不上時改用 MAST。', 'True brightness (absolute magnitude) = G + 5 log₁₀(parallax / 100 mas): every star moved to the same distance before comparing. Data from ESA’s Gaia archive, with MAST as the fallback.')}</p>
        </>}>
        {m === null ? <div className="skel-card sc-skel" /> : <Cmd marks={marks} height={460} />}
        {(missing.length > 0 || mvOut.length > 0) && <p className="hint">{missing.map((t) => L(`${name(t)} 不在 Gaia 星表裡：它太冷、在可見光太暗，只有紅外線看得到。`, `${name(t)} is not in Gaia: too cold and faint in visible light; only infrared sees it.`)).join(' ')}{mvOut.length > 0 && L(` 另有 ${mvOut.length} 顆 SPHEREx 找到的移動天體在 Gaia 裡沒有對應的星。`, ` ${mvOut.length} more moving object${mvOut.length > 1 ? 's' : ''} found by SPHEREx ${mvOut.length > 1 ? 'have' : 'has'} no Gaia counterpart.`)}</p>}
      </ChartCard>
    </section>
  )
}
