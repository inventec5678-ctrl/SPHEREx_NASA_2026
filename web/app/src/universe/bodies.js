// Procedural bodies: build(type, params, seed) -> THREE.Object3D. All appearance comes from the
// parameter set (see presets.js); the same builder renders the scene object and the preview.
import * as THREE from 'three'
import { bbColor } from './presets.js'

const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){const vec2 C=vec2(1./6.,1./3.);const vec4 D=vec4(0.,.5,1.,2.);
 vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.-g;
 vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
 i=mod289(i);vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
 float n_=.142857142857;vec3 ns=n_*D.wyz-D.xzx;vec4 j=p-49.*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.*x_);
 vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.-abs(x)-abs(y);vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
 vec4 s0=floor(b0)*2.+1.;vec4 s1=floor(b1)*2.+1.;vec4 sh=-step(h,vec4(0.));vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
 vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
 vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
 vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.);m=m*m;
 return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));}
float fbm(vec3 p){float a=.5,s=0.;for(int k=0;k<5;k++){s+=a*snoise(p);p*=2.03;a*=.5;}return s;}
`

export const shared = { uTime: { value: 0 }, uSun: { value: new THREE.Vector3(1, 0.35, 0.6).normalize() } }
const sphereGeo = new THREE.SphereGeometry(1, 48, 32)
const rockGeo = new THREE.IcosahedronGeometry(1, 5)

function starMesh(p, seed) {
  const [r, g, b] = bbColor(p.temperature)
  const mat = new THREE.ShaderMaterial({
    uniforms: { uTime: shared.uTime, uColor: { value: new THREE.Color(r, g, b) }, uSeed: { value: seed }, uGran: { value: p.granulation }, uSpots: { value: p.spots } },
    vertexShader: `varying vec3 vN;varying vec3 vP;varying vec3 vV;void main(){vN=normalize(normalMatrix*normal);vP=position;vec4 mv=modelViewMatrix*vec4(position,1.);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
    fragmentShader: NOISE + `uniform vec3 uColor;uniform float uTime,uSeed,uGran,uSpots;varying vec3 vN;varying vec3 vP;varying vec3 vV;
      void main(){float g=fbm(vP*6.+uSeed+vec3(0.,0.,uTime*.08));float s=smoothstep(.55,.75,snoise(vP*2.2+uSeed*1.7));
      float limb=pow(max(dot(vN,vV),0.),.45);vec3 c=uColor*(1.+uGran*.35*g)*(1.-uSpots*.7*s);
      gl_FragColor=vec4(c*(.35+.85*limb),1.);}`,
  })
  const m = new THREE.Mesh(sphereGeo, mat)
  m.scale.setScalar(p.radius)
  const glow = glowSprite(new THREE.Color(r, g, b), p.radius * (2.6 + 3 * p.corona), 0.6 + 0.4 * p.corona)
  const o = new THREE.Group(); o.add(m, glow); return o
}

// Analytic radial glow drawn as a single point sprite (always round, no texture, no bloom artifacts).
const glowGeo = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0], 3))
const SHARED_GEOS = new Set([sphereGeo, rockGeo, glowGeo])
const noRaycast = () => {}
function glowSprite(color, size, opacity) {
  const mat = new THREE.ShaderMaterial({
    uniforms: { uColor: { value: color }, uSize: { value: size }, uOpacity: { value: opacity }, uScale: { value: window.innerHeight / 2 } },
    vertexShader: `uniform float uSize,uScale;void main(){vec4 mv=modelViewMatrix*vec4(0.,0.,0.,1.);gl_Position=projectionMatrix*mv;
      gl_PointSize=clamp(uSize*uScale*projectionMatrix[1][1]/max(-mv.z,1e-3),1.,512.);}`,
    fragmentShader: `uniform vec3 uColor;uniform float uOpacity;void main(){vec2 d=gl_PointCoord-.5;float r=length(d)*2.;
      if(r>1.)discard;float a=exp(-r*r*4.)*0.7+exp(-r*r*30.)*0.9;gl_FragColor=vec4(uColor*a*uOpacity,1.);}`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  })
  const p = new THREE.Points(glowGeo, mat); p.raycast = noRaycast; p.frustumCulled = false
  return p
}

function hsl(h, s, l) { return new THREE.Color().setHSL(((h % 1) + 1) % 1, s, l) }

function rockyMesh(p, seed) {
  const tint = hsl(p.hue, 0.28, 0.5)
  const mat = new THREE.ShaderMaterial({
    uniforms: { uSun: shared.uSun, uSeed: { value: seed }, uIrr: { value: p.irregularity }, uCr: { value: p.craters }, uAlb: { value: p.albedo }, uTint: { value: tint } },
    vertexShader: NOISE + `uniform float uSeed,uIrr,uCr;varying vec3 vW;varying vec3 vP;
      float crater(vec3 q){float c=0.;for(int k=0;k<3;k++){vec3 cq=q*(2.5+float(k)*2.1)+uSeed+float(k)*7.3;float n=snoise(cq);c+=smoothstep(.55,.85,n)*(-.6)+smoothstep(.45,.55,n)*.15;}return c;}
      void main(){vec3 n=normalize(position);float d=uIrr*fbm(n*1.3+uSeed)+uCr*.06*crater(n);vec3 pos=n*(1.+d);vP=n;
      vec4 w=modelMatrix*vec4(pos,1.);vW=w.xyz;gl_Position=projectionMatrix*viewMatrix*w;}`,
    fragmentShader: NOISE + `uniform vec3 uSun,uTint;uniform float uAlb,uSeed;varying vec3 vW;varying vec3 vP;
      void main(){vec3 N=normalize(cross(dFdx(vW),dFdy(vW)));float l=max(dot(N,uSun),0.);float v=.75+.35*fbm(vP*8.+uSeed);
      vec3 c=uTint*v*(.35+uAlb*3.2);gl_FragColor=vec4(c*(.1+1.5*l),1.);}`,
  })
  mat.extensions = { derivatives: true }
  const m = new THREE.Mesh(rockGeo, mat)
  m.scale.setScalar(p.radius)
  m.userData.spin = (2 * Math.PI) / (p.rotation_h || 8) / 3
  return m
}

function iceGiantMesh(p, seed) {
  const base = hsl(p.hue, 0.55, 0.55), alt = hsl(p.hue + 0.04, 0.45, 0.72)
  const mat = new THREE.ShaderMaterial({
    uniforms: { uSun: shared.uSun, uTime: shared.uTime, uA: { value: base }, uB: { value: alt }, uBands: { value: p.bands }, uSeed: { value: seed } },
    vertexShader: `varying vec3 vN;varying vec3 vP;varying vec3 vV;void main(){vP=position;vN=normalize(mat3(modelMatrix)*normal);vec4 w=modelMatrix*vec4(position,1.);vV=normalize(cameraPosition-w.xyz);gl_Position=projectionMatrix*viewMatrix*w;}`,
    fragmentShader: NOISE + `uniform vec3 uSun,uA,uB;uniform float uBands,uSeed,uTime;varying vec3 vN;varying vec3 vP;varying vec3 vV;
      void main(){float lat=vP.y;float w=fbm(vec3(vP.x*1.5,lat*6.,vP.z*1.5)+uSeed+vec3(uTime*.02,0.,0.));
      float b=.5+.5*sin(lat*(10.+uBands*22.)+w*2.5*uBands);vec3 c=mix(uA,uB,b*uBands+.15);
      float l=max(dot(normalize(vN),uSun),0.);float rim=pow(1.-max(dot(normalize(vN),vV),0.),3.);
      gl_FragColor=vec4(c*(.05+1.15*l)+uA*rim*.6,1.);}`,
  })
  const m = new THREE.Mesh(sphereGeo, mat); m.scale.setScalar(p.radius)
  const o = new THREE.Group(); o.add(m)
  if (p.atmosphere > 0) o.add(glowSprite(base, p.radius * (2.6 + 1.6 * p.atmosphere), 0.25 + 0.35 * p.atmosphere))
  if (p.rings > 0.02) {
    const rg = new THREE.RingGeometry(p.radius * 1.45, p.radius * (1.9 + p.rings), 96)
    const rm = new THREE.ShaderMaterial({
      uniforms: { uIn: { value: p.radius * 1.45 }, uOut: { value: p.radius * (1.9 + p.rings) }, uC: { value: alt }, uA: { value: p.rings } },
      vertexShader: `varying vec3 vP;void main(){vP=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
      fragmentShader: `uniform float uIn,uOut,uA;uniform vec3 uC;varying vec3 vP;void main(){float r=(length(vP.xy)-uIn)/(uOut-uIn);float a=(.4+.6*sin(r*40.))*smoothstep(0.,.1,r)*smoothstep(1.,.85,r)*uA;gl_FragColor=vec4(uC,a*.75);}`,
      transparent: true, side: THREE.DoubleSide, depthWrite: false,
    })
    const ring = new THREE.Mesh(rg, rm); ring.rotation.x = Math.PI / 2.4; ring.raycast = noRaycast; o.add(ring)
  }
  o.userData.spin = 0.25
  return o
}

function cometMesh(p, seed) {
  const o = new THREE.Group()
  o.add(rockyMesh({ radius: p.radius, albedo: p.albedo, irregularity: 0.4, craters: 0.4, rotation_h: 12, hue: 0.08 }, seed))
  if (p.coma > 0) o.add(glowSprite(new THREE.Color(0.7, 0.95, 0.9), p.radius * (6 + 10 * p.coma), 0.35 + 0.4 * p.coma))
  if (p.tail > 0) {
    const len = 20 + 60 * p.tail
    const tg = new THREE.ConeGeometry(p.radius * 3, len, 32, 1, true); tg.translate(0, -len / 2, 0)
    const tm = new THREE.ShaderMaterial({
      uniforms: { uLen: { value: len } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
      vertexShader: `varying float vY;void main(){vY=position.y;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`,
      fragmentShader: `uniform float uLen;varying float vY;void main(){float a=pow(1.+vY/uLen,2.);gl_FragColor=vec4(.6,.85,1.,a*.35);}`,
    })
    const tail = new THREE.Mesh(tg, tm); tail.raycast = noRaycast
    tail.lookAt(shared.uSun.value.clone().multiplyScalar(-1)); tail.rotateX(-Math.PI / 2)
    o.add(tail)
  }
  return o
}

function galaxyMesh(p, seed) {
  const n = 2500, pos = new Float32Array(n * 3), col = new Float32Array(n * 3)
  const [r, g, b] = bbColor(p.temperature)
  let s = seed * 9301 + 49297
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280)
  for (let k = 0; k < n; k++) {
    const arm = p.arms ? Math.floor(rnd() * p.arms) : 0, rr = Math.pow(rnd(), 0.6) * p.radius
    const th = (p.arms ? arm * (2 * Math.PI / p.arms) + rr * 0.9 : rnd() * 6.283) + (rnd() - 0.5) * 0.7
    const o = k * 3, core = 1 - rr / p.radius
    pos[o] = Math.cos(th) * rr; pos[o + 1] = (rnd() - 0.5) * p.radius * 0.08; pos[o + 2] = Math.sin(th) * rr
    col[o] = r * (0.6 + core); col[o + 1] = g * (0.55 + core * 0.9); col[o + 2] = b * (0.5 + core * 0.7)
  }
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('color', new THREE.BufferAttribute(col, 3))
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ size: 0.35, vertexColors: true, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }))
  pts.rotation.x = p.tilt
  const o = new THREE.Group(); o.add(pts)
  const hit = new THREE.Mesh(sphereGeo, new THREE.MeshBasicMaterial({ visible: false })); hit.scale.setScalar(p.radius * 0.7); o.add(hit)
  o.userData.spin = 0.05
  return o
}

const BUILDERS = { star: starMesh, rocky: rockyMesh, comet: cometMesh, ice_giant: iceGiantMesh, galaxy: galaxyMesh }

export function build(type, p, seed = 1) {
  const o = BUILDERS[type](p, seed % 97)
  o.userData.type = type
  return o
}

/** Free a built body's own GPU resources; the module-wide shared geometries stay. */
export function dispose(o) {
  o.traverse((c) => {
    if (c.material) { for (const m of [].concat(c.material)) m.dispose() }
    if (c.geometry && !SHARED_GEOS.has(c.geometry)) c.geometry.dispose()
  })
}
