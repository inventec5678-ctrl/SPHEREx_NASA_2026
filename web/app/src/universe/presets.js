// Planet / star presets. Every sphere in the universe is BUILT from one of these parameter sets:
// the model prediction (from the measured SPHEREx spectrum or JPL SBDB) fills in the numbers,
// and the user can switch preset or edit any parameter and rebuild the body.

export const PARAMS = {
  star: [
    { key: 'temperature', label: '表面溫度 (K)', min: 2300, max: 40000, step: 100, log: true },
    { key: 'radius', label: '顯示半徑', min: 0.4, max: 6, step: 0.1 },
    { key: 'granulation', label: '米粒組織', min: 0, max: 1, step: 0.05 },
    { key: 'spots', label: '黑子', min: 0, max: 1, step: 0.05 },
    { key: 'corona', label: '日冕光暈', min: 0, max: 1, step: 0.05 },
  ],
  galaxy: [
    { key: 'temperature', label: '整體色溫 (K)', min: 2300, max: 20000, step: 100, log: true },
    { key: 'radius', label: '顯示半徑', min: 2, max: 20, step: 0.5 },
    { key: 'arms', label: '旋臂數', min: 0, max: 4, step: 1 },
    { key: 'tilt', label: '傾角', min: 0, max: 1.5, step: 0.05 },
  ],
  rocky: [
    { key: 'radius', label: '顯示半徑', min: 1, max: 10, step: 0.1 },
    { key: 'albedo', label: '反照率', min: 0.02, max: 0.5, step: 0.01 },
    { key: 'irregularity', label: '形狀不規則', min: 0, max: 0.6, step: 0.02 },
    { key: 'craters', label: '坑洞', min: 0, max: 1, step: 0.05 },
    { key: 'rotation_h', label: '自轉週期 (小時)', min: 2, max: 48, step: 0.5 },
    { key: 'hue', label: '色調', min: 0, max: 1, step: 0.01 },
  ],
  comet: [
    { key: 'radius', label: '核心半徑', min: 0.5, max: 5, step: 0.1 },
    { key: 'albedo', label: '反照率', min: 0.02, max: 0.2, step: 0.01 },
    { key: 'coma', label: '彗髮', min: 0, max: 1, step: 0.05 },
    { key: 'tail', label: '彗尾長度', min: 0, max: 1, step: 0.05 },
  ],
  ice_giant: [
    { key: 'radius', label: '顯示半徑', min: 2, max: 14, step: 0.2 },
    { key: 'hue', label: '大氣色調', min: 0, max: 1, step: 0.01 },
    { key: 'bands', label: '雲帶', min: 0, max: 1, step: 0.05 },
    { key: 'atmosphere', label: '大氣光暈', min: 0, max: 1, step: 0.05 },
    { key: 'rings', label: '光環', min: 0, max: 1, step: 0.05 },
  ],
}

// Named presets (the "library"). type + default parameters.
export const LIBRARY = [
  { id: 'm-dwarf', name: '紅矮星（M 型）', type: 'star', p: { temperature: 3200, radius: 1.0, granulation: 0.6, spots: 0.45, corona: 0.3 } },
  { id: 'k-dwarf', name: '橘矮星（K 型）', type: 'star', p: { temperature: 4500, radius: 1.4, granulation: 0.55, spots: 0.25, corona: 0.35 } },
  { id: 'sun', name: '類太陽（G 型）', type: 'star', p: { temperature: 5800, radius: 1.8, granulation: 0.5, spots: 0.1, corona: 0.4 } },
  { id: 'a-star', name: '白色恆星（A 型）', type: 'star', p: { temperature: 9000, radius: 2.4, granulation: 0.3, spots: 0, corona: 0.55 } },
  { id: 'b-giant', name: '藍巨星（B 型）', type: 'star', p: { temperature: 20000, radius: 3.6, granulation: 0.25, spots: 0, corona: 0.8 } },
  { id: 'spiral', name: '螺旋星系', type: 'galaxy', p: { temperature: 5200, radius: 9, arms: 2, tilt: 0.7 } },
  { id: 'c-type', name: 'C 型小行星（碳質、暗）', type: 'rocky', p: { radius: 4, albedo: 0.06, irregularity: 0.25, craters: 0.7, rotation_h: 8, hue: 0.08 } },
  { id: 's-type', name: 'S 型小行星（石質）', type: 'rocky', p: { radius: 4, albedo: 0.22, irregularity: 0.3, craters: 0.5, rotation_h: 6, hue: 0.07 } },
  { id: 'v-type', name: 'V 型小行星（玄武岩）', type: 'rocky', p: { radius: 3.5, albedo: 0.35, irregularity: 0.2, craters: 0.45, rotation_h: 5.3, hue: 0.12 } },
  { id: 'd-type', name: 'D 型小行星（紅、暗）', type: 'rocky', p: { radius: 4, albedo: 0.05, irregularity: 0.35, craters: 0.6, rotation_h: 10, hue: 0.02 } },
  { id: 'comet', name: '活躍彗星', type: 'comet', p: { radius: 1.6, albedo: 0.04, coma: 0.8, tail: 0.8 } },
  { id: 'neptune', name: '海王星型冰巨星', type: 'ice_giant', p: { radius: 8, hue: 0.6, bands: 0.5, atmosphere: 0.8, rings: 0.1 } },
  { id: 'uranus', name: '天王星型冰巨星', type: 'ice_giant', p: { radius: 8, hue: 0.5, bands: 0.15, atmosphere: 0.7, rings: 0.35 } },
  { id: 'planet-x', name: 'Planet X（假想超級地球／冰巨星）', type: 'ice_giant', p: { radius: 7, hue: 0.56, bands: 0.55, atmosphere: 0.8, rings: 0 } },
]

const clamp = (v, a, b) => Math.min(b, Math.max(a, v))

/** Convert the backend prediction (universe.json) into full parameters for the builder. */
export function predicted(obj) {
  const pr = obj.preset || {}
  if (obj.group === 'source') {
    if (pr.type === 'galaxy') return { type: 'galaxy', p: { temperature: obj.fit.T, radius: clamp(3 + Math.log10(obj.snr), 3, 12), arms: 2, tilt: 0.7 } }
    const r = clamp(0.5 + 0.55 * Math.log10(obj.snr) * Math.cbrt(obj.radius_rsun || 1), 0.5, 5)
    return { type: 'star', p: { temperature: pr.temperature || obj.fit.T, radius: r, granulation: pr.granulation ?? 0.5, spots: pr.spots ?? 0.1, corona: pr.corona ?? 0.4 } }
  }
  if (pr.type === 'ice_giant') return { type: 'ice_giant', p: { radius: 7, hue: pr.hue ?? 0.56, bands: pr.bands ?? 0.55, atmosphere: pr.atmosphere ?? 0.8, rings: pr.rings ?? 0 } }
  const d = pr.diameter_km
  const radius = d ? clamp(1.6 + 1.3 * Math.log10(d), 1.5, 8) : 3
  const hue = { C: 0.08, S: 0.07, X: 0.6, D: 0.02, V: 0.12 }[String(pr.taxonomy || 'S')[0]] ?? 0.07
  if (pr.type === 'comet') return { type: 'comet', p: { radius: clamp(radius * 0.5, 0.8, 3), albedo: pr.albedo ?? 0.04, coma: pr.coma ?? 0.8, tail: 0.8 } }
  return { type: 'rocky', p: { radius, albedo: clamp(pr.albedo ?? 0.15, 0.02, 0.5), irregularity: pr.irregularity ?? 0.25, craters: pr.craters ?? 0.5, rotation_h: pr.rotation_h ?? 8, hue } }
}

/** Blackbody colour (sRGB, 0..1) for temperature T (Tanner Helland approximation). */
export function bbColor(T) {
  const t = clamp(T, 1000, 40000) / 100
  let r, g, b
  if (t <= 66) { r = 255; g = 99.4708025861 * Math.log(t) - 161.1195681661; b = t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307 }
  else { r = 329.698727446 * (t - 60) ** -0.1332047592; g = 288.1221695283 * (t - 60) ** -0.0755148492; b = 255 }
  return [clamp(r, 0, 255) / 255, clamp(g, 0, 255) / 255, clamp(b, 0, 255) / 255]
}
