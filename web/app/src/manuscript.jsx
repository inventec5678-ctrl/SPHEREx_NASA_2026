import { useEffect, useState } from 'react'
import { L, paperUrl } from '@sx/i18n/core.js'
import { api } from './lib.js'
import { go, goUniverse } from './nav.js'
import { BigNumber } from './fx.jsx'

/*
 * The home page as one argument, in the order of the paper:
 *   00 PARALLAX (opening, parallax.jsx) · 01 Method · 02 Validation · 03 The search · 04 Your turn · 05 Paper.
 * Every number comes from /paper/research/manuscript.json, written by scripts/render_paper.py from
 * scripts/paper_aas.py, so the page and the paper cannot drift apart. Text is given in both languages here.
 */
export const PDF = '/paper/static/pdfs/spherex_movers_manuscript.pdf'

export function useManuscript() {
  const [v, setV] = useState(null)
  useEffect(() => { api('/paper/research/manuscript.json').then(setV).catch(() => {}) }, [])
  return v
}

export const CHAPTERS = [
  { id: 'ch-method', en: 'Method', zh: '方法' },
  { id: 'ch-valid', en: 'Validation', zh: '驗證' },
  { id: 'ch-search', en: 'The search', zh: '搜尋' },
  { id: 'ch-tools', en: 'Your turn', zh: '換你' },
  { id: 'ch-paper', en: 'Paper', zh: '論文' },
]

/** Fixed chapter rail (desktop): appears after the opening, marks the chapter in view. */
export function ChapterRail({ lang }) {
  const [on, setOn] = useState(-1)
  const [fill, setFill] = useState(0)
  useEffect(() => {
    // measured on scroll and resize (at most once per frame), not polled every frame: each pass forces layout
    let raf = 0
    const tick = () => {
      raf = 0
      let k = -1
      CHAPTERS.forEach((c, i) => { const el = document.getElementById(c.id); if (el && el.getBoundingClientRect().top < innerHeight * 0.4) k = i })
      setOn((o) => (o === k ? o : k))
      const first = document.getElementById(CHAPTERS[0].id), doc = document.documentElement
      if (first) {
        const a = first.offsetTop, b = doc.scrollHeight - innerHeight
        const f = Math.min(1, Math.max(0, (scrollY - a) / Math.max(1, b - a)))
        setFill((x) => (Math.abs(x - f) < 0.002 ? x : f))
      }
    }
    const queue = () => { if (!raf) raf = requestAnimationFrame(tick) }
    queue()
    window.addEventListener('scroll', queue, { passive: true }); window.addEventListener('resize', queue)
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(queue) : null    // content loading below moves the chapters
    ro?.observe(document.body)
    return () => { cancelAnimationFrame(raf); window.removeEventListener('scroll', queue); window.removeEventListener('resize', queue); ro?.disconnect() }
  }, [])
  return (
    <nav className={`ch-rail ${on >= 0 ? 'show' : ''}`} aria-label={L('章節', 'Chapters')}>
      <div className="bar"><i style={{ transform: `scaleX(${fill})` }} /></div>
      <ol>{CHAPTERS.map((c, i) => (
        <li key={c.id}><a href={`#${c.id}`} className={i === on ? 'on' : ''}
          onClick={(e) => { e.preventDefault(); document.getElementById(c.id)?.scrollIntoView({ behavior: 'smooth' }) }}>{L(c.zh, c.en)}</a></li>
      ))}</ol>
    </nav>
  )
}

export function ChapterHead({ n, label, title, children }) {
  return (
    <div className="ch-head reveal">
      <p className="ms-eyebrow">{n} · {label}</p>
      <h2 className="ms-display">{title}</h2>
      {children}
    </div>
  )
}

const Stat = ({ v, k }) => <div className="ms-stat ms-brackets"><span className="v">{v}</span><span className="k">{k}</span></div>

/** 01 · the question the opening asked, answered in two paragraphs; the method story follows. */
export function MethodHead({ v, lang }) {
  return (
    <ChapterHead n="01" label={L('方法', 'Method')} title={L('一年之內，從地球公轉軌道的兩側看同一顆天體。', 'Within a year, every distant body is seen from both sides of Earth’s orbit.')}>
      <div className="ms-cols">
        <p className="ms-lead">{L('SPHEREx 每六個月掃描全天一次，涵蓋 0.75–5.0 μm 的 102 個頻道。相隔半年的兩次巡天，從地球軌道的兩側觀測同一顆遠方天體，視差直接給出距離，不必假設任何軌道。', 'SPHEREx maps the whole sky every six months in 102 channels between 0.75 and 5.0 μm. Passes half a year apart see the same distant body from opposite sides of Earth’s orbit, so its parallax gives its distance directly, without assuming an orbit.')}</p>
        <p className="ms-body">{L('線性漸變濾鏡讓每張曝光的波長都不同，所以我們把每張影像與逐像素波長相符的參考影像相減，用只以模擬資料訓練的分類器分開真實源與假訊號，跨巡天連線，再同時擬合視差與有上限的軌道漂移。下面用真實影像走一遍每個步驟。', 'Its linear variable filters give every exposure a different wavelength, so we difference each image against references matched in wavelength pixel by pixel, let a classifier trained only on simulations separate real sources from artifacts, link them across passes, and fit parallax jointly with a bounded orbital drift. The real images below show each step.')}</p>
      </div>
    </ChapterHead>
  )
}

/** 02 · one evidence block (replaces the two stat strips of the old home page). */
export function Validation({ v, lang }) {
  if (!v) return null
  return (
    <section id="ch-valid" className="ms-band" aria-labelledby="h-valid">
      <ChapterHead n="02" label={L('驗證', 'Validation')} title={<span id="h-valid">{L('有效嗎？在沒看過的資料上量。', 'Does it work? Measured on data it never saw.')}</span>} />
      <div className="ms-split" style={{ marginTop: '2.4rem' }}>
        <div className="reveal">
          <div className="ms-big"><BigNumber>{v.kc_auc}</BigNumber></div>
          <p className="ms-body">{L(`分類器只用注入影像的模擬源訓練。在 ${v.kc_fields} 個它沒看過的天區裡，它把 ${v.kc_n} 次真實已知小行星的偵測和同一批天區的假訊號分開（AUROC）；只看顯著度只有 ${v.kc_snr}，和亂猜一樣。`, `The classifier was trained only on simulated sources injected into the images. In ${v.kc_fields} fields it never saw, it separates ${v.kc_n} detections of real known asteroids from the artifacts of the same fields (AUROC); significance alone scores ${v.kc_snr}, no better than chance.`)}</p>
          <div className="ms-stats tight">
            <Stat v={`${v.kc_rec}%`} k={L(`假訊號 ${v.kc_fpr}% 時保留的已知小行星`, `Known asteroids kept at ${v.kc_fpr}% artifacts`)} />
            <Stat v={`AB ${v.mag50}`} k={L('單張曝光 50% 完整度', 'Single-exposure 50% completeness')} />
            <Stat v={`${v.a_med}″`} k={L('與 JPL 星曆的位置誤差中位數', 'Median astrometric error vs JPL')} />
            <Stat v={`${v.g3_rec}/${v.g3_n}`} k={L(`500–3000 au 注入天體找回；距離誤差中位數 ${v.g_med}%`, `Injected bodies at 500–3000 au recovered; median distance error ${v.g_med}%`)} />
          </div>
        </div>
        <figure className="ms-plate ms-brackets reveal">
          <img src="/paper/figures/aj/dwarfs-dark.svg" alt={L('Makemake 與 Haumea 的盲搜軌跡', 'Blind tracks of Makemake and Haumea')} loading="lazy" />
          <figcaption><span>{L('真實矮行星', 'Real dwarf planets')}</span>{L(`在跟隨兩顆矮行星的天區中，盲搜量到 Makemake ${v.mm_d} au（JPL ${v.mm_jpl}）、Haumea ${v.hm_d} au（JPL ${v.hm_jpl}），誤差 ${v.mm_err}% 與 ${v.hm_err}%，只用三個觀測窗、不看任何星表。`, `In fields following them, a blind search measures Makemake at ${v.mm_d} au (JPL ${v.mm_jpl}) and Haumea at ${v.hm_d} au (JPL ${v.hm_jpl}): errors of ${v.mm_err}% and ${v.hm_err}%, from three observing windows and no catalogue.`)}</figcaption>
        </figure>
      </div>
    </section>
  )
}

/** 03 · the Planet Nine search, stated once, with what it does and does not exclude. */
export function Search({ v, lang }) {
  if (!v) return null
  return (
    <section id="ch-search" className="ms-band" aria-labelledby="h-search">
      <ChapterHead n="03" label={L('搜尋', 'The search')} title={<span id="h-search">{L('沿第九行星的預測路徑：沒有新行星。', 'Along the predicted path of Planet Nine: no new planet.')}</span>} />
      <div className="ms-split" style={{ marginTop: '2.4rem' }}>
        <div className="reveal">
          <p className="ms-lead">{L(`我們沿預測路徑及一個 IRAS/AKARI 候選位置搜尋了 ${v.sv_fields} 個天區、${v.sv_area} 平方度。單張曝光沒有任何遠方天體；疊加在稀疏天區、400 au 以外達 AB ${v.st_m50}，在銀河面附近約 AB ${v.effA}。`, `We searched ${v.sv_area} deg² in ${v.sv_fields} fields along the predicted path and around a proposed IRAS/AKARI candidate. No distant body appears in single exposures. Stacking reaches AB ${v.st_m50} beyond 400 au in uncrowded fields and AB ≈${v.effA} near the Galactic plane.`)}</p>
          <p className="ms-body">{L(`疊加連出的 ${v.sv_raw} 條軌跡，與打亂巡天時間（真實天體不可能連上）時得到的 ${v.nl_a}、${v.nl_b} 條相當，屬於隨機重合。固定天區只在約 ${v.d_field} au 以外留得住天體；在其中，反照率 0.4、太陽色的條件下，排除了 ${v.nep_b} 的海王星大小與 ${v.jup_b} 的木星大小天體。強甲烷吸收可能讓後者失效，而搜尋範圍不到第九行星容許區域的 1%。`, `The ${v.sv_raw} stacked tracks match the ${v.nl_a} and ${v.nl_b} found when the pass epochs are relabelled — when no real body could link — so they are chance alignments. Fixed fields retain a body over three passes only beyond ≈${v.d_field} au; within them, for an albedo of 0.4 and solar colours, the data exclude Neptune-sized bodies at ${v.nep_b} and Jupiter-sized bodies at ${v.jup_b}. Strong methane absorption could remove the latter, and the searched fields cover well under 1% of the region allowed for Planet Nine.`)}</p>
          <p className="ms-note">{L('我們沒有發現新行星；任何候選都只是需要後續觀測的對象。', 'We have not discovered a new planet. Any candidate would only be a target for follow-up observation.')}</p>
          <div className="ms-actions"><a className="btn primary" href="#/discovery">{L('打開完整的搜尋過程', 'Open the search, step by step')}</a></div>
        </div>
        <div>
          <figure className="ms-plate ms-brackets reveal"><img src="/paper/figures/aj/null-dark.svg" alt={L('真實與打亂巡天時間的軌跡數', 'Tracks with true and relabelled pass epochs')} loading="lazy" />
            <figcaption><span>{L('隨機對照', 'Chance control')}</span>{L('每個天區用真實與打亂時間得到的疊加軌跡數：兩者相當。', 'Stacked tracks per field with the true and the relabelled epochs: the two agree.')}</figcaption></figure>
          <figure className="ms-plate ms-brackets reveal"><img src="/paper/figures/aj/radius-dark.svg" alt={L('未被偵測的最大直徑對距離', 'Largest undetected diameter against distance')} loading="lazy" />
            <figcaption><span>{L('限制', 'Limits')}</span>{L('搜尋路徑上不會被偵測到的最大天體；點線為強甲烷吸收的參數化示意。', 'Largest body that would remain undetected along the searched path; dotted: strong methane absorption (parametric).')}</figcaption></figure>
        </div>
      </div>
    </section>
  )
}

/** 04 · the way into the tools (the field list and the analysis form follow in landing.jsx). */
export function ToolsHead({ lang }) {
  return (
    <div className="ms-band" style={{ paddingBottom: 0 }}>
      <ChapterHead n="04" label={L('換你', 'Your turn')} title={L('每一片天空，都可以播放、放大、逐一檢查。', 'Every patch of sky can be played, zoomed and checked.')}>
        <p className="ms-lead">{L('打開一片天空，點任何天體看它的證據；點影像上任何一點，問它是恆星、小行星，還是可能的遠方行星；或把整片天空重建成光譜組成的宇宙。', 'Open a field, follow any object to its evidence, click any point to ask whether it is a star, an asteroid or a possible distant planet, or rebuild the field as a universe of spectra.')}</p>
        <div className="ms-actions">
          <button className="btn primary" onClick={() => go('cybele')}>{L('探索 65 Cybele 的天空', 'Explore 65 Cybele’s sky')}</button>
          <button className="btn" onClick={() => go('planetx')}>{L('看模擬行星的視差', 'See the simulated planet’s parallax')}</button>
          <button className="btn" onClick={() => goUniverse('cybele')}>{L('星體重建', 'Body reconstruction')}</button>
        </div>
      </ChapterHead>
    </div>
  )
}

/** 05 · paper and citation. */
export function PaperCite({ lang }) {
  return (
    <section id="ch-paper" className="ms-band" aria-labelledby="h-paper">
      <div className="ms-split">
        <ChapterHead n="05" label={L('論文', 'Paper')} title={<span id="h-paper">{L('閱讀論文。', 'Read the paper.')}</span>}>
          <p className="ms-body">{L('《Probing the Outer Solar System with SPHEREx: Parallax-Guided Moving-Object Discovery and Limits on Distant Bodies in All-Sky Spectral Imaging》——AJ 格式稿件，匿名審查版。', 'Probing the Outer Solar System with SPHEREx: Parallax-Guided Moving-Object Discovery and Limits on Distant Bodies in All-Sky Spectral Imaging — AJ-format manuscript, anonymised for review.')}</p>
          <div className="ms-actions">
            <a className="btn primary" href={paperUrl('paper')}>{L('論文全文', 'Full paper')}</a>
            <a className="btn" href={PDF}>PDF</a>
            <a className="btn" href="/paper/research/evidence.json">{L('證據資料 JSON', 'Evidence JSON')}</a>
          </div>
        </ChapterHead>
        <pre className="ms-bib reveal" tabIndex={0} aria-label="BibTeX">{`@unpublished{spherex_parallax_2026,
  title  = {Probing the Outer Solar System with SPHEREx: Parallax-Guided
            Moving-Object Discovery and Limits on Distant Bodies in
            All-Sky Spectral Imaging},
  author = {{Anonymous}},
  year   = {2026},
  note   = {Manuscript prepared for The Astronomical Journal}
}`}</pre>
      </div>
    </section>
  )
}
