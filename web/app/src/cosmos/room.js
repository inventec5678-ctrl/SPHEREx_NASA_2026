import * as THREE from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { HDRLoader } from 'three/addons/loaders/HDRLoader.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { disposeTree, radec, toRadec } from './scene.js'

/*
 * Inside the telescope: a stylised control room (SPHEREx itself has no crew; this is a way in, not a model of it).
 * Walk with WASD / arrow keys or by clicking the floor, look by dragging. The big window looks out at the SPHEREx
 * sky (only sky: the telescope points away from the Earth and the Sun); clicking it points the telescope at a target, which turns the sky to it and shows the real
 * SPHEREx picture of that field on the glass. The computer on the right explains how the verdict was reached.
 *
 * What makes it read as real:
 *   - physically based materials lit by an environment map (three's RoomEnvironment through PMREM), so metal and the
 *     glossy floor reflect;
 *   - scanned PBR metal (ambientCG, CC0) and props (Poly Haven, CC0), lit by an HDR studio (Poly Haven, CC0);
 *   - rounded edges on every box, instanced machinery in the wall bays;
 *   - emissive light strips pushed above 1 and a bloom pass, AgX tone mapping, soft shadows from the window light.
 * With software rendering (no GPU) shadows and bloom are left out and the rest stays.
 * Room: x -6..6, z -8 (window wall) .. 8, floor y 0, ceiling y 5. Eye height 1.7 m.
 */
const W = 12, D = 16, HGT = 5, WIN = { w: 9, h: 3.4, c: 0.9, y: 2.55 }, EYE = 1.7
const MAX_DPR = 1.5, PHONE_DPR = 1.25, LITE_DPR = 0.6       // pixel-ratio caps
const LEVER_MAX = 0.55                                        // lever swing (rad) either side of upright
const WALK_KEYS = new Set(['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'])
const WINDOW_AIM = new THREE.Vector3(0, 0.1, -1).normalize()  // where the chosen field appears, seen from the room
// scratch objects for the frame loop and picking (no per-frame allocation)
const _fw = new THREE.Vector3(), _rt = new THREE.Vector3(), _mv = new THREE.Vector3(), _d = new THREE.Vector3(), _ndc = new THREE.Vector2()

function oct(w, h, c, dx = 0, dy = 0) {
  const s = new THREE.Shape(), x = w / 2, y = h / 2
  const p = [[-x + c, y], [x - c, y], [x, y - c], [x, -y + c], [x - c, -y], [-x + c, -y], [-x, -y + c], [-x, y - c]]
  s.moveTo(p[0][0] + dx, p[0][1] + dy)
  for (const q of p.slice(1)) s.lineTo(q[0] + dx, q[1] + dy)
  s.closePath()
  return s
}
function ringShape(outer, inner) { outer.holes.push(new THREE.Path(inner.getPoints())); return outer }
function rng(seed) { let s = seed >>> 0; return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296 } }

export class Room {
  constructor(canvas, { lite = false, hq, skyUrl, onHover, onAct, onFrame, onLever, onLost, onPick, reduced = false } = {}) {
    this.onPick = onPick
    this.onLever = onLever; this.onLost = onLost; this.canvas = canvas; this.lite = lite; this.hq = hq ?? !lite
    this.onHover = onHover || (() => {}); this.onAct = onAct || (() => {}); this.onFrame = onFrame
    const r = this.renderer = new THREE.WebGLRenderer({ canvas, antialias: !lite, powerPreference: 'high-performance' })
    r.setPixelRatio(lite ? LITE_DPR : Math.min(devicePixelRatio || 1, MAX_DPR)); r.setClearColor(0x000000)   // pure black: the tone mapping in the post pass lifts any near-black to a blue haze outside the window
    // if the GPU drops the context (out of memory on a big screen), say so instead of leaving a black screen
    this._lost = (e) => { e.preventDefault(); cancelAnimationFrame(this._raf); this.onLost?.() }
    canvas.addEventListener('webglcontextlost', this._lost)
    r.toneMapping = THREE.AgXToneMapping; r.toneMappingExposure = 1.25
    // Bloom and the reflection maps render into floating-point buffers. Many phones (iOS Safari among them) cannot,
    // and then everything comes out black. Check, and on phones keep to plain rendering anyway (memory, heat).
    const ex = r.extensions, gl2 = r.capabilities.isWebGL2
    this.floatOK = gl2 ? (ex.has('EXT_color_buffer_float') || ex.has('EXT_color_buffer_half_float')) : (ex.has('OES_texture_half_float') && ex.has('EXT_color_buffer_half_float'))
    const phone = window.matchMedia('(pointer: coarse)').matches || Math.min(window.innerWidth, window.innerHeight) < 600
    if (phone) r.setPixelRatio(Math.min(devicePixelRatio || 1, PHONE_DPR))
    // Phones (iPhone Safari above all) take the plain path even when they claim float buffers: real devices have
    // still drawn the reflection maps black. The plain path is the one checked to draw everywhere.
    this.phone = phone
    if (phone) this.floatOK = false
    this.hq = this.hq && this.floatOK && !phone
    if (this.hq) { r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap }
    const sc = this.scene = new THREE.Scene()
    sc.fog = new THREE.FogExp2(0x06090e, 0.018)
    if (this.floatOK) {
      const pmrem = new THREE.PMREMGenerator(r)
      sc.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; sc.environmentIntensity = 0.32
      pmrem.dispose()
    }
    // then the real light: a small studio photographed in HDR (Poly Haven, CC0), for reflections on every metal surface
    if (this.floatOK) new HDRLoader().load('/room/studio_small_09_1k.hdr', (t) => {
      t.mapping = THREE.EquirectangularReflectionMapping
      if (this._dead) return t.dispose()
      const pm = new THREE.PMREMGenerator(r), old = sc.environment
      sc.environment = pm.fromEquirectangular(t).texture; sc.environmentIntensity = 0.42; pm.dispose(); t.dispose(); old?.dispose()
    })
    this.camera = new THREE.PerspectiveCamera(68, 1, 0.05, 3000)
    this.pos = new THREE.Vector3(0, EYE, 5.5); this.yaw = 0; this.pitch = 0.02
    this.keys = new Set(); this.goal = null; this.t0 = performance.now()

    // ---- outside: the SPHEREx sky ----
    const outside = new THREE.Group(); sc.add(outside)
    this.skyPivot = new THREE.Group(); outside.add(this.skyPivot)
    const skyTex = new THREE.TextureLoader().load(skyUrl); skyTex.colorSpace = THREE.SRGBColorSpace
    const sky = new THREE.Mesh(new THREE.SphereGeometry(900, 64, 32), new THREE.MeshBasicMaterial({ map: skyTex, side: THREE.BackSide, depthWrite: false, fog: false, color: 0xd0d0d0 }))
    sky.rotation.y = Math.PI; sky.name = 'sky'; this.skyPivot.add(sky); this.skyMesh = sky
    // no all-sky map behind the field: against a still backdrop the field's own stars would not be seen to move
    sky.visible = false
    this.skyPivot.quaternion.setFromUnitVectors(radec(266.4, -29), WINDOW_AIM)
    // a telescope looks away from the Earth and the Sun: out of the window there is only the sky it measures

    // ---- materials ----
    // scanned metal surfaces (ambientCG, CC0): colour, normal, and roughness + metalness packed in one image
    // each image is fetched once; a different tiling is a clone sharing the same source (and the same GPU upload)
    const TL = new THREE.TextureLoader(), texCache = new Map()
    const pbr = (name, rep, extra = {}) => {
      const ld = (f, srgb) => {
        const key = `${name}_${f}`, rk = `${key}@${rep}`
        if (texCache.has(rk)) return texCache.get(rk)
        let t = texCache.get(key)
        if (t) t = t.clone()
        else { t = TL.load(`/room/tex/${key}.webp`, (x) => { for (const c of texCache.values()) if (c.source === x.source) c.needsUpdate = true }); texCache.set(key, t) }
        if (srgb) t.colorSpace = THREE.SRGBColorSpace
        t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...rep); t.anisotropy = 8
        texCache.set(rk, t)
        return t
      }
      const orm = ld('orm')
      // without reflection maps a fully metallic surface has nothing to reflect and goes black: keep it mostly diffuse
      return new THREE.MeshStandardMaterial({ map: ld('color', true), normalMap: ld('normal'), roughnessMap: orm, metalnessMap: orm, roughness: 1, metalness: this.floatOK ? 1 : 0.25, ...extra })
    }
    const panel = pbr('wall', [4, 1.25], { color: 0x8796a6 })
    const panel2 = pbr('wall', [3, 1.25], { color: 0x7d8b9a })
    const frontMat = pbr('wall', [1, 1], { color: 0x7d8b9a })
    const ceilMat = pbr('ceiling', [1.4, 5], { color: 0x9aa6b2 })
    const metal = pbr('trim', [1, 1], { color: 0xb4c0cc })
    const darkMetal = pbr('trim', [1, 1], { color: 0x3c444e })
    const strip = (color = 0xcff4ff, k = 3.2) => new THREE.MeshStandardMaterial({ color: 0x000000, emissive: color, emissiveIntensity: k })
    const lightMat = strip(), cyanMat = strip(0x45c8ff, 3.5)
    const rbox = (w, h, d, m, x, y, z, rad = 0.04) => { const b = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 3, Math.min(rad, w / 2.1, h / 2.1, d / 2.1)), m); b.position.set(x, y, z); b.castShadow = b.receiveShadow = this.hq; sc.add(b); return b }

    // ---- floor, ceiling, walls ----
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), pbr('floor', [4, 5.3], { color: 0xc3ccd6 }))
    floor.rotation.x = -Math.PI / 2; floor.name = 'floor'; floor.receiveShadow = this.hq; sc.add(floor); this.floor = floor
    // the ceiling: a recessed central channel and two slanted halves with light bars, like ribs leading to the window
    const ceilC = new THREE.Mesh(new THREE.PlaneGeometry(3.2, D), darkMetal); ceilC.rotation.x = Math.PI / 2; ceilC.position.y = HGT + 0.25; sc.add(ceilC)
    for (const s of [-1, 1]) {
      const slant = new THREE.Mesh(new THREE.PlaneGeometry(4.6, D), ceilMat); slant.rotation.set(Math.PI / 2, s * 0.32, 0)
      slant.rotation.order = 'YXZ'; slant.rotation.set(Math.PI / 2, 0, 0); slant.rotateY(-s * 0.32); slant.position.set(s * 3.75, HGT - 0.35, 0); sc.add(slant)
      for (const z of [-6.5, -4.5, -2.5, -0.5, 1.5, 3.5, 5.5]) { const bar = rbox(2.6, 0.05, 0.12, lightMat, s * 3.6, HGT - 0.33, z, 0.02); bar.rotation.z = s * 0.32; bar.rotation.y = s * 0.35 }
      rbox(0.1, 0.06, D - 1, cyanMat, s * 1.65, HGT + 0.02, 0, 0.02)                   // the channel's edge lights
    }
    for (const z of [-7, -3, 1, 5]) rbox(W, 0.5, 0.45, metal, 0, HGT - 0.1, z, 0.08)     // structural ribs
    for (const s of [-1, 1]) {
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(D, HGT), panel); wall.rotation.y = -s * Math.PI / 2; wall.position.set(s * W / 2, HGT / 2, 0); wall.receiveShadow = this.hq; sc.add(wall)
      for (const z of [-7, -3, 1, 5]) {                                                // pillars with lamps
        rbox(0.7, HGT, 0.8, metal, s * (W / 2 - 0.35), HGT / 2, z, 0.08)
        rbox(0.05, HGT - 1, 0.1, lightMat, s * (W / 2 - 0.72), HGT / 2, z, 0.02)
        rbox(0.45, 0.25, 0.85, darkMetal, s * (W / 2 - 0.4), 0.12, z, 0.05)
      }
      rbox(0.08, 0.03, D - 1.2, cyanMat, s * (W / 2 - 1.0), 0.015, 0, 0.012)          // floor edge strip
      rbox(0.4, 0.08, D - 1.2, darkMetal, s * (W / 2 - 0.75), 0.04, 0, 0.03)          // kick plate
    }
    // machinery in the wall bays: many small rounded boxes, drawn as one instanced mesh
    {
      const r2 = rng(3), geo = new RoundedBoxGeometry(1, 1, 1, 2, 0.08), n = 140
      const inst = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({ color: 0x2a333d, roughness: 0.45, metalness: this.floatOK ? 0.8 : 0.3 }), n)
      const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sz = new THREE.Vector3()
      for (let i = 0; i < n; i++) {
        const s = i % 2 ? 1 : -1, z = -7 + 12 * r2(), y = 0.4 + r2() * 4.2
        sz.set(0.12 + r2() * 0.25, 0.15 + r2() * 0.6, 0.3 + r2() * 1.1)
        p.set(s * (W / 2 - sz.x / 2 - 0.02), y, z); m.compose(p, q, sz); inst.setMatrixAt(i, m)
      }
      inst.castShadow = inst.receiveShadow = this.hq; sc.add(inst)
    }
    const back = new THREE.Mesh(new THREE.PlaneGeometry(W, HGT), panel2); back.rotation.y = Math.PI; back.position.set(0, HGT / 2, D / 2); sc.add(back)
    const door = new THREE.Mesh(new THREE.ShapeGeometry(ringShape(oct(2.4, 3.2, 0.5), oct(2.25, 3.05, 0.45))), cyanMat); door.rotation.y = Math.PI; door.position.set(0, 1.6, D / 2 - 0.02); sc.add(door)
    const doorPanel = new THREE.Mesh(new THREE.ShapeGeometry(oct(2.25, 3.05, 0.45)), darkMetal); doorPanel.rotation.y = Math.PI; doorPanel.position.set(0, 1.6, D / 2 - 0.01); sc.add(doorPanel)

    // ---- the window wall: panelling with an octagonal opening, a deep bevelled frame, glowing edges, glass ----
    const wallShape = new THREE.Shape(); wallShape.moveTo(-W / 2, 0); wallShape.lineTo(W / 2, 0); wallShape.lineTo(W / 2, HGT + 0.3); wallShape.lineTo(-W / 2, HGT + 0.3); wallShape.closePath()
    wallShape.holes.push(new THREE.Path(oct(WIN.w + 1.0, WIN.h + 1.0, WIN.c + 0.35, 0, WIN.y).getPoints()))
    const fgeo = new THREE.ShapeGeometry(wallShape), uv = fgeo.attributes.uv
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) / 4, uv.getY(i) / 5)
    const front = new THREE.Mesh(fgeo, frontMat); front.position.z = -D / 2; sc.add(front)
    const frame = new THREE.Mesh(new THREE.ExtrudeGeometry(ringShape(oct(WIN.w + 1.0, WIN.h + 1.0, WIN.c + 0.35, 0, WIN.y), oct(WIN.w, WIN.h, WIN.c, 0, WIN.y)),
      { depth: 0.8, bevelEnabled: true, bevelThickness: 0.08, bevelSize: 0.06, bevelSegments: 3 }), metal)
    frame.position.z = -D / 2 - 0.25; frame.castShadow = this.hq; sc.add(frame)
    for (const [o, i, z] of [[0.12, 0, 0.66], [0.94, 0.84, 0.66]]) {
      const edge = new THREE.Mesh(new THREE.ShapeGeometry(ringShape(oct(WIN.w + o, WIN.h + o, WIN.c + o * 0.4, 0, WIN.y), oct(WIN.w + i, WIN.h + i, WIN.c + i * 0.4, 0, WIN.y))), cyanMat)
      edge.position.z = -D / 2 + z; sc.add(edge)
    }
    const glass = new THREE.Mesh(new THREE.ShapeGeometry(oct(WIN.w, WIN.h, WIN.c, 0, WIN.y)),
      new THREE.MeshPhysicalMaterial({ color: 0xbfe6ff, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.03, envMapIntensity: 0.06, depthWrite: false }))   // barely there: a haze on the glass would hide faint stars
    glass.position.z = -D / 2 + 0.1; glass.name = 'window'; sc.add(glass); this.glass = glass
    glass.material.visible = false   // lit by the window lamp it drew a blue haze over the stars; it stays as the click target
    rbox(WIN.w - 1, 0.5, 1.1, metal, 0, 0.25, -D / 2 + 0.55, 0.08)                     // sill
    rbox(WIN.w - 1.2, 0.04, 0.06, cyanMat, 0, 0.51, -D / 2 + 1.08, 0.015)
    // the time lever on the sill, right of centre: pull it towards you to go forward in time
    {
      const lv = new THREE.Group(); lv.position.set(1.7, 0.5, -D / 2 + 0.8); sc.add(lv); this.lever = lv
      const base = new THREE.Mesh(new RoundedBoxGeometry(0.34, 0.12, 0.62, 3, 0.04), darkMetal); base.position.y = 0.06; base.name = 'lever'; lv.add(base)
      const slot = new THREE.Mesh(new RoundedBoxGeometry(0.06, 0.02, 0.5, 2, 0.01), cyanMat); slot.position.y = 0.125; lv.add(slot)
      const pivot = new THREE.Group(); pivot.position.y = 0.13; lv.add(pivot); this.leverPivot = pivot
      const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.03, 0.62, 16), metal); arm.position.y = 0.31; arm.name = 'lever'; pivot.add(arm)
      const knob = new THREE.Mesh(new THREE.SphereGeometry(0.075, 24, 16), new THREE.MeshStandardMaterial({ color: 0x000000, emissive: 0xffc46b, emissiveIntensity: 2.6 }))
      knob.position.y = 0.64; knob.name = 'lever'; pivot.add(knob); this.leverKnob = knob
      this.leverA = -LEVER_MAX; pivot.rotation.x = this.leverA
      this.leverParts = [base, arm, knob]
    }

    // ---- the view out of the window: the field the telescope points at, its real SPHEREx picture ----
    // It sits far outside, past the glass, so it is seen through the window like the sky (not on the glass). 0.3 deg of
    // sky is shown magnified across the view (the page says so); its edges fade into the all-sky map behind it, and it is
    // added on top of that map, so its dark background lets the sky through and only its stars show.
    const holo = new THREE.Group(); holo.position.set(0, WIN.y + 1, -D / 2 - 40); holo.scale.setScalar(26); holo.visible = false; sc.add(holo); this.holo = holo
    const fadeCv = document.createElement('canvas'); fadeCv.width = fadeCv.height = 128
    const fg = fadeCv.getContext('2d'), grd = fg.createRadialGradient(64, 64, 34, 64, 64, 64)
    grd.addColorStop(0, '#fff'); grd.addColorStop(1, '#000'); fg.fillStyle = grd; fg.fillRect(0, 0, 128, 128)
    const fadeTex = new THREE.CanvasTexture(fadeCv)
    const hm = () => new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, alphaMap: fadeTex, blending: THREE.AdditiveBlending, depthWrite: false, fog: false, toneMapped: false })
    this.holoA = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 2.6), hm()); this.holoB = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 2.6), hm())
    this.holoA.name = this.holoB.name = 'field'; this.holoB.position.z = 0.001; holo.add(this.holoA, this.holoB)
    this.frames = []; this.fk = 0; this.fadeT0 = 0
    // marks: a ring where the moving star is at this moment, dots where each visit measured it, and the chosen star
    const markM = (c) => new THREE.MeshBasicMaterial({ color: c, transparent: true, depthWrite: false, toneMapped: false, fog: false })
    this.marks = new THREE.Group(); this.marks.position.z = 0.004; holo.add(this.marks)
    this.ring = new THREE.Mesh(new THREE.RingGeometry(0.06, 0.07, 48), markM(0xffb347)); this.ring.visible = false; this.marks.add(this.ring)
    this.dots = new THREE.Group(); this.marks.add(this.dots); this.dotM = markM(0x5fd4ff)
    this.sel = new THREE.Mesh(new THREE.RingGeometry(0.085, 0.095, 48), markM(0xffffff)); this.sel.visible = false; this.marks.add(this.sel)

    // ---- the computer ----
    const pc = new THREE.Group(); pc.position.set(4.7, 0, -2.6); pc.rotation.y = -Math.PI / 2; sc.add(pc); this.pc = pc
    const desk = new THREE.Mesh(new RoundedBoxGeometry(2.4, 0.95, 0.9, 3, 0.06), metal); desk.position.y = 0.475; desk.name = 'computer'; desk.castShadow = desk.receiveShadow = this.hq; pc.add(desk)
    const top = new THREE.Mesh(new RoundedBoxGeometry(2.42, 0.03, 0.92, 2, 0.01), cyanMat); top.position.y = 0.96; pc.add(top)
    this.screenCv = document.createElement('canvas'); this.screenCv.width = 1024; this.screenCv.height = 576
    this.screenTex = new THREE.CanvasTexture(this.screenCv); this.screenTex.colorSpace = THREE.SRGBColorSpace
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 1.24), new THREE.MeshBasicMaterial({ map: this.screenTex, toneMapped: false }))
    screen.position.set(0, 1.75, -0.1); screen.rotation.x = -0.18; screen.name = 'computer'; pc.add(screen)
    const bez = new THREE.Mesh(new RoundedBoxGeometry(2.34, 1.38, 0.08, 3, 0.03), darkMetal); bez.position.set(0, 1.75, -0.15); bez.rotation.x = -0.18; pc.add(bez)
    const pole = new THREE.Mesh(new RoundedBoxGeometry(0.12, 0.8, 0.12, 2, 0.03), metal); pole.position.set(0, 1.2, -0.27); pc.add(pole)
    const scrLight = new THREE.PointLight(0x5fd4ff, 3, 4, 2); scrLight.position.set(0, 1.7, 0.6); pc.add(scrLight); this.scrLight = scrLight
    this.drawScreen(null)

    // ---- the assistant: a small robot hovering by the window; clicking it opens the Ask panel ----
    // All procedural: one shell material for the body, head and arms, one geometry for both eyes, the room's own metal
    // and light-strip materials for the rest (disposed with the scene). It bobs and turns to face the visitor, except
    // with reduced motion or on the light / plain render paths, where it stays still.
    {
      const bot = new THREE.Group(); bot.position.set(-3.2, 1.3, -4.2); bot.rotation.y = 0.32; sc.add(bot); this.bot = bot; this.botY = 1.3
      const shell = new THREE.MeshStandardMaterial({ color: 0xe6ebf0, roughness: 0.35, metalness: this.floatOK ? 0.25 : 0 })
      const eyeMat = new THREE.MeshStandardMaterial({ color: 0x000000, emissive: 0x7fe3ff, emissiveIntensity: 3 })
      const tipMat = new THREE.MeshStandardMaterial({ color: 0x000000, emissive: 0xffc46b, emissiveIntensity: 2.6 })
      const part = (geo, mat, parent, x = 0, y = 0, z = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.name = 'robot'; m.castShadow = this.hq; parent.add(m); return m }
      const body = part(new RoundedBoxGeometry(0.42, 0.44, 0.34, 3, 0.12), shell, bot)
      const chest = part(new RoundedBoxGeometry(0.18, 0.05, 0.02, 2, 0.02), cyanMat, bot, 0, 0.05, 0.172)
      const head = new THREE.Group(); head.position.y = 0.42; bot.add(head); this.botHead = head
      const skull = part(new RoundedBoxGeometry(0.52, 0.36, 0.38, 3, 0.14), shell, head)
      const visor = part(new RoundedBoxGeometry(0.4, 0.2, 0.04, 2, 0.06), darkMetal, head, 0, 0, 0.18)
      const eyeGeo = new THREE.SphereGeometry(0.036, 16, 12)
      const eyes = [-0.08, 0.08].map((x) => { const e = part(eyeGeo, eyeMat, head, x, 0.01, 0.205); e.scale.z = 0.5; return e })
      const stalk = part(new THREE.CylinderGeometry(0.012, 0.012, 0.16, 8), metal, head, 0, 0.26, 0)
      this.botTip = part(new THREE.SphereGeometry(0.036, 16, 12), tipMat, head, 0, 0.36, 0)
      const armGeo = new THREE.CapsuleGeometry(0.045, 0.16, 4, 8)
      const arms = [-1, 1].map((k) => { const a = part(armGeo, shell, bot, k * 0.27, -0.03, 0); a.rotation.z = k * 0.25; return a })
      const ring = part(new THREE.TorusGeometry(0.15, 0.014, 8, 32), cyanMat, bot, 0, -0.3, 0); ring.rotation.x = Math.PI / 2   // the hover thruster
      this.botParts = [body, chest, skull, visor, ...eyes, stalk, this.botTip, ...arms, ring]
      this.botAnim = !reduced && !this.lite && this.floatOK
    }

    // ---- light: a little sky fill, the window's blue light (with shadows), lamps along the ceiling ----
    sc.add(new THREE.HemisphereLight(0x9fd8ff, 0x0a0f14, this.floatOK ? 0.25 : 0.9))
    const winLight = new THREE.SpotLight(0x9fd6ff, 260, 30, 0.75, 0.6, 1.6); winLight.position.set(0, 4.2, -9.5); winLight.target.position.set(0, 0, 0)
    sc.add(winLight, winLight.target)
    if (this.hq) { winLight.castShadow = true; winLight.shadow.mapSize.set(1024, 1024); winLight.shadow.bias = -0.0004; winLight.shadow.radius = 4 }
    for (const z of [-4, 0.5, 5]) { const pl = new THREE.PointLight(0xd8f2ff, 9, 11, 1.8); pl.position.set(0, 4.3, z); sc.add(pl) }
    for (const s of [-1, 1]) { const pl = new THREE.PointLight(0x5fd4ff, 3, 6, 2); pl.position.set(s * 4.6, 0.6, 0); sc.add(pl) }

    // ---- post: bloom on the light strips and the window, then tone mapping (GPU only) ----
    if (this.hq) {
      this.composer = new EffectComposer(r)
      this.composer.addPass(new RenderPass(sc, this.camera))
      this.bloom = new UnrealBloomPass(new THREE.Vector2(512, 512), 0.22, 0.2, 2.6)   // only what is brighter than white blooms: the strips, the Sun
      this.composer.addPass(this.bloom)
      this.composer.addPass(new OutputPass())
    }

    if (!this.phone) this._models(sc)   // the stool, pipes and cables: 15 more 1k textures, too much memory for a phone
    this.interactive = [...this.leverParts, ...this.botParts, glass, screen, desk, floor, this.holoA]
    this.ray = new THREE.Raycaster()
    this._bind(); this.resize()
    try { r.compile(sc, this.camera) } catch { /* only an optimisation */ }
    this._raf = requestAnimationFrame(this._tick)
  }

  /** Real props (Poly Haven, CC0): a stool at the computer, pipe runs along the ceiling, cable runs on the walls. Loaded after the room is up. */
  _models(sc) {
    const gl = new GLTFLoader(), base = '/room/models'
    const prep = (o) => { o.traverse((m) => { if (m.isMesh) { m.castShadow = m.receiveShadow = this.hq; if (!this.floatOK && m.material) m.material.metalness = Math.min(m.material.metalness ?? 0, 0.3) } }); return o }
    gl.load(`${base}/metal_stool_01/metal_stool_01.gltf`, (g) => { const m = prep(g.scene); m.position.set(3.75, 0, -2.0); m.rotation.y = 0.4; sc.add(m) })
    gl.load(`${base}/modular_industrial_pipes_01/modular_industrial_pipes_01.gltf`, (g) => {
      const pipe = g.scene.getObjectByName('modular_industrial_pipes_01_pipe02')
      if (!pipe) return
      pipe.position.set(0, 0, 0); prep(pipe)
      for (const s of [-1, 1]) for (const [dx, dy] of [[0, 0], [0.26, -0.18]]) for (let i = 0; i < 7; i++) {   // two parallel runs each side, 1.96 m pieces
        const c = pipe.clone(); c.rotation.x = Math.PI / 2; c.position.set(s * (5.05 - dx), 4.45 + dy, -6.02 + i * 1.96); sc.add(c)
      }
    })
    gl.load(`${base}/modular_electric_cables/modular_electric_cables.gltf`, (g) => {
      const v = g.scene.getObjectByName('cable_double_alt_long'), h = g.scene.getObjectByName('cable_straight_long')
      if (v) { v.position.set(0, 0, 0); prep(v)
        for (const s of [-1, 1]) for (const z of [-5.1, -1.1, 2.9, 6.6]) for (let i = 0; i < 7; i++) {           // vertical runs on the side walls
          const c = v.clone(); c.position.set(s * 5.975, 0.25 + i * 0.61, z); if (s > 0) c.rotation.y = Math.PI; sc.add(c)
        } }
      if (h) { h.position.set(0, 0, 0); prep(h)
        for (const x of [-1.25, -1.18, 1.18, 1.25]) for (let i = 0; i < 25; i++) {                              // bundles along the ceiling channel
          const c = h.clone(); c.rotation.x = Math.PI / 2; c.position.set(x, HGT + 0.2, -7.6 + i * 0.61); sc.add(c)
        } }
    })
  }

  drawScreen(f) {
    const g = this.screenCv.getContext('2d'), w = 1024, h = 576
    const grd = g.createLinearGradient(0, 0, 0, h); grd.addColorStop(0, '#062033'); grd.addColorStop(1, '#020b12'); g.fillStyle = grd; g.fillRect(0, 0, w, h)
    g.strokeStyle = 'rgba(95,212,255,.14)'; g.lineWidth = 1
    for (let x = 0; x < w; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke() }
    for (let y = 0; y < h; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(w, y); g.stroke() }
    g.fillStyle = '#5fd4ff'; g.font = '600 34px monospace'; g.fillText('SPHEREx · PIPELINE', 40, 64)
    g.fillStyle = 'rgba(95,212,255,.5)'; g.fillRect(40, 82, 944, 2)
    const lines = f
      ? [`TARGET  ${f.target?.name || f.name}`, `RA ${f.ra.toFixed(3)}  DEC ${f.dec.toFixed(3)}`, '', '1 FETCH   cutouts from IRSA (DR1/QR3)', '2 STACK   each half-year visit', '3 MEASURE positions & brightness', '4 COMPARE Gaia / CatWISE / VSX', '', '> CLICK TO SEE HOW IT WAS JUDGED']
      : ['NO TARGET', '', 'Walk to the window and choose', 'what the telescope should look at.', '', '1 FETCH   2 STACK   3 MEASURE   4 COMPARE']
    g.font = '500 28px monospace'
    lines.forEach((s, i) => { g.fillStyle = s.startsWith('>') ? '#ffcf7a' : '#d8f6ff'; g.fillText(s, 40, 130 + i * 46) })
    for (let y = 0; y < h; y += 3) { g.fillStyle = 'rgba(0,0,0,.12)'; g.fillRect(0, y, w, 1) }              // scan lines
    this.screenTex.needsUpdate = true
  }

  /** focus: { W, H, track: [{x, y}] per visit } zooms the hologram onto the moving star (else the whole field). */
  setTarget(f, urls, focus) {
    this.target = f
    const from = this.skyPivot.quaternion.clone(), to = new THREE.Quaternion().setFromUnitVectors(radec(f.ra, f.dec), WINDOW_AIM)
    this.turn = { from, to, t0: performance.now() }
    this.fadeT0 = performance.now() + 1500            // the field comes into view as the turn ends
    const loader = new THREE.TextureLoader(), W = focus?.W || 177, H = focus?.H || 177
    this.crop = { cx: (W - 1) / 2, cy: (H - 1) / 2, c: W, W, H, track: null }
    const old = this.frames
    this.frames = urls.map((u) => this._tex(u, loader))
    for (const t of old) t.dispose()
    this._clearDots(); this.ring.visible = false; this.sel.visible = false     // nothing is marked until a star is chosen
    this.fk = 0; this.holoA.material.map = this.frames[0] || null; this.holoB.material.map = this.frames[1] || this.frames[0] || null
    this.holoA.material.needsUpdate = this.holoB.material.needsUpdate = true
    this.holo.visible = !!this.frames.length; this.holoT0 = performance.now()
    this.manualT = 0; this.leverA = -LEVER_MAX; this.leverPivot.rotation.x = this.leverA      // a still sky at the first visit; the lever moves it on
    this.drawScreen(f)
  }

  /** Show how a chosen star moves: a ring where it is at this moment, dots where each visit measured it and, for a
   *  moving star, an arrow along its motion drawn 10 times longer than the real shift (the page says so). null clears. */
  showTrack(tr, kind) {
    this._clearDots(); this.ring.visible = false
    if (!this.crop) return
    this.crop.track = tr?.length ? tr : null
    if (!this.crop.track) return
    this.ring.visible = true; this._ringAt(this.manualT ?? 0)
    this.dotGeo ??= new THREE.CircleGeometry(0.014, 16)                       // one geometry shared by every dot
    for (const q of tr) { const d = new THREE.Mesh(this.dotGeo, this.dotM); d.position.set(...this._holoXY(q.x, q.y), 0); this.dots.add(d) }
    if (kind === 'pm' && tr.length > 1) {
      const a = tr[0], b = tr[tr.length - 1], [x0, y0] = this._holoXY(a.x, a.y), [x1, y1] = this._holoXY(b.x, b.y)
      const d = new THREE.Vector3(x1 - x0, y1 - y0, 0), L = d.length() * 10
      if (L > 0.02) {
        const ar = new THREE.ArrowHelper(d.normalize(), new THREE.Vector3(x0, y0, 0.001), L, 0xffe08a, Math.min(0.08, L * 0.3), Math.min(0.05, L * 0.2))
        ar.traverse((o) => { o.renderOrder = 6; if (o.material) { o.material.depthTest = false; o.material.transparent = true; o.material.toneMapped = false; o.material.fog = false } })
        this.dots.add(ar)
      }
    }
  }

  /** Remove the track marks; only the arrow owns GPU resources (the dots share one geometry and material). */
  _clearDots() {
    for (const o of this.dots.children) if (o.isArrowHelper) o.dispose()
    this.dots.clear()
  }

  _tex(u, loader) {
    // a picture URL, or a canvas the page composed (chosen bands, raw or enhanced)
    const t = typeof u === 'string' ? (loader || new THREE.TextureLoader()).load(u) : new THREE.CanvasTexture(u)
    t.colorSpace = THREE.SRGBColorSpace
    return t
  }

  /** Swap the pictures of the field in view (another band, a merge, raw or enhanced) without turning the telescope. */
  setFrames(list) {
    const old = this.frames
    this.frames = list.map((u) => this._tex(u))
    const n = this.frames.length, tt = Math.max(0, Math.min(n - 1, this.manualT ?? 0)), i = Math.min(Math.max(0, n - 2), Math.floor(tt))
    this.holoA.material.map = this.frames[i] || null; this.holoB.material.map = this.frames[i + 1] || this.frames[i] || null
    this.holoA.material.needsUpdate = this.holoB.material.needsUpdate = true
    for (const t of old) t.dispose()
  }

  /** Mark a star of the field in view (pixel x, y), or clear the mark with null. */
  selectStar(x, y) {
    if (x == null || !this.crop) { this.sel.visible = false; return }
    const [px, py] = this._holoXY(x, y); this.sel.position.set(px, py, 0); this.sel.visible = true
  }

  _holoXY(x, y) { const { cx, cy, c } = this.crop, s = 2.6 / c; return [(x - cx) * s, (y - cy) * s] }
  _ringAt(t) {
    if (!this.crop?.track) return
    const tr = this.crop.track, n = tr.length, tt = Math.max(0, Math.min(n - 1, t)), i = Math.min(n - 2, Math.floor(tt)), f = tt - Math.max(0, i)
    const a = tr[Math.max(0, i)], b = tr[Math.min(n - 1, i + 1)]
    const [x, y] = this._holoXY(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f); this.ring.position.x = x; this.ring.position.y = y
  }

  /** Time on the hologram: t from 0 (first half-year stack) to n-1 (last); null lets it cycle by itself. */
  setTime(t) {
    this.manualT = t
    if (t != null && this.frames.length > 1) { const a = -LEVER_MAX + 2 * LEVER_MAX * t / (this.frames.length - 1); this.leverA = a; this.leverPivot.rotation.x = a }
  }
  setLeverAngle(a, fromUser) {
    this.leverA = Math.max(-LEVER_MAX, Math.min(LEVER_MAX, a)); this.leverPivot.rotation.x = this.leverA
    if (this.frames.length > 1) { this.manualT = (this.leverA + LEVER_MAX) / (2 * LEVER_MAX) * (this.frames.length - 1); if (fromUser) this.onLever?.(this.manualT) }
  }

  walkTo(where, act) {
    const spots = { window: [0.5, -4.9, 0, 0.04], computer: [2.9, -2.6, -Math.PI / 2, 0.02], door: [0, 6, Math.PI, 0.02] }
    // a phone held upright: look a little down, so the middle of the field sits above the panels at the bottom
    if (this.phone && this.canvas.clientHeight > this.canvas.clientWidth) spots.window = [0.5, -4.9, 0, -0.2]
    const s = spots[where]
    if (!s) return
    this.goal = { x: s[0], z: s[1], yaw: s[2], pitch: s[3], act: act ? where : null }
  }

  resize() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight
    if (!w || !h) return
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.fov = w < h ? 80 : 68; this.camera.updateProjectionMatrix()
    if (this.composer) { this.composer.setPixelRatio(1); this.composer.setSize(w, h) }      // post at 1x: the bloom is soft anyway
  }

  _hit(x, y) {
    const r = this.canvas.getBoundingClientRect()
    this.ray.setFromCamera(_ndc.set((x - r.left) / r.width * 2 - 1, -((y - r.top) / r.height) * 2 + 1), this.camera)
    const hits = this.ray.intersectObjects(this.interactive, false).filter((x) => x.object.name !== 'field' || this.holo.visible)
    const h = hits[0]
    if (!h || h.object.name === 'field' || h.object.name === 'sky') return null          // only through the glass
    if (h.object.name === 'window' && this.pos.z < -2.5) return hits.find((x) => x.object.name === 'field') || hits.find((x) => x.object.name === 'sky') || h
    return h
  }
  _act(name, point, hit) {
    if (name === 'field' && hit?.uv && this.crop) { const { W, H } = this.crop; this.onPick?.({ kind: 'star', x: hit.uv.x * W - 0.5, y: hit.uv.y * H - 0.5 }) }
    else if (name === 'sky') { const v = point.clone().normalize().applyQuaternion(this.skyPivot.quaternion.clone().invert()); this.onPick?.({ kind: 'sky', ...toRadec(v) }) }
    else if (name === 'window') { if (this.pos.z < -3.5) this.onAct('window'); else this.walkTo('window') }
    else if (name === 'computer') { if (Math.hypot(this.pos.x - 2.9, this.pos.z + 2.6) < 1.6) this.onAct('computer'); else this.walkTo('computer', true) }
    else if (name === 'robot') this.onAct('robot')
    else if (name === 'floor' && point) this.goal = { x: point.x, z: point.z }
  }

  _bind() {
    const c = this.canvas
    let down = null, moved = 0
    this._down = (e) => {
      down = { x: e.clientX, y: e.clientY }; moved = 0; c.setPointerCapture?.(e.pointerId)
      const h = this._hit(e.clientX, e.clientY)
      this._lever = h?.object.name === 'lever' && this.frames.length > 1 ? { y: e.clientY, a: this.leverA } : null
    }
    this._move = (e) => {
      if (down && this._lever) { moved += 10; this.setLeverAngle(this._lever.a + (e.clientY - this._lever.y) * 0.006, true); return }
      if (down) {
        const dx = e.clientX - down.x, dy = e.clientY - down.y; down = { x: e.clientX, y: e.clientY }; moved += Math.abs(dx) + Math.abs(dy)
        if (moved > 5) { this.yawT = (this.yawT ?? this.yaw) + dx * 0.0042; this.pitchT = Math.max(-1.1, Math.min(1.1, (this.pitchT ?? this.pitch) + dy * 0.0042)) }
        return
      }
      if (e.pointerType !== 'mouse') return
      const h = this._hit(e.clientX, e.clientY), n = h && h.object.name !== 'floor' ? h.object.name : null
      c.style.cursor = n === 'lever' ? 'ns-resize' : n ? 'pointer' : h ? 'crosshair' : ''
      if (n !== this._hot) { this._hot = n; this.onHover(n) }
    }
    this._up = (e) => {
      this._lever = null
      if (down && moved <= 5) { const h = this._hit(e.clientX, e.clientY); if (h) this._act(h.object.name, h.point, h) }
      down = null
    }
    this._key = (e) => {
      const k = e.key.toLowerCase()
      if (!WALK_KEYS.has(k)) return
      if (e.target.closest?.('input, textarea, select')) return
      e.preventDefault()
      if (e.type === 'keydown') { this.keys.add(k); this.goal = null } else this.keys.delete(k)
    }
    c.addEventListener('pointerdown', this._down); c.addEventListener('pointermove', this._move); c.addEventListener('pointerup', this._up)
    window.addEventListener('keydown', this._key); window.addEventListener('keyup', this._key)
    this._ro = new ResizeObserver(() => this.resize()); this._ro.observe(c)
  }

  _tick = (now) => {
    this._raf = requestAnimationFrame(this._tick)
    if (document.hidden) { this._last = now; return }
    const dt = Math.min(0.1, (now - (this._last || now)) / 1000); this._last = now
    // looking: the drag sets a target, the head eases towards it (no jitter from uneven pointer events)
    // (yawT and pitchT are set separately: walking sets only yawT, so each eases on its own; one undefined made NaN, a black screen)
    const ease = 1 - Math.exp(-dt * 14)
    if (this.yawT != null) this.yaw += (this.yawT - this.yaw) * ease
    if (this.pitchT != null) this.pitch += (this.pitchT - this.pitch) * ease
    const k = this.keys, fw = _fw.set(-Math.sin(this.yaw), 0, -Math.cos(this.yaw)), rt = _rt.set(Math.cos(this.yaw), 0, -Math.sin(this.yaw))
    const mv = _mv.set(0, 0, 0)
    if (k.has('w') || k.has('arrowup')) mv.add(fw)
    if (k.has('s') || k.has('arrowdown')) mv.sub(fw)
    if (k.has('d')) mv.add(rt)
    if (k.has('a')) mv.sub(rt)
    if (k.has('arrowleft')) { this.yaw += dt * 1.6; this.yawT = this.yaw }
    if (k.has('arrowright')) { this.yaw -= dt * 1.6; this.yawT = this.yaw }
    // walking has momentum: speed eases up and down
    this.vel ??= new THREE.Vector3()
    let walking = false
    if (mv.lengthSq() > 0) { mv.normalize().multiplyScalar(3.2); walking = true }
    else if (this.goal) {
      const d = _d.set(this.goal.x - this.pos.x, 0, this.goal.z - this.pos.z), L = d.length()
      if (L > 0.06) {
        mv.copy(d.normalize().multiplyScalar(Math.min(3.4, L * 3))); walking = true
        const want = this.goal.yaw ?? Math.atan2(-mv.x, -mv.z)
        let dy = want - this.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy)); this.yaw += dy * Math.min(1, dt * 4); this.yawT = this.yaw
        if (this.goal.yaw != null) { this.pitch += ((this.goal.pitch ?? 0.02) - this.pitch) * Math.min(1, dt * 3); this.pitchT = this.pitch }
      } else {
        if (this.goal.yaw != null) { let dy = this.goal.yaw - this.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy)); this.yaw += dy * Math.min(1, dt * 6); this.yawT = this.yaw; const dp = (this.goal.pitch ?? this.pitch) - this.pitch; this.pitch += dp * Math.min(1, dt * 6); this.pitchT = this.pitch; if (Math.abs(dy) > 0.02 || Math.abs(dp) > 0.02) walking = true }
        if (!walking) { const a = this.goal.act; this.goal = null; if (a) this.onAct(a) }
      }
    }
    this.vel.lerp(mv, 1 - Math.exp(-dt * 8))
    this.pos.addScaledVector(this.vel, dt)
    this.pos.x = Math.max(-W / 2 + 1.0, Math.min(W / 2 - 1.0, this.pos.x)); this.pos.z = Math.max(-D / 2 + 1.5, Math.min(D / 2 - 0.8, this.pos.z))
    if (this.pos.x > 3.3 && this.pos.z > -4.1 && this.pos.z < -1.1) this.pos.x = 3.3
    const t = (now - this.t0) / 1000, sp = this.vel.length()
    this.stride = (this.stride || 0) + sp * dt * 2.6
    const bob = Math.sin(this.stride * 2) * 0.03 * Math.min(1, sp / 3), sway = Math.cos(this.stride) * 0.012 * Math.min(1, sp / 3)
    if (![this.pos.x, this.pos.z, this.yaw, this.pitch].every(Number.isFinite)) { this.pos.set(0, EYE, 5.5); this.yaw = 0; this.pitch = 0.02; this.yawT = this.pitchT = null; this.goal = null; this.vel?.set(0, 0, 0) }
    this.camera.position.set(this.pos.x, EYE + bob, this.pos.z)
    this.camera.rotation.set(0, 0, 0); this.camera.rotateY(this.yaw); this.camera.rotateX(this.pitch); this.camera.rotateZ(sway)

    if (this.turn) { const u = Math.min(1, (now - this.turn.t0) / 2200), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; this.skyPivot.quaternion.slerpQuaternions(this.turn.from, this.turn.to, e); if (u >= 1) this.turn = null }
    if (this.holo.visible && this.frames.length > 1 && this.manualT != null) {             // the lever sets the time
      const n = this.frames.length, tt = Math.max(0, Math.min(n - 1, this.manualT)), i = Math.min(n - 2, Math.floor(tt)), fr = tt - i
      if (this.holoA.material.map !== this.frames[i] || this.holoB.material.map !== this.frames[i + 1]) { this.holoA.material.map = this.frames[i]; this.holoB.material.map = this.frames[i + 1]; this.holoA.material.needsUpdate = this.holoB.material.needsUpdate = true }
      this._fb = fr
      this._ringAt(tt)
    } else if (this.holo.visible && this.frames.length > 1) {
      const per = 1.4, ph = (now - this.holoT0) / 1000 / per, i = Math.floor(ph) % this.frames.length, fr = ph % 1
      if (i !== this.fk) { this.fk = i; this.holoA.material.map = this.frames[i]; this.holoB.material.map = this.frames[(i + 1) % this.frames.length]; this.holoA.material.needsUpdate = this.holoB.material.needsUpdate = true }
      this._fb = fr > 0.6 ? (fr - 0.6) / 0.4 : 0
      this._ringAt(i + (fr > 0.6 ? (fr - 0.6) / 0.4 : 0))
    }
    if (this.holo.visible) {
      const fade = Math.max(0, Math.min(1, (now - this.fadeT0) / 900)), fb = this.frames.length > 1 ? (this._fb || 0) : 0
      this.holoA.material.opacity = (1 - fb) * fade; this.holoB.material.opacity = fb * fade; this.marks.visible = fade > 0.6
    }
    this.scrLight.intensity = 2.6 + Math.sin(t * 2) * 0.4
    if (this.botAnim) {                                                                   // the robot: hover, face the visitor
      const b = this.bot; b.position.y = this.botY + Math.sin(t * 1.6) * 0.06
      let dy = Math.atan2(this.pos.x - b.position.x, this.pos.z - b.position.z) - b.rotation.y; dy = Math.atan2(Math.sin(dy), Math.cos(dy))
      b.rotation.y += dy * Math.min(1, dt * 2); this.botHead.rotation.z = Math.sin(t * 0.9) * 0.08
      this.botTip.material.emissiveIntensity = 2.2 + Math.sin(t * 3) * 0.6
    }
    this.leverKnob.material.emissiveIntensity = this.frames.length > 1 ? 2.4 + Math.sin(t * 3) * 0.6 : 0.6
    if (this.composer) this.composer.render(); else this.renderer.render(this.scene, this.camera)
    // a GPU can fail without losing the context (no error, just black). Look at the picture twice; if it is all
    // black, hand over to the lighter version, and the page says so if that is black too.
    this._n = (this._n || 0) + 1
    if ((this._n === 30 || this._n === 150) && this._isBlack()) { cancelAnimationFrame(this._raf); this.onLost?.('black'); return }
    this.onFrame?.({ x: this.pos.x, z: this.pos.z, k: this.fk })
  }

  _isBlack() {
    try {
      const gl = this.renderer.getContext(), w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, px = new Uint8Array(4)
      let max = 0
      for (let i = 1; i < 8; i++) for (let j = 1; j < 8; j++) {
        gl.readPixels(Math.floor(w * i / 8), Math.floor(h * j / 8), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px)
        max = Math.max(max, px[0] + px[1] + px[2])
      }
      return max < 30
    } catch { return false }
  }

  destroy() {
    this._dead = true
    cancelAnimationFrame(this._raf); this._ro?.disconnect()
    const c = this.canvas
    c.removeEventListener('pointerdown', this._down); c.removeEventListener('pointermove', this._move); c.removeEventListener('pointerup', this._up)
    window.removeEventListener('keydown', this._key); window.removeEventListener('keyup', this._key)
    c.removeEventListener('webglcontextlost', this._lost)
    for (const t of this.frames) t.dispose()
    this._clearDots(); this.dotGeo?.dispose()
    this.scene.environment?.dispose(); disposeTree(this.scene)
    this.composer?.dispose?.(); this.renderer.dispose(); this.renderer.forceContextLoss()
  }
}
