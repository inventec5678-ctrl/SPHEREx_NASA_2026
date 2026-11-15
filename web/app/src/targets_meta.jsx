// The challenge's five named test targets: names and the card grid. Kept apart from the field lab so the landing
// page and the embed can show them without loading the lab's code.
import { L } from './lib.js'
import { TARGET_IDS } from './sky.js'

export { TARGET_IDS }
// i18n-ignore-start (the English comes from each field's own target record)
export const TARGET_ZH = {
  barnard: ['巴納德星', '天空中移動最快的恆星：1.8 秒差距外的紅矮星，每年移動 10.4 角秒。'],
  epsindi: ['天苑增三 B（Epsilon Indi B）', '繞著恆星天苑增三運行的一對棕矮星，距離 3.7 秒差距，每年一起移動 4.7 角秒。'],
  wise0855: ['WISE 0855−0714', '已知最冷的棕矮星（約 −25 °C），距離 2.3 秒差距。3 µm 以下幾乎看不見，只會出現在 SPHEREx 最長波段。'],
  rwaur: ['御夫座 RW', '160 秒差距外的年輕金牛 T 型星；盤裡的塵埃經過前方時，亮度會不規則地跳動。'],
  rdra: ['天龍座 R', '米拉變星：約 800 秒差距外、每 246 天變亮又變暗的脈動紅巨星。'],
}
// i18n-ignore-end
const EN_NAME = { barnard: "Barnard's Star", epsindi: 'Epsilon Indi B', wise0855: 'WISE 0855−0714', rwaur: 'RW Aurigae', rdra: 'R Draconis' }
export const targetName = (tg) => (L(TARGET_ZH[tg.id]?.[0] || tg.name, tg.name || EN_NAME[tg.id]))
export const targetAbout = (tg) => (L(TARGET_ZH[tg.id]?.[1] || tg.about, tg.about))
const KIND = { pm: () => L('移動的恆星', 'Moving star'), var: () => L('變星', 'Variable star') }

/** The five targets as cards (the landing page and #/targets). */
export function TargetCards({ fields, level = 3 }) {
  const H = `h${level}`
  const by = new Map((fields || []).map((f) => [f.id, f]))
  return (
    <div className="tg-cards">
      {TARGET_IDS.map((id) => {
        const f = by.get(id)
        const ready = f?.target
        return (
          <a key={id} className={`tg-card ${ready ? '' : 'pending'}`} href={ready ? `#/target/${id}` : undefined} aria-disabled={!ready}>
            {f ? <img src={`/data/fields/${id}/${ready ? 'pass/p0_d0.webp' : `sci/${String(f.thumb ?? 0).padStart(4, '0')}.${f.frame_ext || 'png'}`}`} alt="" loading="lazy" decoding="async" width="177" height="177" /> : <div className="tg-ph" />}
            <div>
              <span className="tg-kind">{ready ? KIND[f.target.kind]() : L('分析中', 'Being analysed')}</span>
              <H className="tg-name">{targetName(ready ? f.target : { id, name: EN_NAME[id] })}</H>
              {ready && <p>{f.n_exposures} {L('張影像', 'exposures')}</p>}
            </div>
          </a>
        )
      })}
    </div>
  )
}
