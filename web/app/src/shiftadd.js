// WiseView-style image tools on the survey-pass stacks (UPGRADE_PLAN.md §10, R7), with no React and no DOM so they
// can be checked under node (tests/test_shiftadd.py):
//   - the float16 pass stacks (pass/stacks_g<k>.bin) and their loader, shared by the lab and the "find movers" page;
//   - brightness: low / high limits as percentiles, linear or asinh stretch, invert (WiseView draws black on white);
//   - shift-and-add: shift each pass along a trial motion and combine, so an object moving at that rate adds up while
//     the static stars smear, and a search over trial motions for the one that makes a point sharpest;
//   - a synthetic moving star (Gaussian of the stacks' measured width) for the "spot the fake mover" practice.
// Field pixel arrays are row-major from the bottom row: value(x, y) = a[y * n + x], y points north.

// ---- float16 ------------------------------------------------------------------------------------------------
export const H2F = (() => {
  const t = new Float32Array(65536)
  for (let h = 0; h < 65536; h++) {
    const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 31, m = h & 1023
    t[h] = e === 0 ? s * 2 ** -14 * (m / 1024) : e === 31 ? (m ? NaN : s * Infinity) : s * 2 ** (e - 15) * (1 + m / 1024)
  }
  return t
})()
export function f16(u) { const f = new Float32Array(u.length); for (let k = 0; k < u.length; k++) f[k] = H2F[u[k]]; return f }

// ---- statistics -----------------------------------------------------------------------------------------------
/** Sorted finite values of `a` (every `every`-th one). */
export function finite(a, every = 1) {
  const v = []
  for (let k = 0; k < a.length; k += every) if (Number.isFinite(a[k])) v.push(a[k])
  return v.sort((x, y) => x - y)
}
export const quant = (v, p) => v[Math.min(v.length - 1, Math.max(0, Math.floor(p * (v.length - 1))))]
/** Median and robust sigma (1.4826 x median absolute deviation) of the finite values. */
export function robust(a, every = 1) {
  const v = finite(a, every)
  if (!v.length) return { med: 0, sig: 0 }
  const med = quant(v, 0.5), d = v.map((x) => Math.abs(x - med)).sort((x, y) => x - y)
  return { med, sig: 1.4826 * quant(d, 0.5) }
}

// ---- brightness -----------------------------------------------------------------------------------------------
/** Sorted finite values for a brightness scale: every third pixel of a large image is plenty. */
const SAMPLE_ABOVE = 30000
const scaleSample = (a) => finite(a, a.length > SAMPLE_ABOVE ? 3 : 1)
export const BRIGHT0 = { lo: 25, hi: 99.85, stretch: 'asinh', invert: false }
const BKEY = 'sx:bright:v1'
/** The visitor's brightness settings (localStorage; private windows and blocked storage fall back to the defaults). */
export function loadBright() {
  try {
    const b = JSON.parse(localStorage.getItem(BKEY) || 'null')
    if (b && typeof b === 'object') {
      const lo = +b.lo, hi = +b.hi
      return { lo: lo >= 0 && lo < 100 ? lo : BRIGHT0.lo, hi: hi > 0 && hi <= 100 ? hi : BRIGHT0.hi, stretch: b.stretch === 'linear' ? 'linear' : 'asinh', invert: !!b.invert }
    }
  } catch { /* no storage */ }
  return { ...BRIGHT0 }
}
export function saveBright(b) { try { localStorage.setItem(BKEY, JSON.stringify(b)) } catch { /* no storage */ } }

/**
 * Pixel value -> grey level 0..255 for an image `a` (or a sample of values from several images).
 * lo / hi: percentiles (0-100) mapped to black and white; asinh: softened at 3 sigma of the background, so faint
 * things show without the bright stars burning out (the lab's look so far); invert: black stars on white.
 */
export function stretchMap(a, b = BRIGHT0) {
  const v = scaleSample(a)
  if (!v.length) return () => (b.invert ? 255 : 0)
  let lo = quant(v, b.lo / 100), hi = quant(v, b.hi / 100)
  if (!(hi > lo)) hi = lo + 1e-6
  const med = quant(v, 0.5)
  const sig = Math.max(1e-6, quant(v.map((x) => Math.abs(x - med)).sort((x, y) => x - y), 0.5) * 1.48)
  let f
  if (b.stretch === 'linear') { const k = 255 / (hi - lo); f = (x) => (x - lo) * k }
  else { const s = 3 * sig, den = Math.asinh((hi - lo) / s); f = (x) => (Math.asinh(Math.max(0, x - lo) / s) / den) * 255 }
  return b.invert
    ? (x) => (Number.isFinite(x) ? 255 - Math.min(255, Math.max(0, f(x))) : 255)
    : (x) => (Number.isFinite(x) ? Math.min(255, Math.max(0, f(x))) : 0)
}
/** Histogram of an image's finite values between two percentiles, for the brightness panel. */
export function histogram(a, bins = 48, p0 = 0.5, p1 = 99.95) {
  const v = scaleSample(a)
  if (!v.length) return null
  const x0 = quant(v, p0 / 100), x1 = quant(v, p1 / 100), w = (x1 - x0) / bins || 1, h = new Array(bins).fill(0)
  for (const x of v) { const k = Math.floor((x - x0) / w); if (k >= 0 && k < bins) h[k]++ }
  return { x0, x1, h, at: (p) => quant(v, p / 100) }
}

// ---- time and motion ------------------------------------------------------------------------------------------
const YEAR = 365.25                                       // days per Julian year (MJD differences -> years)
/** Mean exposure time (MJD) of each survey pass; the middle of the pass when its exposures are not listed. */
export function passTimes(passes, exposures = []) {
  return passes.map((p) => {
    const m = exposures.filter((e) => e.mjd >= p.mjd0 - 1e-6 && e.mjd <= p.mjd1 + 1e-6).map((e) => e.mjd)
    return m.length ? m.reduce((s, x) => s + x, 0) / m.length : (p.mjd0 + p.mjd1) / 2
  })
}
/** Arcsec of (east, north) per field pixel step in x and in y at (x, y); `world(x, y)` -> [ra, dec] in degrees. */
export function jacobian(world, x, y) {
  const [a0, d0] = world(x, y), [a1, d1] = world(x + 1, y), [a2, d2] = world(x, y + 1)
  const c = Math.cos((d0 * Math.PI) / 180), wrap = (d) => ((d + 540) % 360) - 180
  return [[wrap(a1 - a0) * c * 3600, wrap(a2 - a0) * c * 3600], [(d1 - d0) * 3600, (d2 - d0) * 3600]]
}
/** Motion in arcsec/yr (east, north) -> field pixels/yr (vx, vy). */
export function motionToPix(J, east, north) {
  const [[a, b], [c, d]] = J, det = a * d - b * c
  return { vx: (d * east - b * north) / det, vy: (-c * east + a * north) / det }
}
/** Field pixels/yr -> arcsec/yr (east, north). */
export function pixToMotion(J, vx, vy) { return { east: J[0][0] * vx + J[0][1] * vy, north: J[1][0] * vx + J[1][1] * vy } }

// ---- shift-and-add --------------------------------------------------------------------------------------------
/** Bilinear value at (x, y); NaN neighbours are left out, NaN when most of the weight is missing or off the image. */
export function sampleAt(f, n, x, y) {
  if (!(x >= 0 && y >= 0 && x <= n - 1 && y <= n - 1)) return NaN
  const i = Math.min(n - 2, Math.floor(x)), j = Math.min(n - 2, Math.floor(y)), fx = x - i, fy = y - j
  const k0 = j * n + i, k1 = k0 + n
  let s = 0, w = 0, v, ww
  // the four neighbours in a fixed order (same summation order as always, so results are bit-identical)
  ww = (1 - fx) * (1 - fy); v = f[k0]; if (ww > 0 && Number.isFinite(v)) { s += v * ww; w += ww }
  ww = fx * (1 - fy); v = f[k0 + 1]; if (ww > 0 && Number.isFinite(v)) { s += v * ww; w += ww }
  ww = (1 - fx) * fy; v = f[k1]; if (ww > 0 && Number.isFinite(v)) { s += v * ww; w += ww }
  ww = fx * fy; v = f[k1 + 1]; if (ww > 0 && Number.isFinite(v)) { s += v * ww; w += ww }
  return w >= 0.5 ? s / w : NaN
}
const medCache = new WeakMap()
const medOf = (f) => { let m = medCache.get(f); if (m === undefined) { m = robust(f, 3).med; medCache.set(f, m) } return m }
const combine = (v, how) => {
  if (!v.length) return NaN
  if (how === 'median') { v.sort((a, b) => a - b); const h = v.length >> 1; return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2 }
  let s = 0; for (const x of v) s += x; return s / v.length
}
/**
 * Shift each pass along a trial motion and combine them (WiseView's "shift and add").
 * frames: one n x n Float32Array per pass; times: MJD of each pass; v: {vx, vy} field pixels per year.
 * Pass p is sampled at (x + vx dt_p, y + vy dt_p), dt_p = (t_p - t_ref) / 365.25, so an object moving at v lands on
 * one spot. t_ref is the mean pass time (WiseView counts from the first epoch; that only moves the whole picture),
 * so the sharpened object sits where it is in the plain sum. Each pass is taken about its own median (the residual
 * backgrounds differ). how: 'mean' (least noise) or 'median' (drops a pass that disagrees).
 * box: optional [x0, y0, x1, y1] (inclusive) to fill only part of the output (the rest stays NaN).
 */
export function shiftAdd(frames, n, times, v, how = 'mean', box = null) {
  const P = frames.length, out = new Float32Array(n * n).fill(NaN)
  const tref = times.reduce((s, t) => s + t, 0) / P
  // per-pass shift (field pixels) and median, hoisted out of the pixel loop
  const dxs = new Float64Array(P), dys = new Float64Array(P), still = new Uint8Array(P)
  for (let p = 0; p < P; p++) {
    dxs[p] = v.vx * (times[p] - tref) / YEAR; dys[p] = v.vy * (times[p] - tref) / YEAR
    still[p] = dxs[p] === 0 && dys[p] === 0 ? 1 : 0
  }
  const meds = frames.map(medOf)
  const [x0, y0, x1, y1] = box || [0, 0, n - 1, n - 1]
  const ya = Math.max(0, y0), yb = Math.min(n - 1, y1), xa = Math.max(0, x0), xb = Math.min(n - 1, x1)
  const vals = []
  for (let y = ya; y <= yb; y++) {
    for (let x = xa; x <= xb; x++) {
      const k = y * n + x
      vals.length = 0
      for (let p = 0; p < P; p++) {
        const s = still[p] ? frames[p][k] : sampleAt(frames[p], n, x + dxs[p], y + dys[p])
        if (Number.isFinite(s)) vals.push(s - meds[p])
      }
      out[k] = combine(vals, how)
    }
  }
  return out
}
/** Local background around (x, y): median of the finite pixels in a RING_IN-RING_OUT px ring (0 when there are none). */
const RING_IN = 5, RING_OUT = 7
function ringBg(img, n, x, y) {
  const ring = []
  for (let j = Math.floor(y - RING_OUT); j <= Math.ceil(y + RING_OUT); j++) for (let i = Math.floor(x - RING_OUT); i <= Math.ceil(x + RING_OUT); i++) {
    const d = Math.hypot(i - x, j - y)
    if (d >= RING_IN && d <= RING_OUT && i >= 0 && j >= 0 && i < n && j < n && Number.isFinite(img[j * n + i])) ring.push(img[j * n + i])
  }
  return ring.length ? combine(ring, 'median') : 0
}
/** Peak pixel above the local background within `reach` px of (x, y): how bright the point looks. */
export function peakNear(img, n, x, y, reach = 1.5) {
  const bg = ringBg(img, n, x, y)
  let best = -Infinity
  for (let j = Math.floor(y - reach); j <= Math.ceil(y + reach); j++) for (let i = Math.floor(x - reach); i <= Math.ceil(x + reach); i++) {
    if (i < 0 || j < 0 || i >= n || j >= n || Math.hypot(i - x, j - y) > reach) continue
    const q = img[j * n + i]; if (Number.isFinite(q) && q - bg > best) best = q - bg
  }
  return best
}
/** Width and elongation of the light around (x, y): background from a 5-7 px ring, then the light-weighted spread
 *  of the pixels within R px (missing and below-background pixels left out). size: rms radius in pixels (smaller is
 *  sharper); elong: long axis / short axis (1 is round, a smeared star is longer along its motion). */
export function moments(img, n, x, y, R = 4) {
  const bg = ringBg(img, n, x, y)
  const pts = []
  let s = 0, sx = 0, sy = 0
  for (let j = Math.floor(y - R); j <= Math.ceil(y + R); j++) for (let i = Math.floor(x - R); i <= Math.ceil(x + R); i++) {
    if (i < 0 || j < 0 || i >= n || j >= n || Math.hypot(i - x, j - y) > R) continue
    const v = img[j * n + i] - bg
    if (v > 0) { pts.push([i, j, v]); s += v; sx += v * i; sy += v * j }
  }
  if (!(s > 0)) return null
  const mx = sx / s, my = sy / s
  let xx = 0, yy = 0, xy = 0
  for (const [i, j, v] of pts) { xx += v * (i - mx) ** 2; yy += v * (j - my) ** 2; xy += v * (i - mx) * (j - my) }
  xx /= s; yy /= s; xy /= s
  const h = Math.sqrt(((xx - yy) / 2) ** 2 + xy * xy), l1 = (xx + yy) / 2 + h, l2 = Math.max(1e-9, (xx + yy) / 2 - h)
  return { size: Math.sqrt((xx + yy) / 2), elong: Math.sqrt(l1 / l2) }
}

// ---- the fake mover -------------------------------------------------------------------------------------------
/** Small seeded random numbers (mulberry32), so a puzzle can be replayed from its seed. */
export function rng(seed) {
  let a = seed >>> 0
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296 }
}
/** Gaussian width (sigma, field pixels) of a star in the all-detector pass stacks: measured on isolated Gaia stars in
 *  five fields (0.62-0.69 px; UPGRADE_PLAN.md §10, R7). */
export const STACK_SIGMA = 0.65
export function addGaussian(f, n, x, y, amp, sigma = STACK_SIGMA) {
  const r = Math.ceil(4 * sigma)
  for (let j = Math.max(0, Math.floor(y) - r); j <= Math.min(n - 1, Math.ceil(y) + r); j++)
    for (let i = Math.max(0, Math.floor(x) - r); i <= Math.min(n - 1, Math.ceil(x) + r); i++)
      if (Number.isFinite(f[j * n + i])) f[j * n + i] += amp * Math.exp(-((i - x) ** 2 + (j - y) ** 2) / (2 * sigma * sigma))
}
export const LEVELS = {
  easy: { shift: [2.0, 3.2], snr: [14, 24] },     // field pixels moved between the first and last pass; peak / noise
  hard: { shift: [0.9, 1.6], snr: [6, 9] },
}
/**
 * A practice picture: a C x C cut of real pass stacks with one synthetic star moving in a straight line.
 * frames: the field's pass stacks (n x n each); times: pass MJDs; avoid: [{x, y, r}] places to keep out of the cut
 * (a real fast mover would be a second answer). Returns null when no clean cut was found.
 */
export function makePuzzle(R, frames, n, times, level = 'easy', { C = 32, avoid = [] } = {}) {
  const lv = LEVELS[level] || LEVELS.easy, P = frames.length
  const span = (times[P - 1] - times[0]) / YEAR, tref = times.reduce((s, t) => s + t, 0) / P
  for (let tries = 0; tries < 60; tries++) {
    const x0 = 2 + Math.floor(R() * (n - C - 4)), y0 = 2 + Math.floor(R() * (n - C - 4))
    if (avoid.some((q) => q.x > x0 - q.r && q.x < x0 + C + q.r && q.y > y0 - q.r && q.y < y0 + C + q.r)) continue
    const cut = frames.map((f) => { const c = new Float32Array(C * C); for (let j = 0; j < C; j++) for (let i = 0; i < C; i++) c[j * C + i] = f[(y0 + j) * n + x0 + i]; return c })
    if (cut.some((c) => c.reduce((s, v) => s + (Number.isFinite(v) ? 0 : 1), 0) > 0.02 * C * C)) continue
    const st = cut.map((c) => robust(c))
    const sig = st.map((s) => s.sig).sort((a, b) => a - b)[P >> 1]
    if (!(sig > 0)) continue
    // no bright star's halo across the picture: the four quarters' backgrounds agree within 2 sigma
    const h = C >> 1, quarter = (qx, qy) => { const v = []; for (let j = qy; j < qy + h; j++) for (let i = qx; i < qx + h; i++) v.push(cut[0][j * C + i]); return robust(v).med }
    const qm = [quarter(0, 0), quarter(h, 0), quarter(0, h), quarter(h, h)]
    if (Math.max(...qm) - Math.min(...qm) > 2 * sig) continue
    const shift = lv.shift[0] + R() * (lv.shift[1] - lv.shift[0]), ang = R() * 2 * Math.PI
    const vx = (shift / Math.max(span, 0.1)) * Math.cos(ang), vy = (shift / Math.max(span, 0.1)) * Math.sin(ang)
    const track0 = times.map((t) => [vx * (t - tref) / YEAR, vy * (t - tref) / YEAR])
    const pad = 5, minx = Math.min(...track0.map((q) => q[0])), maxx = Math.max(...track0.map((q) => q[0]))
    const miny = Math.min(...track0.map((q) => q[1])), maxy = Math.max(...track0.map((q) => q[1]))
    const cx = pad - minx + R() * (C - 1 - 2 * pad - (maxx - minx)), cy = pad - miny + R() * (C - 1 - 2 * pad - (maxy - miny))
    const snr = lv.snr[0] + R() * (lv.snr[1] - lv.snr[0]), amp = snr * sig
    const track = track0.map(([dx, dy]) => ({ x: cx + dx, y: cy + dy }))
    // not on top of a real star (it would hide in it): nothing above 4 sigma within 2 px of the path in any pass
    const busy = track.some((q, p) => { for (let j = Math.round(q.y) - 2; j <= Math.round(q.y) + 2; j++) for (let i = Math.round(q.x) - 2; i <= Math.round(q.x) + 2; i++) if (cut[p][j * C + i] - st[p].med > 4 * sig) return true; return false })
    if (busy) continue
    cut.forEach((c, p) => addGaussian(c, C, track[p].x, track[p].y, amp))
    return { x0, y0, C, frames: cut, track, vx, vy, shift, span, snr, amp, sig, ang }
  }
  return null
}
/** Distance (pixels) from (x, y) to the track (a polyline through the pass positions). */
export function trackDistance(track, x, y) {
  let d = Infinity
  for (let k = 0; k < track.length; k++) {
    const a = track[k], b = track[Math.min(k + 1, track.length - 1)], ux = b.x - a.x, uy = b.y - a.y, L2 = ux * ux + uy * uy
    const t = L2 > 0 ? Math.max(0, Math.min(1, ((x - a.x) * ux + (y - a.y) * uy) / L2)) : 0
    d = Math.min(d, Math.hypot(x - a.x - t * ux, y - a.y - t * uy))
  }
  return d
}

// ---- the stacks themselves ------------------------------------------------------------------------------------
const stackCache = new Map()
/** Every pass and band group of a field (pass/stacks.bin: int32 header P, B, n, n then float16 [pass][band][n][n]). */
export function loadStacks(base) {
  if (!stackCache.has(base)) {
    stackCache.set(base, fetch(`${base}/pass/stacks.bin`).then((r) => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer() }).then((b) => {
      const [P, B, n] = new Int32Array(b, 0, 4), f = f16(new Uint16Array(b, 16))
      const get = (p, d) => f.subarray((p * B + d) * n * n, (p * B + d + 1) * n * n)
      return { P, B, n, get }
    }).catch((e) => { stackCache.delete(base); throw e }))
  }
  return stackCache.get(base)
}
// One band group at a time (pass/stacks_g<k>.bin, float16 [pass][n][n], no header; UPGRADE_PLAN.md §8, T6): the lab
// draws as soon as the group it shows has arrived (a seventh of stacks.bin), with a progress bar meanwhile.
// Older fields without the group files fall back to the whole stacks.bin.
const groupCache = new Map()
export function loadGroup(base, g, P, n, onProgress) {
  const key = `${base}:${g}`
  if (!groupCache.has(key)) {
    groupCache.set(key, (async () => {
      const r = await fetch(`${base}/pass/stacks_g${g}.bin`)
      if (!r.ok) { const all = await loadStacks(base); return { get: (p) => all.get(p, g) } }
      const want = P * n * n * 2, len = +r.headers.get('content-length') || want
      let buf = new Uint8Array(Math.max(len, want)), got = 0
      if (r.body?.getReader) {
        const rd = r.body.getReader()
        for (;;) {
          const { done, value } = await rd.read()
          if (done) break
          if (got + value.length > buf.length) { const b2 = new Uint8Array((got + value.length) * 2); b2.set(buf.subarray(0, got)); buf = b2 }
          buf.set(value, got); got += value.length
          onProgress?.(Math.min(1, got / len))
        }
      } else { buf = new Uint8Array(await r.arrayBuffer()); got = buf.length }
      if (got < want) throw new Error('short stack group')
      const f = f16(new Uint16Array(buf.buffer, 0, P * n * n))
      return { get: (p) => f.subarray(p * n * n, (p + 1) * n * n) }
    })().catch((e) => { groupCache.delete(key); throw e }))
  }
  return groupCache.get(key)
}
