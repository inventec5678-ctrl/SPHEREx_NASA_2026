// Shared data access, frame cache and sky geometry helpers.
import { L, t } from '@sx/i18n/core.js'

/** SPHEREx pixel scale of every field grid, arcsec per pixel. */
export const PIX = 6.15
/** One colour per survey pass (plots, markers, legends). */
export const PASS_C = ['#7aa8ff', '#f2d46b', '#ef6f6c', '#5fd39a', '#c08bff', '#6fe0d4']
/** The visitor asked the system for less motion: nothing plays by itself. */
export const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
export { L } from '@sx/i18n/core.js'      // two-language text; re-exported here because most modules import it with the helpers

const cache = new Map()
export async function api(path, opts) {
  const r = await fetch(path, opts)
  if (!r.ok) throw new Error(`${path}: ${r.status}`)
  return r.json()
}
/** Distance (field px) within which a distant track's detection counts as hitting the injected body. */
const SIM_HIT_PX = 2.5
/** Share of a distant track's detections that must hit the injected body for the track to be the simulation. */
const SIM_HIT_SHARE = 0.5
function indexField(f) {
  f.cand = new Map(f.candidates.map((c) => [c.id, c]))
  f.byExp = new Map()
  for (const c of f.candidates) { const l = f.byExp.get(c.i); if (l) l.push(c); else f.byExp.set(c.i, [c]) }
  f.simByExp = new Map((f.simulated_truth || []).map((s) => [s.i, s]))
  f.ext = f.frame_ext || 'png'
  f.tgByExp = f.target ? new Map(f.target.points.map((p) => [p.i, p])) : null
  // a distant track that follows an injected body is the simulation, and must always say so
  const truth = f.simByExp
  if (!truth.size) return f
  let simD
  for (const tr of f.tracks) {
    if (tr.kind !== 'distant') continue
    const hits = tr.members.filter((m) => { const c = f.cand.get(m), t = truth.get(c.i); return t && Math.hypot(c.x - t.x, c.y - t.y) < SIM_HIT_PX }).length
    if (hits >= SIM_HIT_SHARE * tr.members.length) {
      tr.sim = true
      tr.sim_d = simD ??= f.simulated.find((x) => x.kind === 'distant')?.d_au
    }
  }
  return f
}
export async function getField(id) {
  if (!cache.has(id)) cache.set(id, api(`/api/field/${encodeURIComponent(id)}`).then(indexField).catch((e) => { cache.delete(id); throw e }))
  return cache.get(id)
}
export const forgetField = (id) => cache.delete(id)

export const DET = {
  1: { c: '#7aa8ff', r: '0.75–1.11 µm' }, 2: { c: '#6fe0d4', r: '1.10–1.64 µm' }, 3: { c: '#9be37a', r: '1.63–2.42 µm' },
  4: { c: '#f2d46b', r: '2.40–3.82 µm' }, 5: { c: '#f5a25d', r: '3.81–4.42 µm' }, 6: { c: '#ef6f6c', r: '4.41–5.00 µm' },
}

// ---- images ------------------------------------------------------------------
// One cache for every image the players draw (field frames, quick-look frames, pass stacks). Frames never change
// once written, so an Image object is kept and reused; the oldest are dropped past the limit.
const imgs = new Map()
const IMG_CACHE_MAX = 900
/** Load (or reuse) an image. cb(im) when it is ready, cb(null) if it failed. Returns the Image. */
export function loadImage(url, cb) {
  let im = imgs.get(url)
  if (!im) {
    im = new Image(); im.decoding = 'async'; im._cbs = []
    im.onload = () => { const cbs = im._cbs; im._cbs = []; cbs.forEach((f) => f(im)) }
    // a failed image calls back with null (callers draw nothing) and is dropped so a later visit retries
    im.onerror = () => { im.failed = true; imgs.delete(url); const cbs = im._cbs; im._cbs = []; cbs.forEach((f) => f(null)) }
    im.src = url
    imgs.set(url, im)
    if (imgs.size > IMG_CACHE_MAX) imgs.delete(imgs.keys().next().value)
  }
  if (cb) {
    if (im.complete && im.naturalWidth) cb(im)
    else if (im.failed) cb(null)
    else if (!im._cbs.includes(cb)) im._cbs.push(cb)
  }
  return im
}
/** Where a field's files are: an analysed field, or a finished quick look (which has the same lab products). */
export const isQuickId = (id) => /^k\d{3}p\d{3}[+-]\d{2}p\d{3}s\d{2}$/.test(id)
export const dataBase = (id) => (isQuickId(id) ? `/data/quick/${id}` : `/data/fields/${id}`)
export function frameUrl(field, kind, i) {
  return `/data/fields/${field.id}/${kind}/${String(i).padStart(4, '0')}.${field.ext || 'png'}`
}
export const frameImg = (field, kind, i, onload) => loadImage(frameUrl(field, kind, i), onload)
export const ready = (im) => im && im.complete && im.naturalWidth > 0

// Difference frames store 128 + 16*S/N. |S/N| < DEAD stays dark so only real signals glow; +S/N amber, -S/N blue.
export const DEAD = 3
let LUT = null
export function diffLUT() {
  if (LUT) return LUT
  LUT = new Uint8ClampedArray(256 * 3)
  for (let v = 0; v < 256; v++) {
    const snr = (v - 128) / 16
    const a = Math.min(1, Math.max(0, (Math.abs(snr) - DEAD) / 6)) ** 0.8
    const rgb = snr >= 0 ? [14 + 241 * a, 16 + 170 * a, 24 + 30 * a] : [14 + 40 * a, 16 + 120 * a, 24 + 230 * a]
    LUT.set(rgb, v * 3)
  }
  return LUT
}
export function colorizeDiff(ctx, w, h) {
  const d = ctx.getImageData(0, 0, w, h), lut = diffLUT()
  for (let p = 0; p < d.data.length; p += 4) { const v = d.data[p] * 3; d.data[p] = lut[v]; d.data[p + 1] = lut[v + 1]; d.data[p + 2] = lut[v + 2] }
  ctx.putImageData(d, 0, 0)
}
let scratch = null   // one reusable canvas for colourising difference frames (the result is copied out at once)
/** Paint the region (sx, sy, sw, sh) of a frame image over the whole of a dw x dh canvas context. Difference
 *  frames (kind 'diff') store signed S/N in grey and are colourised first. */
export function blitFrame(g, im, kind, sx, sy, sw, sh, dw, dh) {
  if (kind !== 'diff') { g.drawImage(im, sx, sy, sw, sh, 0, 0, dw, dh); return }
  scratch ||= document.createElement('canvas')
  const tmp = scratch
  if (tmp.width !== sw || tmp.height !== sh) { tmp.width = sw; tmp.height = sh }
  const tg = tmp.getContext('2d', { willReadFrequently: true })
  tg.clearRect(0, 0, sw, sh)
  tg.drawImage(im, sx, sy, sw, sh, 0, 0, sw, sh); colorizeDiff(tg, sw, sh)
  g.drawImage(tmp, 0, 0, dw, dh)
}
export function legendGradient() {
  const lut = diffLUT(), stops = []
  for (let v = 0; v <= 255; v += 16) stops.push(`rgb(${lut[v * 3]},${lut[v * 3 + 1]},${lut[v * 3 + 2]}) ${((v / 255) * 100).toFixed(1)}%`)
  return `linear-gradient(90deg, ${stops.join(',')})`
}

/** Draw a size×size crop of a frame centred on (x, y) [field pixels, y up] into a canvas. */
export function drawCrop(canvas, field, kind, c, size = 21) {
  const g = canvas.getContext('2d')
  g.imageSmoothingEnabled = false
  g.fillStyle = '#000'; g.fillRect(0, 0, canvas.width, canvas.height)
  const im = frameImg(field, kind, c.i)
  if (!ready(im)) {
    if (canvas._wait !== im) { canvas._wait = im; frameImg(field, kind, c.i, (ok) => { canvas._wait = null; if (ok) drawCrop(canvas, field, kind, c, size) }) }
    return
  }
  const H = field.shape[0], h = Math.floor(size / 2)
  const sx = Math.round(c.x) - h, sy = H - 1 - Math.round(c.y) - h
  blitFrame(g, im, kind, sx, sy, size, size, canvas.width, canvas.height)
}

// ---- geometry ---------------------------------------------------------------
export function pix2world(field, x, y) {
  const w = field.wcs, d2r = Math.PI / 180
  const xi = (x + 1 - w.crpix[0]) * w.cdelt[0] * d2r, eta = (y + 1 - w.crpix[1]) * w.cdelt[1] * d2r
  const a0 = w.crval[0] * d2r, d0 = w.crval[1] * d2r
  const den = Math.cos(d0) - eta * Math.sin(d0)
  const ra = a0 + Math.atan2(xi, den), dec = Math.atan2(Math.sin(d0) + eta * Math.cos(d0), Math.hypot(xi, den))
  return [((ra / d2r) + 360) % 360, dec / d2r]
}
/** Gnomonic offsets (arcsec) of (ra, dec) about (ra0, dec0). */
export function tangent(ra, dec, ra0, dec0) {
  const d2r = Math.PI / 180, a = ra * d2r, d = dec * d2r, a0 = ra0 * d2r, d0 = dec0 * d2r
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0)
  const x = Math.cos(d) * Math.sin(a - a0) / cosc
  const y = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc
  return [x / d2r * 3600, y / d2r * 3600]
}
/** Date of an MJD. mjdToIso(m) -> '2026-03-01 12:30'; mjdDate(m) is the Date itself (other precisions slice its ISO string). */
export const mjdDate = (m) => new Date((m - 40587) * 86400e3)
export const mjdToIso = (m) => mjdDate(m).toISOString().slice(0, 16).replace('T', ' ')

export function trackTitle(tr) {
  if (tr.sim) return t`模擬行星（注入，${Math.round(tr.sim_d)} AU）`
  if (tr.kind === 'distant') return t`遠距天體候選 #${tr.id}`
  return tr.known ? tr.known : t`未辨識移動天體 #${tr.id}`
}
export function fieldTitle(f) {
  if (f.user || (f.id && f.id.startsWith('q'))) return t`使用者提交：RA ${Number(f.ra).toFixed(2)}°, Dec ${Number(f.dec).toFixed(2)}°`
  return f.name
}
export const sbdbUrl = (name) => {
  const m = name.match(/^(\d+)\s/) || name.match(/\(([^)]+)\)/)
  return `https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr=${encodeURIComponent(m ? m[1] : name)}`
}

/** A probability for display: never claims certainty. */
export const pct = (p) => (p > 0.99 ? '> 99%' : p < 0.01 ? '< 1%' : `${Math.round(p * 100)}%`)

/** Three plain evidence checks for a track (shared by the viewer card and the object page).
 *  ok: true = passes, false = fails, null = not applicable. */
export function evidenceChecks(field, tr) {
  const thr = field.cnn_threshold_prob || 0.5
  const out = [
    { key: 'psf', label: t`像真的點光源`, ok: tr.mean_p >= thr, note: t`AI 平均分數 ${pct(tr.mean_p)}` },
    tr.kind === 'distant'
      ? { key: 'path', label: t`符合視差路徑`, ok: tr.rms_arcsec <= 5, note: t`殘差 ${tr.rms_arcsec}″` }
      : { key: 'path', label: t`沿直線等速移動`, ok: tr.rms_arcsec <= 5, note: t`殘差 ${tr.rms_arcsec}″` },
  ]
  if (tr.sim) out.push({ key: 'sim', label: t`是注入的模擬行星`, ok: null, note: t`不是真實天體` })
  else if (tr.jpl) out.push({ key: 'jpl', label: t`和 JPL 預測位置一致`, ok: tr.jpl.consistent, note: tr.jpl.consistent ? t`中位數偏差 ${tr.jpl.median_arcsec}″` : t`${tr.jpl.n_match}/${tr.jpl.n} 次相符` })
  else if (tr.known) out.push({ key: 'jpl', label: t`對上已知天體`, ok: true, note: tr.known })
  else out.push({ key: 'jpl', label: t`沒有對到已知天體`, ok: null, note: t`可能是新天體，更常是假訊號` })
  return out
}
