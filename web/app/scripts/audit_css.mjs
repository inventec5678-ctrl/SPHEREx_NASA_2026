// Design-token audit for the site's style sheets (UPGRADE_PLAN.md §8, V9): app.css and every page's own css file in
// src/ (theme.css defines the tokens; fonts.css, the third-party rb/ effects and the 3-D universe page are outside).
// Fails `npm test` when a file uses a value outside the design system: font sizes must be var(--fs-*) (or inherit /
// em), radii one of the tokens, breakpoints one of three widths, and every colour must come from theme.css
// (var(--sx-*) or rgb(var(--c-*) / a)); at most 9 type sizes across all of them.
import { readFileSync, readdirSync } from 'node:fs'
const dir = new URL('../src/', import.meta.url)
const files = readdirSync(dir).filter((f) => f.endsWith('.css') && !['theme.css', 'fonts.css'].includes(f)).sort()
const bad = []
const all = []
for (const file of files) {
const css = readFileSync(new URL(file, dir), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
all.push(css)
const lineOf = (i) => `${file}:${css.slice(0, i).split('\n').length}`
for (const m of css.matchAll(/font-size:\s*([^;}]+)/g)) {
  const v = m[1].trim()
  if (!/^var\(--fs-[\w-]+\)$/.test(v) && !/^(inherit|[\d.]+em)$/.test(v)) bad.push(`font-size ${v} (line ${lineOf(m.index)})`)
}
for (const m of css.matchAll(/(?<![-\w])font:\s*([^;}]+)/g)) {
  const v = m[1].trim()
  if (v === 'inherit') continue
  if (!/var\(--fs-[\w-]+\)/.test(v)) bad.push(`font ${v} (line ${lineOf(m.index)})`)
}
const RADII = new Set(['var(--r-sm)', 'var(--r-md)', '999px', '50%', '0', 'inherit'])
for (const m of css.matchAll(/border-radius:\s*([^;}]+)/g)) for (const p of m[1].replace('!important', '').trim().split(/\s+/)) if (!RADII.has(p)) bad.push(`radius ${p} (line ${lineOf(m.index)})`)
const BP = new Set(['max-width: 560px', 'max-width: 900px', 'max-width: 1280px', 'min-width: 561px', 'min-width: 901px', 'min-width: 1281px'])
for (const m of css.matchAll(/\((max|min)-width:\s*([\d.]+px)\)/g)) if (!BP.has(`${m[1]}-width: ${m[2]}`)) bad.push(`breakpoint ${m[0]} (line ${lineOf(m.index)})`)
for (const m of css.matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\((?!var\(--c-)[^)]*\)|hsla?\(/g)) bad.push(`colour ${m[0]} (line ${lineOf(m.index)})`)
}
const sizes = new Set(all.flatMap((css) => [...css.matchAll(/var\(--fs-([\w-]+)\)/g)].map((m) => m[1])))
sizes.delete('hero')            // the home page's one headline size (home.css), on top of the nine site-wide ones
if (sizes.size > 9) bad.push(`${sizes.size} font sizes in use (at most 9)`)
if (bad.length) { console.error(`audit_css: ${bad.length} values outside the design system\n  ` + bad.slice(0, 40).join('\n  ')); process.exit(1) }
console.log(`audit_css: ${files.length} style sheets use ${sizes.size} type sizes, 4 radii, 3 breakpoints, colours only from theme.css`)
