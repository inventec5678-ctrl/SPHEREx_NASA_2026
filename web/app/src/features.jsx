// Features: every tool on the site, each with a picture, what it does, and a button straight into it.
import { useEffect } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { paperUrl } from '@sx/i18n/core.js'
import { go, goUniverse } from './nav.js'
import { L } from './lib.js'
import { openSky } from './search.jsx'
import { useReveal } from './reveal.js'
import { Accent, Glare, Spot, StarButton } from './fx.jsx'

// Entries written with L() carry their own English; the older ones are translated by the catalogue.
const FEATURES = () => [
  {
    id: 'quick', img: 'quick', title: L('輸入座標就播放：快速預覽', 'Type a position and it plays: the quick look'),
    lead: L('輸入赤經赤緯（十進位或時分秒）或天體名稱，伺服器向 IRSA 要那片天空的所有 SPHEREx 影像，第一批約一分鐘內開始播放，其餘邊下載邊加入。影像到齊後自動加上差分影像、各輪巡天的疊加，並搜尋移動的恆星。', 'Type an RA and Dec (decimal or sexagesimal) or an object name. The server asks IRSA for every SPHEREx image of that patch; the first play within about a minute and the rest join as they arrive. When all are in, difference frames and per-pass stacks are added and moving stars are searched for.'),
    points: [L('按 Enter 就播放；預設只播一個偵測器，畫面穩定', 'Enter plays; one detector by default for a steady picture'), L('視野 0.15°、0.3° 或 0.6°', 'Field of view 0.15°, 0.3° or 0.6°'), L('空白鍵播放或暫停、左右鍵逐張', 'Space plays or pauses; arrow keys step')],
    cta: L('看卡普坦星的快速預覽', "See the quick look of Kapteyn's Star"), go: () => openSky('77.96 -45.02', 0.15),
  },
  {
    id: 'pmsearch', img: 'movers', title: L('自動找移動的恆星，大家一起判斷', 'Moving stars found automatically, judged together'),
    lead: L('程式比較各輪巡天的疊加影像，找出位置移動、而且在至少兩個偵測器裡方向一致的星，之後才拿 Gaia 與 CatWISE 星表來標示。巴納德星、天苑增三 B、WISE 0855 都是這樣不看星表就找到的。候選排進公開的判斷佇列：輪播第一輪與最後一輪，判斷它是真的還是假訊號。', "The search compares the stacks of each survey pass, keeps stars whose position shifts in the same direction in at least two detectors, and only then asks the Gaia and CatWISE catalogues what they are. Barnard's Star, Epsilon Indi B and WISE 0855 were all found this way, blind. Candidates go to a public review queue: blink the first and last pass and say real or artefact."),
    points: [L('已知的移動星當練習題，答完才顯示正解', 'Catalogued movers serve as practice: the answer shows after you judge'), L('自己訓練的光譜模型判斷候選像不像冷棕矮星', 'A self-trained spectrum model says whether a candidate looks like a cold brown dwarf'), L('每個數字的驗證都公開', 'The validation of every number is public')],
    cta: L('打開判斷佇列', 'Open the review queue'), go: () => { location.hash = '#/movers' },
  },
  {
    id: 'embed', img: 'embed', title: L('座標在網址裡：分享與嵌入', 'The position is in the URL: share and embed'),
    lead: L('任何位置都能用網址直接打開：/?ra=…&dec=…。網址還記得目前的畫面（顯示模式、偵測器、暫停的那一張、工作台選的點），所以分享的連結打開就是同一個畫面。加上 &embed=1 就是沒有網站外框的播放器，可以用 <iframe> 放進別的網頁。', 'Any position opens from a URL: /?ra=…&dec=…. The URL also keeps what is on screen (mode, detector, the frame you paused on, the point picked in the lab), so a shared link opens on the same picture. Add &embed=1 for a chrome-less player that drops into another page as an <iframe>.'),
    points: [L('每個天空頁都有可複製的連結與嵌入碼', 'Every sky page has a copyable link and embed snippet'), L('也接受時分秒與天體名稱', 'Sexagesimal positions and object names work too'), L('語言不寫進分享連結', 'The language is never written into a shared link')],
    cta: L('看嵌入版播放器', 'See the embedded player'), go: () => { window.open('/?target=barnard&embed=1', '_blank', 'noopener') },
  },
  {
    id: 'guide', img: 'guide', title: L('怎麼看、有多可靠、題目要求在哪裡', 'How to read it, how far to trust it, where the challenge is met'),
    lead: L('一頁說明：每種畫面在看什麼、真的移動和假訊號各長什麼樣子；每個結果經過哪些檢驗（包含結果不好看的）；這個工具看不到什麼；以及題目的每一項要求在網站的哪裡，每項附直接連結。', 'One page: what each view shows and what real motion and artefacts look like; how each result was checked (including the unflattering ones); what the tool cannot see; and where each requirement of the challenge is met, each with a direct link.'),
    points: [L('高黃緯對照組：亮星假軌跡從 14、21 條降到 0', 'High-latitude control: bright-star false tracks went from 14 and 21 to 0'), L('隨機抽樣的高自行星驗證', 'Validation on randomly drawn high-proper-motion stars'), L('天龍座 R 對照 AAVSO 星曆', 'R Draconis against the AAVSO ephemeris')],
    cta: L('打開說明與驗證', 'Open the guide'), go: () => { location.hash = '#/guide' },
  },
  {
    id: 'lab', img: 'lab', title: L('天區工作台：相加、差分、換偵測器', 'Field lab: add, difference, switch detector'),
    lead: L('每片天空依巡天輪次疊加，可以輪播、全部相加看得更深，或兩輪差分只留下變化；也能只疊加六個偵測器其中一個，或用假彩色看 102 個波段。疊上 Gaia DR3 和 CatWISE 星表，星會依自行移到那一輪的位置。', 'Each field is stacked per survey pass: blink the passes, add them all to go deeper, or take the difference of two to keep only what changed. Stack a single one of the six detectors, or view the 102 bands in false colour. Gaia DR3 and CatWISE overlays move each star to where its proper motion puts it in that pass.'),
    points: [L('視野可選 0.15°、0.3° 或 0.6°；影像可放大 1×／2×／4×', 'Field of view 0.15°, 0.3° or 0.6°; zoom 1× / 2× / 4×'), L('顯示污染旗標；IRSA 有新資料時一鍵重新分析', 'Contamination flags; one-click re-analysis when IRSA has new data'), L('鍵盤也能選點：方向鍵移動十字，Enter 量測', 'Keyboard picking: arrow keys move the cross, Enter measures')],
    cta: L('看 WISE 0855 的工作台', 'See the lab for WISE 0855'), go: () => { location.hash = '#/target/wise0855' },
  },
  {
    id: 'spectrum', img: 'spectrum', title: '點任何一點：即時光譜與光變曲線',
    lead: 'SPHEREx 每張影像的波長隨位置改變。點天空裡任何一點，伺服器在每張影像上做孔徑測光，依波長排開就是光譜，依時間排開就是光變曲線，還能下載 CSV。',
    points: ['挑戰指定的五個測試目標都有專屬頁面', '移動的天體依星表自行與視差追蹤', '附近有其他星混入時會自動警告'],
    cta: '看五個測試目標', go: () => { location.hash = '#/targets' },
  },
  {
    id: 'viewer3d', img: 'viewer3d', title: L('天空檢視器與 3D 重建', 'The sky viewer and its 3D model'),
    lead: L('檢視器打開就是 SPHEREx 的影像，可以逐張播放、切到差分、放大追蹤。再按「3D 重建」，同一片天空變成可以旋轉的場景：恆星是依自己光譜建成的球，小行星依真實的觀測時間沿著它走過的路移動。', 'The viewer opens on the SPHEREx images: play them frame by frame, switch to differences, zoom and follow. Press "3D model" and the same sky becomes a scene you can turn: each star a sphere built from its own spectrum, each asteroid moving along its path at the real observation times.'),
    points: ['按播放讓時間前進，看小行星穿過星場', '拖曳旋轉、滾輪縮放', '點任何一顆星或小行星，右側立刻顯示它是什麼'],
    cta: '打開 65 Cybele 的天空', go: () => go('cybele'),
  },
  {
    id: 'probe', img: 'probe', title: '檢查一個點：它是不是行星？',
    lead: '點天空裡任何一點，伺服器會實際檢查：那裡有沒有偵測、AI 給幾分、它是不是每輪巡天都在同一個位置，以及能不能找到符合「視差＋軌道運動」的搭檔。',
    points: ['白話結論：恆星、小行星、假訊號，或可能的遠方天體', '可能是遠方天體時，畫出它的視差路徑與距離', '至少要三輪巡天才分得開距離和軌道運動'],
    cta: '在 Planet X 測試天區試試', go: () => go('planetx'),
  },
  {
    id: 'object', img: 'object', title: '每個天體都有一頁證據',
    lead: '一句話結論、三個證據勾勾（像點光源、沿直線或視差移動、和 JPL 預測位置一致），以及模型預測的 3D 外觀。',
    points: ['逐次偵測播放與證據並排小圖', '以 SPHEREx 為觀測者和 JPL Horizons 比對位置', '反射光譜、在天空中的位置，以及你的投票'],
    cta: '看 65 Cybele 的證據', go: () => go('cybele', 0),
  },
  {
    id: 'reconstruct', img: 'reconstruct', title: '星體重建',
    lead: '點一顆星，看它在 102 個波段量到的光譜；模型從光譜判定它是什麼——恆星的溫度、星系，或小行星的顏色——再把它建成一顆球。',
    points: ['換一個預設，或拖動溫度、顏色、坑洞等參數', '按「重建這顆球」立刻看到結果', '小行星使用 JPL 的直徑、反照率與光譜分類'],
    cta: '打開星體重建', go: () => goUniverse('cybele'),
  },
  {
    id: 'discovery', img: 'discovery', title: '真正的發現搜尋',
    lead: '用模型去找 Planet Nine：先量出三顆真實矮行星的距離，再沿著它的預測路徑搜尋，把每個候選攤開來做八項檢查。沒找到時，給出這片天空的亮度上限。',
    points: ['只靠 SPHEREx 的視差量出真實海王星外天體的距離', '移位疊加：單張影像看不到的暗天體也能浮現', '新聞裡「上報 NASA」實際的流程，以及我們會怎麼上報'],
    cta: '看搜尋結果', go: () => { location.hash = '#/discovery' },
  },
  {
    id: 'cube', img: 'cube', title: '3D 時空立方體',
    lead: '把幾百張差分影像依時間疊成一個立方體。靜止的恆星相減後消失；每顆移動的小行星都變成一條斜線，遠方行星則是一個之字形。',
    points: ['「顯示雜訊」對比 AI 篩掉了多少東西', '選一個天體，看它在時空中的軌跡', '播放時，目前這張影像會在立方體裡滑動'],
    cta: '打開 3D 時空', go: () => go('cybele'),
  },
  {
    id: 'story', img: 'story', title: '一分鐘看懂方法',
    lead: L('研究故事頁用六個畫面講完整個方法：同一片天空閃爍、相減、AI 篩選、3D 時空裡的斜線、模擬行星的視差，最後換你探索。', 'The research story tells the whole method in six scenes: the same sky blinking, the subtraction, the AI filter, the slanted lines in 3D space-time, the simulated planet’s parallax, then your turn.'),
    points: ['全部使用真實的 SPHEREx 資料', '模擬資料一律標示', '捲動就會前進'],
    cta: L('看研究故事', 'Read the research story'), go: () => { location.hash = '#/story' },
  },
  {
    id: 'research', img: 'research', title: '影像模式與研究模式',
    lead: '想看原始資料時，可以切到差分影像、天空影像或參考影像，逐張播放、放大追蹤。打開「研究模式」，會顯示所有控制項與資料品質說明。',
    points: ['依偵測器（波段）篩選、調整播放速度', '盲連結、星表輔助、JPL 不符等標示', '下載量測（JSON、CSV、MPC ADES 草稿）'],
    cta: '打開檢視器', go: () => go('cybele'),
  },
  {
    id: 'explore', img: 'explore', title: '分析任何一片天空',
    lead: '在全天圖上點一個位置，伺服器會下載那 0.3° 天空的所有 SPHEREx 影像，跑完整的分析管線，完成後自動打開。',
    points: [L('全天任何位置都可以', 'Any position on the sky'), '一片天空約 20 到 40 分鐘', '沒有串成軌跡的 AI 候選也可以投票'],
    cta: '到全天圖選一個位置', go: () => { go(null); setTimeout(() => document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth' }), 400) },
  },
]

export default function Features() {
  useLanguage()
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + (L('功能', 'Features')) }, [])
  useReveal()      // each part rises as it scrolls in (same entrance as the home page)
  const lang = L('zh', 'en')
  return (
    <div className="features">
      <header className="features-head">
        <div>
          <h1>這個網站<br /><Accent>可以做什麼</Accent></h1>
          <p className="lead">把 NASA SPHEREx 的紅外線影像變成可以探索的宇宙：看天空怎麼變化、AI 怎麼找到移動的天體，並親手檢查任何一個點是不是行星。</p>
        </div>
        <video src={`/media/demo_${lang}.webm`} poster="/media/features/viewer3d.webp" autoPlay muted loop playsInline preload="metadata" aria-label="導覽影片" />
      </header>
      <nav className="features-toc" aria-label="功能列表">
          {FEATURES().map((f) => <a key={f.id} href={`#/features#${f.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(f.id)?.scrollIntoView({ behavior: 'smooth' }) }}>{f.title}</a>)}
      </nav>
      {FEATURES().map((f, k) => (
        <section key={f.id} id={f.id} className={`feature ${k % 2 ? 'flip' : ''}`} aria-labelledby={`h-${f.id}`}>
          <div className="reveal"><Glare><img src={`/media/features/${f.img}.webp`} alt="" loading={k < 2 ? 'eager' : 'lazy'} /></Glare></div>
          <div className="reveal" style={{ '--d': '.08s' }}>
            <h2 id={`h-${f.id}`}>{f.title}</h2>
            <p className="lead">{f.lead}</p>
            <ul>{f.points.map((p) => <li key={p}>{p}</li>)}</ul>
            <StarButton onClick={f.go}>{f.cta} →</StarButton>
          </div>
        </section>
      ))}
      <Spot className="feature-more" role="region" aria-labelledby="h-more">
        <h2 id="h-more">方法與資料</h2>
        <p className="lead">所有數字都由公開的證據檔自動產生；方法、驗證與限制寫在論文裡。</p>
        <div className="more-links">
          <a className="btn" href={paperUrl('paper')}>論文全文</a>
          <a className="btn" href="/paper/static/pdfs/spherex_movers_manuscript.pdf">PDF</a>
          <a className="btn" href="/paper/research/evidence.json">證據資料（JSON）</a>
        </div>
        <p className="hint">{L('支援繁體中文與英文。播放、逐張、縮放和工作台的選點都能用鍵盤操作；系統設定「減少動態效果」時，沒有任何畫面會自動播放。Aladin Lite 是第三方元件，它內部有幾個按鈕沒有文字標籤。', 'Traditional Chinese and English. Playback, stepping, zoom and point picking in the lab work from the keyboard; when the system asks for reduced motion, nothing plays by itself. Aladin Lite is a third-party component, and a few of its own buttons have no text label.')}</p>
      </Spot>
    </div>
  )
}
