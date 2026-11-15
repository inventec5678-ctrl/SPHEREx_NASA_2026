// "Other telescopes" links for a position: WiseView (WISE over more than ten years), the Legacy Surveys viewer, SIMBAD,
// VizieR and IRSA's own SPHEREx search (UPGRADE_PLAN.md §10, R7). Each is a button with a picture of what it adds.
import { L } from './lib.js'
import './wiseview.css'

const f6 = (v) => (+v).toFixed(6)
/**
 * WiseView link (https://byw.tools/wiseview, the Backyard Worlds blink tool). Parameters read from its source
 * (flash3.js, fromUrl / buildUrl): ra, dec in degrees; size = field of view in arcsec (176 by default, at most 2000);
 * band 1 = W1, 2 = W2, 3 = W1+W2 in colour; speed = blink interval in ms; minbright / maxbright = pixel-value limits;
 * window = years per time-resolved coadd; diff_window = years left out around each epoch in difference mode;
 * linear = the "a" of its asinh stretch (1 is nearly linear); zoom = screen pixels per WISE pixel; invert = black on
 * white; shift = 1 with pmra / pmdec in mas/yr shifts every epoch along that motion (WiseView's own shift-and-add,
 * reached with window = 100, as its v1 "shift-and-add" mode maps to).
 */
export function wiseviewUrl({ ra, dec, size = 176, pmra = null, pmdec = null }) {
  size = Math.round(Math.min(2000, Math.max(30, size)))
  // zoom 9 at the default 176″ (64 WISE pixels, ~580 screen px); a wider view gets a smaller zoom to stay that size
  const p = { ra: f6(ra), dec: f6(dec), size, band: 3, speed: 500, minbright: '-50.0000', maxbright: '500.0000',
    window: 0.5, diff_window: 1, linear: 1, zoom: Math.max(2, Math.min(9, Math.round(580 / (size / 2.75)))), invert: 1 }
  if (pmra != null && pmdec != null) Object.assign(p, { window: 100, shift: 1, pmra: Math.round(pmra), pmdec: Math.round(pmdec) })
  return `https://byw.tools/wiseview#${Object.entries(p).map(([k, v]) => `${k}=${v}`).join('&')}`
}
/** Legacy Surveys viewer zoom that shows about `deg` across a ~1000 px window (zoom z: 5062.5 / 2^z arcsec per px). */
const lsZoom = (deg) => Math.min(16, Math.max(10, Math.round(Math.log2(5062.5 / ((deg * 3600) / 1000)))))
export const legacyUrl = (ra, dec, deg = 0.15) => `https://www.legacysurvey.org/viewer?ra=${f6(ra)}&dec=${f6(dec)}&layer=ls-dr10&zoom=${lsZoom(deg)}`
export const simbadUrl = (ra, dec, r = 30) => `https://simbad.cds.unistra.fr/simbad/sim-coo?Coord=${f6(ra)}%20${f6(dec)}&CooFrame=ICRS&Radius=${r}&Radius.unit=arcsec`
export const vizierUrl = (ra, dec, r = 30) => `https://vizier.cds.unistra.fr/viz-bin/VizieR?-c=${f6(ra)}%20${f6(dec)}&-c.rs=${r}&-out.add=_r&-sort=_r`
/** Catalogue position {ra, dec, epoch (yr), pmra, pmdec (mas/yr, pmra with cos dec)} moved to another year. */
export function posAt(pm, yr) {
  const dt = yr - pm.epoch, c = Math.cos((pm.dec * Math.PI) / 180)
  return [pm.ra + (pm.pmra / 3.6e6) * dt / c, pm.dec + (pm.pmdec / 3.6e6) * dt]
}
// the same IRSA search the lab's data panel opens
export const irsaUrl = (ra, dec) => `https://irsa.ipac.caltech.edu/applications/spherex/?__action=layout.showDropDown&view=MultiTableSearchCmd&searchTarget=${f6(ra)}%20${f6(dec)}`

/** The years each one covers on one 2010-2027 axis: WISE (2010-2011, then NEOWISE 2013-2024) against SPHEREx (from
 *  May 2025). The long WISE baseline is the reason to open WiseView. */
const SPAN = { wise: [[2010.0, 2011.1], [2013.95, 2024.6]], sphx: [[2025.35, 2026.9]] }
const X = (y) => ((y - 2009.5) / 17.5) * 100
const bar = (k, [a, b], j) => <i key={`${k}${j}`} className={`ew-span ${k}`} style={{ left: `${X(a)}%`, width: `${X(b) - X(a)}%` }} />
function Years({ k }) {
  return (
    <span className="ew-years" aria-hidden="true">
      <i className="ew-axis" />
      {SPAN.sphx.map((s, j) => bar('sx', s, j))}
      {k === 'wise' && SPAN.wise.map((s, j) => bar('wise', s, j))}
      <b style={{ left: 0 }}>2010</b><b style={{ right: 0 }}>2026</b>
    </span>
  )
}
/** A small picture per service: what it gives you (time, a sharper image, names, numbers, the raw data). */
function Glyph({ k }) {
  const P = {
    wise: <><circle cx="14" cy="20" r="4" opacity=".35" /><circle cx="20" cy="18" r="4" opacity=".6" /><circle cx="27" cy="16" r="4.4" /><path d="M8 28h26" strokeWidth="2" fill="none" stroke="currentColor" opacity=".5" /></>,
    ls: <><circle cx="13" cy="14" r="3" /><circle cx="25" cy="12" r="2" /><circle cx="20" cy="24" r="3.6" /><circle cx="30" cy="25" r="1.6" /><circle cx="10" cy="27" r="1.6" /></>,
    simbad: <><circle cx="20" cy="20" r="11" fill="none" stroke="currentColor" strokeWidth="2.2" /><path d="M14 18h12M14 23h8" stroke="currentColor" strokeWidth="2.2" /></>,
    vizier: <><path d="M9 11h22M9 18h22M9 25h22M9 32h22" stroke="currentColor" strokeWidth="2.2" /><path d="M17 8v26" stroke="currentColor" strokeWidth="1.6" opacity=".6" /></>,
    irsa: <><rect x="9" y="9" width="22" height="22" rx="3" fill="none" stroke="currentColor" strokeWidth="2.2" /><path d="M14 25l5-6 4 4 4-7" fill="none" stroke="currentColor" strokeWidth="2.2" /></>,
  }
  return <svg className={`ew-glyph ${k}`} viewBox="0 0 40 40" aria-hidden="true" fill="currentColor">{P[k]}</svg>
}

/**
 * ra, dec: the position (degrees); size: the field of view on this page (degrees).
 * pm (optional): a fast-moving target's catalogue position and motion {ra, dec, epoch, pmra, pmdec}. Its position
 * now is not where older catalogues list it (Barnard's Star has moved 4.5′ since 2000), so WiseView is centred on
 * its position in the middle of the WISE years and widened to hold its whole track, and SIMBAD and VizieR are asked
 * at its year-2000 position (VizieR with a radius that also reaches the Gaia epoch, 2016).
 */
export function ElsewhereLinks({ ra, dec, size = 0.3, pm = null }) {
  if (!Number.isFinite(+ra) || !Number.isFinite(+dec)) return null
  const fast = pm && [pm.ra, pm.dec, pm.epoch, pm.pmra, pm.pmdec].every((v) => Number.isFinite(+v)) && Math.hypot(pm.pmra, pm.pmdec) > 200
  const sp = fast ? Math.hypot(pm.pmra, pm.pmdec) / 1000 : 0
  const wv = fast ? posAt(pm, 2017.3) : [ra, dec], cat = fast ? posAt(pm, 2000) : [ra, dec]
  const items = [
    { k: 'wise', name: 'WiseView', href: wiseviewUrl({ ra: wv[0], dec: wv[1], size: fast ? Math.min(600, Math.max(176, sp * 15 + 90)) : 176 }),
      why: L('輪播 WISE 十多年的紅外線影像：時間基線比 SPHEREx 長很多，慢慢移動的星也看得出來。', 'Blink more than ten years of WISE infrared images: a far longer time baseline than SPHEREx’s, so slow movers show too.'), years: 'wise' },
    { k: 'ls', name: 'Legacy Surveys', href: legacyUrl(ra, dec, size),
      why: L('更深、更清楚的可見光影像：看 SPHEREx 一個像素裡其實有幾顆星。', 'Deeper, sharper optical images: see how many stars share one SPHEREx pixel.') },
    { k: 'simbad', name: 'SIMBAD', href: simbadUrl(cat[0], cat[1]),
      why: L('這裡已知的天體：名稱、種類、距離和相關論文（半徑 30″）。', 'Known objects here: names, types, distances and papers (30″ radius).') },
    { k: 'vizier', name: 'VizieR', href: vizierUrl(cat[0], cat[1], fast ? Math.round(30 + sp * 16) : 30),
      why: fast ? L('所有星表在這顆星的數字：Gaia、2MASS、WISE……', 'Every catalogue’s numbers for this star: Gaia, 2MASS, WISE…') : L('所有星表在這個位置的數字：Gaia、2MASS、WISE……（半徑 30″）。', 'Every catalogue’s numbers at this position: Gaia, 2MASS, WISE… (30″ radius).') },
    { k: 'irsa', name: L('IRSA 的 SPHEREx 資料', 'SPHEREx at IRSA'), href: irsaUrl(ra, dec),
      why: L('原始的 SPHEREx 影像和官方產品，可以自己下載分析。', 'The original SPHEREx images and official products, to download and analyse yourself.'), years: 'sphx' },
  ]
  return (
    <nav className="ew" aria-label={L('在其他網站看同一個位置', 'The same position on other sites')}>
      <p className="ew-h">{L('同一個位置，在別的地方看', 'The same position elsewhere')}<span className="num"> · RA {(+ra).toFixed(4)}°, Dec {(+dec).toFixed(4)}°</span></p>
      <ul className="ew-grid">
        {items.map((it) => (
          <li key={it.k} className={it.k === 'wise' ? 'wide' : ''}>
            <a className="ew-card" href={it.href} target="_blank" rel="noopener noreferrer">
              <Glyph k={it.k} />
              <span className="ew-text"><b>{it.name} <span aria-hidden="true">↗</span></b><span>{it.why}</span>
                {it.years && <Years k={it.years} />}</span>
            </a>
          </li>))}
      </ul>
      {fast && <p className="ew-note">{L(`這顆星每年移動 ${sp.toFixed(1)}″，所以 SIMBAD 和 VizieR 用它 2000 年的位置查，WiseView 對準它在 WISE 年代中間的位置。`, `This star moves ${sp.toFixed(1)}″ a year, so SIMBAD and VizieR are asked at its year-2000 position and WiseView is centred on where it was mid-way through the WISE years.`)}</p>}
      <p className="ew-key" aria-hidden="true"><i className="ew-span sx" />{L('SPHEREx 至今', 'SPHEREx so far')}<i className="ew-span wise" />WISE / NEOWISE</p>
    </nav>
  )
}
