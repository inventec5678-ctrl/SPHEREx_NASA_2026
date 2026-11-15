// Display names for the demo fields (server names are English; Chinese is the UI source language).
import { L } from '@sx/i18n/core.js'
import { fieldTitle } from './lib.js'

const TEXT = {
  cybele: {
    zh: ['室女座的小行星通道（65 Cybele）', '黃道上的一片天空。2025 年 12 月，大型主帶小行星 65 Cybele 從這裡經過；每一輪巡天都有較暗的小行星穿過。'],
    en: ['Asteroid lane in Virgo (65 Cybele)', 'A patch on the ecliptic. In December 2025 the large main-belt asteroid 65 Cybele crossed it; fainter asteroids pass through every survey pass.'],
  },
  planetx: {
    zh: ['Planet X 測試：模擬的遙遠行星', '真實的 SPHEREx 影像，加上一顆用儀器自己的 PSF 注入、距離約 420 AU 的模擬行星。管線能只靠視差找到它嗎？（為了讓單張影像就看得到，它被刻意調亮到 AB 15.5；真正的 Planet X 會暗得多，需要疊加影像。）'],
    en: ['Planet X test: a simulated distant planet', "Real SPHEREx images with one simulated planet at ~420 AU added using the instrument's own PSF. Can the pipeline find it from its parallax alone? (It is made bright, AB 15.5, so you can see it in single images; a real Planet X would be far fainter and need image stacking.)"],
  },
  barnard: { zh: ['巴納德星（挑戰測試目標）', '天空中移動最快的恆星，每年 10.4 角秒。'], en: ["Barnard's Star (challenge target)", 'The fastest-moving star in the sky, 10.4 arcseconds a year.'] },
  epsindi: { zh: ['天苑增三 B（挑戰測試目標）', '繞著天苑增三運行的一對棕矮星，每年移動 4.7 角秒。'], en: ['Epsilon Indi B (challenge target)', 'A pair of brown dwarfs orbiting Epsilon Indi, moving 4.7 arcseconds a year.'] },
  wise0855: { zh: ['WISE 0855−0714（挑戰測試目標）', '已知最冷的棕矮星，每年移動 8.1 角秒，只在最長波段看得到。'], en: ['WISE 0855−0714 (challenge target)', 'The coldest known brown dwarf, moving 8.1 arcseconds a year; visible only in the longest bands.'] },
  rwaur: { zh: ['御夫座 RW（挑戰測試目標）', '亮度不規則跳動的年輕金牛 T 型星。'], en: ['RW Aurigae (challenge target)', 'A young T Tauri star whose brightness jumps irregularly.'] },
  rdra: { zh: ['天龍座 R（挑戰測試目標）', '每 246 天變亮又變暗的米拉變星。'], en: ['R Draconis (challenge target)', 'A Mira variable that brightens and fades every 246 days.'] },
  taurus: {
    zh: ['金牛座的黃道（保留測試天區）', 'AI 在訓練時從沒看過的一片天空。'],
    en: ['Ecliptic in Taurus (held-out test sky)', 'One of the sky patches the AI never saw during training.'],
  },
}
export function fieldName(f) {
  const tx = TEXT[f.id]
  if (tx) return L(tx.zh, tx.en)[0]
  return fieldTitle(f)
}
export function fieldDesc(f) {
  const tx = TEXT[f.id]
  if (tx) return L(tx.zh, tx.en)[1]
  return L('由網頁使用者提交、即時分析的天區。', 'Analysed on request from the web app.')
}
