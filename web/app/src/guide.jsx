// #/guide: how to read the images (a picture beside each explanation), how far to trust the results (the validation
// dashboard: charts, validation.jsx), what cannot be seen here (a list), and where each requirement of the challenge
// is met (a grid of tiles, each with a direct link). #/guide/<section> scrolls to g-<section>.
// Layout styles: validation.css (classes gd-*).
import { useEffect } from 'react'
import { paperUrl } from '@sx/i18n/core.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, reducedMotion } from './lib.js'
import { COL, Legend } from './charts.jsx'
import { ICON } from './icons.jsx'
import { Validation } from './validation.jsx'
import './guide_dev.css'

// [code, short name, the requirement in full, links [[label, href]], note]
const REQ = () => [
  ['O1', L('公開的網頁工具', 'A public web tool'), L('公開的網頁工具，顯示 SPHEREx 的天空影像', 'A public web tool that shows SPHEREx images of the sky'), [[L('首頁', 'Home'), '#/']]],
  ['O2', L('輸入天空座標', 'Enter sky coordinates'), L('使用者輸入一片天空的座標（赤經、赤緯）', 'Users enter the coordinates (RA, Dec) of a patch of sky'), [[L('首頁第一屏的搜尋框', 'The search box at the top of the home page'), '#/'], ['/?ra=133.795&dec=-7.245', '/?ra=133.795&dec=-7.245']]],
  ['O3', L('像影片一樣依序播放', 'Play the images like a video'), L('把那片天空的影像像一段小影片依序播放，容易看出移動的天體', 'Show the images of that patch in sequence, like a little video, so movers are easy to spot'), [[L('卡普坦星的快速預覽（已完成）', "Quick look of Kapteyn's Star (finished)"), '#/sky/77.96%20-45.02?fov=0.15'], [L('65 Cybele 天區逐張播放', 'The 65 Cybele field, frame by frame'), '#/field/cybele']]],
  ['O4', L('測試：巴納德星', "Test: Barnard's Star"), null, [[L('巴納德星', "Barnard's Star"), '#/target/barnard'], [L('兩輪差分', 'Difference of two passes'), '#/target/barnard?t=diff&a=2&b=0']]],
  ['O5', L('測試：天苑增三 B', 'Test: Epsilon Indi B'), L('測試：天苑增三 B（一對棕矮星）', 'Test: Epsilon Indi B (a pair of brown dwarfs)'), [[L('天苑增三 B', 'Epsilon Indi B'), '#/target/epsindi']]],
  ['O6', L('測試：WISE 0855', 'Test: WISE 0855'), null, [['WISE 0855', '#/target/wise0855'], [L('假彩色（越紅越冷）', 'False colour (redder is colder)'), '#/target/wise0855?t=all&band=rgb']]],
  ['O7', L('測試：兩顆變星', 'Test: two variable stars'), L('測試：變星御夫座 RW、天龍座 R', 'Test: the variable stars RW Aurigae and R Draconis'), [[L('御夫座 RW', 'RW Aurigae'), '#/target/rwaur'], [L('天龍座 R', 'R Draconis'), '#/target/rdra']]],
  ['C1', L('用最新資料更新', 'Update with the latest data'), L('容易用最新釋出的資料更新', 'Easy to update with the latest data releases'), [[L('工作台右側「檢查有沒有新的 SPHEREx 資料」', 'In any lab: "Check for new SPHEREx data"'), '#/target/barnard']], L('另有每週自動檢查；快速預覽永遠即時查詢 IRSA，新的資料版本會自動採用。', 'A weekly timer also checks; quick looks always query IRSA live and pick up new releases by themselves.')],
  ['C2', L('102 個波段、依偵測器疊加', '102 bands, stacked per detector'), L('有創意地呈現 102 個波段；依偵測器疊加提高訊噪比', 'Creative display of the 102 bands; per-detector stacks for signal-to-noise'), [[L('單一偵測器 D6 的各輪疊加', 'Pass stacks of detector D6 alone'), '#/target/wise0855?band=6'], [L('假彩色 D6／D3／D1', 'False colour D6 / D3 / D1'), '#/target/epsindi?t=all&band=rgb'], [L('任何新座標也有（快速預覽的工作台）', 'Any new position too (the quick look’s lab)'), '#/sky/77.96%20-45.02?fov=0.15&t=all&band=rgb']]],
  ['C3', L('即時產生光譜', 'Spectra on the fly'), L('即時產生光譜（額外加分）', 'Spectra on the fly ("extra kudos")'), [[L('在工作台點任何一點（這個連結已經選好一點）', 'Click any point in a lab (this link has one picked)'), '#/lab/cybele?x=146.5&y=146.5'], [L('新座標也可以：盧曼 16（棕矮星）的快速預覽，已選好一點', 'A new position too: the quick look of Luhman 16 (brown dwarfs), with a point picked'), '#/sky/162.294%20-53.317?fov=0.15&x=43.5&y=44.1']], L('光譜和光變曲線都是點下去時才從每一張影像量出來的；可下載 CSV。', 'The spectrum and light curve are measured from every exposure when you click; CSV download included.')],
  ['C4', L('影像相加、相減', 'Add and subtract images'), L('把不同時間的影像相加或相減', 'Add together or subtract images taken at different times'), [[L('全部相加', 'Add all passes'), '#/target/epsindi?t=all'], [L('兩輪差分', 'Difference of two passes'), '#/target/barnard?t=diff&a=2&b=0'], [L('新座標的兩輪差分', 'Two passes subtracted, new position'), '#/sky/77.96%20-45.02?fov=0.15&t=diff&a=2&b=0']], L('播放器另有逐張差分（每張減去同波長、其他時間的中位數）。', 'The player also has per-frame differences (each frame minus the median of the same wavelength at other times).')],
  ['C5', L('選擇視野', 'Choose the field of view'), L('讓使用者選擇視野', 'Let users choose the field of view'), [['/?ra=77.96&dec=-45.02&fov=0.15', '/?ra=77.96&dec=-45.02&fov=0.15']], L('0.15°、0.3°、0.6°；工作台另有 1×／2×／4× 縮放。', '0.15°, 0.3° or 0.6°; the lab also zooms 1× / 2× / 4×.')],
  ['C6', L('疊上其他望遠鏡的資料', 'Overlay other telescopes'), L('疊上其他望遠鏡的資料，例如 Gaia、WISE', 'Overlay data from other telescopes such as Gaia or WISE'), [[L('工作台的 Gaia DR3／CatWISE 疊圖與 Aladin', 'Gaia DR3 / CatWISE overlays and Aladin in the lab'), '#/target/epsindi'], [L('新座標：疊在 SPHEREx 影像上，旁邊有 Aladin', 'A new position: on the SPHEREx image, with Aladin beside it'), '#/sky/77.96%20-45.02?fov=0.15']], L('Gaia 位置會依自行推到每一輪的日期。', 'Gaia positions are moved to each pass’s date by their proper motion.')],
  ['C7', L('座標在網址裡、可以嵌入', 'Coordinates in the URL, embeddable'), L('座標寫在網址裡，方便嵌入', 'Coordinates in the URL, so the tool can be embedded'), [[L('嵌入版播放器', 'The embeddable player'), '/?target=barnard&embed=1']], L('每個天空頁都有可複製的 <iframe> 嵌入碼；網址也記得顯示模式、偵測器和暫停的那一張。', 'Every sky page has a copyable <iframe> snippet; the URL also keeps the mode, the detector and the frame you paused on.')],
  ['C8', L('顯示污染旗標等中繼資料', 'Show metadata such as flags'), L('顯示中繼資料，例如污染旗標', 'Display metadata such as contamination flags'), [[L('播放器：每張影像的旗標比例與旗標疊圖', 'Player: each frame’s flag shares and a flag overlay'), '#/sky/77.96%20-45.02?fov=0.15&pf=1'], [L('工作台：各輪的污染旗標圖層', 'Lab: the per-pass contamination-flag layer'), '#/target/barnard?fl=1']], L('旗標名稱直接來自 SPHEREx 影像的 FLAGS 標頭（飽和、殘影、鬼影、離群、熱像素等）；每張影像也顯示時間、偵測器和波長。量測時有旗標的點會自動排除，並列出這個位置被標記了幾張。', 'Flag names come straight from the FLAGS header of the SPHEREx images (saturation, persistence, ghosts, outliers, hot pixels…); each frame also shows its time, detector and wavelength. Measurements drop flagged points and list how many exposures were flagged at that position.')],
  ['C9', L('公開工具：Astropy、Aladin', 'Public tools: Astropy, Aladin'), L('使用公開工具：Astropy 處理資料、Aladin 顯示', 'Use public tools: Astropy for data, Aladin (CDS) for display'), [[L('工作台裡的 Aladin Lite', 'Aladin Lite in the lab'), '#/target/epsindi']], L('後端用 Astropy（WCS、時間、座標、空間運動）；前端嵌入 Aladin Lite v3。', 'The backend uses Astropy (WCS, time, coordinates, space motion); the frontend embeds Aladin Lite v3.')],
  ['B1', L('讓大家一起參與發現', 'Let everyone pitch in'), L('讓越多人能一起參與發現', 'Help as many people as possible pitch in to make discoveries'), [[L('判斷自動找到的移動星、看大家回報的位置', 'Judge the movers found automatically; see positions people flagged'), '#/movers']], L('在任何工作台點一個位置，量完可以按「回報」；其他人會看到並投票。已知答案的候選可以當練習題。', 'In any lab, click a position and flag it after measuring; others see it and vote. Candidates with known answers double as practice.')],
]
// what the letter of a code means in the challenge text
const KIND = () => ({ O: L('必做的目標', 'Objective'), C: L('題目列的可選項目', 'Consideration'), B: L('背景裡的期待', 'Background hope') })

// ---- small diagrams for "how to read the images" (no text inside: the captions are HTML) ------------------------
/** The same measurements sorted two ways: by wavelength (a spectrum) and by time (a light curve). */
function SpectrumVsCurve() {
  const shape = (u) => 0.55 + 0.3 * Math.sin(u * 5.2 + 0.4) * Math.exp(-u * 1.1) - 0.25 * Math.exp(-(((u - 0.62) / 0.09) ** 2))
  const jit = (j) => ((j * 37) % 11) / 11 - 0.5
  const lift = [0, 0.02, 0.2]                         // the third pass is brighter at every wavelength: a real change
  const spec = [0, 1, 2].flatMap((k) => Array.from({ length: 13 }, (_, j) => { const u = (j + k / 3) / 13.4; return { k, x: 16 + u * 136, y: 84 - (shape(u) + lift[k] + jit(j + k * 5) * 0.04) * 72 } }))
  const curve = [0, 1, 2].flatMap((k) => Array.from({ length: 9 }, (_, j) => ({ k, x: 30 + k * 52 + jit(j * 3 + k) * 22, y: 84 - (0.42 + lift[k] + jit(j * 7 + k * 2) * 0.34) * 72 })))
  const Panel = ({ pts }) => (
    <svg className="gd-dia" viewBox="0 0 168 100" aria-hidden="true">
      <path className="ax" d="M12 8V90H160" />
      {pts.map((p, j) => <circle key={j} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r="3" fill={COL.pass[p.k]} />)}
    </svg>
  )
  return (
    <div className="gd-pair">
      <div><Panel pts={spec} /><p><b>{L('光譜', 'Spectrum')}</b>{L('依波長排', 'sorted by wavelength')}</p></div>
      <div><Panel pts={curve} /><p><b>{L('光變曲線', 'Light curve')}</b>{L('依時間排', 'sorted by time')}</p></div>
    </div>
  )
}
/** Fast movers cross several pixels in hours; stars take a year to cross part of one. */
function TwoMotions() {
  const grid = (n, s, x0, y0) => Array.from({ length: n + 1 }, (_, j) => `M${x0 + j * s} ${y0}V${y0 + n * s}M${x0} ${y0 + j * s}H${x0 + n * s}`).join('')
  return (
    <div className="gd-pair">
      <div>
        <svg className="gd-dia" viewBox="0 0 168 100" aria-hidden="true">
          <path className="px" d={grid(8, 20, 4, -30)} />
          <path className="trail" d="M18 84L150 16" />
          {[0, 1, 2, 3, 4].map((j) => <circle key={j} cx={18 + j * 33} cy={84 - j * 17} r="4.5" fill={COL.accent} opacity={0.45 + j * 0.13} />)}
        </svg>
        <p><b>{L('小行星', 'Asteroids')}</b>{L('幾小時跨過好幾個像素', 'several pixels within hours')}</p>
      </div>
      <div>
        <svg className="gd-dia" viewBox="0 0 168 100" aria-hidden="true">
          <path className="px" d="M24 -10V110M84 -10V110M144 -10V110M-10 20H178M-10 80H178" />
          {[0, 1, 2].map((k) => <circle key={k} cx={62 + k * 22} cy={62 - k * 12} r="7" fill={COL.pass[k]} />)}
        </svg>
        <p><b>{L('恆星、棕矮星', 'Stars, brown dwarfs')}</b>{L('多半一年不到一個像素', 'mostly under a pixel a year')}</p>
      </div>
    </div>
  )
}
/** Real data: Barnard's Star in the first and third pass stacks, same sky position, zoomed. */
function PassPair() {
  return (
    <div className="gd-pair">
      {[[0, L('第 1 輪', 'Pass 1'), L('同一片天空', 'the same sky')], [2, L('第 3 輪', 'Pass 3'), L('一年後', 'a year later')]].map(([k, label, note]) => (
        <div key={k}>
          <div className="gd-crop"><img src={`/data/fields/barnard/pass/p${k}_d0.webp`} alt="" loading="lazy" decoding="async" width="177" height="177" /></div>
          <p><b><i style={{ '--c': COL.pass[k] }} />{label}</b>{note}</p>
        </div>
      ))}
    </div>
  )
}

const HOW = () => [
  {
    k: 'images', title: L('影像', 'Images'),
    pic: <img src="/media/step_sky.webp" alt={L('一張 SPHEREx 原始影像：黑底上的星點', 'One SPHEREx frame: stars on a dark sky')} width="480" height="300" loading="lazy" decoding="async" />,
    text: L('SPHEREx 拍到的原始畫面，依時間播放。每張影像的波長都不同，所以同一顆星在相鄰兩張的亮度本來就不一樣。', 'The frames as SPHEREx took them, in time order. Every exposure is at a different wavelength, so a star changes brightness from one frame to the next for that reason alone.'),
    more: L('只播一個偵測器時，波長接近，畫面才穩定。只閃一下的單一亮點或暗點是壞像素或宇宙射線。', 'Playing one detector keeps the wavelengths close and the picture steady. A single dot that flashes once is a bad pixel or a cosmic ray.'),
    go: [L('播放 65 Cybele 天區', 'Play the 65 Cybele field'), '#/field/cybele'],
  },
  {
    k: 'diff', title: L('差分', 'Difference'),
    pic: <img src="/media/step_diff.webp" alt={L('差分影像：橘色和藍色的點', 'A difference image: orange and blue dots')} width="480" height="300" loading="lazy" decoding="async" />,
    legend: [{ c: 'var(--sx-amber)', label: L('變亮或新出現', 'Brighter or new') }, { c: 'var(--sx-d1)', label: L('變暗或離開', 'Fainter or gone') }],
    text: L('每張影像減去同一片天空、其他時間的影像，不變的星互相抵消。移動的天體會留下一對橘藍點：橘色是現在的位置，藍色是原本的位置。', 'Each frame minus frames of the same sky at other times, so steady stars cancel. A mover leaves an orange-blue pair: orange where it is now, blue where it was.'),
    more: L('相減的兩張影像波長要相近。很亮的星減不乾淨，會留下不會移動的殘差。', 'The frames subtracted are at similar wavelengths. Very bright stars never subtract cleanly and leave residuals that do not move.'),
    go: [L('看巴納德星的兩輪差分', "See Barnard's Star, two passes subtracted"), '#/target/barnard?t=diff&a=2&b=0'],
  },
  {
    k: 'passes', title: L('各輪疊加', 'Pass stacks'),
    pic: <PassPair />,
    text: L('SPHEREx 大約每半年回到同一片天空一次，稱為一輪；把一輪的影像平均起來，雜訊低很多。輪流顯示各輪，恆星不動，自行大的星會跳動。', 'SPHEREx returns to a patch of sky about every six months: one pass. Averaging a pass lowers the noise a lot; showing the passes in turn, ordinary stars stay put and a fast star jumps.'),
    more: L('圖是真實資料：巴納德星在第 1 輪和第 3 輪的位置，虛線在兩張圖上是同一個高度（中間的黑點是飽和的核心）。兩輪差分時，這樣的星會變成一對橘藍點。', "The picture is real data: Barnard's Star in passes 1 and 3; the dashed line is at the same height in both (the black core is saturation). In the difference of two passes such a star becomes an orange-blue pair."),
    go: [L('輪播巴納德星', "Blink Barnard's Star"), '#/target/barnard'],
  },
  {
    k: 'spectrum', title: L('光譜與光變曲線', 'Spectrum and light curve'),
    pic: <SpectrumVsCurve />,
    legend: [0, 1, 2].map((k) => ({ c: COL.pass[k], label: L(`第 ${k + 1} 輪`, `Pass ${k + 1}`) })),
    text: L('在工作台點任何一點，伺服器會在每一張影像的那個位置量亮度。依波長排開是光譜，依時間排開是光變曲線。', 'Click any point in a lab and the server measures the brightness there in every exposure. Sorted by wavelength that is a spectrum; sorted by time, a light curve.'),
    more: L('顏色代表巡天輪次：整條光譜在不同輪次高低不同（像圖裡的第 3 輪），才是亮度真的變了。', 'Colour is the survey pass: a real change in brightness moves the whole spectrum up or down between passes (as pass 3 does in the sketch).'),
    go: [L('量一個點試試看', 'Measure a point'), '#/lab/cybele?x=146.5&y=146.5'],
  },
  {
    k: 'motion', title: L('兩種「移動」', 'Two kinds of motion'),
    pic: <TwoMotions />,
    text: L('太陽系天體幾小時就移動好幾個像素，由差分影像加神經網路找。恆星和棕矮星幾年才移動一個像素，由各輪疊加的位置比較找。', 'Solar System objects cross several pixels within hours; difference images and a neural network find them. Stars and brown dwarfs take years to cross one pixel; comparing positions between pass stacks finds them.'),
    more: L('前者列在檢視器右側，後者列在工作台和「找移動星」。兩者用的方法和時間尺度完全不同，網站上分開標示。', 'The first kind is listed in the viewer, the second in the lab and the review queue. The two use different methods and time scales, and the site labels them apart.'),
    go: [L('看自動找到的移動星', 'See the movers found automatically'), '#/movers'],
  },
]

const LIMITS = () => [
  [L('太慢的星', 'Slow stars'), L('只用 SPHEREx 一年的資料時，恆星要一年移動約 0.7″ 以上才看得出來；實測要每年 2″ 以上才穩定找得到。更慢的靠和舊星表（CatWISE，約 10.5 年前）的位置比較，可以到每年約 0.1–0.15″，但只適用於夠孤立的星（大約一半）。', 'With one year of SPHEREx alone, a star must move about 0.7″ a year to show; in practice it is found reliably only above 2″ a year. Slower ones come from comparing with an older catalogue position (CatWISE, about 10.5 years earlier), which reaches about 0.1–0.15″ a year, but only for stars that are isolated enough (about half).')],
  [L('距離', 'Distances'), L('量不出來。自行和視差一起擬合時，靜止的星也會散佈 70–135 mas，所以這個工具不宣稱任何視差。', 'Not measurable here. In the joint proper-motion and parallax fit even static stars scatter by 70–135 mas, so this tool claims no parallax.')],
  [L('很亮的星', 'Very bright stars'), L('會飽和：巴納德星在所有波段、御夫座 RW 在長波段。飽和的核心不能用，光變曲線改用 PSF 外圍的光，誤差約 ×1.2（用不變的巴納德星量出來的）。', "They saturate: Barnard's Star in every band, RW Aurigae at long wavelengths. A saturated core is unusable, so the light curve uses the PSF wings, good to about ×1.2 (measured on Barnard's Star, which does not vary).")],
  [L('靠太近的兩顆星', 'Close pairs'), L('SPHEREx 的像素是 6.15″。比這更近的兩顆星會合成一個點，例如天苑增三 Ba 和 Bb（相距 0.7″）；鄰星的光也會混進孔徑，短波長最明顯。', 'A SPHEREx pixel is 6.15″. Two stars closer than that merge into one point, as Epsilon Indi Ba and Bb do (0.7″ apart); a neighbour also leaks into the aperture, most at short wavelengths.')],
  [L('變得快的變星', 'Fast variables'), L('一輪巡天只有約兩週，所以週期短於幾個月的變星只能看到零星幾個時間點。', 'One survey pass lasts about two weeks, so a variable with a period shorter than a few months is sampled at only a few moments.')],
  [L('光譜 AI', 'The spectrum AI'), L('只用合成光譜訓練，真實的正樣本只有 2 顆；分數高代表「值得再看」，不是確認。', 'Trained on synthetic spectra only, with just 2 real positives; a high score means "worth another look", not a confirmation.')],
  [L('新的行星', 'A new planet'), L('AI 候選和投票都不等於發現。這個網站沒有發現新的行星。', 'Neither an AI candidate nor a vote is a discovery. This site has not discovered a new planet.')],
]

// ---- for developers: each step of ours beside the official IRSA notebook that reproduces it (docs/irsa_tutorial_alignment.md)
const NB = 'https://caltech-ipac.github.io/irsa-tutorials/'
const NOTEBOOK = () => ({
  intro: [L('資料概覽', 'Data Overview'), `${NB}spherex-intro/`],
  cutouts: [L('光譜影像裁切', 'Spectral Image Cutouts'), `${NB}spherex-cutouts/`],
  psf: [L('PSF 模型', 'PSF Models'), `${NB}spherex-psf/`],
  sdt: [L('來源偵測工具', 'Source Discovery Tool'), `${NB}spherex-source-discovery-tool-demo/`],
  mosaic: [L('拼接立方體', 'Mosaic Cube'), `${NB}spherex-mosaic/`],
  hips: [L('HiPS 全天立方體', 'HiPS All-Sky Cube'), `${NB}spherex-hipscube/`],
  spectro: [L('光譜測光工具（網頁）', 'Spectrophotometry Tool (web)'), 'https://irsa.ipac.caltech.edu/applications/spherex/tool-spectrophotometry'],
})
// status: same | close (another route, same result) | fix (we differ and should change) | goal (a different question)
const DEV = () => [
  { step: L('找影像', 'Find the images'), ours: ['sxlib/archive.py search_images()', 'POST /api/quick', 'GET /api/field/<id>/fresh'], nb: ['intro'], st: 'same',
    note: L('都問 IRSA 的 SIA 服務，版本是 spherex_dr1 + spherex_qr3。我們每天向 IRSA 查一次有哪些版本，新版本不用改程式。', 'Both ask IRSA’s SIA service for spherex_dr1 + spherex_qr3. We ask IRSA once a day which releases exist, so a new one needs no code change.') },
  { step: L('裁切一小塊', 'Cut out a patch'), ours: ['sxlib/archive.py fetch_cutout()'], nb: ['cutouts'], st: 'same',
    note: L('同一個 IRSA 裁切服務（?center=&size=）。教學用 TAP 找影像，比 SIA 早一天看到新資料。', 'The same IRSA cutout service (?center=&size=). The notebook finds images with TAP, which sees new data a day before SIA does.') },
  { step: L('每個像素的波長', 'Wavelength of each pixel'), ours: ['sxlib/archive.py _lam_grid()', 'GET /api/field/<id>/point'], nb: ['intro'], st: 'fix',
    note: L('都讀光譜座標「W」。IRSA 會關掉其中的 SIP 變形項，我們沒有，所以波長偏短：24 張影像中位數 3 nm、最多 14 nm。關掉後和 IRSA 差 0.3 nm。', 'Both read the spectral WCS “W”. IRSA turns its SIP distortion terms off and we did not, so our wavelengths came out short: 3 nm median over 24 exposures, 14 nm at most. With SIP off we match IRSA to 0.3 nm.') },
  { step: L('扣掉背景', 'Remove the background'), ours: ['IMAGE − ZODI', 'sxlib/products.py phot()'], nb: ['intro', 'spectro'], st: 'close',
    note: L('ZODI 是黃道光模型，影像裡沒有扣掉。我們先扣 ZODI，再用星周圍的一圈天空扣殘餘；官方工具不用 ZODI，直接擬合局部背景。', 'ZODI is a zodiacal-light model that the image does not subtract. We subtract it, then the residual sky from a ring around the star; the official tool skips ZODI and fits a local background.') },
  { step: L('壞像素旗標', 'Bad-pixel flags'), ours: ['sxlib/archive.py HARD_BAD', 'GET /api/probe'], nb: ['intro', 'spectro'], st: 'fix',
    note: L('我們排除 14 種旗標，比官方工具多（例如 TRANSIENT、OVERFLOW），但漏了官方會排除的 SNOWBALL（第 27 位元）。', 'We leave out 14 flag kinds, more than the official tool does (TRANSIENT and OVERFLOW, for example), but miss SNOWBALL (bit 27), which it leaves out.') },
  { step: L('PSF 模型', 'PSF model'), ours: ['sxlib/psfphot.py', 'scripts/psf_targets.py'], nb: ['psf'], st: 'close',
    note: L('官方取星所在位置最近的那一區 ePSF（每個偵測器 21 × 21 區）。我們在重新取樣、轉過角度的網格上擬合，所以用每個偵測器的平均 PSF，再做對稱化。', 'IRSA takes the ePSF of the zone nearest the star (21 × 21 zones per detector). We fit on a resampled, rotated grid, so we use one averaged, symmetrised PSF per detector.') },
  { step: L('一點的光譜', 'Spectrum of a point'), ours: ['GET /api/field/<id>/point?x=&y=', 'scripts/irsa_spectro_compare.py'], nb: ['spectro', 'sdt'], st: 'close', link: ['#/guide/trust', L('看驗證圖', 'See the check')],
    note: L('官方工具用 Tractor 擬合 PSF；我們的工作台用 2 像素孔徑，目標另做 PSF 擬合。兩者逐張比較的結果在「有多可靠」。', 'The official tool fits the PSF with The Tractor; our labs use a 2-pixel aperture, and the targets also get a PSF fit. The exposure-by-exposure comparison is under “How far to trust it”.') },
  { step: L('換算成 µJy', 'Convert to µJy'), ours: ['sxlib/products.py PIX_SR'], nb: ['sdt'], st: 'close',
    note: L('官方用每個原始像素的立體角圖；我們先把影像重新取樣到 6.15″ 的網格，所以每個像素的立體角都一樣。', 'IRSA uses the solid-angle map of each native pixel; we first resample onto a 6.15″ grid, where every pixel has the same solid angle.') },
  { step: L('找天體', 'Find sources'), ours: ['GET /api/movers', 'sxlib/detect.py', 'sxlib/pmsearch.py'], nb: ['sdt'], st: 'goal',
    note: L('來源偵測工具在兩張不同波段的影像相減後找偏紅的天體；我們比較不同日期，找會動或會變的天體。問題不同，不能一對一比。', 'The Source Discovery Tool subtracts two bands to find red sources; we compare dates to find things that move or change. Different questions, so no one-to-one comparison.') },
  { step: L('全天影像', 'All-sky picture'), ours: ['Aladin Lite', 'irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube'], nb: ['hips'], st: 'same',
    note: L('同一份 IRSA 的 SPHEREx DR1 全天 HiPS。官方提醒它只適合看，量光譜要用光譜測光工具。', 'The same IRSA SPHEREx DR1 all-sky HiPS. IRSA notes it is for viewing; spectra should come from the Spectrophotometry Tool.') },
  { step: L('疊加影像', 'Stack the images'), ours: ['sxlib/products.py', '/data/fields/<id>/pass/stacks.bin'], nb: ['mosaic'], st: 'goal',
    note: L('官方拼接把所有日期依波長合併；我們刻意把日期分開（每輪一張），因為要找變化。', 'The official mosaic merges every date by wavelength; we keep the dates apart (one stack per pass) on purpose, because we look for change.') },
]
const STATUS = () => ({
  same: [L('一致', 'Same'), COL.good],
  close: [L('路線不同', 'Other route'), COL.known],
  fix: [L('要修正', 'Needs a fix'), COL.warn],
  goal: [L('問題不同', 'Other question'), COL.ink3],
})
/** DR1 and QR3 on one time axis (dates from IRSA's release notes); HTML, so the labels keep their size on a phone. */
function Releases() {
  const t0 = Date.UTC(2025, 3, 1), t1 = Date.UTC(2026, 10, 1), P = (d) => `${((Date.UTC(...d) - t0) / (t1 - t0)) * 100}%`
  const bars = [
    { k: 'DR1', a: [2025, 3, 24], b: [2026, 4, 14], n: '945,725', c: COL.known, when: L('2025-04-24 到 2026-05-14', '2025-04-24 to 2026-05-14') },
    { k: 'QR3', a: [2026, 4, 14], b: [2026, 9, 5], n: '362,124', c: COL.accent, when: L('2026-05-14 到 2026-10-05', '2026-05-14 to 2026-10-05') },
  ]
  return (
    <div className="gdv-rel" role="img" aria-label={L('SPHEREx DR1 和 QR3 的時間範圍', 'The time span of SPHEREx DR1 and QR3')}>
      <div className="gdv-track">
        {bars.map((r) => <span key={r.k} className="gdv-bar" style={{ left: P(r.a), width: `calc(${P(r.b)} - ${P(r.a)})`, '--c': r.c }} title={r.when}><b>{r.k}</b><small>{r.n}</small></span>)}
      </div>
      <div className="gdv-axis">{['2025-04', '2025-10', '2026-04', '2026-10'].map((s) => <span key={s} style={{ left: P([+s.slice(0, 4), +s.slice(5) - 1, 1]) }}>{s}</span>)}</div>
    </div>
  )
}
function DevSection() {
  const nb = NOTEBOOK(), st = STATUS(), rows = DEV()
  const count = (k) => rows.filter((r) => r.st === k).length
  return <>
    <p className="lead">{L('我們每一步，和可以重現它的 IRSA 官方筆記本放在一起。', 'Each of our steps beside the official IRSA notebook that reproduces it.')}</p>
    <ul className="gdv-key" aria-label={L('狀態', 'Status')}>
      {Object.entries(st).map(([k, [lab, c]]) => <li key={k}><i style={{ '--c': c }} /><b>{count(k)}</b>{lab}</li>)}
    </ul>
    <ol className="gdv-rows">
      {rows.map((r, j) => (
        <li key={j} className="gdv-row" style={{ '--c': st[r.st][1] }}>
          <div className="gdv-step"><span className="gdv-num">{j + 1}</span><h3>{r.step}</h3><span className="gdv-st">{st[r.st][0]}</span></div>
          <div className="gdv-ours"><span className="gdv-lab">{L('我們', 'Ours')}</span>{r.ours.map((c) => <code key={c}>{c}</code>)}</div>
          <div className="gdv-nb"><span className="gdv-lab">IRSA</span>{r.nb.map((k) => <a key={k} className="gdv-go" href={nb[k][1]} target="_blank" rel="noopener">{nb[k][0]}</a>)}{r.link && <a className="gdv-go own" href={r.link[0]}>{r.link[1]}</a>}</div>
          <p className="gdv-note">{r.note}</p>
        </li>
      ))}
    </ol>
    <div className="gdv-two">
      <div className="gdv-box">
        <h3>{L('用的資料版本', 'The data release we use')}</h3>
        <Releases />
        <p>{L('DR1（第一版正式資料）加上之後的 QR3，這是 IRSA 建議的組合；QR2 已被取代，只留在固定不變的 Planet X 模擬天區。數字是各版本的影像張數。', 'DR1 (the first full data release) plus QR3 after it, the pair IRSA recommends; QR2 is superseded and kept only for the fixed simulated Planet X field. The numbers count each release’s images.')}</p>
      </div>
      <div className="gdv-box">
        <h3>{L('怎麼引用', 'How to cite')}</h3>
        <ul className="gdv-cite">
          <li><b>{L('資料', 'Data')}</b>SPHEREx DR1 <code>doi:10.26131/IRSA678</code> · QR3 <code>doi:10.26131/IRSA662</code></li>
          <li><b>{L('論文', 'Papers')}</b>Bock et al. 2026 · Akeson et al. 2026 · Crill et al. 2025 · Korngut et al. 2026</li>
          <li><b>{L('致謝', 'Acknowledge')}</b>{L('NASA/IPAC 紅外線科學檔案館（IRSA）；用到 Gaia 時加 ESA/DPAC。', 'the NASA/IPAC Infrared Science Archive (IRSA); ESA/DPAC when Gaia data are used.')}</li>
        </ul>
        <a className="gdv-go own" href="#/credits">{L('完整的致謝文字', 'The full acknowledgement text')}</a>
      </div>
    </div>
    <p className="gd-dev">{L('資料介面都是公開的 JSON：', 'The data interfaces are plain public JSON: ')}<code>POST /api/quick</code>{L('（開始快速預覽）', ' (start a quick look)')} · <code>/api/field/&lt;id&gt;/point?x=&amp;y=</code>{L('（任一點的光譜與光變曲線）', ' (spectrum and light curve of any point)')} · <code>/api/movers</code> · <code>/api/validation</code> · <code>/api/resolve?q=</code>{L('（名稱轉座標）', ' (name to position)')} · <code>/data/validation/spectro.json</code>{L('（和 IRSA 工具的比較）', ' (the comparison with IRSA’s tool)')}</p>
  </>
}

export default function Guide({ sec }) {
  useLanguage()
  useEffect(() => { document.title = 'SPHEREx Sky Change · ' + L('說明與驗證', 'Guide and validation') }, [])
  useEffect(() => {
    if (!sec) return
    const id = setTimeout(() => document.getElementById(`g-${sec}`)?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth' }), 150)
    return () => clearTimeout(id)
  }, [sec])
  const jump = (id) => (e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth' }) }
  const req = REQ(), kind = KIND()
  return (
    <div className="object target guide">
      <header className="tg-listhead">
        <h1>{L('怎麼看、有多可靠', 'How to read it, and how far to trust it')}</h1>
        <p className="lead">{L('每種畫面在看什麼、結果經過哪些檢驗、這個工具看不到什麼，以及題目的每一項要求在網站的哪裡。', 'What each view shows, how the results were checked, what this tool cannot see, and where each requirement of the challenge is met.')}</p>
        <nav className="guide-toc" aria-label={L('本頁內容', 'On this page')}>
          <a href="#/guide/read" onClick={jump('g-read')}>{L('怎麼看影像', 'Reading the images')}</a>
          <a href="#/guide/trust" onClick={jump('g-trust')}>{L('有多可靠', 'How far to trust it')}</a>
          <a href="#/guide/limits" onClick={jump('g-limits')}>{L('看不到什麼', 'What it cannot see')}</a>
          <a href="#/guide/requirements" onClick={jump('g-requirements')}>{L('題目要求在哪裡', 'Challenge requirements')}</a>
          <a href="#/guide/more" onClick={jump('g-more')}>{L('更多工具', 'More tools')}</a>
          <a href="#/guide/dev" onClick={jump('g-dev')}>{L('給開發者', 'For developers')}</a>
        </nav>
      </header>

      <section id="g-read" className="guide-sec">
        <h2>{L('怎麼看這些影像', 'Reading the images')}</h2>
        <div className="gd-read">
          {HOW().map((h) => (
            <article key={h.k} className="gd-how">
              <figure className="gd-pic">
                {h.pic}
                {h.legend && <Legend items={h.legend} />}
              </figure>
              <div>
                <h3>{h.title}</h3>
                <p>{h.text}</p>
                <details><summary>{L('再多一點', 'A little more')}</summary><p>{h.more}</p></details>
                <a className="gd-try" href={h.go[1]}>{h.go[0]} →</a>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section id="g-trust" className="guide-sec">
        <h2>{L('有多可靠', 'How far to trust it')}</h2>
        <p className="lead">{L('每張圖都是對真實資料量出來的，包含結果不好看的那些。', 'Every chart below was measured on real data, including the unflattering ones.')}</p>
        <Validation />
        <p className="vd-foot">{L('小行星管線（差分、自己訓練的真假判斷網路、軌跡連結、JPL 比對）的驗證寫在論文裡：', 'The asteroid pipeline (differences, the self-trained real/bogus network, track linking, the JPL match) is validated in the paper: ')}<a href={paperUrl('paper')}>{L('論文全文', 'full text')}</a> · <a href="/paper/research/evidence.json">{L('證據資料（JSON）', 'evidence (JSON)')}</a></p>
      </section>

      <section id="g-limits" className="guide-sec">
        <h2>{L('這裡看不到什麼', 'What it cannot see')}</h2>
        <ul className="gd-limits">
          {LIMITS().map(([lead, text], j) => <li key={j}><b>{lead}{L('：', ': ')}</b>{text}</li>)}
        </ul>
      </section>

      <section id="g-requirements" className="guide-sec">
        <h2>{L('題目的每項要求在哪裡', 'Where each challenge requirement is met')}</h2>
        <p className="gd-score"><strong>{req.length} / {req.length}</strong>{L('NASA Space Apps 2026「Planet X and SPHEREx」的每一項都做到了；每個按鈕直接打開對應的畫面。', 'Every item of NASA Space Apps 2026, "Planet X and SPHEREx", is met; each button opens that exact view.')}</p>
        <ul className="gd-req">
          {req.map(([k, short, what, links, note]) => (
            <li key={k} className="gd-tile">
              <div className="gd-tile-h"><span className="gd-code">{k}</span><span className="gd-kind">{kind[k[0]]}</span><span className="gd-ok">{ICON.check}{L('做到了', 'Met')}</span></div>
              <h3>{short}</h3>
              <div className="gd-links">{links.map(([lab, href], j) => <a key={j} className={`gd-go ${j ? '' : 'first'}`} href={href}>{j ? lab : <span>{L('試試看：', 'Try it: ')}{lab}</span>}</a>)}</div>
              {(what || note) && <details>
                <summary>{L('題目原文與說明', 'The requirement and notes')}</summary>
                {what && <p>{L('題目：', 'Requirement: ')}{what}</p>}
                {note && <p>{note}</p>}
              </details>}
            </li>
          ))}
        </ul>
      </section>

      <section id="g-more" className="guide-sec">
        <h2>{L('更多工具', 'More tools')}</h2>
        <div className="ms-actions">
          <a className="btn" href="#/story">{L('研究故事：它怎麼運作', 'The research story: how it works')}</a>
          <a className="btn" href="#/features">{L('功能總覽', 'All features')}</a>
          <a className="btn" href="#/universe/cybele">{L('星體重建', 'Body reconstruction')}</a>
          <a className="btn" href="#/discovery">{L('遠距天體（Planet X）搜尋', 'The distant-body (Planet X) search')}</a>
          <a className="btn" href={paperUrl('paper')}>{L('論文', 'Paper')}</a>
        </div>
      </section>

      <section id="g-dev" className="guide-sec">
        <h2>{L('給開發者', 'For developers')}</h2>
        <DevSection />
      </section>
    </div>
  )
}
