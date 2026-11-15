// The small part of Markdown the assistant writes: paragraphs, "-"/"*"/"•" and "1." lists, "#" headings, **bold**,
// `code` and [n] citations. Parsed into plain data and rendered by AskPanel as React elements, never as HTML, so an
// answer cannot inject markup. A half-streamed "**" stays visible until its closing pair arrives.

const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBER = /^\s*(\d{1,3})[.)]\s+(.*)$/
const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/
const INLINE = /(\*\*[^*\n]+?\*\*|__[^_\n]+?__|`[^`\n]+`|\[\d+(?:\s*,\s*\d+)*\])/g

/** text -> [{type:'p', lines}, {type:'ul', items}, {type:'ol', start, items}, {type:'h', text}] */
export function parseBlocks(text) {
  const out = []
  let cur = null
  const close = () => { cur = null }
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) { close(); continue }
    let m
    if ((m = HEADING.exec(line))) { close(); out.push({ type: 'h', text: m[1] }); continue }
    if ((m = BULLET.exec(line)) && !/^\s*\*\*/.test(line)) {
      if (cur?.type !== 'ul') { cur = { type: 'ul', items: [] }; out.push(cur) }
      cur.items.push(m[1]); continue
    }
    if ((m = NUMBER.exec(line))) {
      if (cur?.type !== 'ol') { cur = { type: 'ol', start: +m[1], items: [] }; out.push(cur) }
      cur.items.push(m[2]); continue
    }
    if ((cur?.type === 'ul' || cur?.type === 'ol') && /^\s+/.test(raw)) { cur.items[cur.items.length - 1] += ' ' + line.trim(); continue }
    if (cur?.type !== 'p') { cur = { type: 'p', lines: [] }; out.push(cur) }
    cur.lines.push(line)
  }
  return out
}

/** one line -> [{t:'text'|'b'|'code', v}, {t:'cite', n:[...]}] */
export function parseInline(s) {
  return String(s).split(INLINE).filter((p) => p !== '').map((p) => {
    let m
    if ((m = /^\[([\d\s,]+)\]$/.exec(p))) return { t: 'cite', n: m[1].split(',').map((x) => +x.trim()) }
    if ((m = /^\*\*([^*]+)\*\*$/.exec(p)) || (m = /^__([^_]+)__$/.exec(p))) return { t: 'b', v: m[1] }
    if ((m = /^`([^`]+)`$/.exec(p))) return { t: 'code', v: m[1] }
    return { t: 'text', v: p }
  })
}
