// Space-time cube of the difference images. x, y are image pixels; depth is time.
// Every pixel that brightened (amber) or dimmed (blue) by more than THRESH sigma becomes a point at
// (x, y, t). Static stars cancel in the difference, so the cube is mostly empty; a moving object's
// detections line up into a slanted streak whose slope is its sky motion.
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { frameImg, mjdDate, ready } from './lib.js'

const THRESH = 4.5        // |S/N| of a difference-image peak to become a dust point
const PER_FRAME = 160      // brightest peaks kept per difference image
const MAX_FRAMES = 140     // images stacked at most (evenly sampled beyond that)
const PASS_GAP_D = 40      // exposures closer than this many days belong to the same survey pass
const SNR_ZERO = 128, SNR_SCALE = 16   // diff PNG grey level = 128 + 16 * S/N
const ease = (k) => (k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2)

/** Survey passes compressed: each pass gets depth by its duration, gaps between passes are short. */
export function timeAxis(mjds) {
  const passes = []
  for (const m of [...mjds].sort((a, b) => a - b)) { const p = passes.at(-1); if (p && m - p.end < PASS_GAP_D) p.end = m; else passes.push({ start: m, end: m }) }
  const gap = passes.length > 1 ? 0.08 : 0, usable = 1 - gap * (passes.length - 1)
  const tot = passes.reduce((a, p) => a + Math.max(p.end - p.start, 0.05), 0)
  let z = 0
  for (const p of passes) { p.z0 = z; p.dz = usable * Math.max(p.end - p.start, 0.05) / tot; z += p.dz + gap }
  const f = (m) => {
    const p = passes.find((q) => m <= q.end + 1e-6) || passes.at(-1)
    return p.z0 + p.dz * clamp01((m - p.start) / Math.max(p.end - p.start, 1e-6))
  }
  f.passes = passes
  return f
}
const clamp01 = (v) => Math.min(1, Math.max(0, v))

const pointMat = () => new THREE.ShaderMaterial({
  uniforms: { uScale: { value: 300 }, uSpread: { value: 0 }, uAlpha: { value: 1 } },
  vertexShader: `attribute float size;attribute float tz;attribute vec3 color;uniform float uScale,uSpread;varying vec3 vC;varying float vA;
    void main(){vec3 p=position;p.z=tz*uSpread;vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;
      gl_PointSize=clamp(size*uScale/max(-mv.z,1.),1.,48.);vC=color;vA=1.;}`,
  fragmentShader: `uniform float uAlpha;varying vec3 vC;varying float vA;void main(){vec2 d=gl_PointCoord-.5;float r=length(d)*2.;if(r>1.)discard;
    float a=exp(-r*r*3.5);gl_FragColor=vec4(vC*a*uAlpha,1.);}`,
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
})

/** Additive point cloud from flat arrays: positions (xyz), colours (rgb), sizes and time-depths. */
function cloud(pos, col, size, tz) {
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  geo.setAttribute('size', new THREE.Float32BufferAttribute(size, 1))
  geo.setAttribute('tz', new THREE.Float32BufferAttribute(tz, 1))
  const p = new THREE.Points(geo, pointMat()); p.frustumCulled = false
  return p
}

export class SpaceTime {
  constructor(canvas, labels, { reduced, onProgress }) {
    this.canvas = canvas; this.labels = labels; this.reduced = reduced; this.onProgress = onProgress
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#000000')
    this.camera = new THREE.PerspectiveCamera(38, 1, 1, 8000)
    this.controls = new OrbitControls(this.camera, canvas)
    this.controls.enableDamping = true; this.controls.enabled = false; this.controls.minDistance = 60; this.controls.maxDistance = 2600
    this.controls.autoRotateSpeed = 0.35
    this.controls.addEventListener('start', () => { this.controls.autoRotate = false; clearTimeout(this.idle) })
    this.controls.addEventListener('end', () => { clearTimeout(this.idle); this.idle = setTimeout(() => { this.controls.autoRotate = !this.reduced }, 9000) })
    this.group = new THREE.Group(); this.scene.add(this.group)
    this.noise = 1; this.noiseGoal = 1; this.spread = 0; this.target = 1; this.zCur = 0; this.zGoal = 0; this.clock = new THREE.Clock(); this.token = 0
    this.m4 = new THREE.Matrix4(); this.v = new THREE.Vector3()     // scratch for the frame loop
    this.onResize = () => this.resize(); window.addEventListener('resize', this.onResize)
    this.resize()
    this.loop = this.loop.bind(this); this.raf = requestAnimationFrame(this.loop)
  }

  resize() {
    const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix()
    for (const p of [this.points, this.cands]) if (p) p.material.uniforms.uScale.value = h * 0.9
  }

  /** field, exposure indices to stack, optional selected track (+ colour). */
  async setData({ field, frames, track, color, maxFrames = MAX_FRAMES }) {
    const token = ++this.token
    this.clearData()
    const W = field.shape[1], H = field.shape[0], ex = field.exposures
    this.W = W; this.H = H; this.L = Math.max(W, H) * 1.5
    let use = [...frames].sort((a, b) => ex[a].mjd - ex[b].mjd)
    if (use.length > maxFrames) { const st = use.length / maxFrames; use = Array.from({ length: maxFrames }, (_, k) => use[Math.floor(k * st)]) }
    const ta = timeAxis(use.map((j) => ex[j].mjd)); this.ta = ta
    this.Z = (m) => (ta(m) - 0.5) * -this.L          // earliest in front (towards the viewer), later deeper
    this.field = field; this.frames = use

    // wait for the difference frames
    let n = 0
    // a frame that fails or stalls is skipped rather than blocking the cube
    const one = (j) => new Promise((res) => { const to = setTimeout(res, 20000); frameImg(field, 'diff', j, () => { clearTimeout(to); n++; this.onProgress?.(n, use.length); res() }) })
    await Promise.all(use.map(one))
    this.onProgress?.(use.length, use.length)
    if (token !== this.token) return
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H
    const g = cv.getContext('2d', { willReadFrequently: true })
    const pos = [], col = [], size = [], tz = []
    for (const j of use) {
      const im = frameImg(field, 'diff', j); if (!ready(im)) continue
      g.clearRect(0, 0, W, H); g.drawImage(im, 0, 0)
      const d = g.getImageData(0, 0, W, H).data, z = this.Z(ex[j].mjd)
      // one point per local peak (3x3) above THRESH; at most PER_FRAME brightest per image so a bad
      // frame (scattered light, a bright residual) cannot flood the cube
      const S = (x, y) => (d[(y * W + x) * 4] - SNR_ZERO) / SNR_SCALE
      const peaks = []
      for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
        const v = S(x, y), a = Math.abs(v)
        if (a < THRESH) continue
        let peak = true
        for (let dy = -1; dy <= 1 && peak; dy++) for (let dx = -1; dx <= 1; dx++) {
          if ((dx || dy) && Math.abs(S(x + dx, y + dy)) > a) { peak = false; break }
        }
        if (peak) peaks.push([x, y, v])
      }
      peaks.sort((p, q) => Math.abs(q[2]) - Math.abs(p[2]))
      for (const [x, y, snr] of peaks.slice(0, PER_FRAME)) {
        const a = Math.min(1, (Math.abs(snr) - THRESH) / 6 + 0.35)
        pos.push(x - W / 2, H / 2 - 1 - y, 0); tz.push(z)
        const k = 0.42 * a
        if (snr > 0) col.push(1.0 * k, 0.71 * k, 0.28 * k); else col.push(0.1 * k, 0.3 * k, 0.65 * k)
        size.push(snr > 0 ? 1.8 + Math.min(snr, 15) * 0.15 : 1.4)
      }
    }
    this.points = cloud(pos, col, size, tz)
    this.group.add(this.points)

    // the AI layer: every candidate the network scored in these images; brighter = more likely real
    const cp = [], cc = [], cs = [], ct = [], pl = field.p_link || 0.5
    for (const j of use) for (const c of field.byExp.get(j) || []) {
      if (c.p < 0.05) continue
      cp.push(c.x - W / 2, c.y - H / 2, 0); ct.push(this.Z(ex[j].mjd))
      if (c.p >= pl) { const k = 0.75 + 0.25 * c.p; cc.push(1.0 * k, 0.78 * k, 0.42 * k); cs.push(6.5) }
      else { const k = 0.25 + 0.5 * c.p; cc.push(0.85 * k, 0.9 * k, 0.95 * k); cs.push(3.6) }
    }
    this.cands = cloud(cp, cc, cs, ct)
    this.group.add(this.cands)
    this.resize()

    // the cube's edges, very faint, so the eye reads depth as a volume
    const box = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(W, H, 1)), new THREE.LineBasicMaterial({ color: '#2a3c44', transparent: true, opacity: 0.6 }))
    this.box = box; this.group.add(box)

    // the sweep plane: the current difference frame, sliding through time
    this.planeCv = document.createElement('canvas'); this.planeCv.width = W; this.planeCv.height = H
    this.planeTex = new THREE.CanvasTexture(this.planeCv); this.planeTex.magFilter = THREE.NearestFilter; this.planeTex.colorSpace = THREE.SRGBColorSpace
    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({ map: this.planeTex, transparent: true, depthWrite: false, side: THREE.DoubleSide }))
    this.group.add(this.plane)

    // tracks as tubes through (x, y, t): the selected one thick with a marker riding it; with nothing
    // selected, every track whose detections fall in the stacked images, thin, so the field's movers show
    const lo = ex[use[0]].mjd - 0.01, hi = ex[use.at(-1)].mjd + 0.01
    const list = track ? [track] : field.tracks.filter((tr) => tr.members.some((m) => { const t0 = ex[field.cand.get(m).i].mjd; return t0 >= lo && t0 <= hi }))
    const sph = new THREE.SphereGeometry(1, 14, 10)
    this.tubes = list.map((tr) => {
      const mem = tr.members.map((m) => field.cand.get(m)).map((c) => ({ mjd: ex[c.i].mjd, v: new THREE.Vector3(c.x - W / 2, c.y - H / 2, 0), z: this.Z(ex[c.i].mjd) }))
        .filter((m) => track || (m.mjd >= lo && m.mjd <= hi)).sort((a, b) => a.mjd - b.mjd)
      const c3 = new THREE.Color(track ? (color || '#ffb547') : tr.kind === 'distant' ? '#c08bff' : tr.known ? '#6ec3ff' : '#ffb547')
      const r = track ? 1.1 : 0.7, ds = track ? 1.9 : 1.4
      const o = { mem, ds, dets: new THREE.InstancedMesh(sph, new THREE.MeshBasicMaterial({ color: c3 }), mem.length) }
      this.group.add(o.dets)
      if (mem.length > 1) {
        o.tubeOf = (k) => new THREE.TubeGeometry(new THREE.CatmullRomCurve3(mem.map((m) => new THREE.Vector3(m.v.x, m.v.y, m.z * k)), false, 'centripetal'), Math.max(32, mem.length * 6), r, 8, false)
        o.tube = new THREE.Mesh(o.tubeOf(this.spread), new THREE.MeshBasicMaterial({ color: c3, transparent: true, opacity: track ? 0.85 : 0.6 })); o.tubeK = this.spread
        this.group.add(o.tube)
      }
      return o
    })
    this.mem = track && this.tubes[0]?.mem.length ? this.tubes[0].mem : null
    if (this.mem) { this.rider = new THREE.Mesh(new THREE.SphereGeometry(3.2, 20, 14), new THREE.MeshBasicMaterial({ color: '#ffffff' })); this.group.add(this.rider) }

    this.makeLabels(ta)
    this.setCurrent(this.curI ?? use[0], true)
    this.layout()
  }

  makeLabels(ta) {
    this.labels.innerHTML = ''
    this.lab = []
    const add = (text, v, cls = '') => { const el = document.createElement('span'); el.className = `st-label ${cls}`; el.textContent = text; this.labels.appendChild(el); this.lab.push({ el, v }) }
    const fmt = (m) => mjdDate(m).toISOString().slice(0, 10)
    for (const p of ta.passes) {
      add(fmt(p.start), { x: this.W / 2 + 6, y: -this.H / 2, z: (p.z0 - 0.5) * -this.L })
      if (p.end - p.start > 0.3) add(fmt(p.end), { x: this.W / 2 + 6, y: -this.H / 2, z: (p.z0 + p.dz - 0.5) * -this.L })
    }
    this.nowLab = document.createElement('span'); this.nowLab.className = 'st-label now'; this.labels.appendChild(this.nowLab)
  }

  /** exposure index currently shown in 2D: the sweep plane moves there. */
  setCurrent(i, jump = false) {
    this.curI = i
    if (!this.plane || i == null) return   // data not built yet; setData() applies curI when ready
    const ex = this.field.exposures[i]; this.curMjd = ex.mjd
    this.zGoal = this.Z(ex.mjd); if (jump || this.reduced) this.zCur = this.zGoal
    this.nowLab.textContent = `${ex.iso} · ${ex.lam_um.toFixed(2)} µm`
    // texture: colourised difference with transparency where nothing changed
    const im = frameImg(this.field, 'diff', i)
    const paint = () => {
      const g = this.planeCv.getContext('2d', { willReadFrequently: true }); g.clearRect(0, 0, this.W, this.H); g.drawImage(im, 0, 0)
      const d = g.getImageData(0, 0, this.W, this.H), px = d.data
      for (let p = 0; p < px.length; p += 4) {
        const snr = (px[p] - SNR_ZERO) / SNR_SCALE, a = clamp01((Math.abs(snr) - 3) / 6) ** 0.8
        if (snr >= 0) { px[p] = 255; px[p + 1] = 186; px[p + 2] = 84 } else { px[p] = 60; px[p + 1] = 140; px[p + 2] = 255 }
        px[p + 3] = Math.round(255 * (0.035 + 0.965 * a))
      }
      g.putImageData(d, 0, 0); this.planeTex.needsUpdate = true
    }
    if (ready(im)) paint(); else frameImg(this.field, 'diff', i, paint)
  }

  layout() {
    const c = new THREE.Vector3(0, 0, 0), R = Math.max(this.W, this.H)
    // start: looking straight down the time axis at the current frame, like the 2D view
    this.camFlat = new THREE.Vector3(0, 0, R * 1.55)
    this.camOpen = new THREE.Vector3(R * 1.45, R * 0.75, R * 1.15)
    this.camera.position.copy(this.spread > 0.99 ? this.camOpen : this.camFlat); this.controls.target.copy(c); this.camera.lookAt(c)
    this.camFrom = this.camera.position.clone()
  }

  /** Fade the raw difference peaks in or out, leaving what the AI scored. */
  showNoise(on) { this.noiseGoal = on ? 1 : 0 }

  open(on = true) { this.target = on ? 1 : 0; this.camFrom = this.camera.position.clone(); this.controls.enabled = false; this.controls.autoRotate = false }

  loop() {
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(this.clock.getDelta(), 0.05)
    if (!this.points) { this.renderer.render(this.scene, this.camera); return }
    if (this.spread !== this.target) {
      this.spread = this.reduced ? this.target : (this.target > this.spread ? Math.min(1, this.spread + dt / 1.8) : Math.max(0, this.spread - dt / 1.2))
      const k = ease(this.spread)
      this.camera.position.lerpVectors(this.camFrom, this.target ? this.camOpen : this.camFlat, this.target ? k : 1 - k)
      this.camera.lookAt(this.controls.target)
      if (this.spread === 1) { this.controls.enabled = true; this.controls.autoRotate = !this.reduced }
    }
    const k = ease(this.spread)
    this.points.material.uniforms.uSpread.value = k; this.cands.material.uniforms.uSpread.value = k
    this.noise += (this.noiseGoal - this.noise) * Math.min(1, dt * (this.reduced ? 60 : 3))
    this.points.material.uniforms.uAlpha.value = this.noise; this.points.visible = this.noise > 0.01
    this.box.scale.z = Math.max(1e-3, this.L * k)
    this.zCur += (this.zGoal - this.zCur) * Math.min(1, dt * 8)
    this.plane.position.z = this.zCur * k
    const m4 = this.m4
    for (const o of this.tubes || []) {
      if (o.detK !== k) {      // the detection spheres only move while the cube opens or closes
        o.mem.forEach((m, j) => { m4.makeScale(o.ds, o.ds, o.ds); m4.setPosition(m.v.x, m.v.y, m.z * k); o.dets.setMatrixAt(j, m4) })
        o.dets.instanceMatrix.needsUpdate = true; o.detK = k
      }
      if (o.tube && Math.abs(o.tubeK - k) > 0.01) { o.tube.geometry.dispose(); o.tube.geometry = o.tubeOf(k); o.tubeK = k }
    }
    if (this.mem) {
      // the rider follows the object to the current time
      const t = this.curMjd, a = this.mem, p = this.v
      p.copy(a[0].v).setZ(a[0].z)
      for (let j = 0; j < a.length - 1; j++) if (t >= a[j].mjd && t <= a[j + 1].mjd) { const f = (t - a[j].mjd) / Math.max(a[j + 1].mjd - a[j].mjd, 1e-9); p.copy(a[j].v).lerp(a[j + 1].v, f).setZ(a[j].z + (a[j + 1].z - a[j].z) * f); break }
      if (t > a.at(-1).mjd) p.copy(a.at(-1).v).setZ(a.at(-1).z)
      this.rider.position.set(p.x, p.y, p.z * k); this.rider.scale.setScalar(1 + 0.15 * Math.sin(performance.now() / 180))
    }
    if (this.controls.enabled) this.controls.update()
    this.renderer.render(this.scene, this.camera)
    // project the date labels
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight, v = this.v
    for (const l of this.lab) {
      v.set(l.v.x, l.v.y, l.v.z * k).project(this.camera)
      const lx = Math.min(Math.max(((v.x + 1) / 2) * w, 8), w - (l.el.offsetWidth || 80) - 16)
      l.el.style.transform = `translate(${lx}px, ${((1 - v.y) / 2) * h}px)`; l.el.style.opacity = v.z < 1 && k > 0.6 ? 1 : 0
    }
    v.set(this.W / 2 + 6, this.H / 2, this.zCur * k).project(this.camera)
    const nx = Math.min(Math.max(((v.x + 1) / 2) * w, 8), w - (this.nowLab.offsetWidth || 160) - 16), ny = Math.min(Math.max(((1 - v.y) / 2) * h, 56), h - 24)
    this.nowLab.style.transform = `translate(${nx}px, ${ny}px)`; this.nowLab.style.opacity = v.z < 1 ? 1 : 0
  }

  clearData() {
    for (const o of [...this.group.children]) { this.group.remove(o); o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose() }
    this.points = null; this.cands = null; this.tubes = []; this.mem = null; this.rider = null
  }

  destroy() {
    this.token++; cancelAnimationFrame(this.raf); window.removeEventListener('resize', this.onResize); clearTimeout(this.idle)
    this.clearData(); this.controls.dispose(); this.renderer.dispose(); this.renderer.forceContextLoss(); if (this.labels) this.labels.innerHTML = ''
  }
}
