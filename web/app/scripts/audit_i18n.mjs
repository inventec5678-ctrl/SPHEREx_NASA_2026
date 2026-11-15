// Loads each page in English with Playwright-free static checks: every Chinese string the extractor
// finds in src/ must have an English entry (EN or MESSAGES). Exit 1 if anything is missing.
import { readFileSync } from 'node:fs'
import { srcFiles, shortName } from './src_files.mjs'
import { EN, MESSAGES } from '../src/i18n/catalog.js'

const files = srcFiles(['i18n'])
const han = /[㐀-鿿]/
const missing = new Set()
// Three ways a Chinese string already carries its English, none of which needs a catalogue entry:
//   L('中文', 'English')          the two-language helper (first argument dropped here)
//   zh: '中文' / zh: { ... }       tables with zh and en side by side
//   ['中文', 'English']           [zh, en] pairs
// and blocks between "// i18n-ignore-start" and "// i18n-ignore-end" (Chinese-only tables read through a helper).
// The patterns are built once, not per file.
const STR = String.raw`(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|` + '`(?:[^`\\\\]|\\\\.)*`)'
const EN_STR = `('[^'\\n㐀-鿿]*'|"[^"\\n㐀-鿿]*")`
const STRIP = [
  [/\/\/ i18n-ignore-start[\s\S]*?\/\/ i18n-ignore-end/g, ''],
  [new RegExp(String.raw`\bL\(\s*` + STR + String.raw`\s*,`, 'g'), 'L('],
  [new RegExp(String.raw`\bzh:\s*` + STR, 'g'), 'zh: 0'],
  [/\bzh:\s*\{[^{}]*\}/g, 'zh: 0'],
  // a language ternary: en ? 'English' : '中文' (either order)
  [new RegExp(String.raw`\?\s*` + EN_STR + String.raw`\s*:\s*` + STR, 'g'), '? 0 : 0'],
  [new RegExp(String.raw`\?\s*` + STR + String.raw`\s*:\s*` + EN_STR, 'g'), '? 0 : 0'],
  [new RegExp(String.raw`\[\s*` + STR + String.raw`\s*,\s*` + EN_STR + String.raw`\s*\]`, 'g'), '[0]'],
]
for (const f of files) {
  if (f.endsWith('fields_text.js')) continue
  const s = STRIP.reduce((acc, [re, to]) => acc.replace(re, to), readFileSync(f, 'utf8'))
  for (const m of s.matchAll(/t`((?:[^`\\]|\\.)*)`/g)) {
    let i = 0; const key = m[1].replace(/\$\{(?:[^{}]|\{[^{}]*\})*\}/g, () => `{${i++}}`)
    if (han.test(key) && !(key in MESSAGES)) missing.add('T ' + key)
  }
  const noT = s.replace(/t`(?:[^`\\]|\\.)*`/g, '').replace(/\/\/.*$/gm, '')
  for (const m of noT.matchAll(/>([^<>{}]+)</g)) { const v = m[1].trim(); if (han.test(v) && !(v in EN) && !/\n|===|=>/.test(v)) missing.add('E ' + v) }
  for (const m of noT.matchAll(/'([^'\n]*)'|"([^"\n]*)"/g)) {
    const v = (m[1] ?? m[2]).trim()
    if (han.test(v) && !v.includes('${') && !(v in EN) && v !== '繁中' && !v.startsWith('Language')) missing.add('E ' + v)
  }
}
// A language test written by hand is a third way of writing text; only L() and the catalogue are allowed.
const byHand = []
for (const f of files) {
  readFileSync(f, 'utf8').split('\n').forEach((line, k) => {
    if (/===\s*'en'\s*\?|!==\s*'en'\s*\?/.test(line) || /(^|[^\w.])en\s*\?\s*['"`]/.test(line)) byHand.push(`${shortName(f)}:${k + 1}`)
  })
}
if (byHand.length) { console.error(`audit_i18n: ${byHand.length} hand-written language tests (use L(zh, en)):\n  ` + byHand.join('\n  ')); process.exit(1) }
if (missing.size) { console.error(`audit_i18n: ${missing.size} untranslated strings\n  ` + [...missing].join('\n  ')); process.exit(1) }
console.log('audit_i18n: every Chinese UI string has an English entry')
