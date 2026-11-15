// A three-step "how to look" card. Shown on the first visit of each page kind; after "Got it" it folds into a
// small button that brings it back at any time (the choice is kept in localStorage).
import { useState } from 'react'
import { L } from './lib.js'

const STEPS = {
  quick: () => [
    [L('播放', 'Play'), L('影像依時間播放，中間的十字是你輸入的位置。預設只播一個偵測器，畫面比較穩定；偶爾閃一下的單一亮點或暗點是壞像素或宇宙射線，真的天體會連續出現在好幾張裡。', 'Frames play in time order; the cross is the position you entered. One detector plays by default for a steadier picture. A single bright or dark dot that flashes once is a bad pixel or a cosmic ray; a real object shows up in several frames in a row.')],
    [L('切到「差分」', 'Switch to Difference'), L('不變的星會消失，只留下變化：變亮是橘色、變暗是藍色，移動的天體會變成一對橘藍點。', 'Steady stars vanish and only changes remain: orange is brighter, blue fainter, and a moving object becomes an orange-blue pair.')],
    [L('看「各輪疊加」與自動搜尋', 'Pass stacks and the automatic search'), L('每輪巡天的影像疊起來雜訊更低；影像都到齊後，程式會自動找出位置有移動的星，列在下方。', 'Each survey pass stacked has much less noise; once every frame is in, the program lists the stars that moved, below.')],
  ],
  lab: () => [
    [L('輪播或差分', 'Blink or Difference'), L('「輪播」依序顯示每一輪巡天；「差分」只留下兩輪之間的差別，移動的星會變成一對橘藍點。', 'Blink shows each survey pass in turn; Difference keeps only what changed, and a moving star becomes an orange-blue pair.')],
    [L('點任何一點', 'Click any point'), L('立刻量出那個位置在每一張影像裡的亮度：光變曲線，以及由 102 個波段組成的光譜。AI 會判斷光譜像不像冷棕矮星。鍵盤也可以：先按 Tab 到影像，方向鍵移動十字，Enter 量測。', 'Get its brightness in every exposure at once: a light curve and a spectrum built from the 102 bands. An AI says whether the spectrum looks like a cold brown dwarf. By keyboard: Tab to the image, move the cross with the arrow keys, press Enter to measure.')],
    [L('和其他望遠鏡比較', 'Compare with other telescopes'), L('往下捲：自動找到的移動星與變星，以及 Aladin 裡 WISE、2MASS 與 SPHEREx 全天圖的同一片天空。', 'Scroll down for the moving and variable stars found automatically and the same sky in Aladin: WISE, 2MASS and the SPHEREx all-sky map.')],
  ],
}

export function Tour({ kind }) {
  const key = `sx:tour:${kind}`
  const [hide, setHide] = useState(() => { try { return localStorage.getItem(key) === '1' } catch { return false } })
  const set = (v) => { try { v ? localStorage.setItem(key, '1') : localStorage.removeItem(key) } catch { /* private mode */ } setHide(v) }
  if (hide) return <button className="link tour-open" onClick={() => set(false)}>{L('怎麼看這個畫面？', 'How do I read this?')}</button>
  return (
    <aside className="tour" aria-label={L('使用說明', 'How to use')}>
      <ol>{STEPS[kind]().map(([h, t], k) => <li key={k}><b>{h}</b><span>{t}</span></li>)}</ol>
      <div className="tour-act">
        <button className="btn small" onClick={() => set(true)}>{L('知道了', 'Got it')}</button>
        <a className="link" href="#/guide">{L('完整說明', 'Full guide')}</a>
      </div>
    </aside>
  )
}
