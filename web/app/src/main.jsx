import { Component, StrictMode, Suspense, lazy, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { LanguageSwitch, useLanguage } from '@sx/i18n/language.jsx'
import { getLanguage, loadCatalog, paperUrl } from '@sx/i18n/core.js'
import Landing from './landing.jsx'
import { go } from './nav.js'
import { setMode, useMode } from './mode.js'
import { SkySearch } from './search.jsx'
import { L } from './lib.js'
import AskButton from './ask/AskButton.jsx'
import { setRouteContext } from './ask/store.js'
import './app.css'

const Viewer = lazy(() => import('./viewer.jsx'))
const ObjectPage = lazy(() => import('./object.jsx'))
const UniversePage = lazy(() => import('./universe/UniversePage.jsx'))
const Features = lazy(() => import('./features.jsx'))
const Discovery = lazy(() => import('./discovery.jsx'))
const TargetPage = lazy(() => import('./target.jsx').then((m) => ({ default: m.TargetPage })))
const TargetList = lazy(() => import('./target.jsx').then((m) => ({ default: m.TargetList })))
const SkyResolve = lazy(() => import('./skyresolve.jsx'))
const Lab = lazy(() => import('./lab.jsx'))
const Embed = lazy(() => import('./embed.jsx'))
const Movers = lazy(() => import('./movers.jsx'))
const Guide = lazy(() => import('./guide.jsx'))
const StoryPage = lazy(() => import('./storypage.jsx'))
const Follow = lazy(() => import('./follow.jsx'))
const Comet = lazy(() => import('./comet.jsx'))
const Credits = lazy(() => import('./credits.jsx'))
// the decorative WebGL star field behind two content pages: its own chunk, never in the entry
const SkyBackdrop = lazy(() => import('./fx.jsx').then((m) => ({ default: m.SkyBackdrop })))

// Hash routes: #/  ·  #/field/<id>  ·  #/field/<id>/track/<n>   (deep links + browser back)
const dec = decodeURIComponent
/** Pages that take nothing from the path beyond their name. */
const PLAIN = new Set(['story', 'features', 'discovery', 'credits', 'targets'])
function parseHash() {
  const [path, qs] = location.hash.replace(/^#\/?/, '').split('?')
  const p = path.split('/').filter(Boolean)
  const u = new URLSearchParams(qs || '')
  const fovRaw = u.get('fov'), fov = fovRaw ? Number(fovRaw) : null
  const base = { stage: p[0], field: null, track: null }
  const rest = () => dec(p.slice(1).join('/'))
  switch (p[0]) {
    case 'embed': if (p[1]) return { ...base, q: rest(), fov }; break
    case 'guide': case 'comet': return { ...base, sec: p[1] || null }
    case 'lab': case 'target': if (p[1]) return { ...base, field: dec(p[1]) }; break
    case 'movers': return { ...base, focus: u.get('f') ? { f: u.get('f'), m: u.get('m') } : null }
    case 'follow': return { ...base, q: p[1] ? rest() : null }
    case 'sky': if (p[1]) return { ...base, q: rest(), fov }; break
    case 'universe': return { ...base, field: dec(p[1] || 'cybele'), pick: p[2] ? dec(p[2]) : null }
    case 'field':
      if (p[1]) return p[2] === 'track' ? { stage: 'object', field: dec(p[1]), track: Number(p[3]) } : { stage: 'viewer', field: dec(p[1]), track: null }
      break
    default: if (PLAIN.has(p[0])) return base
  }
  return { stage: 'landing', field: null, track: null }
}

/** One render function per page (route -> element). */
const PAGES = {
  landing: () => <Landing />,
  viewer: (r) => <Viewer fieldId={r.field} />,
  object: (r) => <ObjectPage fieldId={r.field} trackId={r.track} />,
  features: () => <Features />,
  discovery: () => <Discovery />,
  universe: (r) => <UniversePage fieldId={r.field} pick={r.pick} />,
  targets: () => <TargetList />,
  lab: (r) => <Lab id={r.field} />,
  target: (r) => <TargetPage id={r.field} />,
  sky: (r) => <SkyResolve q={r.q} fov={r.fov} />,
  movers: (r) => <Movers focus={r.focus} />,
  guide: (r) => <Guide sec={r.sec} />,
  story: () => <StoryPage />,
  follow: (r) => <Follow q={r.q} />,
  comet: (r) => <Comet sec={r.sec} />,
  credits: () => <Credits />,
}
/** Top-bar sections and the stages that belong to each. */
const SKY_STAGES = new Set(['landing', 'sky', 'viewer', 'object', 'lab', 'follow', 'comet'])
const GUIDE_STAGES = new Set(['guide', 'story', 'features', 'discovery', 'universe', 'credits'])
const BACKDROP_STAGES = new Set(['features', 'discovery'])

function TopBar({ route }) {
  const [open, setOpen] = useState(false)
  useEffect(() => { setOpen(false) }, [route.stage, route.field, route.track])
  useEffect(() => {
    if (!open) return
    const k = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [open])
  const first = useRef()
  useEffect(() => { if (open) first.current?.focus() }, [open])
  // one name per thing, five places to go: the sky (search), the challenge targets, the review queue, the guide, the paper
  const items = [
    { k: 'landing', label: L('看天空', 'Sky'), on: SKY_STAGES.has(route.stage), go: () => go(null) },
    { k: 'targets', label: L('測試目標', 'Targets'), on: route.stage === 'targets' || route.stage === 'target', go: () => { location.hash = '#/targets' } },
    { k: 'movers', label: L('找移動星', 'Find movers'), on: route.stage === 'movers', go: () => { location.hash = '#/movers' } },
    { k: 'guide', label: L('說明與驗證', 'Guide'), on: GUIDE_STAGES.has(route.stage), go: () => { location.hash = '#/guide' } },
  ]
  return (
    <header className={`topbar ${open ? 'menu-open' : ''}`}>
      <button className="brand" onClick={() => go(null)} aria-label="回到首頁"><i aria-hidden="true" /><span>SPHEREx Sky Change</span></button>
      {route.stage !== 'landing' && <div className="topsearch"><SkySearch compact id="top-q" examples={false} label={L('換一片天空', 'Go to another patch of sky')} /></div>}
      <nav className="nav" aria-label="網站導覽">
        {items.map((it) => (
          <button key={it.k} className={it.k === 'landing' ? '' : 'opt'} aria-current={it.on ? 'page' : undefined} onClick={it.go}>{it.label}</button>
        ))}
        <a className="opt" href={paperUrl('paper')}>論文</a>
      </nav>
      <ModeSwitch />
      <LanguageSwitch />
      <button className="menu-btn" aria-expanded={open} aria-controls="menu-sheet" aria-label="選單" onClick={() => setOpen(!open)}>
        <svg viewBox="0 0 24 24" aria-hidden="true">{open
          ? <path d="M6 6l12 12M18 6L6 18" />
          : <path d="M4 7h16M4 12h16M4 17h16" />}</svg>
      </button>
      {open && (
        <div id="menu-sheet" className="menu-sheet" role="dialog" aria-label="網站導覽">
          <SkySearch compact id="menu-q" examples={false} label={L('換一片天空（選單）', 'Go to another patch of sky (menu)')} />
          {items.map((it, k) => (
            <button key={it.k} ref={k === 0 ? first : undefined} aria-current={it.on ? 'page' : undefined} onClick={() => { setOpen(false); it.go() }}>{it.label}</button>
          ))}
          <a href={paperUrl('paper')}>論文</a>
          <ModeSwitch />
        </div>
      )}
      {open && <div className="menu-scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
    </header>
  )
}

function ModeSwitch() {
  const m = useMode()
  return (
    <button className={`modesw ${m === 'research' ? 'on' : ''}`} role="switch" aria-checked={m === 'research'} onClick={() => setMode(m === 'research' ? 'story' : 'research')}
      title="研究模式顯示所有控制項與資料品質說明">
      <i aria-hidden="true" /><span>研究模式</span>
    </button>
  )
}

// ---- errors (UPGRADE_PLAN.md §8, T8 / T13) -------------------------------------------------------------------
// Report a front-end error to the server: the message, the stack, the route without its query, the browser.
// No position, no IP is kept (the server only rate-limits); at most 5 reports per page load.
let reported = 0
function reportError(err, where = '') {
  if (reported >= 5 || typeof navigator === 'undefined') return
  reported += 1
  try {
    const body = JSON.stringify({ msg: String(err?.message || err).slice(0, 300), stack: String(err?.stack || where).slice(0, 2000),
      route: location.hash.split('?')[0].slice(0, 200), ua: navigator.userAgent.slice(0, 200) })
    navigator.sendBeacon?.('/api/clienterr', new Blob([body], { type: 'application/json' })) || fetch('/api/clienterr', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {})
  } catch { /* never let reporting break the page */ }
}
window.addEventListener('error', (e) => reportError(e.error || e.message, `${e.filename}:${e.lineno}`))
window.addEventListener('unhandledrejection', (e) => reportError(e.reason))
// After a redeploy, a tab opened earlier may ask for a page chunk that no longer exists: reload once to get the new
// build (the build also keeps the previous one's files, so this is the rare case).
window.addEventListener('vite:preloadError', (e) => {
  const k = 'sx:reloaded', now = Date.now()
  let last = 0
  try { last = +sessionStorage.getItem(k) || 0 } catch { /* private mode */ }
  if (now - last > 30000) { try { sessionStorage.setItem(k, String(now)) } catch { /* */ } e.preventDefault(); location.reload() }
})

/** Catches a crash in one page so the rest of the site (top bar, navigation) keeps working. */
class ErrorBoundary extends Component {
  constructor(p) { super(p); this.state = { err: null } }
  static getDerivedStateFromError(err) { return { err } }
  componentDidCatch(err, info) { reportError(err, info?.componentStack?.slice(0, 1500)) }
  render() {
    if (!this.state.err) return this.props.children
    return (
      <div className="crash" role="alert">
        <h1>{L('這一頁出了問題', 'Something went wrong on this page')}</h1>
        <p className="lead">{L('錯誤已經自動回報（不含你的位置或任何個人資料）。重新載入通常就會好；也可以回到首頁。', 'The error was reported automatically (without your position or any personal data). Reloading usually fixes it; you can also go back to the home page.')}</p>
        <div className="ms-actions">
          <button className="btn primary" onClick={() => location.reload()}>{L('重新載入', 'Reload')}</button>
          <a className="btn" href="#/" onClick={() => this.setState({ err: null })}>{L('回到首頁', 'Home')}</a>
        </div>
      </div>
    )
  }
}

// WiseView's link format (#ra=<deg>&dec=<deg>&size=<arcsec>...) opens the same position here, so a WiseView link can
// be pasted after this site's address. The size picks the nearest of the three fields of view.
function wiseviewToHash() {
  if (!/^#ra=/.test(location.hash)) return
  const u = new URLSearchParams(location.hash.slice(1))
  const ra = Number(u.get('ra')), dec = Number(u.get('dec')), size = Number(u.get('size'))
  if (!Number.isFinite(ra) || !Number.isFinite(dec)) return
  const fov = Number.isFinite(size) && size > 0 ? [0.15, 0.3, 0.6].reduce((a, b) => (Math.abs(b - size / 3600) < Math.abs(a - size / 3600) ? b : a)) : null
  history.replaceState(null, '', `${location.pathname}${location.search}#/sky/${encodeURIComponent(`${ra} ${dec}`)}${fov ? `?fov=${fov}` : ''}`)
}
wiseviewToHash()
// also when a WiseView hash is pasted into a tab that already shows this site (only the hash changes, no reload);
// registered before the router's listener, so the router reads the converted hash
window.addEventListener('hashchange', wiseviewToHash)

function queryToHash() {
  const u = new URLSearchParams(location.search)
  const ra = u.get('ra'), dec = u.get('dec'), q = u.get('target') || u.get('q')
  if (!ra && !dec && !q) return
  const v = ra && dec ? `${ra} ${dec}` : q || `${ra ?? ''}${dec ? ` ${dec}` : ''}`.trim()
  const embed = ['1', 'true', ''].includes(u.get('embed') ?? 'x')
  // field of view and the view state (mode, detector, frame) move into the hash query with the position
  const view = new URLSearchParams()
  for (const k of ['fov', 'v', 'd', 'k']) if (u.get(k) != null) view.set(k, u.get(k))
  for (const k of ['ra', 'dec', 'target', 'q', 'fov', 'embed', 'v', 'd', 'k']) u.delete(k)
  const rest = u.toString()
  history.replaceState(null, '', `${location.pathname}${rest ? '?' + rest : ''}#/${embed ? 'embed' : 'sky'}/${encodeURIComponent(v)}${view.toString() ? `?${view}` : ''}`)
}
queryToHash()

/** What the assistant is asked about by default on each route (the pages add names and facts once loaded). */
function routeAsk(r) {
  switch (r.stage) {
    case 'viewer': case 'lab': return { kind: 'field', id: r.field }
    case 'target': return { kind: 'target', id: r.field }
    case 'object': return { kind: 'object', id: `${r.field}/${r.track}` }
    case 'sky': return r.q ? { kind: 'field', name: r.q } : { kind: 'page', name: 'sky' }
    default: return { kind: 'page', name: r.stage }
  }
}
setRouteContext(routeAsk(parseHash()))

function App() {
  const [route, setRoute] = useState(parseHash)
  useLanguage()
  useEffect(() => {
    let last = location.hash.split('?')[0]
    const on = () => {
      const path = location.hash.split('?')[0]
      // a hash change that leaves the route the same (a view parameter the page writes back) re-renders nothing
      const next = parseHash()
      setRouteContext(routeAsk(next))
      setRoute((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next))
      if (path !== last) { last = path; window.scrollTo({ top: 0 }) }
    }
    window.addEventListener('hashchange', on)
    document.documentElement.classList.add('reveal-ready')
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const key = route.stage + (route.stage === 'universe' ? '' : (route.field || '') + (route.track ?? ''))
  if (route.stage === 'embed') {
    return <ErrorBoundary><Suspense fallback={<div className="route-loading" role="status"><i aria-hidden="true" /></div>}><Embed q={route.q} fov={route.fov} /></Suspense></ErrorBoundary>
  }
  return (
    <div className="shell">
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>{L('跳到主要內容', 'Skip to main content')}</a>
      <TopBar route={route} />
      {/* a faint moving star field behind the content pages (the tools have their own canvases) */}
      {BACKDROP_STAGES.has(route.stage) && <Suspense fallback={null}><SkyBackdrop /></Suspense>}
      {/* a short CSS fade on route change (keyed main) replaces the animation library */}
      <main key={key} id="main" tabIndex={-1} className="route">
        <ErrorBoundary key={key}>
        <Suspense fallback={<div className="route-loading" role="status"><i aria-hidden="true" /><span>載入中…</span></div>}>
          {PAGES[route.stage]?.(route)}
        </Suspense>
        </ErrorBoundary>
      </main>
      <AskButton stage={route.stage} />
    </div>
  )
}

if (getLanguage() === 'en') await loadCatalog()
// offline shell and image cache (public/sw.js): a short tunnel outage does not stop a demo already open
if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === '127.0.0.1')) navigator.serviceWorker.register('/sw.js').catch(() => {})
createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
