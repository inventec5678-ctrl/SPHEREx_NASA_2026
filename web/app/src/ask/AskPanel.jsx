// The assistant panel (its own chunk, loaded when the visitor first opens it). Questions go to POST /api/ask, which
// answers as a server-sent event stream: {type:'sources', items}, {type:'token', text}…, {type:'done', grounded, model}
// or {type:'error', message}; a 429 means too many questions. Answers are light Markdown (markdown.js) with [n]
// markers that point at the source list. One conversation per thing asked about, kept for the browser session (sessionStorage).
import { Fragment, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { L, getLanguage } from '@sx/i18n/core.js'
import { useLanguage } from '@sx/i18n/language.jsx'
import { askContext, clearAskContext, closeAsk, getAsk, subscribe } from './store.js'
import { LLAMA_BUILT_WITH } from '../credits_text.js'
import { parseBlocks, parseInline } from './markdown.js'
import './ask.css'

const STORE = 'sx:ask:conv:v1', MAX_CONVS = 12, MAX_MSGS = 30, MAX_HISTORY = 8
const ctxKey = (c) => `${c.kind}:${c.id ?? c.name ?? ''}`
const loadConvs = () => { try { return JSON.parse(sessionStorage.getItem(STORE)) || {} } catch { return {} } }
function saveConvs(all) {
  try {
    const keys = Object.keys(all).filter((k) => all[k]?.length).slice(-MAX_CONVS)
    sessionStorage.setItem(STORE, JSON.stringify(Object.fromEntries(keys.map((k) => [k, all[k].slice(-MAX_MSGS)]))))
  } catch { /* private mode or full: the conversation just is not kept */ }
}

const KIND = {
  field: () => L('天區', 'Field'), target: () => L('測試目標', 'Test target'), object: () => L('移動天體', 'Moving object'),
  star: () => L('恆星／光源', 'Star / source'), body: () => L('天體', 'Body'), page: () => L('這一頁', 'This page'), room: () => L('控制室', 'Control room'),
}
const PAGE = {
  landing: () => L('首頁', 'Home'), sky: () => L('天空', 'Sky'), movers: () => L('找移動星', 'Find movers'), targets: () => L('測試目標', 'Test targets'),
  guide: () => L('說明', 'Guide'), story: () => L('故事', 'Story'), features: () => L('功能', 'Features'), discovery: () => L('發現', 'Discovery'),
  universe: () => L('星體重建', 'Body reconstruction'), follow: () => L('追蹤', 'Follow-up'), comet: () => L('彗星', 'Comet'), credits: () => L('致謝', 'Credits'),
}
const ctxName = (c) => (c.kind === 'page' ? (c.name === 'general' ? L('一般問題', 'General question') : PAGE[c.name]?.() || c.name || L('這個網站', 'This site')) : c.name || c.id || '')
const SUGGEST = {
  field: () => [L('SPHEREx 在這片天空看到了什麼？', 'What is SPHEREx seeing in this patch of sky?'), L('這裡的移動天體是怎麼找到的？', 'How were the moving objects here found?'), L('什麼會造成假的偵測？', 'What can cause a false detection here?')],
  target: (n) => [L(`${n} 為什麼值得研究？`, `Why is ${n} interesting?`), L('SPHEREx 怎麼量它的移動或亮度變化？', 'How does SPHEREx measure its motion or brightness?'), L('光譜和光變曲線告訴我們什麼？', 'What do its spectrum and light curve tell us?')],
  object: () => [L('這可能是哪一類天體？', 'What kind of object could this be?'), L('怎麼知道它真的在動，不是雜訊？', 'How do we know it really moves and is not noise?'), L('它可能有多遠？', 'How far away could it be?')],
  star: () => [L('這個光譜說明它的溫度是多少？', 'What does this spectrum say about its temperature?'), L('它可能是棕矮星嗎？', 'Could this be a brown dwarf?'), L('為什麼有些波段的點會缺？', 'Why are some bands missing?')],
  body: (n) => [L(`${n} 是由什麼組成的？`, `What is ${n} made of?`), L('SPHEREx 怎麼觀測這類天體？', 'How does SPHEREx observe objects like this?'), L('它離太陽多遠？', 'How far is it from the Sun?')],
  room: () => [L('窗外看到的是什麼？', 'What am I looking at out of the window?'), L('六個偵測器波段代表什麼？', 'What do the six detector bands mean?'), L('為什麼每一輪的影像不一樣？', 'Why does the picture change between passes?')],
  page: () => [L('SPHEREx 是什麼？', 'What is SPHEREx?'), L('這個網站怎麼找到移動天體？', 'How does this site find moving objects?'), L('五個測試目標是什麼？', 'What are the five test targets?')],
}

/** POST the question and hand each event of the stream to `on`. Throws { rate, retry } on 429. */
async function ask(body, signal, on) {
  const r = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify(body), signal })
  if (r.status === 429) {
    let j = null
    try { j = await r.json() } catch { /* no body */ }
    throw Object.assign(new Error(j?.message || j?.error || 'rate limited'), { rate: true, retry: +r.headers.get('Retry-After') || j?.retry_after || null })
  }
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`)
  const rd = r.body.getReader(), dec = new TextDecoder()
  signal.addEventListener('abort', () => { rd.cancel().catch(() => {}) }, { once: true })     // stop reading at once
  let buf = ''
  const block = (b) => {
    const data = b.split(/\r?\n/).filter((l) => l.startsWith('data:')).map((l) => l.slice(5).replace(/^ /, '')).join('\n')
    if (!data) return
    let ev = null
    try { ev = JSON.parse(data) } catch { return }
    on(ev)
  }
  for (;;) {
    const { done, value } = await rd.read()
    if (signal.aborted) throw Object.assign(new Error('stopped'), { name: 'AbortError' })
    if (done) break
    buf += dec.decode(value, { stream: true })
    let m
    while ((m = /\r?\n\r?\n/.exec(buf))) { block(buf.slice(0, m.index)); buf = buf.slice(m.index + m[0].length) }
  }
  if (buf.trim()) block(buf)
}

const authors = (a) => { const l = Array.isArray(a) ? a : String(a || '').split(/,\s*/).filter(Boolean); return l.length > 3 ? `${l.slice(0, 3).join(', ')} et al.` : l.join(', ') }
const srcUrl = (s) => s.url || (s.arxiv ? `https://arxiv.org/abs/${s.arxiv}` : null)

/** Answer text: light Markdown (paragraphs, lists, headings, bold, code) with [n] linked to source n of the answer. */
function AnswerText({ text, sources, uid }) {
  const blocks = useMemo(() => parseBlocks(text), [text])
  const jump = (e, n) => { e.preventDefault(); const el = document.getElementById(`${uid}-s${n}`); el?.scrollIntoView({ block: 'nearest' }); el?.focus() }
  const inline = (s) => parseInline(s).map((p, i) => {
    if (p.t === 'b') return <strong key={i}>{p.v}</strong>
    if (p.t === 'code') return <code key={i}>{p.v}</code>
    if (p.t === 'text') return <Fragment key={i}>{p.v}</Fragment>
    return <sup key={i} className="ask-cite">[{p.n.map((n, j) => (
      <Fragment key={j}>{j ? ',' : ''}{sources?.[n - 1]
        ? <a href={`#${uid}-s${n}`} onClick={(e) => jump(e, n)} aria-label={L(`來源 ${n}：${sources[n - 1].title}`, `Source ${n}: ${sources[n - 1].title}`)}>{n}</a>
        : n}</Fragment>))}]</sup>
  })
  return (
    <div className="ask-text">
      {blocks.map((b, i) => {
        if (b.type === 'h') return <p key={i} className="ask-h"><strong>{inline(b.text)}</strong></p>
        if (b.type === 'ul') return <ul key={i}>{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>
        if (b.type === 'ol') return <ol key={i} start={b.start}>{b.items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ol>
        return <p key={i}>{b.lines.map((l, j) => <Fragment key={j}>{j ? <br /> : null}{inline(l)}</Fragment>)}</p>
      })}
    </div>
  )
}

function Sources({ items, uid }) {
  if (!items?.length) return null
  return (
    <div className="ask-srcs">
      <h3>{L('來源', 'Sources')}</h3>
      <ol>
        {items.map((s, i) => {
          const u = srcUrl(s)
          return (
            <li key={s.id || i} id={`${uid}-s${i + 1}`} tabIndex={-1}>
              {u ? <a href={u} target="_blank" rel="noopener noreferrer">{s.title || s.id}</a> : <b>{s.title || s.id}</b>}
              <span className="ask-meta">{[authors(s.authors), s.year].filter(Boolean).join(' · ')}
                {s.arxiv && <> · <a href={`https://arxiv.org/abs/${s.arxiv}`} target="_blank" rel="noopener noreferrer">arXiv:{s.arxiv}</a></>}</span>
              {s.snippet && <details><summary>{L('摘錄', 'Excerpt')}</summary><p>{s.snippet}</p></details>}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Answer({ m, uid, onRetry }) {
  return (
    <div className="ask-msg is-ai" aria-busy={m.state === 'streaming'}>
      {m.content ? <AnswerText text={m.content} sources={m.sources} uid={uid} /> : m.state === 'streaming' && <p className="ask-typing" aria-label={L('正在回答…', 'Answering…')}><i /><i /><i /></p>}
      {m.state === 'done' && m.grounded === false && <p className="ask-badge">{L('沒有來源：一般知識', 'No source: general knowledge')}</p>}
      {m.state === 'stopped' && <p className="ask-note">{L('已停止。', 'Stopped.')}</p>}
      {m.state === 'error' && (
        <div className="ask-err" role="alert">
          <p>{m.rate
            ? (m.retry ? L(`問題太多了，請 ${m.retry} 秒後再試。`, `Too many questions right now. Try again in ${m.retry} s.`) : L('問題太多了，請稍後再試。', 'Too many questions right now. Please try again in a minute.'))
            : L('沒有拿到回答（伺服器或網路有問題）。', 'No answer came back (a server or network problem).')}</p>
          <button type="button" className="ask-chip" onClick={onRetry}>{L('再試一次', 'Try again')}</button>
        </div>
      )}
      <Sources items={m.sources} uid={uid} />
      {m.state === 'done' && m.model && <p className="ask-model">{m.model}</p>}
    </div>
  )
}

export default function AskPanel() {
  useLanguage()
  const s = useSyncExternalStore(subscribe, getAsk, getAsk)
  const ctx = askContext(s), key = ctxKey(ctx)
  const underlying = s.cleared ? askContext({ ...s, cleared: false }) : null
  const [convs, setConvs] = useState(loadConvs)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(null)              // the key of the conversation being answered
  const abort = useRef(null), input = useRef(), log = useRef(), panel = useRef()
  const conv = convs[key] || []
  const convsRef = useRef(convs); convsRef.current = convs
  const busyRef = useRef(busy); busyRef.current = busy

  const patch = (k, fn) => setConvs((c) => ({ ...c, [k]: fn(c[k] || []) }))
  const patchLast = (k, fn) => patch(k, (l) => l.map((m, i) => (i === l.length - 1 ? { ...m, ...fn(m) } : m)))

  useEffect(() => { input.current?.focus() }, [])
  useEffect(() => { if (!busy) saveConvs(convs) }, [convs, busy])
  // closing mid-answer: stop it and keep what had arrived
  useEffect(() => () => {
    abort.current?.abort()
    const b = busyRef.current
    if (b) { const c = convsRef.current; saveConvs({ ...c, [b]: (c[b] || []).map((m) => (m.state === 'streaming' ? { ...m, state: 'stopped' } : m)) }) }
  }, [])
  useEffect(() => { const el = log.current; if (el) el.scrollTop = el.scrollHeight }, [conv.length, conv.at(-1)?.content?.length])

  async function send(text, k = key, c = ctx, prior = conv) {
    text = text.trim()
    if (!text || busy) return
    const history = prior.filter((m) => m.content && (m.role === 'user' || m.state !== 'error')).slice(-MAX_HISTORY).map((m) => ({ role: m.role, content: m.content }))
    patch(k, (l) => [...l, { role: 'user', content: text }, { role: 'assistant', content: '', sources: [], state: 'streaming' }])
    setQ(''); setBusy(k)
    const ac = abort.current = new AbortController()
    let pending = '', raf = 0
    const flush = () => { raf = 0; const t = pending; pending = ''; if (t) patchLast(k, (m) => ({ content: m.content + t })) }
    try {
      await ask({ question: text, lang: getLanguage(), history, context: c }, ac.signal, (ev) => {
        if (ev.type === 'token' && ev.text) { pending += ev.text; raf ||= requestAnimationFrame(flush) }
        else if (ev.type === 'sources') patchLast(k, () => ({ sources: Array.isArray(ev.items) ? ev.items : [] }))
        else if (ev.type === 'done') { flush(); patchLast(k, () => ({ state: 'done', grounded: ev.grounded !== false, model: ev.model || null })) }
        else if (ev.type === 'error') { flush(); patchLast(k, () => ({ state: 'error', message: ev.message })) }
      })
      cancelAnimationFrame(raf); flush()
      patchLast(k, (m) => (m.state === 'streaming' ? { state: 'done', grounded: m.sources?.length ? m.grounded ?? true : false } : {}))
    } catch (e) {
      cancelAnimationFrame(raf); flush()
      if (ac.signal.aborted) patchLast(k, () => ({ state: 'stopped' }))
      else patchLast(k, () => ({ state: 'error', rate: !!e.rate, retry: e.retry || null }))
    } finally {
      if (abort.current === ac) abort.current = null
      setBusy(null)
    }
  }
  const retry = () => {
    const l = convs[key] || [], u = l.at(-2)
    if (!u || u.role !== 'user') return
    const prior = l.slice(0, -2)
    setConvs((c) => ({ ...c, [key]: prior }))
    send(u.content, key, ctx, prior)
  }
  const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); closeAsk() }
    // keep the room's WASD walking and other page shortcuts from firing while typing here
    else if (e.target.closest?.('textarea')) e.stopPropagation()
  }
  const sugg = useMemo(() => (SUGGEST[ctx.kind] || SUGGEST.page)(ctxName(ctx) || L('它', 'it')), [ctx.kind, ctx.name, ctx.id, getLanguage()]) // eslint-disable-line react-hooks/exhaustive-deps
  const facts = ctx.facts ? Object.entries(ctx.facts).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${k}: ${v}`).join('\n') : ''

  return (
    <section ref={panel} className="ask-panel" role="dialog" aria-modal="false" aria-labelledby="ask-h" onKeyDown={onKey}>
      <header className="ask-head">
        <h2 id="ask-h">{L('問問看', 'Ask about the sky')}</h2>
        {conv.length > 0 && !busy && <button type="button" className="ask-chip" onClick={() => setConvs((c) => ({ ...c, [key]: [] }))}>{L('重新開始', 'New chat')}</button>}
        <button type="button" className="ask-x" onClick={closeAsk} aria-label={L('關閉提問面板', 'Close the assistant')}>×</button>
      </header>
      <div className="ask-ctx">
        <span className="ask-ctxchip" title={facts || undefined}>
          {ctx.kind !== 'page' && <span className="ask-k">{KIND[ctx.kind]?.() || ctx.kind}</span>}
          <b>{ctxName(ctx)}</b>
          {!s.cleared && !(ctx.kind === 'page' && !ctx.name) && <button type="button" onClick={() => clearAskContext(true)} aria-label={L('清除提問對象，改問一般問題', 'Clear the context and ask a general question')}>×</button>}
        </span>
        {underlying && underlying.kind !== 'page' && <button type="button" className="ask-chip" onClick={() => clearAskContext(false)}>{L(`改問：${ctxName(underlying)}`, `Ask about ${ctxName(underlying)}`)}</button>}
      </div>
      <div ref={log} className="ask-log" role="log" aria-live="polite" aria-label={L('對話', 'Conversation')}>
        {conv.length === 0 && (
          <div className="ask-empty">
            <p>{L('可以問這裡看到的東西、SPHEREx，或天文學。回答會盡量引用論文。', 'Ask about what is on screen, about SPHEREx, or astronomy. Answers cite papers where they can.')}</p>
            <div className="ask-sugg">{sugg.map((t) => <button key={t} type="button" className="ask-chip" onClick={() => send(t)} disabled={!!busy}>{t}</button>)}</div>
          </div>
        )}
        {conv.map((m, i) => (m.role === 'user'
          ? <p key={i} className="ask-msg is-me">{m.content}</p>
          : <Answer key={i} m={m} uid={`ask-${i}`} onRetry={retry} />))}
      </div>
      <form className="ask-form" onSubmit={(e) => { e.preventDefault(); send(q) }}>
        <textarea ref={input} rows={2} value={q} maxLength={1000} onChange={(e) => setQ(e.target.value)} aria-label={L('你的問題', 'Your question')}
          placeholder={L('輸入問題…', 'Type a question…')}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(q) } }} />
        {busy
          ? <button type="button" className="ask-send is-stop" onClick={() => abort.current?.abort()}>{L('停止', 'Stop')}</button>
          : <button type="submit" className="ask-send" disabled={!q.trim()}>{L('送出', 'Send')}</button>}
      </form>
      <footer className="ask-foot">
        <span>{L('AI 產生的回答可能有錯，請查看來源。', 'AI-generated answers can be wrong; check the sources.')}</span>
        <a href="#/credits">{LLAMA_BUILT_WITH}</a>
      </footer>
    </section>
  )
}
