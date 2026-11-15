// Two ways to write text, and only two (scripts/audit_i18n.mjs enforces it):
//   1. Chinese source text, translated from catalog.js: plain strings in JSX (children, aria-label, title, alt,
//      placeholder) are translated by the JSX runtime, including strings built at run time (a label looked up in a
//      table); strings with values use the tagged template t`共 ${n} 張影像`. Used by the pages written first.
//   2. L('中文', 'English'): the text carries its own English. Used everywhere else, and for anything new.
// A language test written by hand (lang === 'en' ? ... : ...) is not allowed outside this folder: use L().
// The English catalogue is its own file, fetched only when the page is shown in English (index.html preloads it).
let EN = {}, MESSAGES = {}, PATTERNS = []
let catalog = null
export function loadCatalog() {
  catalog ||= import('./catalog.js').then((m) => { EN = m.EN; MESSAGES = m.MESSAGES; PATTERNS = m.PATTERNS; memo.clear() })
  return catalog
}

export const LANGUAGE_KEY = 'sx:language:v1'
export function initialLanguage(search = '', storage = null) {
  const requested = new URLSearchParams(search).get('lang')
  if (requested === 'en' || requested === 'zh-Hant') return requested
  // English is the primary interface; Traditional Chinese only when asked for or chosen before.
  try { return storage?.getItem(LANGUAGE_KEY) === 'zh-Hant' ? 'zh-Hant' : 'en' } catch { return 'en' }
}
/** Static paper pages in the current language: page is 'index' (project page) or 'paper' (full text). */
export const paperUrl = (page, lang = language) =>
  `/paper/${page === 'index' ? (lang === 'en' ? 'index' : 'zh') : (lang === 'en' ? 'paper' : 'paper-zh')}.html`
let language = typeof window === 'undefined' ? 'en'
  : initialLanguage(window.location.search, { getItem: (k) => window.localStorage.getItem(k) })
const listeners = new Set()
export const getLanguage = () => language
export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn) }
/** Two-language text that carries its own English: L('中文', 'English'). Works for any pair of values. */
export const L = (zh, en) => (language === 'en' ? en : zh)
export async function setLanguage(next) {
  if (!['en', 'zh-Hant'].includes(next) || next === language) return
  if (next === 'en') await loadCatalog()
  language = next
  if (typeof window !== 'undefined') {
    try { window.localStorage.setItem(LANGUAGE_KEY, next) } catch { /* private mode */ }
    // a ?lang= that came with the link is dropped once the visitor chooses: their choice is theirs, not part of what they share
    try { const u = new URL(window.location.href); if (u.searchParams.has('lang')) { u.searchParams.delete('lang'); window.history.replaceState(window.history.state, '', u) } } catch { /* ignore */ }
    document.documentElement.lang = next
  }
  listeners.forEach((fn) => fn())
}

// The JSX runtime translates every string child on every render, so a key (including a miss, which would
// otherwise run every pattern again) is looked up once. Kept bounded: run-time strings (numbers, names) vary.
const memo = new Map()
const MEMO_MAX = 4000
function lookup(key) {
  if (memo.has(key)) return memo.get(key)
  let out
  if (Object.hasOwn(EN, key)) out = EN[key]
  else for (const [re, render] of PATTERNS) { const m = key.match(re); if (m) { out = render(...m.slice(1)); break } }
  if (memo.size >= MEMO_MAX) memo.clear()
  memo.set(key, out)
  return out
}
export function translate(value, lang = language) {
  if (typeof value !== 'string' || lang !== 'en') return value
  const key = value.trim()
  if (!key) return value
  const t = lookup(key)
  if (t === undefined) return value
  const at = value.indexOf(key)
  return value.slice(0, at) + t + value.slice(at + key.length)
}
const translateChildren = (v) => (typeof v === 'string' ? translate(v) : Array.isArray(v) ? v.map(translateChildren) : v)
const TEXT_PROPS = ['aria-label', 'title', 'alt', 'placeholder']
export function localizedProps(type, props) {
  if (!props || language !== 'en') return props
  const out = { ...props }
  if ('children' in props) out.children = translateChildren(props.children)
  for (const k of TEXT_PROPS) if (typeof props[k] === 'string') out[k] = translate(props[k])
  return out
}
// Tagged template for strings with values: t`共 ${n} 張影像`
export function t(parts, ...values) {
  const key = parts.map((p, i) => p + (i < values.length ? `{${i}}` : '')).join('')
  const tpl = language === 'en' && Object.hasOwn(MESSAGES, key) ? MESSAGES[key] : null
  if (tpl) return tpl.replace(/\{(\d+)\}/g, (_, i) => String(translate(values[Number(i)])))
  return parts.map((p, i) => p + (i < values.length ? String(values[i]) : '')).join('')
}
