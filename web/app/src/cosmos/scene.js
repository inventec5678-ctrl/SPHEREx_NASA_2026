import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js'

/*
 * The home page's cosmos: a zoom journey in four stages, driven by scroll or pinch.
 *
 *   0  the Milky Way (procedural spiral of stars, the Sun marked)
 *   1  the Solar System (planets on circular mean orbits; the time dial moves them)
 *   2  the Earth and SPHEREx (a dawn-dusk polar orbit whose plane faces the Sun; the telescope looks straight out,
 *      at right angles to the Sun, which is why it sweeps one great circle of sky at a time)
 *   3  the SPHEREx sky seen from the Earth (DR1 all-sky picture, test targets, today's scan circle; tap to pick)
 *
 * Progress p runs 0 .. 3.5: inside stages 0-2 it dollies the camera in, at each whole number the picture fades
 * through black into the next stage, and in the last half-stage it opens the field of view of the sky.
 * Coordinates are equatorial (x to RA 0, y to the north celestial pole, z to RA 270) so the Earth's axis is y.
 * All textures are drawn here from noise; the only image is the SPHEREx sky (scripts/build_cosmos_sky.py).
 */
const AU = 10, SKY_R = 3000, OBL = 23.4393 * Math.PI / 180, D2R = Math.PI / 180
export const STAGES = 4, P_END = 3.5
const MAX_DPR = 2, LITE_DPR = 0.6                    // pixel-ratio caps (normal / software WebGL)
const SAT_ORBIT_S = 40                               // seconds per drawn SPHEREx orbit (98 min real)
const STAGE_VIEWS = ['galaxy', 'solar', 'earth', 'sky']
// scratch objects reused every frame (no per-frame allocation in the render loop)
const _v1 = new THREE.Vector3(), _v2 = new THREE.Vector3(), _v3 = new THREE.Vector3(), _fwd = new THREE.Vector3()
const _m4 = new THREE.Matrix4(), ORIGIN = new THREE.Vector3()

/** Free the GPU resources (geometries, materials, textures) of everything under obj. */
export function disposeTree(obj) {
  const seen = new Set()
  const free = (x) => { if (x && !seen.has(x)) { seen.add(x); x.dispose?.() } }
  obj.traverse((o) => {
    free(o.geometry)
    for (const m of [].concat(o.material || [])) {
      for (const k in m) { const v = m[k]; if (v && v.isTexture) free(v) }
      if (m.uniforms) for (const u of Object.values(m.uniforms)) if (u.value?.isTexture) free(u.value)
      free(m)
    }
  })
}

export function radec(ra, dec, r = 1) {
  const a = ra * D2R, d = dec * D2R
  return new THREE.Vector3(r * Math.cos(d) * Math.cos(a), r * Math.sin(d), -r * Math.cos(d) * Math.sin(a))
}
export function toRadec(v) {
  const n = v.clone().normalize()
  return { ra: ((Math.atan2(-n.z, n.x) / D2R) + 360) % 360, dec: Math.asin(Math.max(-1, Math.min(1, n.y))) / D2R }
}
function ecl(lon, r, lat = 0) {
  const l = lon * D2R, b = lat * D2R
  const xe = r * Math.cos(b) * Math.cos(l), ye = r * Math.cos(b) * Math.sin(l), ze = r * Math.sin(b)
  const yq = ye * Math.cos(OBL) - ze * Math.sin(OBL), zq = ye * Math.sin(OBL) + ze * Math.cos(OBL)
  return new THREE.Vector3(xe * AU, zq * AU, -yq * AU)
}
// name, a (au), mean longitude J2000 and rate (deg/day), drawn radius, colour (circular approximation)
const PLANETS = [
  ['Mercury', 0.387, 252.25, 4.09233, 0.30, [156, 150, 144]], ['Venus', 0.723, 181.98, 1.60213, 0.52, [222, 200, 156]],
  ['Earth', 1.0, 100.46, 0.98561, 0.56, [80, 130, 210]], ['Mars', 1.524, 355.45, 0.52403, 0.40, [196, 106, 68]],
  ['Jupiter', 5.203, 34.40, 0.08309, 1.5, 'bands'], ['Saturn', 9.537, 49.94, 0.03346, 1.25, 'bands'],
  ['Uranus', 19.19, 313.23, 0.01173, 0.9, [160, 212, 218]], ['Neptune', 30.07, 304.88, 0.00598, 0.88, [86, 116, 216]],
]
const daysJ2000 = (date) => (date.getTime() - Date.UTC(2000, 0, 1, 12)) / 864e5
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
const clamp = (x, a, b) => Math.max(a, Math.min(b, x))
const smooth = (x) => { const t = clamp(x, 0, 1); return t * t * (3 - 2 * t) }
const lerp = (a, b, t) => a + (b - a) * t
const loglerp = (a, b, t) => Math.exp(lerp(Math.log(a), Math.log(b), t))

// ---- noise and procedural textures ---------------------------------------------------------------------------------
function hash(x, y, z, s) {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(z, 1274126177) ^ Math.imul(s, 982451653)
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}
function vnoise(x, y, z, s) {
  const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z)
  const xf = x - xi, yf = y - yi, zf = z - zi
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf), w = zf * zf * (3 - 2 * zf)
  const c = (i, j, k) => hash(xi + i, yi + j, zi + k, s)
  const x00 = lerp(c(0, 0, 0), c(1, 0, 0), u), x10 = lerp(c(0, 1, 0), c(1, 1, 0), u)
  const x01 = lerp(c(0, 0, 1), c(1, 0, 1), u), x11 = lerp(c(0, 1, 1), c(1, 1, 1), u)
  return lerp(lerp(x00, x10, v), lerp(x01, x11, v), w)
}
function fbm(x, y, z, s, oct) {
  let a = 0.5, f = 1, t = 0, n = 0
  for (let i = 0; i < oct; i++) { t += a * vnoise(x * f, y * f, z * f, s + i); n += a; f *= 2.03; a *= 0.5 }
  return t / n
}
/** An equirectangular texture painted point by point on the unit sphere: fn(x, y, z, lat) -> [r, g, b, a]. */
function sphereTex(w, h, fn) {
  const c = document.createElement('canvas'); c.width = w; c.height = h
  const g = c.getContext('2d'), img = g.createImageData(w, h), d = img.data
  for (let j = 0; j < h; j++) {
    const lat = (0.5 - (j + 0.5) / h) * Math.PI, cl = Math.cos(lat), y = Math.sin(lat)
    for (let i = 0; i < w; i++) {
      const lon = (i + 0.5) / w * 2 * Math.PI, o = (j * w + i) * 4
      const p = fn(-cl * Math.cos(lon), y, cl * Math.sin(lon), lat)
      d[o] = p[0]; d[o + 1] = p[1]; d[o + 2] = p[2]; d[o + 3] = p[3] ?? 255
    }
  }
  g.putImageData(img, 0, 0)
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace
  return t
}
const mix = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)]

export function cloudTex(w) {
  return sphereTex(w, w / 2, (x, y, z) => {
    const n = fbm(x * 2.6, y * 5.2, z * 2.6, 41, 5)
    return [255, 255, 255, 255 * smooth((n - 0.52) / 0.2) * 0.85]
  })
}
function sunTex() {
  return sphereTex(256, 128, (x, y, z) => {
    const n = fbm(x * 9, y * 9, z * 9, 7, 4)
    return mix([255, 150, 40], [255, 236, 170], n)
  })
}
function bandTex(name) {
  const pal = name === 'Jupiter' ? [[206, 170, 128], [240, 226, 200], [168, 122, 88]] : [[220, 196, 150], [240, 228, 196], [196, 170, 120]]
  return sphereTex(256, 128, (x, y, z) => {
    const n = fbm(x * 3, y * 3, z * 3, 3, 4), b = Math.sin(y * (name === 'Jupiter' ? 22 : 16) + n * 3)
    return b > 0 ? mix(pal[0], pal[1], b) : mix(pal[0], pal[2], -b)
  })
}
function rockTex(rgb, seed) {
  return sphereTex(128, 64, (x, y, z) => { const n = fbm(x * 4, y * 4, z * 4, seed, 4); return mix(rgb.map((v) => v * 0.7), rgb.map((v) => Math.min(255, v * 1.15)), n) })
}

// ---- small pieces ----------------------------------------------------------------------------------------------------
const _glowCache = new Map()
/** Radial glow textures are shared per colour (one canvas and one GPU upload per colour). */
function glowTexture(color) {
  let t = _glowCache.get(color)
  if (t) return t
  const c = document.createElement('canvas'); c.width = c.height = 64
  const g = c.getContext('2d'), grd = g.createRadialGradient(32, 32, 0, 32, 32, 32)
  grd.addColorStop(0, '#fff'); grd.addColorStop(0.22, color); grd.addColorStop(1, 'rgba(0,0,0,0)')
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64)
  t = new THREE.CanvasTexture(c)
  t.addEventListener('dispose', () => _glowCache.delete(color))      // a torn-down scene: the next one re-creates it
  _glowCache.set(color, t)
  return t
}
export function glowSprite(color, size, opacity = 1) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(color), transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending }))
  s.scale.set(size, size, 1)
  return s
}
function line(pts, color, opacity) {
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }))
}
function ring(r, color, opacity, segs = 256) {
  const pts = []
  for (let i = 0; i <= segs; i++) pts.push(ecl((i / segs) * 360, r))
  return line(pts, color, opacity)
}
function basis(n) {
  const a = new THREE.Vector3(0, 1, 0).cross(n)
  if (a.lengthSq() < 1e-6) a.set(1, 0, 0)
  a.normalize()
  return [a, n.clone().cross(a).normalize()]
}
function greatCircle(normal, r, color, opacity) {
  const [a, b] = basis(normal.clone().normalize()), pts = []
  for (let i = 0; i <= 360; i++) { const t = i * D2R; pts.push(a.clone().multiplyScalar(Math.cos(t) * r).addScaledVector(b, Math.sin(t) * r)) }
  return line(pts, color, opacity)
}
function gauss(rnd) { return Math.sqrt(-2 * Math.log(rnd() + 1e-9)) * Math.cos(2 * Math.PI * rnd()) }
function rng(seed) { let s = seed >>> 0; return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296 } }

// ---- the stages ------------------------------------------------------------------------------------------------------
const GAL_R = 60
function buildGalaxy(n) {
  const g = new THREE.Group(), rnd = rng(7)
  const pos = new Float32Array(n * 3), col = new Float32Array(n * 3)
  const arms = 4, pitch = 13 * D2R
  for (let i = 0; i < n; i++) {
    let x, y, z, c
    if (rnd() < 0.16) {                                                          // the bulge
      const r = Math.abs(gauss(rnd)) * 5.5, th = rnd() * 2 * Math.PI, ph = Math.acos(2 * rnd() - 1)
      x = r * Math.sin(ph) * Math.cos(th); z = r * Math.sin(ph) * Math.sin(th); y = r * Math.cos(ph) * 0.55
      c = mix([1, 0.86, 0.62], [1, 0.95, 0.85], rnd())
    } else {
      const r = clamp(-Math.log(1 - rnd() * 0.985) * GAL_R / 3.6 + 3, 3, GAL_R)
      const arm = Math.floor(rnd() * arms), spread = gauss(rnd) * (0.18 + 0.25 * (1 - r / GAL_R))
      const th = arm * 2 * Math.PI / arms + Math.log(r / 3) / Math.tan(pitch) + spread
      x = r * Math.cos(th); z = r * Math.sin(th); y = gauss(rnd) * 0.7 * (1 - 0.6 * r / GAL_R)
      const t = r / GAL_R
      c = mix([1, 0.88, 0.7], [0.62, 0.76, 1], smooth(t * 1.6))
      if (rnd() < 0.025 && Math.abs(spread) < 0.12) c = [1, 0.42, 0.62]                 // star-forming knots on the arms
    }
    const b = 0.55 + rnd() * 0.45, o = i * 3
    pos[o] = x; pos[o + 1] = y; pos[o + 2] = z; col[o] = c[0] * b; col[o + 1] = c[1] * b; col[o + 2] = c[2] * b
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('color', new THREE.BufferAttribute(col, 3))
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.55, map: glowTexture('#ffffff'), vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }))
  g.add(pts)
  g.add(glowSprite('#ffd9a0', 30, 0.55))                                          // the glow of the centre
  // the Sun: 8 kpc out (0.55 of this radius), on the inner edge of an arm
  const r = 0.55 * GAL_R, th = Math.log(r / 3) / Math.tan(pitch) + 0.28
  const sun = new THREE.Vector3(r * Math.cos(th), 0, r * Math.sin(th))
  const mark = glowSprite('#f2e6c9', 2.4); mark.position.copy(sun); g.add(mark)
  // background stars
  const bn = 2500, bp = new Float32Array(bn * 3)
  const v = new THREE.Vector3()
  for (let i = 0; i < bn; i++) { v.set(gauss(rnd), gauss(rnd), gauss(rnd)).normalize().multiplyScalar(1500); v.toArray(bp, i * 3) }
  const bg = new THREE.BufferGeometry(); bg.setAttribute('position', new THREE.BufferAttribute(bp, 3))
  g.add(new THREE.Points(bg, new THREE.PointsMaterial({ size: 1.6, color: 0x8890a0, sizeAttenuation: false, transparent: true, opacity: 0.6, depthWrite: false })))
  return { group: g, disc: pts, sun, mark }
}

export class Cosmos {
  constructor(canvas, { skyUrl, reduced = false, lite = false, date = new Date(), onView } = {}) {
    // lite: no hardware WebGL (software rendering): lower resolution, fewer stars, render only when something moves
    this.canvas = canvas; this.reduced = reduced; this.lite = lite; this.onView = onView || (() => {})
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: !lite, alpha: false })
    this.renderer.setPixelRatio(lite ? LITE_DPR : Math.min(devicePixelRatio || 1, MAX_DPR))
    this.renderer.setClearColor(0x05070c)
    this.scene = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(55, 1, 0.05, 20000)
    this.days0 = daysJ2000(date); this.dayOff = 0
    this.sunDir = ecl((280.46 + 0.9856474 * this.days0) % 360, 1).normalize()

    // stage 0: the galaxy
    this.gal = buildGalaxy(lite ? 22000 : 70000)
    this.scene.add(this.gal.group)

    // stage 1: the Solar System
    const solar = new THREE.Group(); this.solar = solar; this.scene.add(solar)
    const sun = new THREE.Mesh(new THREE.SphereGeometry(1.6, 48, 24), new THREE.MeshBasicMaterial({ map: sunTex() }))
    solar.add(sun); this.sunMesh = sun
    solar.add(glowSprite('#ffb347', 9, 0.9)); solar.add(glowSprite('#ffe2a8', 26, 0.35))
    solar.add(new THREE.PointLight(0xfff1dc, 3, 0, 0)); solar.add(new THREE.AmbientLight(0xffffff, 0.07))
    this.bodies = [{ name: 'Sun', pos: new THREE.Vector3() }]
    for (const [name, a, L0, n, rad, look] of PLANETS) {
      solar.add(ring(a, name === 'Earth' ? 0x6fb6ff : 0xc9ccd3, name === 'Earth' ? 0.7 : 0.28))
      const map = look === 'bands' ? bandTex(name) : name === 'Earth' ? rockTex([70, 120, 200], 9) : rockTex(look, a * 100 | 0)
      const m = new THREE.Mesh(new THREE.SphereGeometry(rad, 32, 16), new THREE.MeshStandardMaterial({ map, roughness: 1, metalness: 0 }))
      if (name === 'Saturn') {
        const rg = new THREE.Mesh(new THREE.RingGeometry(rad * 1.3, rad * 2.3, 64), new THREE.MeshBasicMaterial({ color: 0xd8c8a0, side: THREE.DoubleSide, transparent: true, opacity: 0.55 }))
        rg.rotation.x = -Math.PI / 2 + 0.47; m.add(rg)
      }
      solar.add(m)
      this.bodies.push({ name, a, L0, n, mesh: m, pos: m.position })
    }

    // stage 2: the Earth and SPHEREx (radius 10; the orbit is drawn at 1.3 radii, higher than real so it can be seen)
    const ge = new THREE.Group(); this.earthStage = ge; this.scene.add(ge)
    this.earthMesh = new THREE.Mesh(new THREE.SphereGeometry(10, lite ? 48 : 96, lite ? 24 : 48), new THREE.MeshStandardMaterial({ color: 0x4a6a9a, roughness: 0.9, metalness: 0 }))
    this.clouds = new THREE.Mesh(new THREE.SphereGeometry(10.12, lite ? 48 : 96, lite ? 24 : 48), new THREE.MeshStandardMaterial({ transparent: true, opacity: 0, depthWrite: false, roughness: 1 }))
    const atmo = new THREE.Mesh(new THREE.SphereGeometry(10.9, 64, 32), new THREE.ShaderMaterial({
      transparent: true, side: THREE.BackSide, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { sun: { value: this.sunDir.clone() } },
      vertexShader: 'varying vec3 vN; varying vec3 vW; void main(){ vN = normalize(mat3(modelMatrix) * normal); vW = (modelMatrix * vec4(position,1.)).xyz; gl_Position = projectionMatrix * viewMatrix * vec4(vW,1.); }',
      fragmentShader: 'uniform vec3 sun; varying vec3 vN; varying vec3 vW; void main(){ vec3 v = normalize(cameraPosition - vW); float rim = pow(1. - abs(dot(v, vN)), 3.); float lit = smoothstep(-.35, .45, dot(-vN, sun)); gl_FragColor = vec4(vec3(.35,.62,1.) * rim * (.15 + lit), 1.); }',
    }))
    this.atmo = atmo
    ge.add(this.earthMesh, this.clouds, atmo)
    this.sunLight = new THREE.DirectionalLight(0xffffff, 2.6); ge.add(this.sunLight); ge.add(new THREE.AmbientLight(0x8899bb, 0.12))
    // SPHEREx, simplified from NASA/JPL illustrations (no public 3D model exists): a hexagonal spacecraft bus, three
    // nested conical photon shields around the telescope, and one solar array on the side that faces the Sun.
    // Local axes: +y is where the telescope looks (straight away from the Earth), +x towards the Sun.
    const sat = new THREE.Group()
    const foil = new THREE.MeshStandardMaterial({ color: 0xe8edf3, roughness: 0.3, metalness: 0.5, side: THREE.DoubleSide })
    const dark = new THREE.MeshStandardMaterial({ color: 0x2c333b, roughness: 0.55, metalness: 0.6 })
    const gold = new THREE.MeshStandardMaterial({ color: 0xc9a34e, roughness: 0.4, metalness: 0.7 })
    const bus = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.36, 6), gold); bus.position.y = -0.12; sat.add(bus)
    const deck = new THREE.Mesh(new THREE.CylinderGeometry(0.46, 0.46, 0.04, 6), dark); deck.position.y = 0.07; sat.add(deck)
    for (const [rb, rt, h] of [[0.34, 0.6, 1.0], [0.4, 0.72, 0.88], [0.46, 0.84, 0.76]]) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, 36, 1, true), foil); c.position.y = 0.09 + h / 2; sat.add(c)
    }
    const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.2, 0.55, 24), dark); tube.position.y = 0.36; sat.add(tube)
    const cells = new THREE.MeshStandardMaterial({ color: 0x1b2c58, roughness: 0.3, metalness: 0.4, emissive: 0x0a1630 })
    const arr = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.62, 1.2), cells); arr.position.set(0.78, -0.12, 0); sat.add(arr)
    const yoke = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.05, 0.05), dark); yoke.position.set(0.58, -0.12, 0); sat.add(yoke)
    sat.add(glowSprite('#bfe0ff', 1.6, 0.5)); sat.scale.setScalar(2.2)
    // then swap in a real NASA model: NASA has not released one of SPHEREx, so this is WIRE (Wide-Field Infrared
    // Explorer, NASA 3D Resources), a small infrared survey telescope of similar build. The simple model above stays
    // if it cannot be loaded.
    {
      const draco = new DRACOLoader().setDecoderPath('/draco/')
      new GLTFLoader().setDRACOLoader(draco).load('/cosmos/wire_nasa.glb', (g) => {
        const m = g.scene, box = new THREE.Box3().setFromObject(m), size = box.getSize(new THREE.Vector3())
        m.position.sub(box.getCenter(new THREE.Vector3()))
        const holder = new THREE.Group(); holder.add(m); holder.scale.setScalar(1.7 / Math.max(size.x, size.y, size.z))
        m.traverse((o) => { if (o.isMesh && o.material) { o.material.metalness = Math.min(o.material.metalness ?? 0, 0.5); o.material.roughness = Math.max(o.material.roughness ?? 0.5, 0.35) } })
        const fill = new THREE.PointLight(0xdfeaff, 4, 6, 2); fill.position.set(0.8, 0.6, 1.2)          // a little light on it, also on the night side
        sat.clear(); sat.add(holder, fill, glowSprite('#bfe0ff', 1.6, 0.35)); draco.dispose(); this.dirty()
      }, undefined, () => draco.dispose())
    }
    this.sat = sat; ge.add(sat)
    this.beam = line([new THREE.Vector3(), new THREE.Vector3(0, 1, 0)], 0x6fb6ff, 0.8); ge.add(this.beam)
    this.orbitLine = null; this.ORB = 13

    // stage 3: the SPHEREx sky from the Earth (camera at the centre)
    const gs = new THREE.Group(); this.skyStage = gs; this.scene.add(gs)
    const tex = new THREE.TextureLoader().load(skyUrl, () => this.dirty())
    tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4
    const sky = new THREE.Mesh(new THREE.SphereGeometry(SKY_R, lite ? 64 : 128, lite ? 32 : 64), new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide, depthWrite: false }))
    sky.rotation.y = Math.PI; gs.add(sky)
    gs.add(ring(SKY_R * 0.995 / AU, 0xf2e6c9, 0.18, 512))                     // ecliptic, drawn on the sky
    this.scanCircle = null

    this.markers = []; this.pin = null
    this.p = 2.55; this.pT = 2.55; this.view = 'earth'                   // start at the Earth with SPHEREx going round; click it to go inside
    this.look = { yaw: 266.4, pitch: -29, fov: 70 }                         // first look: towards the centre of the Galaxy
    this.shiftOn = true; this._shift = 1
    this.fovT = this.look.fov; this.pv = 0                                     // zoom targets: field of view, and the stage spring's velocity
    this.user = { az: 0.4, el: 0 }                                              // drag offsets for the dolly stages
    this.vel = { x: 0, y: 0 }; this.flight = null; this.t0 = performance.now()
    this._place(); this._bind(); this.resize(); this._paintEarth()
    // compile every stage's shaders now, so no stage stutters the first time it is shown
    this._precompile()
    // paint the Earth in idle time shortly after load, not in the middle of a zoom
    const idle = window.requestIdleCallback || ((f) => setTimeout(f, 1))
    this._idleT = setTimeout(() => idle(() => { this._paintEarth(); this._precompile() }), 1500)
    this._raf = requestAnimationFrame(this._tick)
  }

  // ---- data ---------------------------------------------------------------------------------------------------------
  setMarkers(list) { this.markers = list.map((m) => ({ ...m, pos: radec(m.ra, m.dec, SKY_R * 0.98) })); this.dirty() }
  setPin(ra, dec, label) { this.pin = ra == null ? null : { ra, dec, label, pos: radec(ra, dec, SKY_R * 0.98) }; this.dirty() }
  dirty() { this._dirty = true }
  /** Move the clock: planets, the Sun's direction, the SPHEREx orbit plane and scan circle (days from today). */
  setDayOffset(d) { this.dayOff = d; this._place(); this.dirty() }
  _precompile() {
    const groups = [this.gal.group, this.solar, this.earthStage, this.skyStage], was = groups.map((g) => g.visible)
    try {
      // one stage at a time: the shader variant depends on which lights are in view, as at run time
      for (const g of groups) { groups.forEach((h) => { h.visible = h === g }); this.renderer.compile(this.scene, this.camera) }
      groups.forEach((g) => { g.visible = true })
      // and upload every texture now: a first upload in the middle of a zoom is a visible hitch
      this.scene.traverse((o) => { const m = o.material; if (m?.map && m.map.image) this.renderer.initTexture(m.map) })
    } catch { /* doing this early is only an optimisation */ }
    groups.forEach((g, i) => { g.visible = was[i] })
  }
  _place() {
    const days = this.days0 + this.dayOff
    for (const b of this.bodies) if (b.a) b.pos.copy(ecl((b.L0 + b.n * days) % 360, b.a))
    this.earthPos = this.bodies.find((b) => b.name === 'Earth').pos
    this.sunDir = ecl((280.46 + 0.9856474 * days) % 360, 1).normalize()
    this.sunLight.position.copy(this.sunDir).multiplyScalar(100)
    this.atmo.material.uniforms.sun.value.copy(this.sunDir)
    // the scan circle and the orbit are rewritten in place (no new geometry while the dial is dragged)
    if (!this.scanCircle) {
      this.scanCircle = greatCircle(this.sunDir, SKY_R * 0.99, 0x6fb6ff, 0.45); this.skyStage.add(this.scanCircle)
      this.orbitLine = greatCircle(this.sunDir, this.ORB, 0x6fb6ff, 0.35); this.earthStage.add(this.orbitLine)
    } else {
      const [a, b] = basis(this.sunDir)
      for (const [ln, r] of [[this.scanCircle, SKY_R * 0.99], [this.orbitLine, this.ORB]]) {
        const pa = ln.geometry.attributes.position
        for (let i = 0; i < pa.count; i++) { const t = i * D2R, c = Math.cos(t) * r, sn = Math.sin(t) * r; pa.setXYZ(i, a.x * c + b.x * sn, a.y * c + b.y * sn, a.z * c + b.z * sn) }
        pa.needsUpdate = true; ln.geometry.computeBoundingSphere()
      }
    }
    this.orbitBasis = basis(this.sunDir)
  }
  /** Angle (deg) between a sky position and the scan circle on the dial's date: 0 = SPHEREx sweeps over it then. */
  scanDistance(ra, dec) { return Math.abs(90 - Math.acos(clamp(radec(ra, dec).dot(this.sunDir), -1, 1)) / D2R) }
  /** The textures of the Earth are painted on first approach (a fraction of a second of noise). */
  _paintEarth() {
    if (this._painted) return
    this._painted = true
    // the Earth: NASA Blue Marble Next Generation (August 2004), public domain; light clouds painted here on top
    const t = new THREE.TextureLoader().load(this.lite ? '/cosmos/earth_2k.webp' : '/cosmos/earth_4k.webp', () => this.dirty())
    t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8
    this.earthMesh.material.map = t; this.earthMesh.material.color.set(0xffffff); this.earthMesh.material.roughness = 0.75; this.earthMesh.material.needsUpdate = true
    this.clouds.material.map = cloudTex(this.lite ? 256 : 512); this.clouds.material.opacity = 0.55; this.clouds.material.needsUpdate = true
  }

  // ---- navigation ---------------------------------------------------------------------------------------------------
  stage() { return Math.min(STAGES - 1, Math.floor(this.p + 1e-6)) }
  goStage(i) { this.pT = i >= STAGES - 1 ? P_END : i + 0.62; if (this.reduced) this.p = this.pT; this.dirty() }
  centre() { return this.stage() === 3 ? { ra: this.look.yaw, dec: this.look.pitch, fov: this.camera.fov } : null }
  /** Turn the sky view onto a position (flying through the stages first if needed). */
  goSky(ra, dec, fov = 55, done) {
    if (this.p < 3) { this.p = 3; }
    this.pT = P_END
    const from = { ...this.look }, to = { yaw: ra, pitch: dec, fov }
    if (Math.abs(to.yaw - from.yaw) > 180) from.yaw += to.yaw > from.yaw ? 360 : -360
    if (this.reduced) { this.look = to; this.fovT = to.fov; this.dirty(); return done?.() }
    this.flight = { from, to, t0: performance.now(), ms: 1500, done }
    this.onView('flying')
  }

  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight
    if (!w || !h) return
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.w = w; this.h = h
    this.dirty()
  }

  _camera() {
    const s = this.stage(), t = clamp(this.p - s, 0, 1), e = ease(t), cam = this.camera
    const sph = (target, dist, el, az) => cam.position.set(target.x + dist * Math.cos(el) * Math.sin(az), target.y + dist * Math.sin(el), target.z + dist * Math.cos(el) * Math.cos(az))
    const el = (base) => clamp(base + this.user.el, -1.45, 1.45), az = this.user.az
    let fov = 50
    if (s === 0) {
      const target = _v1.lerpVectors(ORIGIN, this.gal.sun, smooth(t * 1.15))
      const dist = loglerp(120, 3.2, e)
      sph(target, dist, el(lerp(0.85, 0.3, e)), az); cam.lookAt(target)
      this.gal.disc.material.size = clamp(dist * 0.0045, 0.05, 0.55)                // stars stay points up close
      this.gal.mark.scale.setScalar(clamp(dist * 0.03, 0.06, 2.4))
    } else if (s === 1) {
      const target = _v1.lerpVectors(ORIGIN, this.earthPos, smooth(t * 1.1))
      sph(target, loglerp(520, 4.2, e), el(lerp(0.62, 0.2, e)), az); cam.lookAt(target)
    } else if (s === 2) {
      sph(ORIGIN, loglerp(150, 34, e), el(lerp(0.45, 0.12, e)), az + 0.6); cam.lookAt(0, 0, 0)
    } else {
      cam.position.set(0, 0, 0); cam.up.set(0, 1, 0)
      fov = this.p < P_END - 0.01 ? lerp(100, this.look.fov, smooth((this.p - 3) / (P_END - 3))) : this.look.fov
      cam.lookAt(radec(this.look.yaw, this.look.pitch))
    }
    if (s !== 3) cam.up.set(0, 1, 0)
    cam.fov = fov
    // on wide screens the opening search panel covers the left: shift the picture right while it is shown
    this._shift += ((this.shiftOn ? 1 : 0) - this._shift) * 0.08
    const shift = this.w > 900 ? Math.round(this.w * 0.17 * this._shift) : 0
    if (shift) cam.setViewOffset(this.w, this.h, -shift, 0, this.w, this.h); else cam.clearViewOffset()
    cam.updateProjectionMatrix()
    // fade through black at each stage boundary
    const fadeIn = s === 0 ? 1 : smooth(t / 0.14), fadeOut = s >= 2 ? (s === 2 ? smooth((1 - t) / 0.14) : 1) : smooth((1 - t) / 0.14)
    this.fade = 1 - Math.min(fadeIn, fadeOut)
    this.gal.group.visible = s === 0; this.solar.visible = s === 1; this.earthStage.visible = s === 2; this.skyStage.visible = s === 3
  }

  // ---- input --------------------------------------------------------------------------------------------------------
  _bind() {
    const c = this.canvas, pts = new Map()
    let moved = 0, pinch = 0, lastMove = 0
    const local = (e) => { const r = c.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top } }
    const spread = () => { const [a, b] = [...pts.values()]; return Math.hypot(a.x - b.x, a.y - b.y) }
    this._down = (e) => {
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY }); c.setPointerCapture?.(e.pointerId)
      if (pts.size === 1) { moved = 0; this.vel = { x: 0, y: 0 } }
      if (pts.size === 2) { pinch = spread(); moved = 99 }
      this._pressed = true; this.onInteract?.()
    }
    this._move = (e) => {
      const p = pts.get(e.pointerId)
      if (!p) {
        if (e.pointerType === 'mouse' && !this.flight) {
          const { x, y } = local(e), h = this.pick(x, y), key = h && h.kind !== 'point' ? h.key : null
          c.style.cursor = key ? 'pointer' : ''
          if (key !== this._hot) { this._hot = key; this.onHover?.(key) }
        }
        return
      }
      const dx = e.clientX - p.x, dy = e.clientY - p.y
      p.x = e.clientX; p.y = e.clientY
      if (pts.size === 2) { const d = spread(); if (pinch && d) this._zoom(Math.log(d / pinch) * 2.2, true); pinch = d; return }
      moved += Math.abs(dx) + Math.abs(dy)
      if (moved < 6) return
      this._turn(dx, dy); this.vel = { x: dx, y: dy }; lastMove = performance.now()
    }
    this._up = (e) => {
      if (!pts.delete(e.pointerId)) return
      this._pressed = pts.size > 0
      if (pts.size) { pinch = 0; return }
      if (moved < 6 && !this.flight) { const { x, y } = local(e); this.onPick?.(this.pick(x, y)) }
      if (performance.now() - lastMove > 80) this.vel = { x: 0, y: 0 }
    }
    this._wheel = (e) => {
      const d = e.deltaMode === 1 ? e.deltaY * 30 : e.deltaY
      e.preventDefault()
      this._zoom(Math.sign(d) * Math.min(Math.abs(d), 120) * 0.0011)        // a mouse notch and a trackpad swipe feel alike
    }
    c.addEventListener('pointerdown', this._down); c.addEventListener('pointermove', this._move)
    c.addEventListener('pointerup', this._up); c.addEventListener('pointercancel', this._up)
    c.addEventListener('wheel', this._wheel, { passive: false })
    this._ro = new ResizeObserver(() => this.resize()); this._ro.observe(c)
    // no drawing while the canvas is scrolled out of view (the home page goes on below it)
    if (typeof IntersectionObserver !== 'undefined') {
      this._io = new IntersectionObserver(([en]) => { this._offscreen = !en.isIntersecting; if (!this._offscreen) this.dirty() })
      this._io.observe(c)
    }
  }
  /** Zoom in (k > 0) or out: through the stages, and at the end, into the sky. */
  _zoom(k, direct) {
    if (this.flight) return
    if (this.pT >= P_END - 1e-6 && this.p >= P_END - 0.02 && (k > 0 || this.fovT < 70)) {
      if (k > 0 && this.fovT <= 4.01) { if (this.look.fov < 4.6) this.onDiveRequest?.(); return }   // all the way in: land on a measured field
      this.fovT = clamp(this.fovT * Math.exp(-k * 1.4), 4, 70); this.dirty(); return
    }
    this.pT = clamp(this.pT + k, 0, P_END)
    this.dirty()
  }
  _turn(dx, dy) {
    if (this.stage() === 3) {
      const k = this.look.fov / this.canvas.clientHeight
      this.look.yaw = (this.look.yaw + dx * k + 360) % 360
      this.look.pitch = clamp(this.look.pitch + dy * k, -89, 89)
    } else {
      this.user.az -= dx * 0.005; this.user.el = clamp(this.user.el + dy * 0.005, -1.2, 1.2)
    }
    this.dirty()
  }

  // ---- labels and picking -------------------------------------------------------------------------------------------
  labels() {
    const w = this.w, h = this.h, out = [], cam = this.camera
    if (!w || this.fade > 0.6) return out
    const fwd = cam.getWorldDirection(_fwd), s = _v3
    const put = (key, p, extra) => {
      if (s.copy(p).sub(cam.position).dot(fwd) <= 0) return
      s.copy(p).project(cam)
      if (Math.abs(s.x) > 1.05 || Math.abs(s.y) > 1.05) return
      out.push({ key, x: (s.x + 1) / 2 * w, y: (1 - s.y) / 2 * h, ...extra })
    }
    const st = this.stage()
    if (st === 0) put('here', this.gal.sun, { kind: 'here', label: 'Sun' })
    if (st === 1) for (const b of this.bodies) put(b.name, b.pos, { kind: b.name === 'Earth' ? 'earth' : b.name === 'Sun' ? 'sun' : 'planet', label: b.name, a: b.a })
    if (st === 2) put('spherex', this.sat.position, { kind: 'sat', label: 'SPHEREx' })
    if (st === 3) {
      for (const m of this.markers) put(m.id, m.pos, { kind: m.kind, label: m.label, id: m.id, ra: m.ra, dec: m.dec })
      if (this.pin) put('pin', this.pin.pos, { kind: 'pin', label: this.pin.label, ra: this.pin.ra, dec: this.pin.dec })
    }
    return out
  }
  pick(x, y) {
    let best = null, bd = 30
    for (const l of this.labels()) { if (l.kind === 'pin') continue; const d = Math.hypot(l.x - x, l.y - y) - (l.kind === 'earth' ? 14 : 0); if (d < bd) { bd = d; best = l } }
    if (best || this.stage() !== 3) return best
    const rc = new THREE.Raycaster()
    rc.setFromCamera(new THREE.Vector2(x / this.w * 2 - 1, 1 - y / this.h * 2), this.camera)
    return { kind: 'point', ...toRadec(rc.ray.direction) }
  }

  // ---- frame --------------------------------------------------------------------------------------------------------
  _tick = (now) => {
    this._raf = requestAnimationFrame(this._tick)
    // inside the telescope, scrolled out of view or in a hidden tab: the cosmos waits
    if (this.paused || this._offscreen || document.hidden) { this._last = now; return }
    const dt = Math.min(0.1, (now - (this._last || now)) / 1000); this._last = now
    let moving = false
    const f60 = dt * 60
    if (Math.abs(this.pT - this.p) > 1e-4 || Math.abs(this.pv) > 1e-5) {        // a damped spring towards the scroll target
      this.pv += (this.pT - this.p) * 0.045 * f60; this.pv *= Math.pow(0.68, f60)
      this.p = clamp(this.p + this.pv * f60, 0, P_END)
      if (Math.abs(this.pT - this.p) < 1e-4 && Math.abs(this.pv) < 1e-5) { this.p = this.pT; this.pv = 0 }
      moving = true
    }
    if (this.p > 1.4) this._paintEarth()
    if (!this.flight && Math.abs(this.fovT - this.look.fov) > 1e-3) {           // the sky's zoom glides too
      this.look.fov += (this.fovT - this.look.fov) * (1 - Math.exp(-dt * 9)); moving = true
    }
    if (this.flight) {
      const f = this.flight, t = Math.min(1, (now - f.t0) / f.ms), k = ease(t)
      this.look = { yaw: (lerp(f.from.yaw, f.to.yaw, k) + 360) % 360, pitch: lerp(f.from.pitch, f.to.pitch, k), fov: lerp(f.from.fov, f.to.fov, k) }
      if (t >= 1) { this.flight = null; this.fovT = this.look.fov; f.done?.() }
      moving = true
    } else if (Math.abs(this.vel.x) + Math.abs(this.vel.y) > 0.3 && !this._pressed) {
      this._turn(this.vel.x, this.vel.y); this.vel.x *= 0.92; this.vel.y *= 0.92; moving = true
    }
    const s = this.stage(), tsec = (now - this.t0) / 1000
    // things that move by themselves: the galaxy turns, the Sun churns, the Earth spins, SPHEREx goes round
    const live = !this.reduced && (!this.lite || s === 2)
    if (live) {
      if (s === 0) this.gal.disc.rotation.y = -tsec * 0.01
      if (s === 1) this.sunMesh.rotation.y = tsec * 0.05
      if (s === 2) {
        this.earthMesh.rotation.y = tsec * 0.04; this.clouds.rotation.y = tsec * 0.05
        const [a, b] = this.orbitBasis, th = tsec * 2 * Math.PI / SAT_ORBIT_S          // slow enough to click
        const r = _v1.copy(a).multiplyScalar(Math.cos(th)).addScaledVector(b, Math.sin(th))
        this.sat.position.copy(r).multiplyScalar(this.ORB)
        const sx = _v2.copy(this.sunDir).addScaledVector(r, -this.sunDir.dot(r)).normalize(), sz = _v3.copy(sx).cross(r)
        this.sat.quaternion.setFromRotationMatrix(_m4.makeBasis(sx, r, sz))       // telescope straight out, array to the Sun
        const bp = this.beam.geometry.attributes.position, r0 = this.ORB + 0.9, r1 = this.ORB + 9
        bp.setXYZ(0, r.x * r0, r.y * r0, r.z * r0); bp.setXYZ(1, r.x * r1, r.y * r1, r.z * r1); bp.needsUpdate = true
      }
      moving = true
    }
    const view = this.flight ? 'flying' : STAGE_VIEWS[s]
    if (view !== this.view) { this.view = view; this.onView(view) }
    if (Math.abs((this.shiftOn ? 1 : 0) - this._shift) > 0.01) moving = true
    if (!moving && !this._dirty) return
    this._dirty = false
    this._camera()
    this.renderer.render(this.scene, this.camera)
    this.onFrame?.()
  }

  destroy() {
    cancelAnimationFrame(this._raf); this._ro?.disconnect(); this._io?.disconnect(); clearTimeout(this._idleT)
    const c = this.canvas
    c.removeEventListener('pointerdown', this._down); c.removeEventListener('pointermove', this._move)
    c.removeEventListener('pointerup', this._up); c.removeEventListener('pointercancel', this._up)
    c.removeEventListener('wheel', this._wheel)
    disposeTree(this.scene)                                            // hand the GPU memory back now, not at garbage collection
    this.renderer.dispose(); this.renderer.forceContextLoss()
  }
}
