// Sky positions as text: parsing what people type, and the hash links that carry a position and the view state.
// No React and no heavy imports here: the landing page, the embed and the tools all share this file.

export const TARGET_IDS = ['barnard', 'epsindi', 'wise0855', 'rwaur', 'rdra']
const NAMES = [
  [/barnard/i, 'barnard'], [/eps(ilon)?\s*ind/i, 'epsindi'], [/wise\s*(j?0855|085510)/i, 'wise0855'], [/^0855$/, 'wise0855'],
  [/^rw\s*aur/i, 'rwaur'], [/^r\s*dra/i, 'rdra'],
]
export const EXAMPLES = [
  { q: 'barnard', zh: '巴納德星', en: "Barnard's Star" },
  { q: 'epsilon indi b', zh: '天苑增三 B', en: 'Epsilon Indi B' },
  { q: 'wise 0855', zh: 'WISE 0855', en: 'WISE 0855' },
  { q: 'rw aur', zh: '御夫座 RW', en: 'RW Aurigae' },
  { q: 'r dra', zh: '天龍座 R', en: 'R Draconis' },
  { q: '77.96 -45.02', fov: 0.15, zh: '卡普坦星', en: "Kapteyn's Star" },      // finished quick looks kept on the server
  { q: '162.294 -53.317', fov: 0.15, zh: 'Luhman 16', en: 'Luhman 16' },
  { q: '43.28 16.853', fov: 0.15, zh: 'Teegarden 星', en: "Teegarden's Star" },
]

/** What a typed coordinate may contain (digits and coordinate marks, before the comma and minus-sign clean-up):
 *  text that matches this yet is not a position is a broken coordinate, not a name to look up. */
export const COORD_CHARS = /^[\d\s.:+\-−,hdms°′″'"]+$/i
/** The default field of view (degrees): left out of links. */
export const DEFAULT_FOV = 0.3
const DEG = Math.PI / 180
const NUM = /[+-]?\d+(?:\.\d+)?/g
/** One coordinate ("12h30m", "08:55:10.8", "-07d14m42s", "133.79") -> degrees, or null. `ra` picks hours for
 *  sexagesimal and h-marked values. */
function angle(s, ra) {
  const nums = (s.match(NUM) || []).map(Number)
  if (!nums.length || nums.length > 3 || nums.slice(1).some((v) => v < 0 || v >= 60)) return null
  const neg = /^\s*[-−]/.test(s)
  const v = Math.abs(nums[0]) + (nums[1] || 0) / 60 + (nums[2] || 0) / 3600
  const hours = ra && (/h/i.test(s) || (nums.length > 1 && !/[d°]/i.test(s)))
  return (neg ? -v : v) * (hours ? 15 : 1)
}

/** "ra dec" in decimal degrees or sexagesimal -> {ra, dec}; a challenge target name -> {id}; anything else -> null
 *  (the caller may then ask the name resolver). */
export function parseSky(q) {
  q = String(q || '').replace(/[，,;]/g, ' ').replace(/−/g, '-').trim()
  if (!q) return null
  for (const [re, id] of NAMES) if (re.test(q)) return { id }
  if (!/^[\d\s.:+\-hdms°′″'"]+$/i.test(q)) return null
  // split into RA and Dec: at a sign that is not the first character, else in the middle of the numbers
  let a, b
  const sign = q.slice(1).search(/[+-]/)
  if (sign >= 0) { a = q.slice(0, sign + 1); b = q.slice(sign + 1) }
  else {
    const parts = q.split(/\s+/)
    if (parts.length === 2) [a, b] = parts
    else {
      const toks = q.match(/\d+(?:\.\d+)?\s*[hdms°:′″'"]?/gi) || []
      if (toks.length % 2 || toks.length < 2) return null
      a = toks.slice(0, toks.length / 2).join(' '); b = toks.slice(toks.length / 2).join(' ')
    }
  }
  if (/h/i.test(a) && !/m/i.test(a) && /^\s*\d+(\.\d+)?\s*m/i.test(b)) return null     // "12h30m" is one coordinate, not two
  const ra = angle(a, true), dec = angle(b, false)
  if (ra == null || dec == null || !(ra >= 0 && ra < 360 && dec >= -90 && dec <= 90)) return null
  return { ra, dec }
}

/** Angular separation in degrees. */
export function sep(a, b, c, d) {
  return Math.acos(Math.min(1, Math.sin(b * DEG) * Math.sin(d * DEG) + Math.cos(b * DEG) * Math.cos(d * DEG) * Math.cos((a - c) * DEG))) / DEG
}

export const skyHash = (q, fov) => `#/sky/${encodeURIComponent(String(q).trim())}${fov && +fov !== DEFAULT_FOV ? `?fov=${fov}` : ''}`

// ---- view state in the hash query (so a shared link reproduces the picture) --------------------------------------
// replaceState does not fire hashchange, so writing state never re-routes or scrolls.
export function hashParams() {
  return new URLSearchParams(location.hash.split('?')[1] || '')
}
export function setHashParams(obj) {
  const [path, qs] = location.hash.split('?')
  const u = new URLSearchParams(qs || '')
  for (const [k, v] of Object.entries(obj)) { if (v == null || v === '' || v === false) u.delete(k); else u.set(k, String(v)) }
  const qs2 = u.toString()
  const next = `${path || '#/'}${qs2 ? '?' + qs2 : ''}`
  if (next !== location.hash) history.replaceState(history.state, '', `${location.pathname}${location.search}${next}`)
}
/** The current page as a link to share: the hash with its state, and never the viewer's own language choice. */
export function shareUrl() {
  const u = new URL(location.href)
  u.searchParams.delete('lang')
  return u.toString()
}

// ---- the all-sky map's projection (home page map, the lab's locator; scripts/allsky_map.py draws the picture) ----
// Hammer–Aitoff, RA increasing to the left as on the sky, centre RA 180°; x in [-2√2, 2√2], y in [-√2, √2].
const S2 = Math.SQRT2
export function hammer(ra, dec) {
  const l = -((ra - 180) * Math.PI) / 180, b = (dec * Math.PI) / 180
  const z = Math.sqrt(1 + Math.cos(b) * Math.cos(l / 2))
  return [(2 * S2 * Math.cos(b) * Math.sin(l / 2)) / z, (S2 * Math.sin(b)) / z]
}
export function invHammer(x, y) {
  if (!(x * x / 8 + y * y / 2 <= 1)) return null
  const z = Math.sqrt(1 - (x / 4) ** 2 - (y / 2) ** 2)
  const l = 2 * Math.atan2(z * x, 2 * (2 * z * z - 1)), b = Math.asin(z * y)
  return [(((-l * 180) / Math.PI + 180) % 360 + 360) % 360, (b * 180) / Math.PI]
}
/** A sky position as percentages of the map's width and height (the picture's ellipse fills it). */
export const skyPlace = (ra, dec) => { const [x, y] = hammer(ra, dec); return [50 + (x / (4 * S2)) * 100, 50 - (y / (2 * S2)) * 100] }
/** SVG path (viewBox 0 0 200 100) through sky positions, broken where it wraps round the map's edge. */
export const skyPath = (pts, close = false) => { let d = '', px = null; for (const [ra, dec] of pts) { const [x, y] = skyPlace(ra, dec); d += `${px == null || Math.abs(x - px) > 25 ? 'M' : 'L'}${(2 * x).toFixed(1)} ${y.toFixed(1)}`; px = x } return close ? `${d}Z` : d }
/** Planet Nine: median predicted orbit on the sky (Brown & Batygin 2021; DISCOVERY_NEWS.md section 4) and the ±12°
 *  band around it where the prediction is most likely, as [RA, Dec] in degrees. */
export const P9_PATH = [[0, -17], [26, -5], [40, 1], [53, 8], [67, 14], [82, 19], [97, 23], [114, 26], [130, 26]]
export const P9_HALF_WIDTH = 12
