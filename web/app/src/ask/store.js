// The in-site assistant's state, kept out of React so any module (a three.js scene, a page) can open it cheaply:
//   import { askAbout } from '../ask/store.js';  askAbout({ kind: 'body', name: 'Mars', facts: { a_au: 1.52 } })
// What is asked about, in order: the context cleared by the visitor (general questions), one handed in by askAbout(),
// what the page itself reports (setPageContext, once its data is loaded), and the route's default (setRouteContext).
// The panel (AskPanel.jsx, its own chunk) keeps the conversations; this file stays tiny because it is in the entry.
let st = { open: false, ctx: null, page: null, route: null, cleared: false, n: 0 }
const fns = new Set()
const emit = (patch) => { st = { ...st, ...patch, n: st.n + 1 }; fns.forEach((f) => f()) }
export const subscribe = (f) => { fns.add(f); return () => fns.delete(f) }
export const getAsk = () => st
/** What the next question is about. */
export const askContext = (s = st) => (s.cleared ? { kind: 'page', name: 'general' } : s.ctx || s.page || s.route || { kind: 'page' })

// where focus was when the panel opened, so closing it can go back there
let opener = null
const mark = () => { if (!st.open && typeof document !== 'undefined') opener = document.activeElement }
export const takeOpener = () => { const o = opener; opener = null; return o }

/** Open the assistant about one thing: { kind, id?, name?, ra?, dec?, facts? }. */
export function askAbout(ctx) { mark(); emit({ open: true, ctx: ctx || null, cleared: false }) }
export const openAsk = () => { mark(); emit({ open: true }) }
export const closeAsk = () => emit({ open: false })
export const clearAskContext = (on = true) => emit({ cleared: on })
/** A page's own description of what is on screen (null when it goes away). */
export function setPageContext(ctx) { if (JSON.stringify(ctx || null) !== JSON.stringify(st.page)) emit({ page: ctx || null }) }
/** The route's default; a new route drops what an earlier page or askAbout() set. */
export function setRouteContext(ctx) {
  if (JSON.stringify(ctx) === JSON.stringify(st.route)) return
  emit({ route: ctx, page: null, ctx: null, cleared: false })
}
