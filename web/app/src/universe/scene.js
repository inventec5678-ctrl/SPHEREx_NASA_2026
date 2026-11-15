// The "image -> universe" scene. Every detected source sits on the SPHEREx image at its pixel
// position; expanding the universe lifts each body to a depth derived from its model fit while the
// image recedes into a backdrop. Bodies are built from parameter presets (bodies.js).
//
// Rendering goes through an EffectComposer (render pass + output pass) so that the additive glows blend in linear
// HDR before tone mapping. No bloom pass: the glows are analytic (bodies.js); bloom mips made square halos on bright
// stars, and leaving the pass out saves its render targets and its code.
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { build, dispose, shared } from './bodies.js'

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
const BACK_Z = -900
const MAX_DPR = 2
const AUTO_ROTATE_SPEED = 0.45, AUTO_ROTATE_RESUME_MS = 8000
const CLICK_PX = 5                                    // a press that moves less than this is a click
const noRaycast = () => {}
const viewSize = (c) => [c.clientWidth || window.innerWidth, c.clientHeight || window.innerHeight]

export class UniverseScene {
  constructor(canvas, { onPick, onHover, onPlane, reducedMotion, noShift }) {
    this.canvas = canvas; this.onPick = onPick; this.onHover = onHover; this.onPlane = onPlane; this.reduced = reducedMotion; this.noShift = !!noShift
    this.timeMjd = null
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_DPR))
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#020408')
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.5, 5000)
    this.controls = new OrbitControls(this.camera, canvas)
    this.controls.enableDamping = true; this.controls.enabled = false; this.controls.maxDistance = 1400; this.controls.minDistance = 20
    // gentle auto-orbit once the universe is open; pauses while the user drags and resumes after 8 s
    this.controls.autoRotateSpeed = reducedMotion ? 0 : AUTO_ROTATE_SPEED
    this.controls.addEventListener('start', () => { this.controls.autoRotate = false; clearTimeout(this.idle) })
    this.controls.addEventListener('end', () => { clearTimeout(this.idle); this.idle = setTimeout(() => { this.controls.autoRotate = !this.reduced }, AUTO_ROTATE_RESUME_MS) })
    this.composer = new EffectComposer(this.renderer)
    this.composer.addPass(new RenderPass(this.scene, this.camera)); this.composer.addPass(new OutputPass())
    this.items = []; this.progress = 0; this.target = 0; this.clock = new THREE.Clock()
    this.ray = new THREE.Raycaster(); this.ptr = new THREE.Vector2(); this.down = null
    this.selRing = this.makeRing(); this.scene.add(this.selRing)
    this.bind(); this.resize(); this.loop = this.loop.bind(this); this.raf = requestAnimationFrame(this.loop)
  }

  makeRing() {
    const r = new THREE.Mesh(new THREE.RingGeometry(1.25, 1.4, 64), new THREE.MeshBasicMaterial({ color: '#ffb547', transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthTest: false }))
    r.visible = false; r.renderOrder = 10; r.raycast = noRaycast; return r
  }

  bind() {
    const c = this.canvas
    this.onResize = () => this.resize(); window.addEventListener('resize', this.onResize)
    this._down = (e) => { this.down = [e.clientX, e.clientY] }
    this._up = (e) => {
      if (this.down && Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) < CLICK_PX) {
        const it = this.pick(e)
        if (!it && this.onPlane) { const px = this.pickPlane(e); if (px) { this.onPlane(px); this.down = null; return } }
        this.select(it); this.onPick?.(it?.data || null)
      }
      this.down = null
    }
    // hover picking is a recursive raycast: do it at most once per frame, for the latest pointer position
    this._move = (e) => { this._hoverEv = e }
    c.addEventListener('pointerdown', this._down); c.addEventListener('pointerup', this._up); c.addEventListener('pointermove', this._move)
  }

  _hover(e) {
    const it = this.pick(e); this.canvas.style.cursor = it ? 'pointer' : 'grab'; this.hovered = it
    this.onHover?.(it ? { data: it.data, x: e.clientX, y: e.clientY } : null)
  }

  resize() {
    const [w, h] = viewSize(this.canvas)
    this.renderer.setSize(w, h, false); this.composer.setSize(w, h)
    this.camera.aspect = w / h; this.applyOffset(w, h)
  }

  setPanel(open) {
    if (this.panelOpen === open) return
    this.panelOpen = open
    this.applyOffset(...viewSize(this.canvas))
  }

  /** Keep the scene centred in the part of the canvas not covered by floating panels ({ l, t, r, b } in px). */
  setFrame(f) {
    this.frame = f
    this.applyOffset(...viewSize(this.canvas))
  }

  // Desktop: shift the whole scene right so the text column on the left sits on empty sky.
  applyOffset(w, h) {
    if (this.frame) {
      const f = this.frame, fw = Math.max(80, w - f.l - f.r), fh = Math.max(80, h - f.t - f.b)
      this.camera.setViewOffset(w, h, -(f.l - f.r) / 2, -(f.t - f.b) / 2, w, h)
      this.camera.zoom = Math.min(1, Math.max(0.72, Math.min(fw / w, fh / h) * 1.1))     // a little smaller, so the field fits between the panels
      this.camera.updateProjectionMatrix(); return
    }
    this.shift = w >= 900 && !this.noShift ? (this.panelOpen ? 0.04 : 0.2) : 0   // with the details panel open the gap between text and panel is centred
    if (this.shift) this.camera.setViewOffset(w, h, -this.shift * w, 0, w, h)
    else this.camera.clearViewOffset()
    this.camera.updateProjectionMatrix()
  }

  _aim(e) {
    const r = this.canvas.getBoundingClientRect()
    this.ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    this.ray.setFromCamera(this.ptr, this.camera)
  }

  pick(e) {
    this._aim(e)
    const objs = []
    for (const i of this.items) if (i.obj.visible) objs.push(i.obj)
    const hits = this.ray.intersectObjects(objs, true)
    if (!hits.length) return null
    let o = hits[0].object; while (o && !o.userData.item) o = o.parent
    return o?.userData.item || null
  }

  /** Image pixel (x, y up) under the pointer, by intersecting the ray with the backdrop plane. */
  pickPlane(e) {
    if (!this.plane) return null
    this._aim(e)
    const pl = new THREE.Plane(new THREE.Vector3(0, 0, 1), -this.plane.position.z), hit = new THREE.Vector3()
    if (!this.ray.ray.intersectPlane(pl, hit)) return null
    const sc = this.plane.scale.x, x = hit.x / sc + this.W / 2, y = hit.y / sc + this.H / 2
    return x >= 0 && y >= 0 && x < this.W && y < this.H ? { x, y } : null
  }

  /** Elements to keep positioned over bodies: Map(body key -> element), moved with a CSS transform every frame. */
  setLabels(map) { this.labels = map }

  /** Time mode: movers sit where they were at this time (MJD) instead of looping. null = loop. */
  setTime(mjd) { this.timeMjd = mjd }

  select(it) {
    this.selected = it
    this.selRing.visible = !!it
  }

  /** Load a field: backdrop texture + bodies. */
  load({ W, H, imageUrl, bodies }) {
    this.clear()
    this.W = W; this.H = H
    const tex = new THREE.TextureLoader().load(imageUrl); tex.colorSpace = THREE.SRGBColorSpace
    tex.magFilter = THREE.NearestFilter; this.tex = tex
    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }))
    this.plane.raycast = noRaycast; this.scene.add(this.plane)
    for (const b of bodies) this.add(b)
    this.fitImage()
    this.progress = 0; this.target = 0
  }

  add(data) {
    const obj = build(data.type, data.params, data.seed)
    const mover = data.group === 'mover'
    const it = { data, obj, home: new THREE.Vector3(data.x - this.W / 2, data.y - this.H / 2, 0.5), z: data.z, mult: mover ? (data.type === 'ice_giant' ? 1.4 : 2.4) : 1 }
    obj.userData.item = it; obj.position.copy(it.home); this.scene.add(obj); this.items.push(it)
    if (mover && data.path?.length > 1) {        // the measured track, drawn at the body's depth
      const pts = data.path.map(([x, y]) => new THREE.Vector3(x - this.W / 2, y - this.H / 2, 0))
      const col = data.type === 'ice_giant' ? '#c08bff' : '#ffb547'
      it.trail = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color: col, dashSize: 3, gapSize: 2, transparent: true, opacity: 0.7 }))
      it.trail.computeLineDistances(); it.trail.raycast = noRaycast; it.trail.visible = false; this.scene.add(it.trail)
      it.marker = new THREE.Mesh(new THREE.RingGeometry(1, 1.12, 48), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.75, side: THREE.DoubleSide, depthWrite: false }))
      it.marker.raycast = noRaycast; this.scene.add(it.marker)
    }
    return it
  }

  rebuild(data) {
    const it = this.items.find((i) => i.data.key === data.key); if (!it) return
    const pos = it.obj.position.clone(), scale = it.obj.scale.clone()
    this.scene.remove(it.obj); dispose(it.obj)
    it.data = data; it.obj = build(data.type, data.params, data.seed); it.obj.userData.item = it
    it.obj.position.copy(pos); it.obj.scale.copy(scale); this.scene.add(it.obj)
    if (this.selected === it) this.select(it)
  }

  clear() {
    for (const it of this.items) {
      this.scene.remove(it.obj); dispose(it.obj)
      for (const x of [it.trail, it.marker]) if (x) { this.scene.remove(x); x.geometry.dispose(); x.material.dispose() }
    }
    this.items = []
    if (this.plane) { this.scene.remove(this.plane); this.plane.material.map?.dispose(); this.plane.material.dispose(); this.plane.geometry.dispose(); this.plane = null }
    this.select(null)
  }

  fitImage() {
    const d = (this.H / 2) / Math.tan((this.camera.fov * Math.PI) / 360) * 1.08
    this.camStart = new THREE.Vector3(0, 0, Math.max(d, (this.W / 2) / Math.tan((this.camera.fov * Math.PI) / 360) / (this.camera.aspect * (1 - 2 * (this.shift || 0))) * 1.08))
    // the home hero looks in from the side; the viewer keeps the field centred with a gentle tilt
    this.camEnd = this.noShift ? new THREE.Vector3(this.W * 0.18, -this.H * 0.42, this.camStart.z * 0.82) : new THREE.Vector3(this.W * 0.95, -this.H * 0.55, this.camStart.z * 0.7)
    this.camera.position.copy(this.camStart); this.controls.target.set(0, 0, 0); this.camera.lookAt(0, 0, 0)
    this.controls.enabled = false
  }

  expand(on = true) { this.target = on ? 1 : 0 }

  loop() {
    if (this.paused) return
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(this.clock.getDelta(), 0.05)
    shared.uTime.value += dt
    if (this._hoverEv) { const e = this._hoverEv; this._hoverEv = null; this._hover(e) }
    if (this.progress !== this.target) {
      const step = dt / (this.reduced ? 1.2 : 2.6)
      this.progress = this.target > this.progress ? Math.min(this.target, this.progress + step) : Math.max(this.target, this.progress - step)
      const k = ease(this.progress)
      if (this.plane) {
        const z = BACK_Z * k, s = 1 + k * ((this.camStart.z - BACK_Z) / this.camStart.z - 1)
        this.plane.position.z = z; this.plane.scale.setScalar(s); this.plane.material.opacity = 1 - 0.6 * k
        const f = k > 0.15 ? THREE.LinearFilter : THREE.NearestFilter   // crisp pixels as an image, soft as a backdrop
        if (this.tex && this.tex.magFilter !== f) { this.tex.magFilter = f; this.tex.needsUpdate = true }
      }
      this.camera.position.lerpVectors(this.camStart, this.camEnd, k); this.controls.target.set(0, 0, -120 * k); this.camera.lookAt(this.controls.target)
      if (this.progress === 1) { this.controls.enabled = true; this.controls.autoRotate = !this.reduced }
      if (this.progress === 0) { this.controls.enabled = false; this.controls.autoRotate = false }
    }
    const k = ease(this.progress), t = shared.uTime.value
    for (const it of this.items) {
      const d = it.data
      let x = it.home.x, y = it.home.y, shown = true
      if (this.timeMjd != null && d.pathT && d.path?.length > 1) {   // time mode: where it was at this moment
        const T = d.pathT, tm = this.timeMjd, n = T.length
        shown = d.type === 'ice_giant' || (tm >= T[0] - 1 && tm <= T[n - 1] + 1)
        let a = 0
        while (a < n - 2 && T[a + 1] <= tm) a++
        const f = Math.min(1, Math.max(0, (tm - T[a]) / Math.max(T[a + 1] - T[a], 1e-9)))
        x = d.path[a][0] + (d.path[a + 1][0] - d.path[a][0]) * f - this.W / 2
        y = d.path[a][1] + (d.path[a + 1][1] - d.path[a][1]) * f - this.H / 2
        if (it.trail) it.trail.geometry.setDrawRange(0, tm < T[0] ? 0 : a + 2)
      } else if (d.path && d.path.length > 1) {           // movers loop along their measured path
        const n = d.path.length, ph = ((t / (6 + n * 0.25)) % 1) * (n - 1), a = Math.floor(ph), f = ph - a
        x = d.path[a][0] + (d.path[a + 1][0] - d.path[a][0]) * f - this.W / 2
        y = d.path[a][1] + (d.path[a + 1][1] - d.path[a][1]) * f - this.H / 2
      }
      const z = 0.5 + (it.z - 0.5) * k
      it.obj.position.set(x, y, z); it.obj.visible = shown
      it.obj.scale.setScalar((0.35 + 0.65 * k) * it.mult)
      if (it.trail) { it.trail.position.z = z; it.trail.visible = shown && (this.timeMjd != null || it === this.selected || it === this.hovered) }   // tracks on demand (always in time mode)
      if (it.marker) {
        it.marker.visible = shown
        const r = (d.params.radius || 3) * it.mult * (0.35 + 0.65 * k) * 1.45
        it.marker.position.set(x, y, z); it.marker.scale.setScalar(r * (1 + 0.08 * Math.sin(t * 3))); it.marker.quaternion.copy(this.camera.quaternion)
      }
      if (it.obj.userData.spin) it.obj.rotation.y += it.obj.userData.spin * dt
      if (d.type === 'star' && it.obj.children[0]) it.obj.children[0].rotation.y += 0.05 * dt
    }
    if (this.selected) {
      const o = this.selected.obj, r = (this.selected.data.params.radius || 3) * o.scale.x * 1.35
      this.selRing.position.copy(o.position); this.selRing.scale.setScalar(Math.max(r, 2)); this.selRing.quaternion.copy(this.camera.quaternion)
    }
    if (this.controls.enabled) this.controls.update()
    this.composer.render()
    // HTML labels that follow bodies on screen (the viewer names the moving objects in the sky)
    if (this.labels?.size) {
      const w = this.canvas.clientWidth, h = this.canvas.clientHeight, v = this._v || (this._v = new THREE.Vector3())
      for (const it of this.items) {
        const el = this.labels.get(it.data.key); if (!el) continue
        v.copy(it.obj.position).project(this.camera)
        const on = it.obj.visible && v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05
        el.style.visibility = on ? 'visible' : 'hidden'
        if (on) el.style.transform = `translate(${((v.x + 1) / 2 * w).toFixed(1)}px, ${((1 - v.y) / 2 * h).toFixed(1)}px)`
      }
    }
  }

  focus(key) {
    const it = this.items.find((i) => i.data.key === key); if (!it) return
    this.select(it)
    if (this.progress < 1) return
    const p = it.obj.position, off = new THREE.Vector3(0, 0, Math.max(70, (it.data.params.radius || 3) * 16))
    this.controls.target.copy(p); this.camera.position.copy(p.clone().add(off))
  }

  /** Pause rendering while the scene is off screen or the tab is hidden. */
  setActive(on) {
    if (on === !this.paused) return
    this.paused = !on
    if (on) { this.clock.getDelta(); this.raf = requestAnimationFrame(this.loop) } else cancelAnimationFrame(this.raf)
  }

  destroy() {
    cancelAnimationFrame(this.raf); clearTimeout(this.idle); window.removeEventListener('resize', this.onResize)
    const c = this.canvas
    c.removeEventListener('pointerdown', this._down); c.removeEventListener('pointerup', this._up); c.removeEventListener('pointermove', this._move)
    this.clear(); this.selRing.geometry.dispose(); this.selRing.material.dispose()
    this.controls.dispose(); this.composer.dispose?.(); this.renderer.dispose(); this.renderer.forceContextLoss()
  }
}

/** Small rotating preview of one body (parameter editor). */
export class Preview {
  constructor(canvas) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, MAX_DPR)); this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.scene = new THREE.Scene(); this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1000)
    this.clock = new THREE.Clock(); this.loop = this.loop.bind(this); this.raf = requestAnimationFrame(this.loop)
    this.canvas = canvas
    // no drawing while the preview is scrolled out of view
    if (typeof IntersectionObserver !== 'undefined') { this.io = new IntersectionObserver(([en]) => { this.hidden = !en.isIntersecting }); this.io.observe(canvas) }
  }
  show(type, params, seed) {
    if (this.obj) { this.scene.remove(this.obj); dispose(this.obj) }
    this.obj = build(type, params, seed); this.scene.add(this.obj)
    const r = params.radius || 3, ext = type === 'ice_giant' ? r * (2 + (params.rings || 0)) : type === 'galaxy' ? r * 1.3 : type === 'comet' ? r * 9 : r * 1.9
    this.camera.position.set(0, ext * 0.35, ext * 2.6); this.camera.lookAt(0, 0, 0)
  }
  loop() {
    this.raf = requestAnimationFrame(this.loop)
    if (this.hidden) { this.clock.getDelta(); return }
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight
    if (this.canvas.width !== Math.round(w * this.renderer.getPixelRatio())) { this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix() }
    const dt = Math.min(this.clock.getDelta(), 0.05)
    if (this.obj) this.obj.rotation.y += 0.4 * dt
    this.renderer.render(this.scene, this.camera)
  }
  destroy() { cancelAnimationFrame(this.raf); this.io?.disconnect(); if (this.obj) dispose(this.obj); this.renderer.dispose(); this.renderer.forceContextLoss() }
}
