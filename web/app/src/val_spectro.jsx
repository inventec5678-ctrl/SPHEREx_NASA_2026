// Validation card: each challenge target's spectrum, ours against IRSA's official SPHEREx Spectrophotometry Tool,
// exposure by exposure (scripts/irsa_spectro_compare.py -> /data/validation/spectro.json). Renders nothing until that
// file exists. Left: both spectra; right: ours / IRSA for every shared exposure, coloured by survey pass.
import { useEffect, useState } from 'react'
import { L } from './lib.js'
import { COL, ChartCard, Plot, extent } from './charts.jsx'
import './val_spectro.css'

let pending = null
const load = () => (pending ||= fetch('/data/validation/spectro.json').then((r) => (r.ok ? r.json() : null)).catch(() => null))

// point columns written by the script
const LAM = 0, IR = 1, IR_E = 2, AP = 3, PSF = 4, PASS = 5, DET = 6, BITS = 7
const B_IRSA_OK = 1, B_USE_AP = 4, B_USE_PSF = 8

const NAME = () => ({ barnard: L('巴納德星', "Barnard's Star"), epsindi: L('天苑增三 B', 'Epsilon Indi B'), wise0855: 'WISE 0855', rwaur: L('御夫座 RW', 'RW Aurigae'), rdra: L('天龍座 R', 'R Draconis') })
const SHORT = () => ({ barnard: L('巴納德星', 'Barnard'), epsindi: L('天苑增三 B', 'Eps Indi B'), wise0855: 'WISE 0855', rwaur: L('御夫座 RW', 'RW Aur'), rdra: L('天龍座 R', 'R Dra') })

const fmtFlux = (v) => (v == null || !isFinite(v) ? '—' : Math.abs(v) >= 1e6 ? `${(v / 1e6).toPrecision(3)} Jy` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toPrecision(3)} mJy` : `${v.toPrecision(3)} µJy`)
const fmtTick = (v) => (v >= 1e6 ? `${v / 1e6} Jy` : v >= 1e3 ? `${v / 1e3} mJy` : `${v} µJy`)
const pct = (x) => `${Math.round(Math.abs(x) * 100)}%`
const times = (x) => `×${x.toFixed(2)}`

/** One plain sentence per target: what the comparison can and cannot say. */
function honest(t, s, byPass) {
  const n = NAME()[t.id] || t.name
  if (!t.meaningful || !s) {
    if (t.caveat === 'saturated') return L(`${n}太亮，在每個波段都讓偵測器飽和：兩邊都只量得到星的外圍，這兩條曲線不能判斷誰對。`, `${n} is so bright that it saturates the detector in every band: both tools see only its wings, so these curves cannot say which is right.`)
    return L(`${n}沒有夠多兩邊都可靠的點可以比較。`, `${n} has too few points that both tools measure reliably to compare.`)
  }
  const d = s.median - 1, close = Math.abs(d) < 0.05
  const verdict = close ? L(`兩邊相差不到 5%（中位數 ${times(s.median)}）`, `the two agree within 5% (median ${times(s.median)})`)
    : d > 0 ? L(`我們的比 IRSA 高 ${pct(d)}`, `ours is ${pct(d)} brighter than IRSA's`) : L(`我們的比 IRSA 低 ${pct(d)}`, `ours is ${pct(d)} fainter than IRSA's`)
  const passes = (byPass || []).filter((q) => q.pass >= 0).map((q) => times(q.median)).join(L('、', ', '))
  const why = {
    variable: L(`${n}的亮度會變，所以每一點都和同一張影像的 IRSA 量測比（各輪 ${passes}）`, `${n} changes brightness, so each point is compared with IRSA’s measurement of the same exposure (per pass ${passes})`),
    faint: L(`${n}很暗，只有 ${s.n} 張影像兩邊的訊噪比都超過 10`, `${n} is faint: only ${s.n} exposures have S/N above 10 in both`),
    pair: L(`${n}是相距 0.7″ 的兩顆棕矮星，兩邊都當成一個點量`, `${n} is two brown dwarfs 0.7″ apart, measured as one point by both`),
  }[t.caveat]
  return why ? L(`${why}；${verdict}。`, `${why}; ${verdict}.`) : L(`${n}：${verdict}。`, `${n}: ${verdict}.`)
}

export default function ValSpectro() {
  const [doc, setDoc] = useState(null)
  const [pick, setPick] = useState(null)
  const [mode, setMode] = useState('psf')
  useEffect(() => { let on = true; load().then((d) => on && setDoc(d)); return () => { on = false } }, [])
  const tg = doc?.targets || []
  if (!tg.length) return null
  const names = NAME(), short = SHORT()
  const t = tg.find((x) => x.id === pick) || tg.find((x) => x.meaningful && x.ratio_psf) || tg[0]
  const useBit = mode === 'psf' ? B_USE_PSF : B_USE_AP, col = mode === 'psf' ? PSF : AP
  const stat = mode === 'psf' ? t.ratio_psf : t.ratio_aperture
  const good = tg.filter((x) => x.meaningful && x.ratio_psf)
  const lo = Math.min(...good.map((x) => x.ratio_psf.median)), hi = Math.max(...good.map((x) => x.ratio_psf.median))
  const nPass = Math.max(1, ...t.points.map((p) => p[PASS] + 1))

  // left: both spectra
  const ours = t.points.filter((p) => p[col] != null && p[col] > 0)
  const irsa = t.points.filter((p) => p[IR] != null && p[IR] > 0)
  const yd = extent([...irsa.map((p) => p[IR]), ...ours.map((p) => p[col])], 0.08, true)
  const specPts = [
    ...irsa.map((p) => ({ x: p[LAM], y: p[IR], r: 6, tip: `IRSA ${fmtFlux(p[IR])} ± ${fmtFlux(p[IR_E])}`, hint: `${p[LAM].toFixed(3)} µm · D${p[DET]}${p[BITS] & B_IRSA_OK ? '' : L(' · 有壞像素旗標', ' · bad-pixel flag')}` })),
    ...ours.map((p) => ({ x: p[LAM], y: p[col], r: 6, tip: `${L('我們', 'Ours')} ${fmtFlux(p[col])}`, hint: `${p[LAM].toFixed(3)} µm · D${p[DET]} · ${L(`第 ${p[PASS] + 1} 輪`, `pass ${p[PASS] + 1}`)}` })),
  ]
  // right: ours / IRSA, same exposure
  const ratios = t.points.filter((p) => p[col] != null && p[IR] > 0 && p[col] > 0).map((p) => ({ p, v: p[col] / p[IR], use: !!(p[BITS] & useBit) }))
  const rUse = ratios.filter((r) => r.use).map((r) => r.v)
  const rd = extent([...rUse, 0.5, 2], 0.04, true)
  const clamp = (v) => Math.min(rd[1], Math.max(rd[0], v))
  const tri = (x, y, up) => `M${x - 5} ${up ? y + 4 : y - 4}L${x + 5} ${up ? y + 4 : y - 4}L${x} ${up ? y - 4 : y + 4}Z`
  const ratioPts = ratios.map((r) => ({ x: r.p[LAM], y: clamp(r.v), r: 7, tip: `${L('我們 / IRSA', 'Ours / IRSA')} ${times(r.v)}`, hint: `${r.p[LAM].toFixed(3)} µm · D${r.p[DET]} · ${L(`第 ${r.p[PASS] + 1} 輪`, `pass ${r.p[PASS] + 1}`)}${r.use ? '' : L(' · 不列入統計（有旗標或訊噪比低）', ' · not counted (flagged or low S/N)')}` }))
  const rTicks = [0.25, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 4].filter((v) => v >= rd[0] && v <= rd[1])
  const xd = [0.7, 5.1], xt = [1, 2, 3, 4, 5]

  const nGood = good.length === 1 ? L('1 個', 'the one target') : L(`${good.length} 個`, `the ${good.length} targets`)
  const take = good.length
    ? <>{L(`同一顆星、同一張影像：${nGood}能比的目標，我們的 PSF 擬合亮度是 IRSA 的 `, `Same star, same exposure: for ${nGood} that can be compared, our PSF-fit brightness is `)}<b>{lo === hi ? times(lo) : `${times(lo)}–${times(hi)}`}</b>{L('（中位數）。', ' IRSA’s (median).')}</>
    : L('還沒有能比較的目標。', 'No target can be compared yet.')
  const iJobs = t.irsa.jobs || []
  const rel = Object.entries(t.ours.releases || {}).map(([k, n]) => `${k} ${n}`).join(' · ')
  const coll = Object.entries(t.irsa.collections || {}).map(([k, n]) => `${k.toUpperCase()} ${n}`).join(' · ')
  return (
    <ChartCard className="vs-card" id="val-spectro"
      title={L('我們的光譜 vs IRSA 官方工具', 'Our spectra vs IRSA’s official tool')}
      take={take}
      legend={[
        { c: COL.known, label: L('IRSA 光譜測光工具', 'IRSA Spectrophotometry Tool') },
        { c: COL.good, label: mode === 'psf' ? L('我們：PSF 擬合', 'Ours: PSF fit') : L('我們：孔徑測光', 'Ours: aperture') },
        { c: COL.ink3, hollow: true, label: L('有旗標或訊噪比低，不列入統計（▲▼ 超出圖外）', 'Flagged or low S/N, not counted (▲▼ off the chart)') },
      ]}
      more={<>
        <p>{L('IRSA 的工具在每一張 SPHEREx 影像的同一個位置擬合官方 PSF（強制測光），得到一條光譜。我們把它和自己量的光譜逐張配對（同一次曝光、同一個偵測器），所以變星本身的亮度變化會互相抵消。會動的星每輪送一次，位置用 Gaia 的自行和視差推到那一輪。', 'IRSA’s tool fits the official PSF at a fixed position in every SPHEREx image (forced photometry) and returns a spectrum. We pair it with ours exposure by exposure (same exposure, same detector), so a variable star’s own changes cancel. Moving stars are sent once per pass, at the position Gaia’s motion and parallax give for that pass.')}</p>
        <p>{L(`這個目標：IRSA ${t.irsa.n} 點（${coll}），配對到 ${t.n_matched} 張；我們的天區 ${t.ours.field_created || ''} 建立（${rel}）。統計只用兩邊都沒有旗標、訊噪比都超過 ${doc.selection?.snr_min ?? 10} 的點；分散是中位數絕對偏差 × 1.48。`, `This target: IRSA returned ${t.irsa.n} points (${coll}), ${t.n_matched} paired with ours; our field was built ${t.ours.field_created || ''} (${rel}). Statistics use only points unflagged in both with S/N above ${doc.selection?.snr_min ?? 10}; the scatter is 1.48 × the median absolute deviation.`)}</p>
        {t.dlam_um && <p>{L(`波長：我們的比 IRSA 短 ${Math.abs(t.dlam_um.median * 1000).toFixed(1)} nm（中位數）。原因是我們算波長時沒有關掉天空座標用的 SIP 變形項，IRSA 的教學有關；改正寫在開發者說明。`, `Wavelength: ours is ${Math.abs(t.dlam_um.median * 1000).toFixed(1)} nm shorter than IRSA’s (median). Our wavelength map kept the SIP distortion terms that belong to the sky coordinates; IRSA’s tutorials turn them off. The fix is in the developer notes.`)}</p>}
        <p>{L('我們的孔徑測光半徑 2 像素、沒有做孔徑修正，所以會比總亮度少一點；PSF 擬合才和 IRSA 的量法相同。', 'Our aperture photometry uses a 2-pixel radius without an aperture correction, so it misses some light; the PSF fit is the method comparable to IRSA’s.')}{' '}<a href={doc.tool?.url}>{L('IRSA 光譜測光工具', 'IRSA Spectrophotometry Tool')}</a> · <a href={doc.tool?.help}>{L('說明文件', 'its documentation')}</a>{iJobs.length > 0 && L(` · IRSA 工作 ${iJobs.length} 個，${(iJobs[0].submitted || '').slice(0, 10)} 送出`, ` · ${iJobs.length} IRSA jobs, sent ${(iJobs[0].submitted || '').slice(0, 10)}`)}</p>
      </>}>
      <div className="vs-bar">
        <div className="seg" role="group" aria-label={L('選目標', 'Choose a target')}>
          {tg.map((x) => { const r = mode === 'psf' ? x.ratio_psf : x.ratio_aperture; return <button key={x.id} type="button" aria-pressed={x.id === t.id} onClick={() => setPick(x.id)}>{short[x.id] || x.name}<small className="vs-r">{x.meaningful && r ? times(r.median) : '—'}</small></button> })}
        </div>
        <div className="seg" role="group" aria-label={L('我們的量法', 'Our method')}>
          <button type="button" aria-pressed={mode === 'psf'} onClick={() => setMode('psf')}>{L('PSF 擬合', 'PSF fit')}</button>
          <button type="button" aria-pressed={mode === 'ap'} onClick={() => setMode('ap')}>{L('孔徑', 'Aperture')}</button>
        </div>
      </div>
      <p className={`vs-line ${t.meaningful && stat ? '' : 'warn'}`}>{honest(t, stat, mode === 'psf' ? t.ratio_psf_by_pass : t.ratio_aperture_by_pass)}</p>
      <div className="vs-stats">
        <div><span>{L('我們 / IRSA（中位數）', 'Ours / IRSA (median)')}</span><strong>{stat ? times(stat.median) : '—'}</strong></div>
        <div><span>{L('逐張分散', 'Scatter, per exposure')}</span><strong>{stat ? `±${pct(stat.scatter)}` : '—'}</strong></div>
        <div><span>{L('比較的影像', 'Exposures compared')}</span><strong>{stat ? stat.n : 0}<small> / {t.n_matched}</small></strong></div>
      </div>
      <div className="vd-two vs-two">
        <div>
          <p className="vd-sub">{L(`${names[t.id] || t.name}的光譜`, `${names[t.id] || t.name}: the spectrum`)}</p>
          <Plot height={300} points={specPts} label={L('光譜：我們和 IRSA 的', 'Spectrum: ours and IRSA’s')}
            x={{ domain: xd, ticks: xt, fmt: (v) => `${v}`, label: L('波長（微米）', 'Wavelength (µm)') }}
            y={{ domain: yd, log: true, fmt: fmtTick, gutter: 62 }}>
            {({ X, Y }) => <>
              {irsa.map((p, j) => <circle key={`i${j}`} cx={X(p[LAM])} cy={Y(p[IR])} r="3.5" fill={p[BITS] & B_IRSA_OK ? COL.known : 'none'} stroke={COL.known} strokeOpacity={p[BITS] & B_IRSA_OK ? 0 : 0.6} strokeWidth="1.5" />)}
              {ours.map((p, j) => <circle key={`o${j}`} cx={X(p[LAM])} cy={Y(p[col])} r="3" fill={p[BITS] & useBit ? COL.good : 'none'} stroke={COL.good} strokeOpacity={p[BITS] & useBit ? 0 : 0.55} strokeWidth="1.5" />)}
            </>}
          </Plot>
        </div>
        <div>
          <p className="vd-sub">{L('我們 ÷ IRSA，同一張影像（顏色是巡天輪次）', 'Ours ÷ IRSA, same exposure (colour: survey pass)')}</p>
          <Plot height={300} points={ratioPts} label={L('我們和 IRSA 的亮度比', 'Brightness ratio, ours over IRSA')}
            x={{ domain: xd, ticks: xt, fmt: (v) => `${v}`, label: L('波長（微米）', 'Wavelength (µm)') }}
            y={{ domain: rd, log: true, ticks: rTicks, fmt: (v) => `×${v}`, gutter: 48 }}>
            {({ X, Y, m, w }) => <>
              <line className="vd-ref" x1={m.l} x2={w - m.r} y1={Y(1)} y2={Y(1)} />
              {stat && <line className="vs-med" x1={m.l} x2={w - m.r} y1={Y(stat.median)} y2={Y(stat.median)} />}
              {ratios.map((r, j) => (r.v > rd[1] || r.v < rd[0]
                ? <path key={j} d={tri(X(r.p[LAM]), Y(clamp(r.v)), r.v > rd[1])} fill="none" stroke={COL.ink3} strokeWidth="1.5" strokeOpacity=".6" />
                : <circle key={j} cx={X(r.p[LAM])} cy={Y(r.v)} r={r.use ? 3.5 : 3} fill={r.use ? COL.pass[r.p[PASS]] || COL.ink2 : 'none'} stroke={r.use ? 'none' : COL.ink3} strokeWidth="1.5" strokeOpacity=".6" />))}
            </>}
          </Plot>
          {nPass > 1 && <ul className="legend">{Array.from({ length: nPass }, (_, k) => <li key={k}><i style={{ '--c': COL.pass[k] }} />{L(`第 ${k + 1} 輪`, `Pass ${k + 1}`)}</li>)}<li><i className="line" style={{ '--c': COL.accent }} />{L('中位數', 'Median')}</li></ul>}
        </div>
      </div>
    </ChartCard>
  )
}
