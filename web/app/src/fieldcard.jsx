// "This patch of sky" as pictures (UPGRADE_PLAN.md §9, D10): where it is on the whole sky, how big it is next to
// the full Moon, how many catalogue stars it holds. Used beside the image on the lab and the quick-look lab.
import { L, PIX } from './lib.js'
import { P9_HALF_WIDTH, P9_PATH, skyPlace } from './sky.js'

const MOON = 0.52            // degrees: the full Moon, for scale
const FOV_BOX = 112          // px: the field-of-view drawing
const P9_RA_WINDOW = 9       // degrees of RA either side of a Planet Nine path point
const OTHER_C = '#a3a8b2'    // a release without its own colour

/** The whole sky (the home page's SPHEREx all-sky picture, same projection) with this field ringed. */
export function SkyLocator({ ra, dec }) {
  const [x, y] = skyPlace(ra, dec)
  // inside the Planet Nine band? (nearest median-orbit point within its half width)
  const inP9 = P9_PATH.some(([r, d]) => Math.abs(((ra - r + 540) % 360) - 180) < P9_RA_WINDOW && Math.abs(dec - d) <= P9_HALF_WIDTH)
  return (
    <figure className="fc-sky">
      <div className="fc-sky-map">
        <img src="/media/allsky.webp" alt="" width="1600" height="800" loading="lazy" decoding="async" />
        <i style={{ left: `${x}%`, top: `${y}%` }} aria-hidden="true" />
      </div>
      <figcaption>
        <b className="num">RA {ra.toFixed(4)}°, Dec {dec.toFixed(4)}°</b>
        <span>{L('在全天的位置', 'Where it is on the whole sky')}{inP9 ? L('：在 Planet Nine 預測帶內', ': inside the Planet Nine band') : ''}</span>
      </figcaption>
    </figure>
  )
}

/** The field of view drawn to scale next to the full Moon. */
export function FovScale({ size, px }) {
  const S = FOV_BOX, k = (S - 16) / Math.max(size, MOON), side = size * k, moon = MOON * k
  return (
    <figure className="fc-fov">
      <svg width={S} height={S} viewBox={`0 0 ${S} ${S}`} role="img" aria-label={L(`視野 ${size}° 見方，旁邊是滿月（0.52°）的大小`, `Field of view ${size}° square, beside the full Moon (0.52°)`)}>
        <circle cx={S / 2} cy={S / 2} r={moon / 2} fill="rgb(242 230 201 / .14)" stroke="rgb(242 230 201 / .55)" strokeDasharray="3 3" />
        <rect x={(S - side) / 2} y={(S - side) / 2} width={side} height={side} fill="none" stroke="#6ec3ff" strokeWidth="2" rx="2" />
      </svg>
      <figcaption>
        <b className="num">{size}° × {size}°</b>
        <span>{L(`${px} × ${px} 像素，${PIX}″／像素；虛線圓是滿月`, `${px} × ${px} px at ${PIX}″/px; dashed circle: the full Moon`)}</span>
      </figcaption>
    </figure>
  )
}

/** Catalogue stars the overlays can draw, as two bars. */
export function CatalogueBars({ gaia, catwise }) {
  const top = Math.max(gaia || 0, catwise || 0, 1)
  return (
    <div className="fc-cat pm-bars" role="img" aria-label={L(`星表裡的星：Gaia DR3 ${gaia}、CatWISE2020 ${catwise}`, `Catalogue stars: Gaia DR3 ${gaia}, CatWISE2020 ${catwise}`)}>
      <span>Gaia DR3</span><i style={{ width: `${(100 * (gaia || 0)) / top}%`, '--c': '#6ec3ff' }} /><b>{(gaia ?? 0).toLocaleString()}</b>
      <span>CatWISE2020</span><i style={{ width: `${(100 * (catwise || 0)) / top}%`, '--c': '#ef6f6c' }} /><b>{(catwise ?? 0).toLocaleString()}</b>
    </div>
  )
}

// the releases IRSA serves now (DR1 first) and their DOIs; QR2 was retired when DR1 came out
const RELEASES = [['DR1', '10.26131/IRSA678', '#f2e6c9'], ['QR3', '10.26131/IRSA662', '#6ec3ff'], ['QR2', '10.26131/IRSA652', OTHER_C]]

/** Which SPHEREx data release the field's images come from, as one stacked bar (nothing for fields made before the
 *  release was recorded). */
export function ReleaseBar({ exposures }) {
  const n = {}
  for (const e of exposures || []) if (e.release) n[e.release] = (n[e.release] || 0) + 1
  const total = Object.values(n).reduce((a, b) => a + b, 0)
  if (!total) return null
  const rows = RELEASES.filter(([r]) => n[r]).concat(Object.keys(n).filter((r) => !RELEASES.some(([k]) => k === r)).map((r) => [r, null, OTHER_C]))
  return (
    <div className="fc-rel">
      <p className="fc-k">{L('影像來自哪一版資料', 'Which data release the images come from')}</p>
      <div className="fc-rel-bar" role="img" aria-label={rows.map(([r]) => `${r} ${n[r]}`).join(', ')}>
        {rows.map(([r, , c]) => <i key={r} style={{ flexGrow: n[r], '--c': c }} />)}
      </div>
      <ul className="fc-rel-keys">
        {rows.map(([r, doi, c]) => <li key={r} style={{ '--c': c }}><b>{r}</b> <span className="num">{n[r]}</span>{doi && <a href={`https://doi.org/${doi}`} className="hint">DOI</a>}</li>)}
      </ul>
    </div>
  )
}

/** The three together, with the panel's own actions under them. */
export function FieldFacts({ field, children, title }) {
  const ov = field.products?.overlays
  return (
    <aside className="lab-data fc">
      <h2 className="lab-data-h">{title || L('這片天空', 'This patch of sky')}</h2>
      <SkyLocator ra={field.ra} dec={field.dec} />
      <div className="fc-row">
        <FovScale size={field.size_deg} px={field.shape[0]} />
        {ov && <div className="fc-cat-wrap"><p className="fc-k">{L('可以疊上的星表', 'Catalogues to overlay')}</p><CatalogueBars gaia={ov.gaia} catwise={ov.catwise} /></div>}
      </div>
      <ReleaseBar exposures={field.exposures} />
      {children}
    </aside>
  )
}
