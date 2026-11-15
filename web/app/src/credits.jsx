// #/credits: the data this site uses and how to acknowledge it, as each archive asks (IRSA's SPHEREx pages give the
// acknowledgement sentence, the data DOIs and the four canonical papers).
import { L } from './lib.js'
import './credits.css'
import { LLAMA_BUILT_WITH, LLAMA_NOTICE, SPHEREX_ACK } from './credits_text.js'

const IRSA_ACK = 'This work has made use of the NASA/IPAC Infrared Science Archive, which is funded by the National Aeronautics and Space Administration and operated by the California Institute of Technology.'
const GAIA_ACK = 'This work has made use of data from the European Space Agency (ESA) mission Gaia (https://www.cosmos.esa.int/gaia), processed by the Gaia Data Processing and Analysis Consortium (DPAC, https://www.cosmos.esa.int/web/gaia/dpac/consortium). Funding for the DPAC has been provided by national institutions, in particular the institutions participating in the Gaia Multilateral Agreement.'

const DOIS = [
  ['10.26131/IRSA678', () => L('SPHEREx DR1 光譜影像：這個網站的主要資料', 'SPHEREx DR1 spectral images: this site\'s main data')],
  ['10.26131/IRSA662', () => L('SPHEREx QR3 光譜影像：DR1 之後的新影像', 'SPHEREx QR3 spectral images: the images after DR1')],
  ['10.26131/IRSA679', () => L('SPHEREx DR1 全天立方體：首頁與天空頁的背景圖', 'SPHEREx DR1 all-sky cube: the backdrop of the home and sky pages')],
  ['10.26131/IRSA652', () => L('SPHEREx QR2：只用於固定不變的「模擬第九行星」測試天區', 'SPHEREx QR2: only the fixed simulated-Planet-X test field')],
]
const PAPERS = [
  ['Bock et al. 2026, ApJ, 999, 139', 'https://ui.adsabs.harvard.edu/abs/2026ApJ...999..139B/abstract', () => L('任務', 'Mission')],
  ['Akeson et al. 2026, ApJS, 285, 67', 'https://ui.adsabs.harvard.edu/abs/2026ApJS..285...67A/abstract', () => L('資料處理流程', 'Pipeline')],
  ['Crill et al. 2025, ApJS, 281, 10', 'https://ui.adsabs.harvard.edu/abs/2025ApJS..281...10C/abstract', () => L('天空模擬', 'Sky simulator')],
  ['Korngut et al. 2026, arXiv:2603.29835', 'https://ui.adsabs.harvard.edu/abs/2026arXiv260329835K/abstract', () => L('儀器與校正', 'Instrument and calibration')],
]
const OTHERS = [
  ['Gaia DR3', 'ESA / DPAC · Gaia Collaboration, Vallenari et al. 2023, A&A, 674, A1', () => L('恆星位置、自行、視差（從 ESA 或 NASA MAST 查詢）', 'Star positions, motions and parallaxes (queried at ESA or NASA MAST)')],
  ['CatWISE2020', 'Marocco et al. 2021, ApJS, 253, 8', () => L('紅外線星表與自行', 'Infrared catalogue and motions')],
  ['NEOSSat', () => L('加拿大太空總署；加拿大天文資料中心（CADC）', 'Canadian Space Agency; Canadian Astronomy Data Centre (CADC)'), () => L('含有加拿大太空總署 NEOSSat 任務的資料，依加拿大開放政府授權（Open Government Licence – Canada）使用', 'Contains data from the Canadian Space Agency\'s NEOSSat mission, used under the Open Government Licence – Canada')],
  ['JPL', 'Small-Body Identification, Horizons, SBDB', () => L('已知小行星和彗星的位置', 'Positions of known asteroids and comets')],
  ['IRSA MOST', 'NASA/IPAC IRSA', () => L('找出拍到某顆小行星的所有 SPHEREx 影像', 'Finds every SPHEREx image that caught a given asteroid')],
  ['CDS', 'SIMBAD, VizieR, Aladin Lite (Bonnarel et al. 2000; Wenger et al. 2000; Ochsenbein et al. 2000)', () => L('名稱查詢、星表、互動星圖', 'Name lookup, catalogues, the interactive sky map')],
  ['AAVSO VSX', () => L('經由 VizieR 查詢', 'queried through VizieR'), () => L('變星的週期和類型', 'Periods and types of variable stars')],
]
// the 3D home page and the telescope room: everything that is not ours, and what it may be used for
const SCENE = [
  ['NASA Blue Marble', () => L('NASA Earth Observatory，Blue Marble Next Generation（2004 年 8 月，地形與海床），公有領域', 'NASA Earth Observatory, Blue Marble Next Generation (August 2004, topography and bathymetry); public domain'), () => L('首頁的地球', 'The Earth on the home page')],
  ['ambientCG', 'MetalPlates004, MetalPlates007, MetalPlates008, SheetMetal001 · CC0', () => L('控制室的金屬牆板、地板、天花板材質', 'Metal wall, floor and ceiling materials in the control room')],
  ['Poly Haven', () => L('studio_small_09（HDRI）；metal_stool_01、modular_industrial_pipes_01、modular_electric_cables（模型）· CC0', 'studio_small_09 (HDRI); metal_stool_01, modular_industrial_pipes_01, modular_electric_cables (models) · CC0'), () => L('控制室的環境光、凳子、管線和電纜', 'Room lighting, the stool, pipes and cables')],
  [() => L('音樂', 'Music'), () => L('團隊原創：Mysterious Cosmos、Interstellar Inspired', 'Original, by the team: Mysterious Cosmos, Interstellar Inspired'), () => L('首頁與望遠鏡內的背景音樂', 'Background music outside and inside the telescope')],
  [() => L('望遠鏡模型', 'Telescope model'), () => L('NASA 3D Resources：Wide-Field Infrared Explorer（WIRE）。NASA 沒有公開 SPHEREx 的 3D 模型，所以用外型相近的紅外線巡天衛星代替', 'NASA 3D Resources: Wide-Field Infrared Explorer (WIRE). NASA has not released a SPHEREx 3D model, so a similar infrared survey satellite stands in'), () => L('首頁繞地球的望遠鏡', 'The telescope orbiting the Earth on the home page')],
]
// the assistant (the Ask button on every page): the models behind it and where its answers come from
const AI = [
  ['Meta Llama 3.2', () => L('Meta Platforms, Inc.；Llama 3.2 Community License（Llama 3.2 社群授權）', 'Meta Platforms, Inc.; Llama 3.2 Community License'), () => L('回答問題的語言模型（經過微調）', 'The language model that answers questions (fine-tuned)')],
  ['BGE-M3', () => L('北京智源人工智慧研究院（BAAI）；MIT', 'Beijing Academy of Artificial Intelligence (BAAI); MIT'), () => L('多語言向量模型：讓中文或英文問題都能找到相關論文段落', 'Multilingual embedding model: finds the relevant paper passages for questions in Chinese or English')],
  ['Qwen2.5', () => L('阿里雲 Qwen 團隊；Apache-2.0', 'Alibaba Cloud Qwen team; Apache-2.0'), () => L('只用來產生訓練資料，不在網站上執行', 'Used only to generate training data; it does not run on this site')],
  [() => L('arXiv 論文', 'arXiv papers'), () => L('arXiv.org；每篇論文依其作者選擇的授權', 'arXiv.org; each paper under the licence its authors chose'), () => L('回答引用的來源（檢索增強生成）：每個回答都列出用到的論文、作者、年份和 arXiv 連結', 'The sources answers cite (retrieval-augmented generation): each answer lists the papers it used, with authors, year and arXiv link')],
]
const txt = (v) => (typeof v === 'function' ? v() : v)

/** One line under a page: who made the data, with a link to the full list. */
export function CreditLine() {
  return (
    <p className="credit-line">
      {L('SPHEREx 資料來自 NASA/IPAC 紅外線科學檔案館（IRSA），主要是第一版正式資料（DR1）。', 'SPHEREx data from the NASA/IPAC Infrared Science Archive (IRSA), mainly Data Release 1 (DR1).')}{' '}
      <a href="#/credits">{L('資料來源與致謝 →', 'Data credits →')}</a>
    </p>
  )
}

export default function Credits() {
  return (
    <article className="credits">
      <h1>{L('資料來源與致謝', 'Data credits')}</h1>
      <p className="lead">{L('這個網站用的都是公開資料。下面是各資料庫要求的致謝方式；引用這個網站的結果時，請一併引用。', 'Everything here is built on public data. Below is how each archive asks to be acknowledged; please include these when you use results from this site.')}</p>
      <section className="cr-block">
        <h2>SPHEREx</h2>
        <blockquote lang="en">{SPHEREX_ACK}</blockquote>
        <blockquote lang="en">{IRSA_ACK}</blockquote>
        <h3>{L('資料的 DOI', 'Data DOIs')}</h3>
        <ul className="cr-list">
          {DOIS.map(([d, what]) => <li key={d}><a href={`https://doi.org/${d}`}>{d}</a><span>{what()}</span></li>)}
        </ul>
        <h3>{L('SPHEREx 標準論文', 'SPHEREx canonical papers')}</h3>
        <ul className="cr-list">
          {PAPERS.map(([t, u, what]) => <li key={t}><a href={u}>{t}</a><span>{what()}</span></li>)}
        </ul>
      </section>
      <section className="cr-block">
        <h2>Gaia</h2>
        <blockquote lang="en">{GAIA_ACK}</blockquote>
      </section>
      <section className="cr-block">
        <h2>{L('其他資料與服務', 'Other data and services')}</h2>
        <ul className="cr-list">
          {OTHERS.map(([n, who, what]) => <li key={n}><strong>{n}</strong><span>{txt(who)}</span><span>{txt(what)}</span></li>)}
        </ul>
      </section>
      <section className="cr-block">
        <h2>{L('3D 場景的素材', '3D scene assets')}</h2>
        <ul className="cr-list">
          {SCENE.map(([n, who, what], i) => <li key={i}><strong>{txt(n)}</strong><span>{txt(who)}</span><span>{txt(what)}</span></li>)}
        </ul>
      </section>
      <section className="cr-block" id="cr-ai">
        <h2>{L('提問助理', 'The assistant')} · {LLAMA_BUILT_WITH}</h2>
        <ul className="cr-list">
          {AI.map(([n, who, what], i) => <li key={i}><strong>{txt(n)}</strong><span>{txt(who)}</span><span>{txt(what)}</span></li>)}
        </ul>
        <blockquote lang="en">{LLAMA_NOTICE}</blockquote>
        <p className="hint">{L('AI 產生的回答可能有錯；請以回答列出的論文為準。', 'AI-generated answers can be wrong; rely on the papers each answer lists.')}</p>
      </section>
      <p className="hint">{L('這是 NASA Space Apps 2026 的黑客松原型，不是 NASA、加拿大太空總署或任何資料提供者的官方產品。', 'A NASA Space Apps 2026 hackathon prototype; not an official product of NASA, the Canadian Space Agency or any data provider.')}</p>
    </article>
  )
}
